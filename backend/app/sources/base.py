"""Shared contracts for image sources (SPEC Section 7, Stage B "collect").

A source is anything that turns the resolved university into ``RawCandidate`` objects. The
contract every source honours:

* ``fetch`` never raises -- a failure becomes ``SourceResult.error`` plus a
  ``source_unavailable`` warning, keeping whatever candidates were gathered before it;
* a source that is simply not applicable (no Commons category, no coordinates, no P18) returns
  an empty result, with the applicable warning if the spec names one;
* no new sub-request is started when less than ``MIN_REMAINING_S`` of the hard deadline is left.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from app.config import Settings
from app.enums import Category, SourceType, WarningCode
from app.models import Coordinates, DateKind, RawCandidate, Warning
from app.resolver.wikidata import ResolvedEntity

log = logging.getLogger("app.sources")

MIN_REMAINING_S = 1.0
MAX_TEXT_LEN = 300  # title / description / alt / page_title / filename
MAX_AUTHOR_LEN = 80
MAX_LICENSE_LEN = 80


@dataclass
class SourceContext:
    """Everything a source needs: settings, the shared client, the entity and the deadline."""

    settings: Settings
    http: httpx.AsyncClient
    resolved: ResolvedEntity
    deadline: float  # time.monotonic() value of the pipeline's hard deadline

    def remaining_s(self) -> float:
        return self.deadline - time.monotonic()

    def can_start_request(self) -> bool:
        return self.remaining_s() >= MIN_REMAINING_S

    def budget(self) -> RequestBudget:
        return RequestBudget(deadline=self.deadline)


@dataclass
class RequestBudget:
    """Deadline gate + failure log shared by the sub-requests of one source.

    Helpers in ``app.sources.commons`` / ``app.sources.flickr`` never raise; they record what
    went wrong here so the owning source can report it in ``SourceResult.error``.
    """

    deadline: float | None = None
    errors: list[str] = field(default_factory=list)
    skipped: int = 0

    def remaining_s(self) -> float | None:
        return None if self.deadline is None else self.deadline - time.monotonic()

    def can_start_request(self) -> bool:
        remaining = self.remaining_s()
        return remaining is None or remaining >= MIN_REMAINING_S

    def skip(self, what: str) -> None:
        self.skipped += 1
        log.info("skipping %s: less than %.1f s of the deadline left", what, MIN_REMAINING_S)

    def fail(self, what: str, exc: BaseException) -> None:
        self.errors.append(f"{what}: {describe_error(exc)}")
        log.warning("%s failed: %s", what, describe_error(exc))

    @property
    def error(self) -> str | None:
        return "; ".join(self.errors) if self.errors else None


@dataclass
class SourceResult:
    name: str
    source_type: SourceType
    candidates: list[RawCandidate] = field(default_factory=list)
    warnings: list[Warning] = field(default_factory=list)
    error: str | None = None
    elapsed_ms: int = 0


class Source(Protocol):
    name: str
    source_type: SourceType

    async def fetch(self, ctx: SourceContext) -> SourceResult: ...


class BaseSource:
    """Timing + the never-raise guard; subclasses implement ``collect``."""

    name: str = "base"
    source_type: SourceType = SourceType.commons_search

    async def collect(self, ctx: SourceContext, result: SourceResult) -> None:
        """Fill ``result.candidates`` / ``result.warnings``; may raise, ``fetch`` catches."""
        raise NotImplementedError

    async def fetch(self, ctx: SourceContext) -> SourceResult:
        started = time.monotonic()
        result = SourceResult(name=self.name, source_type=self.source_type)
        try:
            await self.collect(ctx, result)
        except Exception as exc:  # noqa: BLE001 - a source must never take the pipeline down
            log.warning("source %s crashed: %s", self.name, describe_error(exc))
            result.error = f"{self.name}: {describe_error(exc)}"
        # "source unavailable" is only honest when the source contributed nothing; a partial
        # failure (one subcategory, one search leg) is logged but the photos it did find count
        if (
            result.error
            and not result.candidates
            and not any(w.code == WarningCode.source_unavailable for w in result.warnings)
        ):
            result.warnings.append(Warning(code=WarningCode.source_unavailable, detail=self.name))
        result.elapsed_ms = int((time.monotonic() - started) * 1000)
        log.info(
            "source %s: %d candidates in %d ms%s",
            self.name,
            len(result.candidates),
            result.elapsed_ms,
            f" (error: {result.error})" if result.error else "",
        )
        return result


def describe_error(exc: BaseException) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    text = str(exc).strip()
    name = type(exc).__name__
    return f"{name}: {text}" if text else name


def apply_budget(result: SourceResult, budget: RequestBudget) -> None:
    """Copy the sub-request failures of ``budget`` into ``result`` (warning added by ``fetch``)."""
    if budget.errors:
        result.error = budget.error


def is_http_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if text != value or any(ch.isspace() for ch in text):
        return False
    try:
        url = httpx.URL(text)
    except (ValueError, httpx.InvalidURL):
        return False
    return url.scheme in ("http", "https") and bool(url.host)


def clip_text(value: object, limit: int) -> str | None:
    """Whitespace-collapsed, truncated text; ``None`` when empty or not a string."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text:
        return None
    return text[:limit]


def build_candidate(
    *,
    source_type: SourceType,
    image_url: object,
    source_page_url: object,
    source_label: str,
    title: object = None,
    description: object = None,
    alt: object = None,
    author: object = None,
    license: object = None,
    date: str | None = None,
    date_kind: DateKind = "unknown",
    geo: Coordinates | None = None,
    distance_m: float | None = None,
    page_title: object = None,
    filename: object = None,
    width: int | None = None,
    height: int | None = None,
    source_hint_category: Category | None = None,
) -> RawCandidate | None:
    """A ``RawCandidate`` with validated http(s) URLs and clipped text; ``None`` if unusable."""
    if not is_http_url(image_url) or not is_http_url(source_page_url):
        return None
    return RawCandidate(
        source_type=source_type,
        image_url=str(image_url),
        source_page_url=str(source_page_url),
        source_label=source_label,
        title=clip_text(title, MAX_TEXT_LEN),
        description=clip_text(description, MAX_TEXT_LEN),
        alt=clip_text(alt, MAX_TEXT_LEN),
        author=clip_text(author, MAX_AUTHOR_LEN),
        license=clip_text(license, MAX_LICENSE_LEN),
        date=date,
        date_kind=date_kind,
        geo=geo,
        distance_m=distance_m,
        page_title=clip_text(page_title, MAX_TEXT_LEN),
        filename=clip_text(filename, MAX_TEXT_LEN),
        width=width,
        height=height,
        source_hint_category=source_hint_category,
    )


def dedupe_by_url(candidates: list[RawCandidate]) -> list[RawCandidate]:
    """Drop repeated ``image_url`` values, keeping the first occurrence (API order)."""
    seen: set[str] = set()
    unique: list[RawCandidate] = []
    for candidate in candidates:
        if candidate.image_url in seen:
            continue
        seen.add(candidate.image_url)
        unique.append(candidate)
    return unique
