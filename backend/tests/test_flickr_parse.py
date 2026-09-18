"""Section 7.4 Flickr parsing on the SYNTHETIC sample (no key was available to record a real one)."""

from __future__ import annotations

import copy

import pytest

from app.enums import SourceType
from app.geo import haversine_m
from app.models import Coordinates
from app.sources.flickr import (
    DEFAULT_LICENSES,
    EXTRAS,
    geo_search_params,
    license_name,
    parse_flickr_photos,
    parse_license_names,
    parse_taken_date,
    text_search_params,
)
from tests.conftest import read_fixture

FIXTURE = "flickr_photos_search_sample.json"
CAMPUS = Coordinates(lat=42.359722, lon=-71.091944)


def test_fixture_is_labelled_synthetic() -> None:
    data = read_fixture(FIXTURE)
    assert data["_note"].startswith("synthetic sample following the documented response shape")
    assert data["stat"] == "ok"
    assert len(data["photos"]["photo"]) == 5


def test_parse_sample_applies_every_rule() -> None:
    data = read_fixture(FIXTURE)
    candidates = parse_flickr_photos(data, campus=CAMPUS, license_names=DEFAULT_LICENSES)
    ids = [c.source_page_url for c in candidates]
    assert ids == [
        "https://www.flickr.com/photos/11111111@N01/10000000001/",
        "https://www.flickr.com/photos/22222222@N02/10000000002/",
        "https://www.flickr.com/photos/44444444@N04/10000000004/",
    ]  # 3 skipped (no url_z/url_m), 5 skipped (title "Campus map poster")
    first, second, fourth = candidates
    for candidate in candidates:
        assert candidate.source_type is SourceType.flickr_geo
        assert candidate.source_label == "Flickr"
        assert candidate.filename is None and candidate.page_title is None

    # url_z present -> url_z + width_z/height_z
    assert first.image_url == "https://live.staticflickr.com/65535/10000000001_abcdef0001_z.jpg"
    assert (first.width, first.height) == (640, 480)
    assert first.title == "Great Dome at sunset"
    assert first.author == "Sample Photographer"
    assert first.license == "CC BY 2.0"  # id 4
    assert (first.date, first.date_kind) == ("2019-06-12", "taken")
    assert first.description == "The main building of the campus, seen from Killian Court."
    assert first.alt == "campus dome architecture summer"
    assert first.geo == Coordinates(lat=42.359722, lon=-71.091944)
    assert first.distance_m == 0.0

    # only url_m -> url_m + width_m/height_m (strings in the sample), license 0, empty description
    assert second.image_url == "https://live.staticflickr.com/65535/10000000002_abcdef0002.jpg"
    assert (second.width, second.height) == (500, 333)
    assert second.license == "All Rights Reserved"
    assert second.description is None
    assert second.geo == Coordinates(lat=42.3615, lon=-71.0901)
    assert second.distance_m == round(haversine_m(CAMPUS.lat, CAMPUS.lon, 42.3615, -71.0901), 1)
    assert 100.0 < second.distance_m < 500.0

    # latitude/longitude "0" -> no geo; datetakenunknown=1 -> the date is an upload date
    assert fourth.geo is None and fourth.distance_m is None
    assert (fourth.date, fourth.date_kind) == ("2018-05-20", "uploaded")
    assert fourth.image_url.endswith("_z.jpg")


def test_license_names_override_and_unknown_ids() -> None:
    data = read_fixture(FIXTURE)
    names = {4: "Attribution License", 0: "All Rights Reserved"}
    candidates = parse_flickr_photos(data, campus=CAMPUS, license_names=names)
    assert candidates[0].license == "Attribution License"
    assert candidates[1].license == "All Rights Reserved"
    assert license_name("99", names) is None
    assert license_name("9", names) == "CC0"  # falls back to the hardcoded map
    assert license_name(None, names) is None
    assert license_name("x", names) is None
    assert parse_flickr_photos(data, campus=CAMPUS)[0].license == "CC BY 2.0"


def test_unknown_keys_ignored_and_no_campus() -> None:
    data = read_fixture(FIXTURE)
    assert "an_unknown_future_key" in data["photos"]["photo"][0]
    candidates = parse_flickr_photos(data, campus=None, license_names=DEFAULT_LICENSES)
    assert len(candidates) == 3
    assert candidates[0].geo is not None and candidates[0].distance_m is None


def test_exclusion_regex_on_tags_and_description() -> None:
    data = copy.deepcopy(read_fixture(FIXTURE))
    photos = data["photos"]["photo"]
    photos[0]["tags"] = "campus logo"
    photos[1]["description"]["_content"] = "Screenshot of the site"
    candidates = parse_flickr_photos(data, campus=CAMPUS, license_names=DEFAULT_LICENSES)
    assert [c.source_page_url for c in candidates] == [
        "https://www.flickr.com/photos/44444444@N04/10000000004/"
    ]


def test_malformed_entries_and_shapes() -> None:
    assert parse_flickr_photos({}, campus=CAMPUS) == []
    assert parse_flickr_photos(None, campus=CAMPUS) == []
    assert parse_flickr_photos({"photos": {"photo": "nope"}}, campus=CAMPUS) == []
    data = copy.deepcopy(read_fixture(FIXTURE))
    photos = data["photos"]["photo"]
    photos[0].pop("owner")  # no owner -> no source page URL -> skipped
    photos[1]["url_m"] = "javascript:alert(1)"  # not http(s) -> skipped
    photos[3]["latitude"], photos[3]["longitude"] = "", None
    photos.append("garbage")
    photos.append({"id": "x", "owner": "y", "url_z": "https://live.staticflickr.com/x_z.jpg"})
    candidates = parse_flickr_photos(data, campus=CAMPUS)
    assert [c.source_page_url for c in candidates] == [
        "https://www.flickr.com/photos/44444444@N04/10000000004/",
        "https://www.flickr.com/photos/y/x/",
    ]
    assert candidates[0].geo is None
    minimal = candidates[1]
    assert minimal.title is None and minimal.license is None
    assert (minimal.date, minimal.date_kind) == (None, "unknown")
    assert (minimal.width, minimal.height) == (None, None)


@pytest.mark.parametrize(
    ("value", "flag", "expected"),
    [
        ("2019-06-12 18:45:03", "0", ("2019-06-12", "taken")),
        ("2019-06-12 18:45:03", None, ("2019-06-12", "taken")),
        ("2019-06-12 18:45:03", "1", ("2019-06-12", "uploaded")),
        ("2019-13-12 18:45:03", "0", (None, "unknown")),
        ("0000-00-00 00:00:00", "0", (None, "unknown")),
        ("12 June 2019", "0", (None, "unknown")),
        ("", "0", (None, "unknown")),
        (None, "0", (None, "unknown")),
    ],
)
def test_parse_taken_date(value: str | None, flag: str | None, expected: tuple) -> None:
    assert parse_taken_date(value, unknown_flag=flag) == expected


def test_geo_search_params_are_section_7_4a() -> None:
    params = geo_search_params("KEY", CAMPUS)
    assert params == {
        "method": "flickr.photos.search",
        "api_key": "KEY",
        "lat": "42.359722",
        "lon": "-71.091944",
        "radius": "1",
        "radius_units": "km",
        "has_geo": "1",
        "min_taken_date": "2008-01-01",
        "content_type": "1",
        "media": "photos",
        "safe_search": "1",
        "sort": "relevance",
        "per_page": "60",
        "page": "1",
        "extras": EXTRAS,
        "format": "json",
        "nojsoncallback": "1",
    }
    assert EXTRAS == "date_taken,license,geo,url_m,url_z,url_l,owner_name,o_dims,description,tags"


def test_text_search_params_are_section_7_4b() -> None:
    params = text_search_params("KEY", "Nazarbayev University", CAMPUS)
    assert params["text"] == "Nazarbayev University"
    assert params["radius"] == "5"
    assert params["per_page"] == "40"
    assert params["has_geo"] == "1"
    assert params["min_taken_date"] == "2008-01-01"
    assert params["lat"] == "42.359722" and params["radius_units"] == "km"
    assert params["nojsoncallback"] == "1" and params["format"] == "json"
    without = text_search_params("KEY", "Nazarbayev University", None)
    assert "lat" not in without and "radius" not in without
    assert without["has_geo"] == "1"


def test_parse_license_names() -> None:
    data = {
        "licenses": {
            "license": [
                {"id": 0, "name": "All Rights Reserved", "url": ""},
                {"id": "4", "name": "Attribution License", "url": "https://creativecommons.org/"},
                {"id": "x", "name": "bad"},
                {"id": 5},
                "garbage",
            ]
        },
        "stat": "ok",
    }
    assert parse_license_names(data) == {0: "All Rights Reserved", 4: "Attribution License"}
    assert parse_license_names({"stat": "fail"}) == {}
    assert parse_license_names(None) == {}
    assert DEFAULT_LICENSES[7] == "No known copyright restrictions" and DEFAULT_LICENSES[10] == (
        "Public Domain Mark"
    )
