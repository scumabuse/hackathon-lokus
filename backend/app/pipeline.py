"""Profile pipeline: Stages A-I of SPEC Section 6 as an async event generator.

``run_pipeline`` yields ``PipelineEvent`` objects (header, warnings, photos chunks, description,
stats, done); ``build_profile`` consumes them into a ``Profile`` for the blocking endpoint. Only
the resolve stage may raise (``ProfileNotFound`` -> 404, ``ResolverUnavailableError`` -> 503);
after the header is emitted every failure becomes a warning.

Stage F (vision) runs ``VISION_CONCURRENCY`` batches in flight and emits a photos chunk as each
batch is scored; the deadline monitor refuses to start a batch when fewer than 4 s remain and
scores the rest without vision (``vision_timeout``). Stage H (description) runs in parallel with
F. The cached path and the concurrency guard are Phase 6.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import time
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel

from app.ai import describe as describe_mod
from app.ai import vision
from app.ai.client import AIClient
from app.cache import Cache
from app.config import Settings
from app.enums import Category, ReasonCode, SourceType, Verification, WarningCode, source_rank
from app.models import (
    Description,
    Photo,
    ProcessedImage,
    Profile,
    RawCandidate,
    Stats,
    UniversityHeader,
    Warning,
)
from app.processing.dedup import dedupe, drop_duplicates_of
from app.processing.download import DownloadResult, download_candidates, fetch_logo_hashes
from app.processing.textmatch import name_terms
from app.resolver.wikidata import ResolvedEntity, ResolverUnavailableError, resolve_university
from app.resolver.wikipedia import WikiSummary, rest_summary
from app.scoring import VisionInfo, score_candidate
from app.selection import (
    HIDDEN_CAP,
    TOTAL_SHOWN_CAP,
    category_cap,
    finalize_selection,
    heuristic_category,
)
from app.sources import commons
from app.sources.base import SourceContext, SourceResult
from app.sources.registry import build_sources

log = logging.getLogger("app.pipeline")

STAGE_A_TIMEOUT_S = 5.0  # Section 6: resolve hard limit
SOURCE_TIMEOUT_S = 8.0  # Section 6: per source
DOWNLOAD_STAGE_TIMEOUT_S = 8.0  # Section 6: download stage (hard limit, wave 2)
FIRST_WAVE_SIZE = 16  # best candidates downloaded first so classification can start early
EARLY_WAVE_S = 2.0  # sources still running after this feed the second wave instead
FIRST_WAVE_TIMEOUT_S = 4.0  # Section 6: download stage target, used for wave 1
FIRST_BATCH_SIZE = 4  # a small first vision batch returns the first photos sooner
VISION_BATCH_TIMEOUT_S = 20.0  # Section 6/9: per batch
VISION_MIN_REMAINING_S = 4.0  # Section 6 deadline monitor: do not start a batch below this
DESCRIBE_TIMEOUT_S = 12.0  # Section 6: describe hard limit
CITY_CANDIDATE_CAP = 20  # Section 6.1
TIMING_KEYS = ("resolve", "collect", "download", "dedup", "vision", "describe", "total")

# Section 6.2: at most 3 concurrent pipeline runs; a 4th waits and gets warning: queued.
_PIPELINE_SEMAPHORE = asyncio.Semaphore(3)


class ProfileNotFound(Exception):
    """The QID does not exist or is not a university (HTTP 404)."""


@dataclass(slots=True)
class PipelineDeps:
    settings: Settings
    http: httpx.AsyncClient
    ai: AIClient
    cache: Cache


@dataclass(slots=True)
class PipelineEvent:
    """One SSE event: ``name`` is header | description | photos | warning | stats | done."""

    name: str
    data: dict[str, Any]


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


# ----------------------------------------------------------------------------- Stage C


@dataclass(slots=True)
class Normalized:
    candidates: list[RawCandidate]
    found: int
    dropped_duplicate_urls: int
    dropped_by_caps: int


def _merge_duplicate(kept: RawCandidate, other: RawCandidate) -> None:
    """Keep the higher-priority source but borrow signals only the duplicate carries."""
    if kept.geo is None and other.geo is not None:
        kept.geo = other.geo
        kept.distance_m = other.distance_m
    if kept.source_hint_category is None and other.source_hint_category is not None:
        kept.source_hint_category = other.source_hint_category


def normalize_candidates(
    results: Iterable[SourceResult], *, max_candidates: int, city_cap: int = CITY_CANDIDATE_CAP
) -> Normalized:
    """Section 6.1: URL-dedupe across sources, then caps in SOURCE_PRIORITY order.

    Sources are visited best-first, API order preserved within a source, so the first occurrence
    of a URL is the highest-priority one. City candidates (``city_commons``) have their own cap.
    """
    by_url: dict[str, RawCandidate] = {}
    by_id: dict[str, RawCandidate] = {}
    ordered: list[RawCandidate] = []
    dropped_urls = 0
    for result in sorted(results, key=lambda r: source_rank(r.source_type)):
        for candidate in result.candidates:
            existing = by_url.get(candidate.image_url) or by_id.get(candidate.photo_id)
            if existing is not None:
                _merge_duplicate(existing, candidate)
                dropped_urls += 1
                continue
            by_url[candidate.image_url] = candidate
            by_id[candidate.photo_id] = candidate
            ordered.append(candidate)

    kept: list[RawCandidate] = []
    non_city = city = 0
    dropped_caps = 0
    for candidate in ordered:
        if candidate.source_type is SourceType.city_commons:
            if city >= city_cap:
                dropped_caps += 1
                continue
            city += 1
        else:
            if non_city >= max_candidates:
                dropped_caps += 1
                continue
            non_city += 1
        kept.append(candidate)
    return Normalized(
        candidates=kept,
        found=len(kept),
        dropped_duplicate_urls=dropped_urls,
        dropped_by_caps=dropped_caps,
    )


# ----------------------------------------------------------------------------- Stage G


def build_photo(image: ProcessedImage, info: VisionInfo, names: list[str]) -> Photo:
    """One scored ``Photo`` (Section 5) from a processed image and its vision verdict."""
    candidate = image.candidate
    if info.usable and info.category is not None:
        category, category_source = info.category, "vision"
        extra_reasons: list[ReasonCode] = []
    else:
        category, category_source = heuristic_category(candidate)
        extra_reasons = [ReasonCode.category_heuristic]
    if candidate.source_type is SourceType.city_commons:
        category = Category.city
    score = score_candidate(candidate, names=names, vision=info)
    return Photo(
        id=image.photo_id,
        thumb_url=f"/api/thumb/{image.photo_id}.jpg",
        image_url=candidate.image_url,
        source_page_url=candidate.source_page_url,
        source_type=candidate.source_type,
        source_label=candidate.source_label,
        title=candidate.title,
        author=candidate.author,
        license=candidate.license,
        date=candidate.date,
        date_kind=candidate.date_kind,
        category=category,
        category_source=category_source,
        width=image.width,
        height=image.height,
        confidence=score.confidence,
        verification=score.verification,
        reasons=[*score.reasons, *extra_reasons],
        geo=candidate.geo,
        distance_m=candidate.distance_m,
        visible_text=info.visible_text if info.usable else None,
        vision_reason=info.reason if info.usable else None,
    )


class _RunningSelection:
    """Section 11 caps applied while streaming (batches arrive best-source first)."""

    def __init__(self) -> None:
        self.per_category: dict[Category, int] = {}
        self.shown = 0
        self.hidden = 0
        self.cut = 0

    def admit(self, photo: Photo) -> bool:
        if photo.verification is Verification.unverified:
            if self.hidden >= HIDDEN_CAP:
                self.cut += 1
                return False
            self.hidden += 1
            return True
        count = self.per_category.get(photo.category, 0)
        if self.shown >= TOTAL_SHOWN_CAP or count >= category_cap(photo.category):
            self.cut += 1
            return False
        self.per_category[photo.category] = count + 1
        self.shown += 1
        return True


# ----------------------------------------------------------------------------- Stage F


@dataclass(slots=True)
class _Batch:
    index: int
    target: str
    images: list[ProcessedImage]


@dataclass(slots=True)
class _BatchResult:
    batch: _Batch
    infos: list[VisionInfo]
    skipped: bool = False  # deadline monitor refused to start it
    parsed_first_attempt: bool | None = None
    error: str | None = None


def _plan_batches(
    images: list[ProcessedImage], size: int, *, start: int, first_small: bool
) -> list[_Batch]:
    """Batches ordered by SOURCE_PRIORITY; city images go to their own ``city`` batches.

    With ``first_small`` the first FIRST_BATCH_SIZE university images form a batch of their own so
    the first photos chunk is emitted as early as possible.
    """
    size = max(1, size)
    ordered = sorted(images, key=lambda im: source_rank(im.candidate.source_type))
    university = [im for im in ordered if im.candidate.source_type is not SourceType.city_commons]
    city = [im for im in ordered if im.candidate.source_type is SourceType.city_commons]
    groups: list[tuple[str, list[ProcessedImage]]] = []
    if first_small and len(university) > FIRST_BATCH_SIZE:
        groups.append(("university", university[:FIRST_BATCH_SIZE]))
        university = university[FIRST_BATCH_SIZE:]
    groups += [
        ("university", university[pos : pos + size]) for pos in range(0, len(university), size)
    ]
    groups += [("city", city[pos : pos + size]) for pos in range(0, len(city), size)]
    return [
        _Batch(index=start + i, target=target, images=chunk)
        for i, (target, chunk) in enumerate(groups)
        if chunk
    ]


async def _run_batch(
    deps: PipelineDeps,
    batch: _Batch,
    header: UniversityHeader,
    *,
    semaphore: asyncio.Semaphore,
    deadline: float,
) -> _BatchResult:
    async with semaphore:
        remaining = deadline - time.monotonic()
        if remaining < VISION_MIN_REMAINING_S:
            return _BatchResult(
                batch=batch,
                infos=[VisionInfo(available=True, timed_out=True) for _ in batch.images],
                skipped=True,
            )
        timeout = min(VISION_BATCH_TIMEOUT_S, max(1.0, remaining - 1.0))
        try:
            # absolute guard: retries and backoff inside the batch can never outlive the deadline
            outcome = await asyncio.wait_for(
                vision.classify_batch(
                    deps.ai, batch.images, header, target=batch.target, timeout=timeout
                ),
                timeout=max(1.0, remaining - 0.5),
            )
        except TimeoutError:
            log.warning("F batch %d cut by the hard deadline", batch.index)
            return _BatchResult(
                batch=batch,
                infos=[VisionInfo(available=True, timed_out=True) for _ in batch.images],
                skipped=True,
            )
        return _BatchResult(
            batch=batch,
            infos=outcome.infos,
            parsed_first_attempt=outcome.parsed_first_attempt,
            error=outcome.error,
        )


# ----------------------------------------------------------------------------- helpers


async def _fetch_summaries(
    client: httpx.AsyncClient, resolved: ResolvedEntity
) -> list[WikiSummary]:
    """Section 7.2: en + ru REST summaries in parallel (4 s each); failures are just absent."""
    titles = [(lang, resolved.wiki_titles.get(lang)) for lang in ("en", "ru")]
    tasks = [rest_summary(client, lang, title) for lang, title in titles if title]
    if not tasks:
        return []
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)
    return [o for o in outcomes if isinstance(o, WikiSummary)]


async def _logo_hashes(
    client: httpx.AsyncClient, logo_filename: str | None
) -> tuple[str, str] | None:
    """Download the P154 logo (via its Commons imageinfo) and hash it; ``None`` when absent/failed."""
    if not logo_filename:
        return None
    try:
        info = await commons.fetch_file_info(client, logo_filename)
    except Exception:  # a logo problem must never affect the profile, but it must be visible
        log.warning(
            "logo lookup failed for %r; logo exclusion skipped", logo_filename, exc_info=True
        )
        return None
    if not info:
        return None
    url = info.get("thumburl") or info.get("url")
    if not isinstance(url, str) or not url:
        return None
    return await fetch_logo_hashes(client, url)


def _settle(task: asyncio.Task[SourceResult]) -> SourceResult | BaseException:
    """A finished source task as its result or its exception (cancellation counts as failure)."""
    if task.cancelled():
        return asyncio.CancelledError()
    error = task.exception()
    return error if error is not None else task.result()


async def _run_source(source: Any, ctx: SourceContext) -> SourceResult:
    return await asyncio.wait_for(source.fetch(ctx), SOURCE_TIMEOUT_S)


async def _describe(
    deps: PipelineDeps, resolved: ResolvedEntity, summaries_task: asyncio.Task[list[WikiSummary]]
) -> Description:
    header = resolved.header
    summaries = await summaries_task
    inputs = describe_mod.DescriptionInputs(
        name=header.name,
        local_name=header.local_name,
        city=header.city.name if header.city else None,
        country=header.country,
        summaries=summaries,
    )
    try:
        return await asyncio.wait_for(
            describe_mod.describe_campus(deps.ai, inputs), DESCRIBE_TIMEOUT_S
        )
    except TimeoutError:
        log.warning("H describe timed out after %.0fs; using the fallback text", DESCRIBE_TIMEOUT_S)
        return describe_mod.fallback_description(inputs)


@dataclass(slots=True)
class _Run:
    deps: PipelineDeps
    qid: str
    started: float
    deadline: float
    warnings: list[Warning] = field(default_factory=list)
    timings: dict[str, int] = field(default_factory=dict)
    per_source: dict[str, int] = field(default_factory=dict)

    def warn(self, code: WarningCode, detail: str | None = None) -> PipelineEvent:
        warning = Warning(code=code, detail=detail)
        self.warnings.append(warning)
        return PipelineEvent("warning", _dump(warning))

    @property
    def elapsed_ms(self) -> int:
        return _ms(self.started)


# ----------------------------------------------------------------------------- the run


async def run_pipeline(
    deps: PipelineDeps, qid: str, *, refresh: bool = False
) -> AsyncIterator[PipelineEvent]:
    """Stages A-I with Section 6.2 concurrency guard and Section 6.3 cache fast path."""

    # ---- Section 6.2: concurrency guard
    if _PIPELINE_SEMAPHORE.locked() and _PIPELINE_SEMAPHORE._value == 0:  # type: ignore[attr-defined]
        queued_warning = Warning(code=WarningCode.queued)
        yield PipelineEvent("warning", _dump(queued_warning))

    async with _PIPELINE_SEMAPHORE:
        async for event in _run_pipeline_inner(deps, qid, refresh=refresh):
            yield event


async def _run_pipeline_inner(
    deps: PipelineDeps, qid: str, *, refresh: bool = False
) -> AsyncIterator[PipelineEvent]:
    """Stages A-I. ``refresh`` is accepted now and used by the cache fast path."""
    settings = deps.settings
    run = _Run(
        deps=deps,
        qid=qid,
        started=time.monotonic(),
        deadline=time.monotonic() + settings.hard_deadline_s,
    )

    # ---- Section 6.3: cached fast path
    if not refresh:
        cached = await deps.cache.get_profile(qid, settings.profile_ttl_hours)
        if cached is not None:
            cached_data, created_at = cached
            # verify at least one thumb exists on disk
            photos = cached_data.get("photos", [])
            thumb_ok = True
            if photos:
                first_id = photos[0].get("id", "")
                if first_id:
                    thumb_path = settings.thumbs_dir / f"{first_id}.jpg"
                    thumb_ok = thumb_path.is_file()
            if thumb_ok:
                from datetime import UTC as _UTC
                from datetime import datetime as _datetime

                minutes_ago = int(((_datetime.now(_UTC) - created_at).total_seconds()) / 60)
                # patch header.cached and cached_at
                if "header" in cached_data:
                    cached_data["header"]["cached"] = True
                    cached_data["header"]["cached_at"] = created_at.isoformat()
                yield PipelineEvent("header", cached_data.get("header", {}))
                yield PipelineEvent(
                    "warning",
                    _dump(
                        Warning(
                            code=WarningCode.served_from_cache,
                            detail=f"built {minutes_ago} minutes ago",
                        )
                    ),
                )
                if cached_data.get("description"):
                    yield PipelineEvent("description", cached_data["description"])
                photos_list = cached_data.get("photos", [])
                if photos_list:
                    yield PipelineEvent("photos", {"batch": 0, "photos": photos_list})
                if cached_data.get("stats"):
                    yield PipelineEvent("stats", cached_data["stats"])
                yield PipelineEvent("done", {"total_ms": 0, "cached": True})
                return

    # ---- A. resolve (may raise: ProfileNotFound / ResolverUnavailableError)
    stage = time.monotonic()
    try:
        resolved = await asyncio.wait_for(resolve_university(deps.http, qid), STAGE_A_TIMEOUT_S)
    except TimeoutError as exc:
        raise ResolverUnavailableError(
            f"wikidata did not answer within {STAGE_A_TIMEOUT_S}s"
        ) from exc
    run.timings["resolve"] = _ms(stage)
    if resolved is None:
        raise ProfileNotFound(qid)
    header = resolved.header
    yield PipelineEvent("header", _dump(header))
    log.info("A resolve %s -> %s in %dms", qid, header.name, run.timings["resolve"])
    summaries_task = asyncio.create_task(_fetch_summaries(deps.http, resolved))
    if header.coords is None:
        yield run.warn(WarningCode.no_coordinates)
    if header.commons_category is None:
        yield run.warn(WarningCode.no_commons_category)
    if header.official_website is None:
        yield run.warn(WarningCode.no_official_site)
    vision_off = not deps.ai.available
    if vision_off:
        yield run.warn(WarningCode.vision_unavailable, deps.ai.unavailable_reason)

    # ---- B. collect. Sources that have answered within EARLY_WAVE_S feed the first download
    # wave immediately; the slower ones keep running and join the second wave, so the first
    # photos never wait for the slowest source (nothing is skipped or cut).
    stage = time.monotonic()
    ctx = SourceContext(settings=settings, http=deps.http, resolved=resolved, deadline=run.deadline)
    sources = build_sources(settings)
    source_tasks = [asyncio.create_task(_run_source(source, ctx)) for source in sources]
    done_tasks, pending_tasks = await asyncio.wait(source_tasks, timeout=EARLY_WAVE_S)

    def early_candidates() -> list[RawCandidate]:
        results = [r for r in (_settle(t) for t in done_tasks) if isinstance(r, SourceResult)]
        return normalize_candidates(results, max_candidates=settings.max_candidates).candidates

    candidates_so_far = early_candidates()
    # a first wave needs at least one small batch; keep waiting source by source until it has one
    while len(candidates_so_far) < FIRST_BATCH_SIZE and pending_tasks:
        more_done, pending_tasks = await asyncio.wait(
            pending_tasks, return_when=asyncio.FIRST_COMPLETED
        )
        done_tasks = done_tasks | more_done
        candidates_so_far = early_candidates()
    wave1 = candidates_so_far[:FIRST_WAVE_SIZE]
    if pending_tasks:
        log.info(
            "B early start after %.1fs: %d of %d sources still running; first wave = %d candidates",
            EARLY_WAVE_S,
            len(pending_tasks),
            len(sources),
            len(wave1),
        )

    # ---- D (wave 1). The best candidates so far, within the 4 s target budget.
    download_started = time.monotonic()
    logo_task = asyncio.create_task(_logo_hashes(deps.http, resolved.logo_filename))
    downloaded1 = await download_candidates(
        deps.http,
        wave1,
        thumbs_dir=settings.thumbs_dir,
        concurrency=settings.download_concurrency,
        stage_timeout_s=FIRST_WAVE_TIMEOUT_S,
        deadline=run.deadline,
    )
    logo = await logo_task

    # ---- B (finish). Every source has its own 8 s limit inside _run_source.
    if pending_tasks:
        await asyncio.wait(pending_tasks)
    results: list[SourceResult] = []
    for source, task in zip(sources, source_tasks, strict=True):
        outcome = _settle(task)
        if isinstance(outcome, BaseException):
            reason = "timeout" if isinstance(outcome, TimeoutError) else type(outcome).__name__
            log.warning("B source %s failed: %s", source.name, reason)
            run.per_source[source.name] = 0
            yield run.warn(WarningCode.source_unavailable, source.name)
            continue
        run.per_source[source.name] = len(outcome.candidates)
        results.append(outcome)
        for warning in outcome.warnings:
            run.warnings.append(warning)
            yield PipelineEvent("warning", _dump(warning))
        log.info(
            "B source %s -> %d candidates in %dms%s",
            source.name,
            len(outcome.candidates),
            outcome.elapsed_ms,
            f" (error: {outcome.error})" if outcome.error else "",
        )
    run.timings["collect"] = _ms(stage)

    # ---- C. normalize (all sources) and split off wave 2
    normalized = normalize_candidates(results, max_candidates=settings.max_candidates)
    wave1_ids = {candidate.photo_id for candidate in wave1}
    wave2 = [c for c in normalized.candidates if c.photo_id not in wave1_ids]
    found = len(wave1_ids | {c.photo_id for c in normalized.candidates})
    log.info(
        "C normalize -> %d candidates (%d duplicate urls, %d cut by caps); wave 1 = %d, wave 2 = %d",
        found,
        normalized.dropped_duplicate_urls,
        normalized.dropped_by_caps,
        len(wave1),
        len(wave2),
    )

    # ---- D (wave 2). The rest downloads while wave 1 is already being classified.
    wave2_task: asyncio.Task[DownloadResult] | None = None
    if wave2:
        wave2_task = asyncio.create_task(
            download_candidates(
                deps.http,
                wave2,
                thumbs_dir=settings.thumbs_dir,
                concurrency=settings.download_concurrency,
                stage_timeout_s=DOWNLOAD_STAGE_TIMEOUT_S,
                deadline=run.deadline,
            )
        )
    downloads: list[DownloadResult] = [downloaded1]
    run.timings["download"] = _ms(download_started)

    # ---- E. dedup (wave 1 now; wave 2 is deduplicated against it when it lands)
    stage = time.monotonic()
    logo_sha1, logo_phash = logo if logo is not None else (None, None)
    deduped1 = dedupe(downloaded1.images, logo_sha1=logo_sha1, logo_phash=logo_phash)
    run.timings["dedup"] = _ms(stage)
    duplicates_removed = deduped1.removed
    irrelevant_removed = deduped1.logo_removed
    kept: list[ProcessedImage] = list(deduped1.kept)

    # ---- H starts now and runs in parallel with F
    stage_describe = time.monotonic()
    describe_task = asyncio.create_task(_describe(deps, resolved, summaries_task))

    # ---- F + G. vision per batch (concurrent, deadline-monitored), score, emit
    stage = time.monotonic()
    names = name_terms(header.name, header.local_name, header.aliases)
    admitted = _RunningSelection()
    emitted: list[Photo] = []
    semaphore = asyncio.Semaphore(max(1, settings.vision_concurrency))
    batches: list[_Batch] = []
    pending: dict[asyncio.Task[_BatchResult], _Batch] = {}

    def schedule(images: list[ProcessedImage], *, first_small: bool) -> None:
        planned = _plan_batches(
            images, settings.vision_batch_size, start=len(batches), first_small=first_small
        )
        for batch in planned:
            batches.append(batch)
            task = asyncio.create_task(
                _run_batch(deps, batch, header, semaphore=semaphore, deadline=run.deadline)
            )
            pending[task] = batch

    schedule(kept, first_small=True)
    unclassified = 0
    batches_ok = batches_first_ok = batches_failed = 0
    first_error: str | None = None
    chunk_index = 0
    while pending or wave2_task is not None:
        waiting: set[asyncio.Task[Any]] = set(pending)
        if wave2_task is not None:
            waiting.add(wave2_task)
        done, _ = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task is wave2_task:
                wave2_task = None
                try:
                    downloaded2 = task.result()
                except Exception as exc:  # download_candidates never raises; belt and braces
                    log.warning("D wave 2 crashed: %s", exc, exc_info=True)
                    downloaded2 = DownloadResult(failed=len(wave2))
                downloads.append(downloaded2)
                run.timings["download"] = _ms(download_started)
                dedup_started = time.monotonic()
                deduped2 = dedupe(downloaded2.images, logo_sha1=logo_sha1, logo_phash=logo_phash)
                fresh, cross = drop_duplicates_of(deduped2.kept, against=kept)
                run.timings["dedup"] += _ms(dedup_started)
                duplicates_removed += deduped2.removed + cross
                irrelevant_removed += deduped2.logo_removed
                kept.extend(fresh)
                schedule(fresh, first_small=False)
                continue
            batch = pending.pop(task)  # type: ignore[arg-type]
            try:
                result = task.result()
            except Exception as exc:  # a batch must never take the run down
                log.warning("F batch %d crashed: %s", batch.index, exc, exc_info=True)
                result = _BatchResult(
                    batch=batch,
                    infos=[
                        VisionInfo(available=False, reason="vision unavailable: internal error")
                        for _ in batch.images
                    ],
                    error=str(exc),
                )
            timed_out_images = sum(1 for info in result.infos if info.timed_out)
            unclassified += timed_out_images
            if result.skipped or timed_out_images == len(result.infos):
                pass  # cut by the deadline monitor: scored without vision, reason vision_timeout
            elif result.error:
                batches_failed += 1
                first_error = first_error or result.error
            else:
                batches_ok += 1
                if result.parsed_first_attempt:
                    batches_first_ok += 1
            chunk: list[Photo] = []
            for image, raw_info in zip(result.batch.images, result.infos, strict=True):
                info, keep = vision.apply_post_processing(image, raw_info)
                if not keep:
                    irrelevant_removed += 1
                    continue
                photo = build_photo(image, info, names)
                if admitted.admit(photo):
                    chunk.append(photo)
            if chunk:
                emitted.extend(chunk)
                yield PipelineEvent(
                    "photos", {"batch": chunk_index, "photos": [_dump(p) for p in chunk]}
                )
                chunk_index += 1
    run.timings["vision"] = _ms(stage)

    total_candidates = found
    total_downloaded = sum(len(d.images) for d in downloads)
    failed_downloads = sum(d.failed for d in downloads)
    timed_out_downloads = sum(d.timed_out for d in downloads)
    if total_candidates and total_downloaded == 0:
        # nothing could be fetched: say so instead of showing an empty profile without a reason
        hosts: collections.Counter[str] = collections.Counter()
        for d in downloads:
            hosts.update(d.failed_hosts)
        host = hosts.most_common(1)[0][0] if hosts else "image hosts"
        yield run.warn(
            WarningCode.source_unavailable,
            f"{host} ({failed_downloads} failed, {timed_out_downloads} timed out)",
        )
    if timed_out_downloads:
        yield run.warn(
            WarningCode.time_budget_exceeded,
            f"download: {timed_out_downloads} of {total_candidates} images not fetched within "
            f"the {DOWNLOAD_STAGE_TIMEOUT_S:.0f} s stage budget",
        )
    total_images = len(kept)
    if batches:
        log.info(
            "F vision: %d batches, %d ok (%d parsed on the first attempt), %d failed, %d images "
            "skipped by the deadline monitor, %dms",
            len(batches),
            batches_ok,
            batches_first_ok,
            batches_failed,
            unclassified,
            run.timings["vision"],
        )
    if unclassified:
        yield run.warn(
            WarningCode.time_budget_exceeded,
            f"vision: {unclassified} of {total_images} images not classified",
        )
    vision_failed_everywhere = bool(batches) and not vision_off and batches_ok == 0
    if vision_failed_everywhere and batches_failed:
        # the model answered nothing usable for the whole run (quota, outage, bad key)
        yield run.warn(
            WarningCode.vision_unavailable,
            "vision model failed for every batch: " + (first_error or "unknown error")[:100],
        )

    # ---- H. describe (started before F)
    description = await describe_task
    run.timings["describe"] = _ms(stage_describe)
    yield PipelineEvent("description", _dump(description))

    # ---- I. finalize
    selection = finalize_selection(emitted)
    for warning in selection.warnings:
        run.warnings.append(warning)
        yield PipelineEvent("warning", _dump(warning))
    total_ms = run.elapsed_ms
    run.timings["total"] = total_ms
    for key in TIMING_KEYS:
        run.timings.setdefault(key, 0)
    stats = Stats(
        found=found,
        duplicates_removed=duplicates_removed,
        irrelevant_removed=irrelevant_removed,
        shown=len(selection.shown),
        hidden_unverified=len(selection.hidden),
        per_source=dict(run.per_source),
        timings_ms=dict(run.timings),
        total_ms=total_ms,
    )
    yield PipelineEvent("stats", _dump(stats))
    profile = Profile(
        header=header,
        description=description,
        photos=[*selection.shown, *selection.hidden],
        stats=stats,
        warnings=list(run.warnings),
        generated_at=datetime.now(UTC),
    )
    if stats.shown == 0 or (vision_failed_everywhere and batches_failed):
        # a run that produced nothing to show (or whose model failed throughout) is a transient
        # failure: caching it would replay the failure for PROFILE_TTL_HOURS
        log.warning(
            "I not caching %s: shown=%d, vision failed everywhere=%s",
            qid,
            stats.shown,
            vision_failed_everywhere,
        )
    else:
        await deps.cache.set_profile(qid, _dump(profile))
    log.info(
        "I done %s: found=%d dupes=%d irrelevant=%d shown=%d hidden=%d cut=%d total=%dms",
        qid,
        stats.found,
        stats.duplicates_removed,
        stats.irrelevant_removed,
        stats.shown,
        stats.hidden_unverified,
        admitted.cut,
        total_ms,
    )
    yield PipelineEvent("done", {"total_ms": total_ms, "cached": False})


async def build_profile(deps: PipelineDeps, qid: str, *, refresh: bool = False) -> Profile:
    """Blocking variant for GET /api/profile/{qid}: consume the stream into one ``Profile``."""
    header: UniversityHeader | None = None
    description: Description | None = None
    photos: list[Photo] = []
    warnings: list[Warning] = []
    stats: Stats | None = None
    async for event in run_pipeline(deps, qid, refresh=refresh):
        if event.name == "header":
            header = UniversityHeader.model_validate(event.data)
        elif event.name == "description":
            description = Description.model_validate(event.data)
        elif event.name == "photos":
            photos.extend(Photo.model_validate(p) for p in event.data["photos"])
        elif event.name == "warning":
            warnings.append(Warning.model_validate(event.data))
        elif event.name == "stats":
            stats = Stats.model_validate(event.data)
    if header is None or stats is None:  # pragma: no cover - the generator always emits both
        raise RuntimeError("pipeline ended without header/stats")
    selection = finalize_selection(photos)
    return Profile(
        header=header,
        description=description,
        photos=[*selection.shown, *selection.hidden],
        stats=stats,
        warnings=warnings,
        generated_at=datetime.now(UTC),
    )
