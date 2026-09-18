"""Deterministic scoring and verification (SPEC Section 10, Stage G).

``confidence = min(1.0, base + sum(bonuses))`` rounded to 2 decimals, a label from fixed
thresholds, then the hard rules (Section 2 rule 4): a vision verdict alone never yields
``verified``, and neither does a web-search image.  Reason codes are appended in a stable
order: base reason, bonuses in spec order, hard-rule reasons.

Text normalization and name matching for the ``name_in_metadata`` bonus live in
``app.processing.textmatch`` (the single implementation); ``normalize_text`` is re-exported from
there for ``app.selection``.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, Field

from app.enums import Category, ReasonCode, SourceType, Verification
from app.models import RawCandidate
from app.processing.textmatch import match_names, normalize

# base score and its reason per source (Section 10 table)
BASE_SCORE: dict[SourceType, tuple[float, ReasonCode]] = {
    SourceType.wikidata_p18: (0.60, ReasonCode.wikidata_main_image),
    SourceType.official_site: (0.55, ReasonCode.official_site_source),
    SourceType.commons_category: (0.55, ReasonCode.commons_category_source),
    SourceType.city_commons: (0.55, ReasonCode.city_category_source),
    SourceType.commons_geo: (0.40, ReasonCode.commons_geo_source),
    SourceType.flickr_geo: (0.40, ReasonCode.flickr_geo_source),
    SourceType.commons_search: (0.25, ReasonCode.commons_search_source),
    SourceType.web_search: (0.15, ReasonCode.web_search_source),
}

NAME_IN_METADATA_BONUS = 0.20
GEO_WITHIN_300M_BONUS = 0.20
GEO_WITHIN_1KM_BONUS = 0.10
VISION_CONSISTENT_BONUS = 0.15
NAME_ON_SIGN_BONUS = 0.15

GEO_NEAR_M = 300.0
GEO_FAR_M = 1000.0

VERIFIED_MIN = 0.70
LIKELY_MIN = 0.40

# the name bonus is "already implied" for these sources (Section 10)
NAME_BONUS_EXCLUDED: frozenset[SourceType] = frozenset(
    {SourceType.official_site, SourceType.city_commons}
)
# web-search results can never reach verified (Section 2 rule 4)
CAPPED_AT_LIKELY: frozenset[SourceType] = frozenset({SourceType.web_search})

# Section 10 normalization (NFKD, drop combining marks, casefold, punctuation and ``_`` -> space)
normalize_text = normalize


class VisionInfo(BaseModel):
    """What the vision stage (Section 9) knows about one image, as scoring needs it.

    ``available=False`` means the model failed or there is no key (reason ``vision_unavailable``);
    ``timed_out=True`` means the deadline monitor skipped the image (reason ``vision_timeout``).
    """

    available: bool = True
    timed_out: bool = False
    is_photo: bool = True
    plausibly_university_related: bool = True
    category: Category | None = None
    category_confidence: float | None = None
    name_on_sign: bool = False
    visible_text: str | None = None
    people_prominent: bool = False
    quality_ok: bool = True
    reason: str | None = None

    @property
    def usable(self) -> bool:
        """True when a real model verdict exists for this image."""
        return self.available and not self.timed_out

    @property
    def consistent(self) -> bool:
        """Section 10 ``vision_consistent``: succeeded, is_photo, plausibly related, not other."""
        return (
            self.usable
            and self.is_photo
            and self.plausibly_university_related
            and self.category != Category.other
        )


class ScoreResult(BaseModel):
    confidence: float  # 0.0-1.0, 2 decimals
    verification: Verification
    reasons: list[ReasonCode] = Field(default_factory=list)


def match_names_in(names: Iterable[str | None], texts: Iterable[str | None]) -> bool:
    """``name_in_metadata`` test: any usable name (>= 4 chars) occurs in any text.

    Delegates to ``textmatch.match_names`` (normalization + token-boundary matching).
    """
    return match_names(names, texts)


def metadata_texts(candidate: RawCandidate) -> list[str | None]:
    """The five fields the ``name_in_metadata`` bonus looks at (Section 10)."""
    return [
        candidate.title,
        candidate.description,
        candidate.filename,
        candidate.alt,
        candidate.page_title,
    ]


def round_confidence(value: float) -> float:
    """``min(1.0, value)`` rounded to 2 decimals; the epsilon absorbs float sums like 0.6999."""
    return round(min(1.0, value) + 1e-9, 2)


def verification_for(confidence: float) -> Verification:
    """Section 10 thresholds: >= 0.70 verified, 0.40..0.70 likely, else unverified."""
    if confidence >= VERIFIED_MIN:
        return Verification.verified
    if confidence >= LIKELY_MIN:
        return Verification.likely
    return Verification.unverified


def _at_most_likely(verification: Verification) -> Verification:
    if verification is Verification.verified:
        return Verification.likely
    return verification


def score_candidate(
    candidate: RawCandidate,
    *,
    names: list[str],
    texts_match: bool | None = None,
    vision: VisionInfo | None,
) -> ScoreResult:
    """Score one image exactly as Section 10 prescribes.

    ``names`` is the university name plus aliases; ``texts_match`` lets the caller pass a
    precomputed name-in-metadata verdict (``None`` = compute it here).  ``vision=None`` means no
    vision stage ran at all (treated as unavailable).
    """
    base, base_reason = BASE_SCORE[candidate.source_type]
    total = base
    reasons: list[ReasonCode] = [base_reason]

    if candidate.source_type not in NAME_BONUS_EXCLUDED:
        matched = (
            match_names_in(names, metadata_texts(candidate)) if texts_match is None else texts_match
        )
        if matched:
            total += NAME_IN_METADATA_BONUS
            reasons.append(ReasonCode.name_in_metadata)

    distance = candidate.distance_m
    if distance is not None:
        if distance < GEO_NEAR_M:
            total += GEO_WITHIN_300M_BONUS
            reasons.append(ReasonCode.geo_within_300m)
        elif distance < GEO_FAR_M:
            total += GEO_WITHIN_1KM_BONUS
            reasons.append(ReasonCode.geo_within_1km)

    if vision is not None and vision.consistent:
        total += VISION_CONSISTENT_BONUS
        reasons.append(ReasonCode.vision_consistent)

    if vision is not None and vision.usable and vision.name_on_sign:
        total += NAME_ON_SIGN_BONUS
        reasons.append(ReasonCode.name_on_sign)

    confidence = round_confidence(total)
    verification = verification_for(confidence)

    # hard rules, applied after the thresholds
    if vision is not None and vision.timed_out:
        verification = _at_most_likely(verification)
        reasons.append(ReasonCode.vision_timeout)
    elif vision is None or not vision.available:
        verification = _at_most_likely(verification)
        reasons.append(ReasonCode.vision_unavailable)

    if candidate.source_type in CAPPED_AT_LIKELY:
        verification = _at_most_likely(verification)

    return ScoreResult(confidence=confidence, verification=verification, reasons=reasons)
