"""Profile pipeline: Stages A-I of SPEC Section 6 as an async event generator.

``run_pipeline`` yields ``PipelineEvent`` objects in the Section 12 order (header, warnings,
photos chunks, description, stats, done); ``build_profile`` consumes them into a ``Profile`` for
the blocking endpoint. Only the resolve stage may raise (``ProfileNotFound`` -> 404,
``ResolverUnavailableError`` -> 503); after the header is emitted every failure becomes a warning.

Vision (Stage F) and the description (Stage H) are plugged in by Phase 3 through
``classify_batch`` / ``describe_campus``; the cached path, deadline monitor and concurrency guard
are Phase 6.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel

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
from app.processing.dedup import dedupe
from app.processing.download import download_candidates, fetch_logo_hashes
from app.processing.textmatch import name_terms
from app.resolver.wikidata import ResolvedEntity, ResolverUnavailableError, resolve_university
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
DOWNLOAD_STAGE_TIMEOUT_S = 8.0  # Section 6: download stage
CITY_CANDIDATE_CAP = 20  # Section 6.1
TIMING_KEYS = ("resolve", "collect", "download", "dedup", "vision", "describe", "total")


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


# ----------------------------------------------------------------------------- Stage F hooks


def unavailable_vision(reason: str | None = None) -> VisionInfo:
    """Every image gets this when the model is off (Section 10 hard rule: at most ``likely``)."""
    return VisionInfo(available=False, reason=reason)


async def classify_batch(
    deps: PipelineDeps,
    images: list[ProcessedImage],
    header: UniversityHeader,
    *,
    target: str = "university",
) -> list[VisionInfo]:
    """Phase 3 plugs the real Section 9 classifier in here; Phase 2 marks everything unavailable."""
    return [unavailable_vision(deps.ai.unavailable_reason) for _ in images]


async def describe_campus(deps: PipelineDeps, resolved: ResolvedEntity) -> Description | None:
    """Phase 3 plugs the Section 7.8(a) description in here."""
    return None


# ----------------------------------------------------------------------------- Stage G


def build_photo(image: ProcessedImage, vision: VisionInfo | None, names: list[str]) -> Photo:
    """One scored ``Photo`` (Section 5) from a processed image and its vision verdict."""
    candidate = image.candidate
    if vision is not None and vision.usable and vision.category is not None:
        category, category_source = vision.category, "vision"
        extra_reasons: list[ReasonCode] = []
    else:
        category, category_source = heuristic_category(candidate)
        extra_reasons = [ReasonCode.category_heuristic]
    if candidate.source_type is SourceType.city_commons:
        category = Category.city
    score = score_candidate(candidate, names=names, vision=vision)
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
        visible_text=vision.visible_text if vision is not None and vision.usable else None,
        vision_reason=vision.reason if vision is not None and vision.usable else None,
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


# ----------------------------------------------------------------------------- the run


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


async def _run_source(source: Any, ctx: SourceContext) -> SourceResult:
    return await asyncio.wait_for(source.fetch(ctx), SOURCE_TIMEOUT_S)


def _batches(images: list[ProcessedImage], size: int) -> list[list[ProcessedImage]]:
    ordered = sorted(images, key=lambda im: source_rank(im.candidate.source_type))
    size = max(1, size)
    return [ordered[i : i + size] for i in range(0, len(ordered), size)]


async def run_pipeline(
    deps: PipelineDeps, qid: str, *, refresh: bool = False
) -> AsyncIterator[PipelineEvent]:
    """Stages A-I. ``refresh`` is accepted now and used by the Phase 6 cached path."""
    settings = deps.settings
    run = _Run(
        deps=deps,
        qid=qid,
        started=time.monotonic(),
        deadline=time.monotonic() + settings.hard_deadline_s,
    )

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
    if header.coords is None:
        yield run.warn(WarningCode.no_coordinates)
    if header.commons_category is None:
        yield run.warn(WarningCode.no_commons_category)
    if header.official_website is None:
        yield run.warn(WarningCode.no_official_site)
    if not deps.ai.available:
        yield run.warn(WarningCode.vision_unavailable, deps.ai.unavailable_reason)

    # ---- B. collect
    stage = time.monotonic()
    ctx = SourceContext(settings=settings, http=deps.http, resolved=resolved, deadline=run.deadline)
    sources = build_sources(settings)
    outcomes = await asyncio.gather(
        *(_run_source(source, ctx) for source in sources), return_exceptions=True
    )
    results: list[SourceResult] = []
    for source, outcome in zip(sources, outcomes, strict=True):
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

    # ---- C. normalize
    normalized = normalize_candidates(results, max_candidates=settings.max_candidates)
    log.info(
        "C normalize -> %d candidates (%d duplicate urls, %d cut by caps)",
        normalized.found,
        normalized.dropped_duplicate_urls,
        normalized.dropped_by_caps,
    )

    # ---- D. download (logo hashes fetched alongside for Section 8 logo exclusion)
    stage = time.monotonic()
    download_task = asyncio.create_task(
        download_candidates(
            deps.http,
            normalized.candidates,
            thumbs_dir=settings.thumbs_dir,
            concurrency=settings.download_concurrency,
            stage_timeout_s=DOWNLOAD_STAGE_TIMEOUT_S,
            deadline=run.deadline,
        )
    )
    logo_task = asyncio.create_task(_logo_hashes(deps.http, resolved.logo_filename))
    downloaded = await download_task
    logo = await logo_task
    run.timings["download"] = _ms(stage)

    # ---- E. dedup
    stage = time.monotonic()
    logo_sha1, logo_phash = logo if logo is not None else (None, None)
    deduped = dedupe(downloaded.images, logo_sha1=logo_sha1, logo_phash=logo_phash)
    run.timings["dedup"] = _ms(stage)
    irrelevant_removed = deduped.logo_removed

    # ---- F + G. vision per batch, score, emit
    stage = time.monotonic()
    names = name_terms(header.name, header.local_name, header.aliases)
    admitted = _RunningSelection()
    emitted: list[Photo] = []
    batch_index = 0
    university_images = [
        im for im in deduped.kept if im.candidate.source_type is not SourceType.city_commons
    ]
    city_images = [im for im in deduped.kept if im.candidate.source_type is SourceType.city_commons]
    for target, group in (("university", university_images), ("city", city_images)):
        for batch in _batches(group, settings.vision_batch_size):
            infos = await classify_batch(deps, batch, header, target=target)
            chunk: list[Photo] = []
            for image, info in zip(batch, infos, strict=True):
                photo = build_photo(image, info, names)
                if admitted.admit(photo):
                    chunk.append(photo)
            if chunk:
                emitted.extend(chunk)
                yield PipelineEvent(
                    "photos", {"batch": batch_index, "photos": [_dump(p) for p in chunk]}
                )
                batch_index += 1
    run.timings["vision"] = _ms(stage)

    # ---- H. describe
    stage = time.monotonic()
    description = await describe_campus(deps, resolved)
    run.timings["describe"] = _ms(stage)
    if description is not None:
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
        found=normalized.found,
        duplicates_removed=deduped.removed,
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


async def _logo_hashes(
    client: httpx.AsyncClient, logo_filename: str | None
) -> tuple[str, str] | None:
    """Download the P154 logo (via its Commons imageinfo) and hash it; ``None`` when absent/failed."""
    if not logo_filename:
        return None
    try:
        info = await commons.fetch_file_info(client, logo_filename)
    except Exception:  # a logo problem must never affect the profile
        log.debug("logo info failed", exc_info=True)
        return None
    if not info:
        return None
    url = info.get("thumburl") or info.get("url")
    if not isinstance(url, str) or not url:
        return None
    return await fetch_logo_hashes(client, url)


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
