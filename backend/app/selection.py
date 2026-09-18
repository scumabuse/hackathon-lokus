"""Selection, caps, heuristic categories and warnings (SPEC Section 11, Stage I).

Pure functions over already-scored photos: nothing here touches the network or the clock.
"""

from __future__ import annotations

import re
from collections import Counter

from pydantic import BaseModel, Field

from app.enums import Category, SourceType, Verification, WarningCode, source_rank
from app.models import CategorySource, Photo, RawCandidate, Stats, Warning
from app.scoring import normalize_text

PER_CATEGORY_CAP = 12
CITY_CAP = 6
TOTAL_SHOWN_CAP = 45
HIDDEN_CAP = 15
LOW_DATA_MIN_SHOWN = 6

# categories whose absence is reported as missing_category (Section 11.5), in this order
REPORTED_CATEGORIES: tuple[Category, ...] = (
    Category.campus,
    Category.dormitory,
    Category.classroom,
    Category.library,
    Category.city,
)

_VERIFICATION_ORDER: dict[Verification, int] = {
    Verification.verified: 0,
    Verification.likely: 1,
    Verification.unverified: 2,
}


def _keyword_pattern(keywords: list[str]) -> re.Pattern[str]:
    """Compile an alternation whose plain-word branches are normalized like the text they match.

    NFKD splits Cyrillic ``й`` / ``ё`` into a base letter plus a combining mark that Section 10
    normalization drops, so ``бассейн`` must become ``бассеин`` on the pattern side too.  Branches
    with regex syntax (``\\blab\\b``) are kept verbatim.
    """
    branches = [normalize_text(k) if k.isalpha() else k for k in keywords]
    return re.compile("|".join(branches))


# Section 11.4 keyword rules, in precedence order (first match wins)
HEURISTIC_RULES: tuple[tuple[Category, re.Pattern[str]], ...] = (
    (Category.dormitory, _keyword_pattern(["dorm", "hostel", "residen", "общежит", "жатақхана"])),
    (Category.library, _keyword_pattern(["librar", "библиотек", "кітапхана"])),
    (Category.lab, _keyword_pattern([r"\blab\b", "laborator", "лаборатор"])),
    (
        Category.classroom,
        _keyword_pattern(["lecture", "auditorium", "classroom", "аудитор", "лекци"]),
    ),
    (
        Category.sport,
        _keyword_pattern(["sport", "stadium", "gym", "pool", "спорт", "стадион", "бассейн"]),
    ),
    (
        Category.student_life,
        _keyword_pattern(["student", "graduat", "ceremon", "festival", "студент", "выпуск"]),
    ),
)


def heuristic_text(candidate: RawCandidate) -> str:
    """``filename + title + page_title`` normalized (Section 11.4)."""
    parts = [candidate.filename, candidate.title, candidate.page_title]
    return normalize_text(" ".join(p for p in parts if p))


def heuristic_category(candidate: RawCandidate) -> tuple[Category, CategorySource]:
    """Category without a vision verdict (Section 11.4).

    A Commons subcategory hint wins outright (``source_hint``).  City-category images are always
    ``city`` (Section 9 forces that even against the model), then the keyword rules in spec order,
    else ``campus``.  The caller appends ``ReasonCode.category_heuristic``.
    """
    if candidate.source_hint_category is not None:
        return candidate.source_hint_category, "source_hint"
    if candidate.source_type is SourceType.city_commons:
        return Category.city, "heuristic"
    text = heuristic_text(candidate)
    if text:
        for category, pattern in HEURISTIC_RULES:
            if pattern.search(text):
                return category, "heuristic"
    return Category.campus, "heuristic"


class Selection(BaseModel):
    shown: list[Photo] = Field(default_factory=list)  # verified + likely, sorted and capped
    hidden: list[Photo] = Field(default_factory=list)  # up to 15 unverified, best first
    warnings: list[Warning] = Field(default_factory=list)
    cut_by_caps: int = 0  # shown photos dropped by the category / city / total caps


def shown_sort_key(photo: Photo) -> tuple[int, float, int]:
    """Section 11.2: verified first, confidence desc, SOURCE_PRIORITY."""
    return (
        _VERIFICATION_ORDER.get(photo.verification, len(_VERIFICATION_ORDER)),
        -photo.confidence,
        source_rank(photo.source_type),
    )


def hidden_sort_key(photo: Photo) -> tuple[float, int]:
    """Section 11.3: highest confidence first (source priority breaks ties)."""
    return (-photo.confidence, source_rank(photo.source_type))


def category_cap(category: Category) -> int:
    return CITY_CAP if category is Category.city else PER_CATEGORY_CAP


def apply_caps(sorted_shown: list[Photo]) -> tuple[list[Photo], int]:
    """Per-category cap 12, city cap 6, total cap 45; returns (kept, cut_count)."""
    kept: list[Photo] = []
    per_category: Counter[Category] = Counter()
    cut = 0
    for photo in sorted_shown:
        if len(kept) >= TOTAL_SHOWN_CAP or per_category[photo.category] >= category_cap(
            photo.category
        ):
            cut += 1
            continue
        per_category[photo.category] += 1
        kept.append(photo)
    return kept, cut


def selection_warnings(shown: list[Photo]) -> list[Warning]:
    """``low_data`` and ``missing_category:<name>`` (Section 11.5, the selection-owned ones)."""
    warnings: list[Warning] = []
    if len(shown) < LOW_DATA_MIN_SHOWN:
        warnings.append(Warning(code=WarningCode.low_data))
    present = {photo.category for photo in shown}
    warnings.extend(
        Warning(code=WarningCode.missing_category, detail=category.value)
        for category in REPORTED_CATEGORIES
        if category not in present
    )
    return warnings


def finalize_selection(photos: list[Photo]) -> Selection:
    """Section 11 steps 1-3 and 5: split, sort, cap, pick hidden, warn."""
    shown_all = [p for p in photos if p.verification is not Verification.unverified]
    hidden_all = [p for p in photos if p.verification is Verification.unverified]

    shown, cut = apply_caps(sorted(shown_all, key=shown_sort_key))
    hidden = sorted(hidden_all, key=hidden_sort_key)[:HIDDEN_CAP]
    return Selection(
        shown=shown, hidden=hidden, warnings=selection_warnings(shown), cut_by_caps=cut
    )


def build_stats(
    selection: Selection,
    *,
    found: int,
    duplicates_removed: int,
    irrelevant_removed: int,
    per_source: dict[str, int],
    timings_ms: dict[str, int],
    total_ms: int,
) -> Stats:
    """Assemble ``Stats`` (Section 11.6); ``timings_ms['total']`` is set from ``total_ms``."""
    timings = dict(timings_ms)
    timings.setdefault("total", total_ms)
    return Stats(
        found=found,
        duplicates_removed=duplicates_removed,
        irrelevant_removed=irrelevant_removed,
        shown=len(selection.shown),
        hidden_unverified=len(selection.hidden),
        per_source=dict(per_source),
        timings_ms=timings,
        total_ms=total_ms,
    )
