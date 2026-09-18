"""Section 10 scoring: every worked example, bonuses, rounding, caps and hard rules."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from app.enums import Category, ReasonCode, SourceType, Verification
from app.models import RawCandidate
from app.processing import textmatch
from app.scoring import (
    ScoreResult,
    VisionInfo,
    match_names_in,
    normalize_text,
    round_confidence,
    score_candidate,
    verification_for,
)

# "NU" is shorter than 4 characters and must never match (Section 10)
NAMES = ["Nazarbayev University", "NU", "Назарбаев Университет"]


def _candidate(source_type: SourceType, **overrides: object) -> RawCandidate:
    fields: dict[str, object] = {
        "source_type": source_type,
        "image_url": "https://upload.wikimedia.org/x/y/Photo.jpg",
        "source_page_url": "https://commons.wikimedia.org/wiki/File:Photo.jpg",
        "source_label": "Wikimedia Commons",
    }
    fields.update(overrides)
    return RawCandidate.model_validate(fields)


def _vision(**overrides: object) -> VisionInfo:
    fields: dict[str, object] = {"category": Category.campus}
    fields.update(overrides)
    return VisionInfo.model_validate(fields)


def _score(
    candidate: RawCandidate, vision: VisionInfo | None, texts_match: bool | None = None
) -> ScoreResult:
    return score_candidate(candidate, names=NAMES, texts_match=texts_match, vision=vision)


# ------------------------------------------------------------------ worked examples (Section 10)


def test_commons_category_name_in_filename_and_vision_is_0_90_verified() -> None:
    cand = _candidate(SourceType.commons_category, filename="Nazarbayev_University_main_gate.jpg")
    result = _score(cand, _vision())
    assert result.confidence == 0.90
    assert result.verification is Verification.verified
    assert result.reasons == [
        ReasonCode.commons_category_source,
        ReasonCode.name_in_metadata,
        ReasonCode.vision_consistent,
    ]


def test_commons_category_vision_only_is_0_70_verified() -> None:
    cand = _candidate(SourceType.commons_category, filename="Main_gate_at_night.jpg")
    result = _score(cand, _vision())
    assert result.confidence == 0.70
    assert result.verification is Verification.verified
    assert result.reasons == [ReasonCode.commons_category_source, ReasonCode.vision_consistent]


def test_commons_search_name_and_vision_is_0_60_likely() -> None:
    cand = _candidate(SourceType.commons_search, title="Nazarbayev University in spring")
    result = _score(cand, _vision())
    assert result.confidence == 0.60
    assert result.verification is Verification.likely
    assert result.reasons == [
        ReasonCode.commons_search_source,
        ReasonCode.name_in_metadata,
        ReasonCode.vision_consistent,
    ]


def test_commons_search_name_vision_and_sign_is_0_75_verified() -> None:
    cand = _candidate(SourceType.commons_search, title="Nazarbayev University in spring")
    result = _score(cand, _vision(name_on_sign=True))
    assert result.confidence == 0.75
    assert result.verification is Verification.verified
    assert result.reasons == [
        ReasonCode.commons_search_source,
        ReasonCode.name_in_metadata,
        ReasonCode.vision_consistent,
        ReasonCode.name_on_sign,
    ]


def test_flickr_200m_and_vision_is_0_75_verified() -> None:
    cand = _candidate(SourceType.flickr_geo, distance_m=200.0, title="Dome")
    result = _score(cand, _vision())
    assert result.confidence == 0.75
    assert result.verification is Verification.verified
    assert result.reasons == [
        ReasonCode.flickr_geo_source,
        ReasonCode.geo_within_300m,
        ReasonCode.vision_consistent,
    ]


def test_flickr_800m_and_vision_is_0_65_likely() -> None:
    cand = _candidate(SourceType.flickr_geo, distance_m=800.0, title="Dome")
    result = _score(cand, _vision())
    assert result.confidence == 0.65
    assert result.verification is Verification.likely
    assert result.reasons == [
        ReasonCode.flickr_geo_source,
        ReasonCode.geo_within_1km,
        ReasonCode.vision_consistent,
    ]


def test_official_site_and_vision_is_0_70_verified() -> None:
    cand = _candidate(SourceType.official_site, alt="Main building")
    result = _score(cand, _vision())
    assert result.confidence == 0.70
    assert result.verification is Verification.verified
    assert result.reasons == [ReasonCode.official_site_source, ReasonCode.vision_consistent]


def test_official_site_without_vision_is_0_55_likely() -> None:
    cand = _candidate(SourceType.official_site, alt="Main building")
    result = _score(cand, None)
    assert result.confidence == 0.55
    assert result.verification is Verification.likely
    assert result.reasons == [ReasonCode.official_site_source, ReasonCode.vision_unavailable]


def test_web_search_name_vision_and_sign_is_0_65_likely() -> None:
    cand = _candidate(SourceType.web_search, page_title="Nazarbayev University - Wikipedia")
    result = _score(cand, _vision(name_on_sign=True))
    assert result.confidence == 0.65
    assert result.verification is Verification.likely
    assert result.reasons == [
        ReasonCode.web_search_source,
        ReasonCode.name_in_metadata,
        ReasonCode.vision_consistent,
        ReasonCode.name_on_sign,
    ]


# ------------------------------------------------------------------------------ base and bonuses


@pytest.mark.parametrize(
    ("source_type", "base", "reason"),
    [
        (SourceType.wikidata_p18, 0.60, ReasonCode.wikidata_main_image),
        (SourceType.official_site, 0.55, ReasonCode.official_site_source),
        (SourceType.commons_category, 0.55, ReasonCode.commons_category_source),
        (SourceType.city_commons, 0.55, ReasonCode.city_category_source),
        (SourceType.flickr_geo, 0.40, ReasonCode.flickr_geo_source),
        (SourceType.commons_search, 0.25, ReasonCode.commons_search_source),
        (SourceType.web_search, 0.15, ReasonCode.web_search_source),
    ],
)
def test_base_score_per_source(source_type: SourceType, base: float, reason: ReasonCode) -> None:
    result = _score(_candidate(source_type), None)
    assert result.confidence == base
    assert result.reasons[0] is reason


def test_commons_search_alone_is_unverified() -> None:
    result = _score(_candidate(SourceType.commons_search, title="Some building"), None)
    assert result.confidence == 0.25
    assert result.verification is Verification.unverified
    assert result.reasons == [ReasonCode.commons_search_source, ReasonCode.vision_unavailable]


@pytest.mark.parametrize("source_type", [SourceType.official_site, SourceType.city_commons])
def test_name_bonus_not_applied_to_official_site_and_city_commons(
    source_type: SourceType,
) -> None:
    cand = _candidate(source_type, title="Nazarbayev University", filename="NU_building.jpg")
    result = _score(cand, _vision(), texts_match=True)
    assert result.confidence == 0.70
    assert ReasonCode.name_in_metadata not in result.reasons


@pytest.mark.parametrize("field", ["title", "description", "filename", "alt", "page_title"])
def test_name_bonus_from_each_metadata_field(field: str) -> None:
    cand = _candidate(SourceType.commons_search, **{field: "the Nazarbayev University campus"})
    result = _score(cand, None)
    assert ReasonCode.name_in_metadata in result.reasons
    assert result.confidence == 0.45


def test_name_bonus_requires_a_match() -> None:
    cand = _candidate(SourceType.commons_search, title="Random building", filename="x.jpg")
    assert ReasonCode.name_in_metadata not in _score(cand, None).reasons


def test_name_bonus_ignores_aliases_shorter_than_4() -> None:
    cand = _candidate(SourceType.commons_search, title="NU main gate", filename="NU_gate.jpg")
    assert ReasonCode.name_in_metadata not in _score(cand, None).reasons


def test_name_bonus_matches_local_name_in_cyrillic() -> None:
    cand = _candidate(SourceType.commons_search, description="Корпус Назарбаев Университета")
    assert ReasonCode.name_in_metadata in _score(cand, None).reasons


def test_texts_match_argument_overrides_metadata_lookup() -> None:
    cand = _candidate(SourceType.commons_search, title="Nazarbayev University")
    assert ReasonCode.name_in_metadata not in _score(cand, None, texts_match=False).reasons
    cand2 = _candidate(SourceType.commons_search, title="nothing here")
    assert ReasonCode.name_in_metadata in _score(cand2, None, texts_match=True).reasons


@pytest.mark.parametrize(
    ("distance", "bonus", "reason"),
    [
        (0.0, 0.20, ReasonCode.geo_within_300m),
        (299.9, 0.20, ReasonCode.geo_within_300m),
        (300.0, 0.10, ReasonCode.geo_within_1km),
        (999.9, 0.10, ReasonCode.geo_within_1km),
        (1000.0, 0.0, None),
        (None, 0.0, None),
    ],
)
def test_geo_bonus_thresholds(
    distance: float | None, bonus: float, reason: ReasonCode | None
) -> None:
    result = _score(_candidate(SourceType.flickr_geo, distance_m=distance), None)
    assert result.confidence == round(0.40 + bonus, 2)
    geo_reasons = [r for r in result.reasons if r.value.startswith("geo_")]
    assert geo_reasons == ([reason] if reason else [])


def test_only_one_geo_bonus_applies() -> None:
    result = _score(_candidate(SourceType.flickr_geo, distance_m=100.0), None)
    assert ReasonCode.geo_within_300m in result.reasons
    assert ReasonCode.geo_within_1km not in result.reasons


@pytest.mark.parametrize(
    "vision",
    [
        _vision(is_photo=False),
        _vision(plausibly_university_related=False),
        _vision(category=Category.other),
        _vision(available=False),
        _vision(timed_out=True),
    ],
)
def test_vision_consistent_requires_every_condition(vision: VisionInfo) -> None:
    result = _score(_candidate(SourceType.commons_category), vision)
    assert ReasonCode.vision_consistent not in result.reasons
    assert result.confidence == 0.55


def test_vision_category_none_counts_as_consistent() -> None:
    result = _score(_candidate(SourceType.commons_category), VisionInfo())
    assert ReasonCode.vision_consistent in result.reasons
    assert result.confidence == 0.70


def test_name_on_sign_ignored_when_vision_unusable() -> None:
    unavailable = _score(
        _candidate(SourceType.commons_category), _vision(available=False, name_on_sign=True)
    )
    assert ReasonCode.name_on_sign not in unavailable.reasons
    timed_out = _score(
        _candidate(SourceType.commons_category), _vision(timed_out=True, name_on_sign=True)
    )
    assert ReasonCode.name_on_sign not in timed_out.reasons


# ---------------------------------------------------------------------- rounding, cap, thresholds


def test_confidence_is_capped_at_1_0() -> None:
    cand = _candidate(SourceType.wikidata_p18, title="Nazarbayev University", distance_m=10.0)
    result = _score(cand, _vision(name_on_sign=True))  # 0.60+0.20+0.20+0.15+0.15 = 1.30
    assert result.confidence == 1.0
    assert result.verification is Verification.verified
    assert result.reasons == [
        ReasonCode.wikidata_main_image,
        ReasonCode.name_in_metadata,
        ReasonCode.geo_within_300m,
        ReasonCode.vision_consistent,
        ReasonCode.name_on_sign,
    ]


def test_float_sums_are_rounded_to_two_decimals() -> None:
    # 0.55 + 0.15 is 0.7000000000000001 in binary floating point
    result = _score(_candidate(SourceType.commons_category), _vision())
    assert result.confidence == 0.7
    assert result.confidence == round(result.confidence, 2)
    # 0.15 + 0.20 + 0.15 + 0.15 accumulates to 0.65 only after rounding
    result = _score(
        _candidate(SourceType.web_search, title="Nazarbayev University"), _vision(name_on_sign=True)
    )
    assert result.confidence == 0.65


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.7000000000000001, 0.70), (0.6999999999999, 0.70), (1.3, 1.0), (0.25, 0.25), (0.0, 0.0)],
)
def test_round_confidence(value: float, expected: float) -> None:
    assert round_confidence(value) == expected


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [
        (1.0, Verification.verified),
        (0.70, Verification.verified),
        (0.69, Verification.likely),
        (0.40, Verification.likely),
        (0.39, Verification.unverified),
        (0.0, Verification.unverified),
    ],
)
def test_verification_thresholds(confidence: float, expected: Verification) -> None:
    assert verification_for(confidence) is expected


def test_boundary_0_70_is_verified_and_0_65_is_likely() -> None:
    assert _score(_candidate(SourceType.commons_category), _vision()).verification is (
        Verification.verified
    )
    assert (
        _score(_candidate(SourceType.flickr_geo, distance_m=500.0), _vision()).verification
        is Verification.likely
    )


# ---------------------------------------------------------------------------------- hard rules


def test_vision_none_caps_at_likely_with_reason() -> None:
    cand = _candidate(SourceType.wikidata_p18, title="Nazarbayev University", distance_m=50.0)
    result = _score(cand, None)
    assert result.confidence == 1.0
    assert result.verification is Verification.likely
    assert result.reasons[-1] is ReasonCode.vision_unavailable


def test_vision_unavailable_caps_at_likely_with_reason() -> None:
    cand = _candidate(SourceType.commons_category, filename="Nazarbayev_University.jpg")  # 0.75
    result = _score(cand, _vision(available=False))
    assert result.confidence == 0.75
    assert result.verification is Verification.likely
    assert result.reasons == [
        ReasonCode.commons_category_source,
        ReasonCode.name_in_metadata,
        ReasonCode.vision_unavailable,
    ]


def test_vision_timeout_caps_at_likely_with_reason() -> None:
    cand = _candidate(SourceType.commons_category, filename="Nazarbayev_University.jpg")  # 0.75
    result = _score(cand, _vision(timed_out=True))
    assert result.confidence == 0.75
    assert result.verification is Verification.likely
    assert result.reasons == [
        ReasonCode.commons_category_source,
        ReasonCode.name_in_metadata,
        ReasonCode.vision_timeout,
    ]
    assert ReasonCode.vision_unavailable not in result.reasons


def test_vision_timeout_wins_over_unavailable_when_both_set() -> None:
    result = _score(
        _candidate(SourceType.commons_category), _vision(available=False, timed_out=True)
    )
    assert result.reasons == [ReasonCode.commons_category_source, ReasonCode.vision_timeout]


def test_hard_rule_does_not_change_confidence_or_lower_below_likely() -> None:
    unverified = _score(_candidate(SourceType.commons_search), None)
    assert unverified.verification is Verification.unverified
    likely = _score(_candidate(SourceType.flickr_geo, distance_m=800.0), None)  # 0.50
    assert likely.confidence == 0.50
    assert likely.verification is Verification.likely


def test_web_search_never_verified_even_if_forced_over_threshold() -> None:
    # 0.15 + 0.20 (name) + 0.20 (geo, hypothetically) + 0.15 + 0.15 = 0.85 -> still likely
    cand = _candidate(SourceType.web_search, title="Nazarbayev University", distance_m=10.0)
    result = _score(cand, _vision(name_on_sign=True))
    assert result.confidence == 0.85
    assert result.verification is Verification.likely
    assert ReasonCode.vision_unavailable not in result.reasons


def test_reason_order_is_stable() -> None:
    cand = _candidate(SourceType.flickr_geo, title="Nazarbayev University", distance_m=500.0)
    result = _score(cand, _vision(name_on_sign=True, timed_out=True))
    assert result.reasons == [
        ReasonCode.flickr_geo_source,
        ReasonCode.name_in_metadata,
        ReasonCode.geo_within_1km,
        ReasonCode.vision_timeout,
    ]


# ------------------------------------------------------------------- text matching + textmatch


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Massachusetts Institute of Technology", "massachusetts institute of technology"),
        ("  MIT—Great  Dome.jpg ", "mit great dome jpg"),
        ("ETH_Zurich_main_building.jpg", "eth zurich main building jpg"),
        ("Université de Montréal", "universite de montreal"),
        ("Назарбаев Университет", "назарбаев университет"),
        ("бассейн", "бассеин"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_text(raw: str | None, expected: str) -> None:
    assert normalize_text(raw) == expected


def test_normalize_text_is_the_textmatch_normalizer() -> None:
    # one implementation: selection.py imports normalize_text, scoring delegates to textmatch
    assert normalize_text is textmatch.normalize


def test_match_names_in_requires_min_length_and_normalizes() -> None:
    assert match_names_in(["MIT"], ["MIT dome"]) is False  # alias shorter than 4
    assert match_names_in(["ETH Zürich"], ["ETH_Zurich_main_building.jpg"]) is True
    assert (
        match_names_in(["Nazarbayev University"], [None, "", "NAZARBAYEV UNIVERSITY gate"]) is True
    )
    assert match_names_in(["Nazarbayev University"], ["Astana skyline"]) is False
    assert match_names_in([], ["anything"]) is False


def test_scoring_delegates_to_textmatch_with_the_five_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], list[str | None]]] = []

    def fake_match_names(names: Iterable[str | None], texts: Iterable[str | None]) -> bool:
        calls.append(([n for n in names if n is not None], list(texts)))
        return True

    monkeypatch.setattr("app.scoring.match_names", fake_match_names)

    cand = _candidate(SourceType.commons_search, title="t", description="d", filename="f")
    result = _score(cand, None)
    assert ReasonCode.name_in_metadata in result.reasons
    assert calls == [(NAMES, ["t", "d", "f", None, None])]


def test_score_result_is_serializable() -> None:
    result = _score(_candidate(SourceType.commons_category), _vision())
    dumped = result.model_dump(mode="json")
    assert dumped == {
        "confidence": 0.7,
        "verification": "verified",
        "reasons": ["commons_category_source", "vision_consistent"],
    }
