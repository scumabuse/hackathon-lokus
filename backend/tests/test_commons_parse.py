"""Section 7.3 / 7.4A parsing and filters on REAL saved Commons responses (scripts/probe_commons*.py)."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.enums import Category, SourceType
from app.geo import haversine_m
from app.models import Coordinates
from app.sources.commons import (
    ALLOWED_MIMES,
    DATE_RE,
    EXCLUSION_RE,
    PROP_BLOCK,
    SUBCAT_RE,
    choose_subcategories,
    commons_pages,
    continuation_params,
    geosearch_params,
    page_coordinates,
    parse_commons_page,
    parse_commons_pages,
    parse_date,
    strip_html,
    subcategory_hint,
)
from tests.conftest import read_fixture

MIT_COORDS = Coordinates(lat=42.359722, lon=-71.091944)
NU_COORDS = Coordinates(lat=51.09, lon=71.399444)
ALL_FILE_FIXTURES = (
    "commons_category_mit.json",
    "commons_category_mit_page2.json",
    "commons_subcat_files_mit.json",
    "commons_search_mit.json",
    "commons_category_nu.json",
    "commons_search_nu.json",
    "commons_search_nu_local.json",
    "commons_category_cambridge.json",
    "commons_category_astana.json",
    "commons_geosearch_mit.json",
    "commons_geosearch_nu.json",
)


def page_by_title(fixture: str, title: str) -> dict[str, Any]:
    for page in commons_pages(read_fixture(fixture)):
        if page["title"] == title:
            return page
    raise AssertionError(f"{title} not in {fixture}")


def candidate_by_filename(candidates: list[Any], filename: str) -> Any:
    for candidate in candidates:
        if candidate.filename == filename:
            return candidate
    raise AssertionError(f"{filename} not among candidates")


# ----------------------------------------------------------------------------- constants


def test_prop_block_is_section_7_3() -> None:
    assert PROP_BLOCK == {
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|size|mime|timestamp",
        "iiurlwidth": "640",
        "iiextmetadatafilter": (
            "DateTimeOriginal|LicenseShortName|Artist|ImageDescription|ObjectName"
        ),
    }


def test_geosearch_params_are_section_7_4a() -> None:
    params = geosearch_params(MIT_COORDS)
    assert params["action"] == "query"
    assert params["generator"] == "geosearch"
    assert params["ggscoord"] == "42.359722|-71.091944"
    assert params["ggsradius"] == "1000"
    assert params["ggsnamespace"] == "6"
    assert params["ggslimit"] == "50"
    assert params["ggsprimary"] == "all"
    assert params["prop"] == "imageinfo|coordinates"
    assert params["iiprop"] == PROP_BLOCK["iiprop"]
    assert params["iiurlwidth"] == "640"
    assert params["iiextmetadatafilter"] == PROP_BLOCK["iiextmetadatafilter"]
    assert params["colimit"] == "50"  # coordinates prop defaults to 10 per request (probed)


# ----------------------------------------------------------------------------- MIT category page


def test_mit_category_page_counts_after_filters() -> None:
    data = read_fixture("commons_category_mit.json")
    assert len(commons_pages(data)) == 50
    candidates = parse_commons_pages(data, source_type=SourceType.commons_category)
    # 50 pages - 5 non-image mimes (ogg/webm/pdf/pdf/tif) - 6 too small - 4 excluded names = 35
    assert len(candidates) == 35
    names = {c.filename for c in candidates}
    assert "COBOL poster (1969).jpg" not in names  # "poster"
    assert "MIT Campus Map.jpg" not in names  # "\bmap\b"
    assert "DARPA amplifier on silicon MIT.jpg" not in names  # "icon" inside "silicon"
    assert "MIT punched card.agr.jpg" not in names  # 526x237
    assert "Les-2.jpg" not in names  # 310x337
    for candidate in candidates:
        assert candidate.source_type is SourceType.commons_category
        assert candidate.source_label == "Wikimedia Commons"
        assert candidate.page_title == f"File:{candidate.filename}"
        assert candidate.width is not None and candidate.width >= 400
        assert candidate.height is not None and candidate.height >= 300
        assert candidate.filename is not None
        assert not EXCLUSION_RE.search(candidate.filename)
        assert candidate.image_url.startswith("https://")
        assert candidate.source_page_url.startswith("https://commons.wikimedia.org/wiki/File:")
        assert candidate.source_hint_category is None
        assert candidate.geo is None and candidate.distance_m is None


def test_other_real_pages_counts() -> None:
    expected = {
        "commons_category_mit_page2.json": (31, 24),
        "commons_subcat_files_mit.json": (30, 23),
        "commons_search_mit.json": (40, 33),
        "commons_category_nu.json": (31, 28),
        "commons_search_nu.json": (40, 35),
        "commons_search_nu_local.json": (40, 35),
    }
    for fixture, (pages, kept) in expected.items():
        data = read_fixture(fixture)
        assert len(commons_pages(data)) == pages, fixture
        assert len(parse_commons_pages(data, source_type=SourceType.commons_search)) == kept, (
            fixture
        )


def test_taken_date_author_license_urls_from_real_page() -> None:
    page = page_by_title("commons_category_mit.json", "File:BEC1.1.jpg")
    info = page["imageinfo"][0]
    assert info["extmetadata"]["DateTimeOriginal"]["value"] == "2020-01-15 11:59:27"
    assert info["extmetadata"]["Artist"]["value"].startswith("<a href=")
    candidates = parse_commons_pages(
        read_fixture("commons_category_mit.json"), source_type=SourceType.commons_category
    )
    candidate = candidate_by_filename(candidates, "BEC1.1.jpg")
    assert (candidate.date, candidate.date_kind) == ("2020-01-15", "taken")
    assert candidate.author == "SJMW1987"
    assert candidate.license == "CC BY 4.0"
    assert candidate.source_page_url == info["descriptionurl"]
    assert candidate.source_page_url == "https://commons.wikimedia.org/wiki/File:BEC1.1.jpg"
    assert candidate.image_url == info["thumburl"]
    assert candidate.image_url.startswith("https://thumb.wikimedia.org/")
    assert candidate.page_title == "File:BEC1.1.jpg"
    assert candidate.filename == "BEC1.1.jpg"
    assert (candidate.width, candidate.height) == (1500, 1000)
    assert candidate.title is not None and candidate.title.startswith("BEC 1, the apparatus")
    assert len(candidate.title) <= 300


def test_uploaded_fallback_for_free_text_dates() -> None:
    # "1969" -- the page itself is excluded by the filename filter ("poster"); parse without it
    cobol = page_by_title("commons_category_mit.json", "File:COBOL poster (1969).jpg")
    assert cobol["imageinfo"][0]["extmetadata"]["DateTimeOriginal"]["value"] == "1969"
    assert cobol["imageinfo"][0]["timestamp"] == "2025-07-16T00:13:45Z"
    candidate = parse_commons_page(
        cobol, source_type=SourceType.commons_category, name_filter=False
    )
    assert candidate is not None
    assert (candidate.date, candidate.date_kind) == ("2025-07-16", "uploaded")

    subcat = parse_commons_pages(
        read_fixture("commons_subcat_files_mit.json"), source_type=SourceType.commons_category
    )
    circa = candidate_by_filename(
        subcat, "Katherine Moore Dexter McCormick in laboratory, circa 1890s.png"
    )
    assert (circa.date, circa.date_kind) == ("2024-10-05", "uploaded")  # "circa 1890-1900"

    taken_on = next(
        c
        for c in subcat
        if c.filename is not None and c.filename.startswith("Colleges and Universities")
    )
    raw = page_by_title("commons_subcat_files_mit.json", taken_on.page_title)
    assert raw["imageinfo"][0]["extmetadata"]["DateTimeOriginal"]["value"] == (
        "Taken on\xa025 April 1918"
    )
    assert (taken_on.date, taken_on.date_kind) == ("2017-09-20", "uploaded")


def test_html_wrapped_exif_date_falls_back_to_upload_timestamp() -> None:
    page = page_by_title("commons_category_nu.json", "File:Nazarbayev University 2.jpg")
    raw = page["imageinfo"][0]["extmetadata"]["DateTimeOriginal"]["value"]
    assert raw.startswith("11 March 2018\xa0(according to <span")
    assert "Exif" in raw
    assert not DATE_RE.match(strip_html(raw) or "")
    candidates = parse_commons_pages(
        read_fixture("commons_category_nu.json"), source_type=SourceType.commons_category
    )
    candidate = candidate_by_filename(candidates, "Nazarbayev University 2.jpg")
    assert (candidate.date, candidate.date_kind) == ("2018-03-11", "uploaded")
    assert candidate.author == "Dinononozavr1"
    assert candidate.license == "CC BY-SA 4.0"


def test_only_the_regex_ever_produces_a_taken_date() -> None:
    """Invariant over every real page: taken <=> regex matched; uploaded <=> timestamp[:10]."""
    seen_taken = seen_uploaded = 0
    for fixture in ALL_FILE_FIXTURES:
        for page in commons_pages(read_fixture(fixture)):
            candidate = parse_commons_page(page, source_type=SourceType.commons_search)
            if candidate is None:
                continue
            info = page["imageinfo"][0]
            raw = info.get("extmetadata", {}).get("DateTimeOriginal", {}).get("value")
            stripped = strip_html(raw) or ""
            if candidate.date_kind == "taken":
                seen_taken += 1
                match = DATE_RE.match(stripped)
                assert match is not None, (fixture, page["title"], raw)
                assert candidate.date == "-".join(match.groups())
            elif candidate.date_kind == "uploaded":
                seen_uploaded += 1
                assert candidate.date == info["timestamp"][:10]
            else:
                raise AssertionError("every real page has an upload timestamp")
    assert seen_taken > 100 and seen_uploaded > 50


@pytest.mark.parametrize(
    ("value", "timestamp", "expected"),
    [
        ("2020-01-15 11:59:27", "2026-01-23T16:09:31Z", ("2020-01-15", "taken")),
        ("2013-03-05", None, ("2013-03-05", "taken")),
        ("2006:08:03 12:49", None, ("2006-08-03", "taken")),
        ("2019/11/09 (Exif)", None, ("2019-11-09", "taken")),
        ("1969", "2025-07-16T00:13:45Z", ("2025-07-16", "uploaded")),
        ("1852-05-??", "2021-01-01T00:00:00Z", ("2021-01-01", "uploaded")),
        (
            "11/09/2019\xa0(according to Exif data)",
            "2019-11-10T00:00:00Z",
            ("2019-11-10", "uploaded"),
        ),
        ("2020-13-40", "2021-02-03T00:00:00Z", ("2021-02-03", "uploaded")),
        ("2020-00-10", "2021-02-03T00:00:00Z", ("2021-02-03", "uploaded")),
        ("<p>2016-05-04</p><div style='display:none'>x</div>", None, ("2016-05-04", "taken")),
        (None, "2010-01-02T03:04:05Z", ("2010-01-02", "uploaded")),
        (None, None, (None, "unknown")),
        ("nope", "garbage", (None, "unknown")),
        ("", "", (None, "unknown")),
    ],
)
def test_parse_date_rules(value: str | None, timestamp: str | None, expected: tuple) -> None:
    assert parse_date(value, timestamp) == expected


def test_author_none_and_title_falls_back_to_objectname() -> None:
    page = page_by_title("commons_category_mit.json", "File:Building62and64.jpg")
    ext = page["imageinfo"][0]["extmetadata"]
    assert "Artist" not in ext and "ImageDescription" not in ext
    candidate = parse_commons_page(page, source_type=SourceType.commons_category)
    assert candidate is not None
    assert candidate.author is None
    assert candidate.title == ext["ObjectName"]["value"] == "Building62and64"


def test_artist_html_variants_are_stripped_and_clipped() -> None:
    assert strip_html('<a href="//commons.wikimedia.org/wiki/User:X" title="User:X">X</a>') == "X"
    assert strip_html("Unknown author<span style='display: none;'>Unknown author</span>") == (
        "Unknown author Unknown author"
    )
    assert strip_html("  plain   text\n\xa0here ") == "plain text here"
    assert strip_html("") is None
    assert strip_html(None) is None
    page = copy.deepcopy(page_by_title("commons_category_mit.json", "File:BEC1.1.jpg"))
    page["imageinfo"][0]["extmetadata"]["Artist"]["value"] = "<b>" + "a" * 200 + "</b>"
    page["imageinfo"][0]["extmetadata"]["ImageDescription"]["value"] = "<p>" + "d " * 400 + "</p>"
    candidate = parse_commons_page(page, source_type=SourceType.commons_category)
    assert candidate is not None
    assert candidate.author == "a" * 80
    assert candidate.title is not None and len(candidate.title) == 300


# ----------------------------------------------------------------------------- filters


def test_non_image_mimes_are_excluded() -> None:
    data = read_fixture("commons_category_mit.json")
    raw_mimes = {p["imageinfo"][0]["mime"] for p in commons_pages(data)}
    assert {"application/ogg", "video/webm", "application/pdf", "image/tiff"} <= raw_mimes
    raw_titles = {p["title"] for p in commons_pages(data)}
    assert any(t.endswith(".ogg") for t in raw_titles)
    assert any(t.endswith(".pdf") for t in raw_titles)
    candidates = parse_commons_pages(data, source_type=SourceType.commons_category)
    for candidate in candidates:
        assert candidate.filename is not None
        assert not candidate.filename.lower().endswith((".ogg", ".pdf", ".svg", ".tif", ".webm"))
    search = parse_commons_pages(
        read_fixture("commons_search_mit.json"), source_type=SourceType.commons_search
    )
    assert "MIT 2023 red logo.svg" not in {c.filename for c in search}
    assert ALLOWED_MIMES == {"image/jpeg", "image/png", "image/webp"}


def test_size_filter_boundaries() -> None:
    page = copy.deepcopy(page_by_title("commons_category_mit.json", "File:BEC1.1.jpg"))
    info = page["imageinfo"][0]
    for width, height, kept in [(400, 300, True), (399, 300, False), (400, 299, False)]:
        info["width"], info["height"] = width, height
        result = parse_commons_page(page, source_type=SourceType.commons_category)
        assert (result is not None) is kept, (width, height)
    del info["width"]
    assert parse_commons_page(page, source_type=SourceType.commons_category) is None


@pytest.mark.parametrize(
    ("filename", "excluded"),
    [
        ("MIT Campus Map.jpg", True),
        ("Mapping the campus.jpg", False),  # \bmap\b is a whole word
        ("MITstem new best Logo.jpg", True),
        ("Emblem of Nazarbaev University projected by Pyramid Hologram.jpg", True),
        ("Coat of arms of X.png", True),
        ("coat_of_arms.png", True),
        ("Diagram.jpg", True),
        ("Unknown portrait - Cambridge, MA - DSC05544.JPG", True),
        ("Something.svg", True),
        ("Something.SVG", True),
        ("Something.pdf", True),
        ("Something.tif", True),
        ("Something.tiff", True),
        ("Something.tifx", False),
        ("Screenshot 2019-11-07.png", True),
        ("Building 10 at night.jpg", False),
        ("Nazarbayev University 2.jpg", False),
        ("DARPA amplifier on silicon MIT.jpg", True),  # documented in-word false positive
    ],
)
def test_exclusion_regex_on_filenames(filename: str, excluded: bool) -> None:
    assert bool(EXCLUSION_RE.search(filename)) is excluded


def test_excluded_filenames_never_survive_parsing() -> None:
    for fixture in ALL_FILE_FIXTURES:
        for candidate in parse_commons_pages(
            read_fixture(fixture), source_type=SourceType.commons_search
        ):
            assert candidate.filename is not None
            assert not EXCLUSION_RE.search(candidate.filename), (fixture, candidate.filename)


def test_missing_and_malformed_pages_are_skipped() -> None:
    assert parse_commons_pages({}, source_type=SourceType.commons_search) == []
    assert parse_commons_pages({"batchcomplete": ""}, source_type=SourceType.commons_search) == []
    assert parse_commons_pages(None, source_type=SourceType.commons_search) == []
    pages = {
        "-1": {"title": "File:Nope.jpg", "missing": ""},
        "2": {"title": "File:No info.jpg"},
        "3": {"title": "File:Empty info.jpg", "imageinfo": []},
        "4": {"pageid": 4, "ns": 6},
    }
    assert (
        parse_commons_pages({"query": {"pages": pages}}, source_type=SourceType.commons_search)
        == []
    )


# ----------------------------------------------------------------------------- URL fallbacks


def test_source_page_url_and_image_url_fallbacks() -> None:
    page = copy.deepcopy(page_by_title("commons_category_mit.json", "File:BEC1.1.jpg"))
    page["title"] = "File:Foo bar.jpg"
    info = page["imageinfo"][0]
    del info["descriptionurl"]
    del info["thumburl"]
    candidate = parse_commons_page(page, source_type=SourceType.commons_category)
    assert candidate is not None
    assert candidate.source_page_url == "https://commons.wikimedia.org/wiki/File%3AFoo%20bar.jpg"
    assert candidate.image_url == info["url"]
    assert candidate.filename == "Foo bar.jpg"
    info["url"] = "ftp://not-http/x.jpg"
    assert parse_commons_page(page, source_type=SourceType.commons_category) is None


# ----------------------------------------------------------------------------- single files


def test_p18_fixture_under_single_file_rules() -> None:
    data = read_fixture("commons_file_mit_p18.json")
    pages = commons_pages(data)
    assert len(pages) == 1
    assert "DateTimeOriginal" not in pages[0]["imageinfo"][0]["extmetadata"]
    candidate = parse_commons_page(
        pages[0], source_type=SourceType.wikidata_p18, size_filter=False, name_filter=False
    )
    assert candidate is not None
    assert candidate.source_type is SourceType.wikidata_p18
    assert candidate.filename == "MIT Dome night1 Edit.jpg"
    assert candidate.page_title == "File:MIT Dome night1 Edit.jpg"
    assert (candidate.date, candidate.date_kind) == ("2007-11-12", "uploaded")
    assert candidate.author == "Fcb981, this edited version by Thermos"
    assert candidate.license == "CC BY-SA 3.0"
    assert (
        candidate.source_page_url
        == "https://commons.wikimedia.org/wiki/File:MIT_Dome_night1_Edit.jpg"
    )
    assert candidate.image_url.startswith("https://thumb.wikimedia.org/")
    assert (candidate.width, candidate.height) == (2644, 1610)
    # the same page also passes the full filters (it is a real photo)
    assert parse_commons_pages(data, source_type=SourceType.wikidata_p18)[0] == candidate


def test_single_file_rules_keep_small_or_oddly_named_main_image() -> None:
    page = copy.deepcopy(commons_pages(read_fixture("commons_file_mit_p18.json"))[0])
    page["title"] = "File:Founder portrait hall.jpg"
    page["imageinfo"][0]["width"], page["imageinfo"][0]["height"] = 320, 240
    assert parse_commons_page(page, source_type=SourceType.wikidata_p18) is None
    kept = parse_commons_page(
        page, source_type=SourceType.wikidata_p18, size_filter=False, name_filter=False
    )
    assert kept is not None and kept.filename == "Founder portrait hall.jpg"
    page["imageinfo"][0]["mime"] = "image/gif"  # the mime filter always applies
    assert (
        parse_commons_page(
            page, source_type=SourceType.wikidata_p18, size_filter=False, name_filter=False
        )
        is None
    )


def test_logo_fixture_is_excluded() -> None:
    data = read_fixture("commons_file_mit_logo.json")
    page = commons_pages(data)[0]
    assert page["title"] == "File:MIT 2023 red logo.svg"
    assert page["imageinfo"][0]["mime"] == "image/svg+xml"
    assert parse_commons_pages(data, source_type=SourceType.commons_search) == []
    # even without size/name filters: svg is not an allowed mime
    assert (
        parse_commons_page(
            page, source_type=SourceType.wikidata_p18, size_filter=False, name_filter=False
        )
        is None
    )
    assert data["continue"] == {"iistart": "2025-06-23T23:48:08Z", "continue": "||"}
    assert continuation_params(data) is None  # not a category continuation


# ----------------------------------------------------------------------------- continuation


def test_category_continuation_shape() -> None:
    first = read_fixture("commons_category_mit.json")
    cont = continuation_params(first)
    assert cont is not None
    assert set(cont) == {"gcmcontinue", "continue"}
    assert cont["continue"] == "gcmcontinue||"
    assert cont["gcmcontinue"].startswith("file|")
    assert cont == first["continue"]
    second = read_fixture("commons_category_mit_page2.json")
    assert "continue" not in second
    assert continuation_params(second) is None
    assert continuation_params(read_fixture("commons_search_mit.json")) is None  # gsroffset only
    assert read_fixture("commons_search_mit.json")["continue"] == {
        "gsroffset": 40,
        "continue": "gsroffset||",
    }
    first_urls = {
        c.image_url for c in parse_commons_pages(first, source_type=SourceType.commons_category)
    }
    second_urls = {
        c.image_url for c in parse_commons_pages(second, source_type=SourceType.commons_category)
    }
    assert not first_urls & second_urls


def test_search_pages_follow_search_rank_index() -> None:
    data = read_fixture("commons_search_mit.json")
    raw_order = [p["index"] for p in data["query"]["pages"].values()]
    assert raw_order != sorted(raw_order)  # pageid-keyed object, not in rank order
    assert [p["index"] for p in commons_pages(data)] == list(range(1, 41))


# ----------------------------------------------------------------------------- geosearch (7.4A)


def test_geosearch_fixture_gives_geo_and_distance() -> None:
    data = read_fixture("commons_geosearch_mit.json")
    pages = commons_pages(data)
    assert len(pages) == 50
    candidates = parse_commons_pages(data, source_type=SourceType.commons_geo, campus=MIT_COORDS)
    assert len(candidates) == 50
    with_geo = [c for c in candidates if c.geo is not None]
    assert len(with_geo) == 47
    for candidate in with_geo:
        assert candidate.source_type is SourceType.commons_geo
        assert candidate.source_label == "Wikimedia Commons"
        assert candidate.distance_m is not None
        assert 0.0 < candidate.distance_m <= 1000.0
        assert candidate.distance_m == round(
            haversine_m(MIT_COORDS.lat, MIT_COORDS.lon, candidate.geo.lat, candidate.geo.lon), 1
        )
    dome = candidate_by_filename(candidates, "MIT Dome night1 Edit.jpg")
    assert dome.geo == Coordinates(lat=42.35908333, lon=-71.09166667)
    assert dome.distance_m == pytest.approx(74.6, abs=0.1)
    # real pages the coordinates prop returned nothing for -> geo None, distance None
    no_geo = candidate_by_filename(
        candidates, "MIT Building 10 and the Great Dome, Cambridge MA.jpg"
    )
    assert no_geo.geo is None and no_geo.distance_m is None
    assert {c.filename for c in candidates if c.geo is None} == {
        "MIT Building 10 and the Great Dome, Cambridge MA.jpg",
        "Great Dome, Massachusetts Institute of Technology, Cambridge MA.jpg",
        "051909 MIT Hack Apollo 10 Snoopy.jpg",
    }


def test_geosearch_nu_fixture() -> None:
    data = read_fixture("commons_geosearch_nu.json")
    assert len(commons_pages(data)) == 50
    candidates = parse_commons_pages(data, source_type=SourceType.commons_geo, campus=NU_COORDS)
    # one image/tiff and one filename matching the regex ("Bacteria planet.jpg": "plan")
    assert len(candidates) == 48
    assert all(c.geo is not None and c.distance_m is not None for c in candidates)
    assert max(c.distance_m for c in candidates if c.distance_m is not None) <= 1000.0
    without_campus = parse_commons_pages(data, source_type=SourceType.commons_geo)
    assert all(c.geo is not None and c.distance_m is None for c in without_campus)


def test_real_coordinates_shape() -> None:
    for page in commons_pages(read_fixture("commons_geosearch_nu.json")):
        entries = page["coordinates"]
        assert len(entries) == 1
        assert set(entries[0]) == {"lat", "lon", "primary", "globe"}
        assert entries[0]["primary"] == ""  # format=json boolean true
        assert entries[0]["globe"] == "earth"


def test_page_coordinates_prefers_primary_and_earth() -> None:
    secondary = {"lat": 1.0, "lon": 2.0, "globe": "earth"}
    primary = {"lat": 3.0, "lon": 4.0, "primary": "", "globe": "earth"}
    assert page_coordinates({"coordinates": [secondary, primary]}) == Coordinates(lat=3.0, lon=4.0)
    assert page_coordinates({"coordinates": [secondary]}) == Coordinates(lat=1.0, lon=2.0)
    v2 = {"lat": 5.0, "lon": 6.0, "primary": True, "globe": "earth"}
    assert page_coordinates({"coordinates": [secondary, v2]}) == Coordinates(lat=5.0, lon=6.0)
    moon = {"lat": 7.0, "lon": 8.0, "primary": "", "globe": "moon"}
    assert page_coordinates({"coordinates": [moon]}) is None
    assert page_coordinates({"coordinates": [moon, secondary]}) == Coordinates(lat=1.0, lon=2.0)
    assert page_coordinates({"coordinates": []}) is None
    assert page_coordinates({}) is None
    assert page_coordinates({"coordinates": [{"lat": "x", "lon": 1}]}) is None
    assert page_coordinates({"coordinates": [{"lat": 91.0, "lon": 1.0}]}) is None


# ----------------------------------------------------------------------------- subcategories


def test_choose_subcategories_on_real_mit_list() -> None:
    members = read_fixture("commons_subcats_mit.json")["query"]["categorymembers"]
    assert len(members) == 42
    assert {tuple(sorted(m)) for m in members} == {("ns", "pageid", "title")}
    titles = [m["title"] for m in members]
    assert sum(1 for t in titles if SUBCAT_RE.search(t)) == 3
    assert choose_subcategories(titles) == [
        ("Category:MIT former Boston campus", None),
        ("Category:Campus of the Massachusetts Institute of Technology", None),
        ("Category:Charles Stark Draper Laboratory", Category.lab),
    ]


def test_choose_subcategories_on_real_nu_list_uses_first_eight_rule() -> None:
    members = read_fixture("commons_subcats_nu.json")["query"]["categorymembers"]
    titles = [m["title"] for m in members]
    assert titles == ["Category:Shigeo Katsu"]
    assert choose_subcategories(titles) == [("Category:Shigeo Katsu", None)]
    assert choose_subcategories([]) == []


def test_choose_subcategories_caps_at_eight_and_fills_when_few_match() -> None:
    matching = [f"Category:Building {i}" for i in range(10)]
    assert choose_subcategories(matching) == [(t, None) for t in matching[:8]]
    others = [f"Category:Other {i}" for i in range(12)]
    two = ["Category:Main library", "Category:Student dormitories"]
    chosen = choose_subcategories(others[:5] + two + others[5:])
    assert len(chosen) == 8
    assert chosen[:2] == [
        ("Category:Main library", Category.library),
        ("Category:Student dormitories", Category.dormitory),
    ]
    assert [t for t, _ in chosen[2:]] == others[:6]
    three = ["Category:Campus", "Category:Sports hall", "Category:Laboratories"]
    assert choose_subcategories(others + three) == [
        ("Category:Campus", None),
        ("Category:Sports hall", Category.sport),
        ("Category:Laboratories", Category.lab),
    ]


@pytest.mark.parametrize(
    ("title", "hint"),
    [
        ("Category:Libraries of MIT", Category.library),
        ("Category:MIT hostels", Category.dormitory),
        ("Category:Student residences", Category.dormitory),
        ("Category:Dormitories", Category.dormitory),
        ("Category:Stadium", Category.sport),
        ("Category:Sports facilities", Category.sport),
        ("Category:Charles Stark Draper Laboratory", Category.lab),
        ("Category:Student life", Category.student_life),
        ("Category:Campus of X", None),
        ("Category:Buildings", None),
        ("Category:Общежития", None),
    ],
)
def test_subcategory_hint_mapping(title: str, hint: Category | None) -> None:
    assert subcategory_hint(title) is hint
    assert SUBCAT_RE.search(title) is not None
