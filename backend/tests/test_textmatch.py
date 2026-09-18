"""Section 10 text normalization and name matching (``app.processing.textmatch``)."""

from __future__ import annotations

import pytest

from app.processing.textmatch import (
    MIN_NAME_LEN,
    contains_name,
    match_names,
    name_terms,
    normalize,
)

# ------------------------------------------------------------------------------- normalization


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # NFKD + dropped combining marks (diacritics)
        ("Zürich", "zurich"),
        ("ETH Zürich", "eth zurich"),
        ("Université", "universite"),
        ("Université de Montréal", "universite de montreal"),
        ("Hauptgebäude", "hauptgebaude"),
        # casefold on Cyrillic (and Latin)
        ("Назарбаев Университет", "назарбаев университет"),
        ("НАЗАРБАЕВ УНИВЕРСИТЕТ", "назарбаев университет"),
        ("Massachusetts Institute of Technology", "massachusetts institute of technology"),
        # punctuation -> spaces
        ("MIT—Great Dome, 2019 (east).jpg", "mit great dome 2019 east jpg"),
        ("Al-Farabi Kazakh National University", "al farabi kazakh national university"),
        # underscores are separators (Commons / Flickr / official-site file names)
        ("Nazarbayev_University.jpg", "nazarbayev university jpg"),
        ("ETH_Zurich_main_building.jpg", "eth zurich main building jpg"),
        ("a_b__c", "a b c"),
        # whitespace collapse and strip
        ("  lots   of\t\nspace  ", "lots of space"),
        (" nbsp inside ", "nbsp inside"),
        # NFKD compatibility forms
        ("ﬁle", "file"),
        ("Straße", "strasse"),
        # nothing left
        ("", ""),
        (None, ""),
        ("___", ""),
        ("--- ...", ""),
    ],
)
def test_normalize(raw: str | None, expected: str) -> None:
    assert normalize(raw) == expected


def test_normalize_splits_cyrillic_short_i_like_selection_expects() -> None:
    # NFKD decomposes й into и + combining breve; the mark is dropped (selection.py relies on it)
    assert normalize("бассейн") == "бассеин"
    assert normalize("Российский") == "россиискии"


def test_normalize_is_idempotent() -> None:
    for text in ("ETH Zürich", "Nazarbayev_University.jpg", "Назарбаев Университет"):
        once = normalize(text)
        assert normalize(once) == once


# ---------------------------------------------------------------------------------- name_terms


def test_name_terms_dedupes_and_keeps_order() -> None:
    terms = name_terms(
        "Nazarbayev University",
        "Назарбаев Университет",
        ["nazarbayev  university", "Nazarbayev Univ.", None, "", "Назарбаев Университет"],
    )
    assert terms == ["nazarbayev university", "назарбаев университет", "nazarbayev univ"]


def test_name_terms_drops_short_names() -> None:
    assert MIN_NAME_LEN == 4
    assert name_terms("MIT", None, ["ETH", "NU", "KBTU"]) == ["kbtu"]
    assert name_terms("Yale", None) == ["yale"]  # exactly four characters is enough
    assert name_terms(None, None) == []
    assert name_terms("", "", ["", None]) == []


def test_name_terms_accepts_a_generator_of_aliases() -> None:
    assert name_terms("Nazarbayev University", None, (a for a in ["NU", "Nazarbayev Univ"])) == [
        "nazarbayev university",
        "nazarbayev univ",
    ]


# ----------------------------------------------------------------------------------- matching


def test_tech_does_not_match_technology() -> None:
    assert match_names(["Tech"], ["Technology building"]) is False
    assert match_names(["Tech"], ["Caltech campus"]) is False
    assert match_names(["Tech"], ["Tech building"]) is True
    assert match_names(["Tech"], ["Georgia_Tech_tower.jpg"]) is True


def test_single_word_name_needs_the_whole_word() -> None:
    assert match_names(["Columbia"], ["Columbian exposition"]) is False
    assert match_names(["Columbia"], ["Precolumbia"]) is False
    assert match_names(["Columbia"], ["Columbia, Low Library"]) is True


def test_cyrillic_local_name_found_inside_cyrillic_filename() -> None:
    names = ["Nazarbayev University", "Назарбаев Университет"]
    assert match_names(names, ["Назарбаев_Университет_главный_корпус.jpg"]) is True
    assert match_names(names, ["НАЗАРБАЕВ УНИВЕРСИТЕТ, Астана.jpg"]) is True


def test_underscored_filename_matches_the_name() -> None:
    assert match_names(["Nazarbayev University"], ["Nazarbayev_University_main_hall.jpg"]) is True
    assert match_names(["Nazarbayev University"], ["nazarbayev-university-main-hall.jpg"]) is True


def test_multiword_name_tolerates_an_inflected_last_word() -> None:
    # Russian / Kazakh case endings on the last word: the leading words anchor the match
    assert match_names(["Назарбаев Университет"], ["Корпус Назарбаев Университета"]) is True
    assert match_names(["Назарбаев Университет"], ["Назарбаев Университеті"]) is True
    # the leading words must still match whole, and the name must start a word
    assert match_names(["Nazarbayev University"], ["Nazarbayevs University"]) is False
    assert match_names(["Nazarbayev University"], ["XNazarbayev University"]) is False
    assert match_names(["Nazarbayev University"], ["Nazarbayev Universe"]) is False


def test_no_usable_names_is_false() -> None:
    assert match_names([], ["anything"]) is False
    assert match_names(["MIT", "NU", None, ""], ["MIT campus NU"]) is False


def test_none_and_empty_texts_are_ignored() -> None:
    assert match_names(["Nazarbayev University"], [None, "", "   "]) is False
    assert match_names(["Nazarbayev University"], []) is False
    assert match_names(["Nazarbayev University"], [None, "", "Nazarbayev University"]) is True


def test_match_is_case_and_accent_insensitive() -> None:
    assert match_names(["ETH Zürich"], ["eth zurich hauptgebaude.jpg"]) is True
    assert match_names(["ETH Zurich"], ["ETH Zürich Hauptgebäude"]) is True


def test_any_alias_in_any_text() -> None:
    names = ["Massachusetts Institute of Technology", "MIT"]
    texts = ["Great Dome", None, "the massachusetts institute of technology campus"]
    assert match_names(names, texts) is True
    assert match_names(names, ["Great Dome", "MIT campus"]) is False  # MIT too short


def test_contains_name_edge_cases() -> None:
    assert contains_name("", "abcd") is False
    assert contains_name("abcd", "") is False
    assert contains_name("abcd", "abcd") is True
    assert contains_name("x abcd y", "abcd") is True
    assert contains_name("xabcd", "abcd") is False
