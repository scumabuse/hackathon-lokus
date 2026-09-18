"""Section 11: heuristic categories, split / sort / caps, hidden list, warnings, stats."""

from __future__ import annotations

import itertools

import pytest

from app.enums import Category, ReasonCode, SourceType, Verification, WarningCode
from app.models import Photo, RawCandidate, Warning
from app.selection import (
    CITY_CAP,
    HIDDEN_CAP,
    PER_CATEGORY_CAP,
    TOTAL_SHOWN_CAP,
    Selection,
    build_stats,
    finalize_selection,
    heuristic_category,
    heuristic_text,
)

_ids = itertools.count(1)


def _photo(
    verification: Verification = Verification.verified,
    confidence: float = 0.9,
    category: Category = Category.campus,
    source_type: SourceType = SourceType.commons_category,
) -> Photo:
    n = next(_ids)
    return Photo(
        id=f"{n:016x}",
        thumb_url=f"/api/thumb/{n:016x}.jpg",
        image_url=f"https://upload.wikimedia.org/{n}.jpg",
        source_page_url=f"https://commons.wikimedia.org/wiki/File:{n}.jpg",
        source_type=source_type,
        source_label="Wikimedia Commons",
        category=category,
        category_source="vision",
        confidence=confidence,
        verification=verification,
        reasons=[ReasonCode.commons_category_source],
    )


def _candidate(
    source_type: SourceType = SourceType.commons_category, **overrides: object
) -> RawCandidate:
    fields: dict[str, object] = {
        "source_type": source_type,
        "image_url": "https://upload.wikimedia.org/x/y/Photo.jpg",
        "source_page_url": "https://commons.wikimedia.org/wiki/File:Photo.jpg",
        "source_label": "Wikimedia Commons",
    }
    fields.update(overrides)
    return RawCandidate.model_validate(fields)


def _codes(warnings: list[Warning]) -> list[tuple[WarningCode, str | None]]:
    return [(w.code, w.detail) for w in warnings]


# ---------------------------------------------------------------------------- heuristic category


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("Main_Dormitory_Building.jpg", Category.dormitory),
        ("Student hostel no 3.jpg", Category.dormitory),
        ("Student residence hall.jpg", Category.dormitory),  # dormitory outranks student_life
        ("Общежитие №3.jpg", Category.dormitory),
        ("Жатақхана.jpg", Category.dormitory),
        ("Central Library reading room.jpg", Category.library),
        ("Библиотека университета.jpg", Category.library),
        ("Кітапхана.jpg", Category.library),
        ("Physics lab.jpg", Category.lab),
        ("Chemistry Laboratory.jpg", Category.lab),
        ("Лаборатория физики.jpg", Category.lab),
        ("Lecture hall A.jpg", Category.classroom),
        ("Main Auditorium.jpg", Category.classroom),
        ("Classroom 101.jpg", Category.classroom),
        ("Аудитория 101.jpg", Category.classroom),
        ("Лекция по математике.jpg", Category.classroom),
        ("University stadium.jpg", Category.sport),
        ("Sports complex.jpg", Category.sport),
        ("Gym interior.jpg", Category.sport),
        ("Swimming pool.jpg", Category.sport),
        ("Спортзал.jpg", Category.sport),
        ("Стадион.jpg", Category.sport),
        ("Бассейн университета.jpg", Category.sport),  # NFKD splits the й: keyword normalized too
        ("Graduation ceremony 2019.jpg", Category.student_life),
        ("Students on campus.jpg", Category.student_life),
        ("Spring festival.jpg", Category.student_life),
        ("Студенты.jpg", Category.student_life),
        ("Выпускной 2020.jpg", Category.student_life),
        ("Main building.jpg", Category.campus),
        ("Aerial view.jpg", Category.campus),
        ("Collaboration space.jpg", Category.campus),  # "lab" only as a whole word
        ("Labs.jpg", Category.campus),
    ],
)
def test_heuristic_keywords(filename: str, expected: Category) -> None:
    category, source = heuristic_category(_candidate(filename=filename))
    assert category is expected
    assert source == "heuristic"


def test_heuristic_lab_word_boundary_variants() -> None:
    assert heuristic_category(_candidate(filename="Lab_1.jpg"))[0] is Category.lab
    assert heuristic_category(_candidate(title="Computer lab"))[0] is Category.lab
    assert heuristic_category(_candidate(title="Collaboration"))[0] is Category.campus
    assert heuristic_category(_candidate(title="Labour day"))[0] is Category.campus


def test_heuristic_uses_title_and_page_title_too() -> None:
    assert heuristic_category(_candidate(title="Reading room of the library"))[0] is (
        Category.library
    )
    assert heuristic_category(_candidate(page_title="File:Dorm.jpg"))[0] is Category.dormitory


def test_heuristic_order_first_rule_wins() -> None:
    # dormitory (residen) before student_life (student); library before lab
    assert heuristic_category(_candidate(title="Student residence"))[0] is Category.dormitory
    assert heuristic_category(_candidate(title="Library lab"))[0] is Category.library


def test_heuristic_is_case_and_accent_insensitive() -> None:
    assert heuristic_category(_candidate(title="BIBLIOTHÈQUE — librarÿ"))[0] is Category.library


def test_heuristic_empty_metadata_is_campus() -> None:
    assert heuristic_category(_candidate()) == (Category.campus, "heuristic")
    assert heuristic_text(_candidate()) == ""


def test_source_hint_takes_precedence() -> None:
    cand = _candidate(filename="Dormitory.jpg", source_hint_category=Category.library)
    assert heuristic_category(cand) == (Category.library, "source_hint")


def test_city_commons_is_city_regardless_of_keywords() -> None:
    assert heuristic_category(_candidate(SourceType.city_commons, title="Old town")) == (
        Category.city,
        "heuristic",
    )
    assert heuristic_category(_candidate(SourceType.city_commons, title="City stadium"))[0] is (
        Category.city
    )
    hinted = _candidate(SourceType.city_commons, source_hint_category=Category.city)
    assert heuristic_category(hinted) == (Category.city, "source_hint")


# ------------------------------------------------------------------------------ split and sort


def test_empty_input() -> None:
    selection = finalize_selection([])
    assert selection == Selection(
        shown=[],
        hidden=[],
        warnings=[
            Warning(code=WarningCode.low_data),
            Warning(code=WarningCode.missing_category, detail="campus"),
            Warning(code=WarningCode.missing_category, detail="dormitory"),
            Warning(code=WarningCode.missing_category, detail="classroom"),
            Warning(code=WarningCode.missing_category, detail="library"),
            Warning(code=WarningCode.missing_category, detail="city"),
        ],
        cut_by_caps=0,
    )


def test_split_shown_and_hidden() -> None:
    verified = _photo(Verification.verified, 0.9)
    likely = _photo(Verification.likely, 0.5)
    unverified = _photo(Verification.unverified, 0.25)
    selection = finalize_selection([unverified, likely, verified])
    assert selection.shown == [verified, likely]
    assert selection.hidden == [unverified]


def test_shown_sort_order() -> None:
    v_low_commons = _photo(Verification.verified, 0.70, source_type=SourceType.commons_category)
    v_high = _photo(Verification.verified, 0.95, source_type=SourceType.commons_search)
    v_low_p18 = _photo(Verification.verified, 0.70, source_type=SourceType.wikidata_p18)
    v_low_flickr = _photo(Verification.verified, 0.70, source_type=SourceType.flickr_geo)
    l_high = _photo(Verification.likely, 0.69, source_type=SourceType.wikidata_p18)
    l_low = _photo(Verification.likely, 0.40)
    selection = finalize_selection([l_low, v_low_flickr, l_high, v_low_commons, v_high, v_low_p18])
    assert selection.shown == [v_high, v_low_p18, v_low_commons, v_low_flickr, l_high, l_low]


def test_sort_is_stable_for_full_ties() -> None:
    first = _photo(Verification.likely, 0.5)
    second = _photo(Verification.likely, 0.5)
    assert finalize_selection([first, second]).shown == [first, second]
    assert finalize_selection([second, first]).shown == [second, first]


# ---------------------------------------------------------------------------------------- caps


def test_per_category_cap_keeps_the_best_12() -> None:
    photos = [_photo(confidence=round(0.70 + i * 0.01, 2)) for i in range(13)]
    selection = finalize_selection(photos)
    assert len(selection.shown) == PER_CATEGORY_CAP == 12
    assert selection.cut_by_caps == 1
    assert photos[0] not in selection.shown  # the lowest one is the one cut
    assert [p.confidence for p in selection.shown] == sorted(
        (p.confidence for p in photos[1:]), reverse=True
    )


def test_city_cap_is_6() -> None:
    photos = [_photo(category=Category.city) for _ in range(8)]
    photos += [_photo(category=Category.library) for _ in range(8)]
    selection = finalize_selection(photos)
    by_category = {c: sum(1 for p in selection.shown if p.category is c) for c in Category}
    assert by_category[Category.city] == CITY_CAP == 6
    assert by_category[Category.library] == 8
    assert selection.cut_by_caps == 2


def test_total_shown_cap_is_45() -> None:
    photos: list[Photo] = []
    for category in Category:
        if category is Category.other:
            continue
        photos += [_photo(category=category) for _ in range(12)]
    selection = finalize_selection(photos)
    assert len(selection.shown) == TOTAL_SHOWN_CAP == 45
    # 7 non-city categories * 12 + city 6 = 90 eligible after the per-category caps
    assert selection.cut_by_caps == len(photos) - 45


def test_total_cap_keeps_the_top_of_the_sorted_order() -> None:
    weak = [_photo(Verification.likely, 0.45, category=Category.lab) for _ in range(12)]
    strong: list[Photo] = []
    for category in (Category.campus, Category.dormitory, Category.classroom):
        strong += [_photo(Verification.verified, 0.9, category=category) for _ in range(12)]
    selection = finalize_selection(weak + strong)  # 36 verified + 12 likely -> 45
    assert len(selection.shown) == 45
    assert all(p in selection.shown for p in strong)
    assert sum(1 for p in selection.shown if p in weak) == 9
    assert selection.cut_by_caps == 3
    assert selection.shown[-1].verification is Verification.likely


def test_caps_do_not_touch_hidden() -> None:
    photos = [_photo(Verification.unverified, 0.3) for _ in range(14)]
    selection = finalize_selection(photos)
    assert selection.shown == []
    assert len(selection.hidden) == 14
    assert selection.cut_by_caps == 0


# ------------------------------------------------------------------------------------- hidden


def test_hidden_cap_15_highest_confidence_first() -> None:
    photos = [
        _photo(Verification.unverified, round(0.05 + i * 0.015, 3)) for i in range(20)
    ]  # 0.05 .. 0.335
    selection = finalize_selection(photos)
    assert len(selection.hidden) == HIDDEN_CAP == 15
    confidences = [p.confidence for p in selection.hidden]
    assert confidences == sorted(confidences, reverse=True)
    assert confidences[0] == photos[-1].confidence
    assert all(p.confidence >= photos[5].confidence for p in selection.hidden)


def test_hidden_ties_break_by_source_priority() -> None:
    web = _photo(Verification.unverified, 0.3, source_type=SourceType.web_search)
    search = _photo(Verification.unverified, 0.3, source_type=SourceType.commons_search)
    assert finalize_selection([web, search]).hidden == [search, web]


# ----------------------------------------------------------------------------------- warnings


def test_low_data_below_6_shown() -> None:
    five = [_photo(category=c) for c in (Category.campus, Category.dormitory, Category.classroom)]
    five += [_photo(category=Category.library), _photo(category=Category.city)]
    assert _codes(finalize_selection(five).warnings) == [(WarningCode.low_data, None)]
    six = [*five, _photo(category=Category.sport)]
    assert finalize_selection(six).warnings == []


def test_low_data_counts_shown_only() -> None:
    photos = [_photo(category=c) for c in (Category.campus, Category.dormitory, Category.classroom)]
    photos += [_photo(category=Category.library), _photo(category=Category.city)]
    photos += [_photo(Verification.unverified, 0.2) for _ in range(10)]
    assert WarningCode.low_data in {w.code for w in finalize_selection(photos).warnings}


def test_missing_category_for_the_five_reported_categories() -> None:
    photos = [_photo(category=Category.campus) for _ in range(6)]
    photos += [_photo(category=Category.lab), _photo(category=Category.sport)]
    photos += [_photo(category=Category.student_life)]
    warnings = finalize_selection(photos).warnings
    assert _codes(warnings) == [
        (WarningCode.missing_category, "dormitory"),
        (WarningCode.missing_category, "classroom"),
        (WarningCode.missing_category, "library"),
        (WarningCode.missing_category, "city"),
    ]


def test_missing_category_ignores_hidden_photos() -> None:
    photos = [_photo(category=Category.campus) for _ in range(6)]
    photos += [_photo(Verification.unverified, 0.2, category=Category.library)]
    details = {w.detail for w in finalize_selection(photos).warnings}
    assert "library" in details


# -------------------------------------------------------------------------------------- stats


def test_build_stats() -> None:
    photos = [_photo() for _ in range(3)] + [_photo(Verification.unverified, 0.2)]
    selection = finalize_selection(photos)
    stats = build_stats(
        selection,
        found=40,
        duplicates_removed=5,
        irrelevant_removed=2,
        per_source={"commons_category": 30, "flickr_geo": 10},
        timings_ms={"resolve": 900, "collect": 4000},
        total_ms=12345,
    )
    assert stats.shown == 3
    assert stats.hidden_unverified == 1
    assert stats.found == 40
    assert stats.timings_ms == {"resolve": 900, "collect": 4000, "total": 12345}
    assert stats.total_ms == 12345
    assert stats.per_source == {"commons_category": 30, "flickr_geo": 10}


def test_build_stats_keeps_an_explicit_total_timing() -> None:
    stats = build_stats(
        finalize_selection([]),
        found=0,
        duplicates_removed=0,
        irrelevant_removed=0,
        per_source={},
        timings_ms={"total": 100},
        total_ms=100,
    )
    assert stats.timings_ms == {"total": 100}
    assert stats.shown == 0
    assert stats.hidden_unverified == 0
