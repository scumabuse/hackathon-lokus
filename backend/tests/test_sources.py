"""Source classes and the registry end-to-end over respx with the real saved responses."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import respx

from app.config import Settings
from app.enums import Category, SourceType, WarningCode
from app.http import create_client
from app.models import Coordinates, UniversityHeader
from app.resolver.wikidata import ResolvedEntity
from app.sources.base import (
    MIN_REMAINING_S,
    BaseSource,
    RequestBudget,
    SourceContext,
    SourceResult,
    build_candidate,
    dedupe_by_url,
)
from app.sources.commons import (
    COMMONS_API,
    CommonsCategorySource,
    CommonsGeoSource,
    CommonsSearchSource,
    WikidataP18Source,
    fetch_file_info,
)
from app.sources.flickr import FLICKR_API, FlickrSource
from app.sources.registry import SOURCE_NAMES, build_sources
from tests.conftest import read_fixture

MIT_COORDS = Coordinates(lat=42.359722, lon=-71.091944)
NU_COORDS = Coordinates(lat=51.09, lon=71.399444)
MIT_CATEGORY = "Massachusetts Institute of Technology"
NU_CATEGORY = "Nazarbayev University"
NU_LOCAL_NAME = "Назарбаев Университет"


def mit_resolved(**overrides: Any) -> ResolvedEntity:
    header = UniversityHeader(
        qid="Q49108",
        name=MIT_CATEGORY,
        coords=MIT_COORDS,
        commons_category=MIT_CATEGORY,
        country="United States",
    )
    fields: dict[str, Any] = {
        "header": header,
        "main_image_filename": "MIT Dome night1 Edit.jpg",
        "logo_filename": "MIT 2023 red logo.svg",
    }
    fields.update(overrides)
    return ResolvedEntity(**fields)


def nu_resolved() -> ResolvedEntity:
    header = UniversityHeader(
        qid="Q2783344",
        name=NU_CATEGORY,
        local_name=NU_LOCAL_NAME,
        coords=NU_COORDS,
        commons_category=NU_CATEGORY,
    )
    return ResolvedEntity(header=header)


@pytest.fixture
def settings() -> Settings:
    return Settings(flickr_api_key=None, disable_sources="")


@pytest.fixture
async def http(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    async with create_client(settings) as client:
        yield client


def make_ctx(
    settings: Settings,
    http: httpx.AsyncClient,
    resolved: ResolvedEntity,
    *,
    remaining_s: float = 30.0,
) -> SourceContext:
    return SourceContext(
        settings=settings, http=http, resolved=resolved, deadline=time.monotonic() + remaining_s
    )


def json_response(data: Any) -> httpx.Response:
    return httpx.Response(200, json=data)


class CommonsFake:
    """Routes real fixtures by request parameters and records every call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.calls.append(params)
        assert params.get("format") == "json"
        assert params.get("action") == "query"
        if params.get("generator") == "categorymembers":
            return self.category(params)
        if params.get("list") == "categorymembers":
            assert params["cmtype"] == "subcat" and params["cmlimit"] == "50"
            if params["cmtitle"] == f"Category:{MIT_CATEGORY}":
                return json_response(read_fixture("commons_subcats_mit.json"))
            if params["cmtitle"] == f"Category:{NU_CATEGORY}":
                return json_response(read_fixture("commons_subcats_nu.json"))
            return json_response({"batchcomplete": "", "query": {"categorymembers": []}})
        if params.get("generator") == "search":
            assert params["gsrnamespace"] == "6" and params["gsrlimit"] == "40"
            name = params["gsrsearch"]
            if name == MIT_CATEGORY:
                return json_response(read_fixture("commons_search_mit.json"))
            if name == NU_CATEGORY:
                return json_response(read_fixture("commons_search_nu.json"))
            if name == NU_LOCAL_NAME:
                return json_response(read_fixture("commons_search_nu_local.json"))
            return json_response({"batchcomplete": ""})
        if params.get("generator") == "geosearch":
            if params["ggscoord"] == "42.359722|-71.091944":
                return json_response(read_fixture("commons_geosearch_mit.json"))
            if params["ggscoord"] == "51.09|71.399444":
                return json_response(read_fixture("commons_geosearch_nu.json"))
            return json_response({"batchcomplete": ""})
        if "titles" in params:
            assert params["prop"] == "imageinfo"
            if params["titles"] == "File:MIT Dome night1 Edit.jpg":
                return json_response(read_fixture("commons_file_mit_p18.json"))
            if params["titles"] == "File:MIT 2023 red logo.svg":
                return json_response(read_fixture("commons_file_mit_logo.json"))
            return json_response(
                {
                    "batchcomplete": "",
                    "query": {"pages": {"-1": {"title": params["titles"], "missing": ""}}},
                }
            )
        return httpx.Response(400, json={"error": {"code": "unknown", "info": "unexpected call"}})

    def category(self, params: dict[str, str]) -> httpx.Response:
        assert params["gcmtype"] == "file"
        assert params["prop"] == "imageinfo" and params["iiurlwidth"] == "640"
        title = params["gcmtitle"]
        if title == f"Category:{MIT_CATEGORY}":
            assert params["gcmlimit"] == "50"
            if "gcmcontinue" in params:
                assert params["continue"] == "gcmcontinue||"
                return json_response(read_fixture("commons_category_mit_page2.json"))
            return json_response(read_fixture("commons_category_mit.json"))
        if title == f"Category:{NU_CATEGORY}":
            assert params["gcmlimit"] == "50"
            return json_response(read_fixture("commons_category_nu.json"))
        # subcategories: gcmlimit=30, no continuation ever requested
        assert params["gcmlimit"] == "30"
        assert "gcmcontinue" not in params
        if title in (
            "Category:MIT former Boston campus",
            "Category:Campus of the Massachusetts Institute of Technology",
        ):
            return json_response(read_fixture("commons_subcat_files_mit.json"))
        if title == "Category:Charles Stark Draper Laboratory":
            # real files of another category stand in for the (unrecorded) Draper category
            return json_response(read_fixture("commons_category_nu.json"))
        return json_response({"batchcomplete": ""})

    def with_params(self, **wanted: str) -> list[dict[str, str]]:
        return [c for c in self.calls if all(c.get(k) == v for k, v in wanted.items())]


# ----------------------------------------------------------------------------- base helpers


def test_source_context_and_budget() -> None:
    budget = RequestBudget(deadline=time.monotonic() + 10)
    assert budget.can_start_request() and budget.error is None
    tight = RequestBudget(deadline=time.monotonic() + MIN_REMAINING_S / 2)
    assert not tight.can_start_request()
    tight.skip("x")
    assert tight.skipped == 1 and tight.errors == []
    tight.fail("commons category", httpx.ConnectError("down"))
    tight.fail("second", ValueError("bad"))
    assert tight.error == "commons category: ConnectError: down; second: ValueError: bad"
    assert RequestBudget().can_start_request()


def test_build_candidate_validates_urls_and_clips() -> None:
    assert (
        build_candidate(
            source_type=SourceType.commons_search,
            image_url="ftp://x/y.jpg",
            source_page_url="https://x/y",
            source_label="L",
        )
        is None
    )
    assert (
        build_candidate(
            source_type=SourceType.commons_search,
            image_url="https://x/y.jpg",
            source_page_url="not a url",
            source_label="L",
        )
        is None
    )
    candidate = build_candidate(
        source_type=SourceType.commons_search,
        image_url="https://x/y.jpg",
        source_page_url="https://x/y",
        source_label="L",
        title="  a " * 400,
        author="b" * 100,
        license="",
    )
    assert candidate is not None
    assert candidate.title is not None and len(candidate.title) == 300
    assert candidate.author == "b" * 80
    assert candidate.license is None
    dup = build_candidate(
        source_type=SourceType.commons_search,
        image_url="https://x/y.jpg",
        source_page_url="https://x/z",
        source_label="L",
    )
    assert dup is not None
    assert dedupe_by_url([candidate, dup, candidate]) == [candidate]


async def test_base_source_never_raises(settings: Settings, http: httpx.AsyncClient) -> None:
    class Broken(BaseSource):
        name = "broken"
        source_type = SourceType.web_search

        async def collect(self, ctx: SourceContext, result: SourceResult) -> None:
            result.candidates.append(
                build_candidate(
                    source_type=self.source_type,
                    image_url="https://x/y.jpg",
                    source_page_url="https://x/y",
                    source_label="L",
                )
            )
            raise KeyError("boom")

    result = await Broken().fetch(make_ctx(settings, http, mit_resolved()))
    assert result.name == "broken"
    assert result.error == "broken: KeyError: 'boom'"
    # a source that still contributed photos is not "unavailable" (no misleading UI warning)
    assert result.warnings == []
    assert len(result.candidates) == 1  # gathered before the failure
    assert result.elapsed_ms >= 0


# ----------------------------------------------------------------------------- Commons category


async def test_commons_category_source_end_to_end(
    settings: Settings, http: httpx.AsyncClient
) -> None:
    fake = CommonsFake()
    with respx.mock(assert_all_called=False) as router:
        router.get(COMMONS_API).mock(side_effect=fake)
        result = await CommonsCategorySource().fetch(make_ctx(settings, http, mit_resolved()))
    assert result.error is None and result.warnings == []
    assert result.name == "commons_category"
    assert result.source_type is SourceType.commons_category
    # main page 35 + continuation 24 + Boston campus 23 (Campus-of duplicates deduped) + Draper 28
    assert len(result.candidates) == 110
    assert len({c.image_url for c in result.candidates}) == 110
    assert all(c.source_type is SourceType.commons_category for c in result.candidates)
    assert all(
        c.page_title is not None and c.page_title.startswith("File:") for c in result.candidates
    )
    hints = [c.source_hint_category for c in result.candidates]
    assert hints.count(Category.lab) == 28
    assert hints.count(None) == 82
    assert result.candidates[0].filename == "BEC1.1.jpg"  # main category files come first
    assert result.candidates[-1].source_hint_category is Category.lab
    assert len(fake.calls) == 6
    assert len(fake.with_params(generator="categorymembers", gcmlimit="50")) == 2
    assert len(fake.with_params(list="categorymembers")) == 1
    subcat_calls = fake.with_params(generator="categorymembers", gcmlimit="30")
    assert [c["gcmtitle"] for c in subcat_calls] == [
        "Category:MIT former Boston campus",
        "Category:Campus of the Massachusetts Institute of Technology",
        "Category:Charles Stark Draper Laboratory",
    ]
    for call in fake.calls:
        assert call["format"] == "json"


async def test_commons_category_source_nu_no_matching_subcats(
    settings: Settings, http: httpx.AsyncClient
) -> None:
    fake = CommonsFake()
    with respx.mock(assert_all_called=False) as router:
        router.get(COMMONS_API).mock(side_effect=fake)
        result = await CommonsCategorySource().fetch(make_ctx(settings, http, nu_resolved()))
    assert result.error is None
    assert len(result.candidates) == 28
    assert all(c.source_hint_category is None for c in result.candidates)
    # no continuation on the NU page; the single (non-matching) subcategory is fetched (first-8 rule)
    assert [c["gcmtitle"] for c in fake.with_params(generator="categorymembers")] == [
        f"Category:{NU_CATEGORY}",
        "Category:Shigeo Katsu",
    ]


async def test_commons_category_source_without_category(
    settings: Settings, http: httpx.AsyncClient
) -> None:
    fake = CommonsFake()
    resolved = mit_resolved(
        header=mit_resolved().header.model_copy(update={"commons_category": None})
    )
    with respx.mock(assert_all_called=False) as router:
        router.get(COMMONS_API).mock(side_effect=fake)
        result = await CommonsCategorySource().fetch(make_ctx(settings, http, resolved))
    assert result.candidates == [] and result.error is None
    assert [w.code for w in result.warnings] == [WarningCode.no_commons_category]
    assert fake.calls == []


async def test_commons_category_source_respects_deadline(
    settings: Settings, http: httpx.AsyncClient
) -> None:
    fake = CommonsFake()
    with respx.mock(assert_all_called=False) as router:
        router.get(COMMONS_API).mock(side_effect=fake)
        ctx = make_ctx(settings, http, mit_resolved(), remaining_s=-5.0)
        result = await CommonsCategorySource().fetch(ctx)
    assert result.candidates == [] and result.warnings == [] and result.error is None
    assert fake.calls == []
    assert ctx.remaining_s() < 0 and not ctx.can_start_request()


@pytest.mark.usefixtures("fast_retries")
async def test_commons_category_source_connect_error(
    settings: Settings, http: httpx.AsyncClient
) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(COMMONS_API).mock(side_effect=httpx.ConnectError("down"))
        result = await CommonsCategorySource().fetch(make_ctx(settings, http, mit_resolved()))
    assert result.candidates == []
    assert result.error is not None and "ConnectError" in result.error
    assert (
        result.warnings == [result.warnings[0]]
        and result.warnings[0].code is WarningCode.source_unavailable
    )
    assert result.warnings[0].detail == "commons_category"


@pytest.mark.usefixtures("fast_retries")
async def test_commons_category_source_partial_failure_keeps_candidates(
    settings: Settings, http: httpx.AsyncClient
) -> None:
    fake = CommonsFake()

    def flaky(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("list") == "categorymembers":
            return httpx.Response(503)
        return fake(request)

    with respx.mock(assert_all_called=False) as router:
        router.get(COMMONS_API).mock(side_effect=flaky)
        result = await CommonsCategorySource().fetch(make_ctx(settings, http, mit_resolved()))
    assert len(result.candidates) == 59  # main page + continuation survived
    assert result.error is not None and "HTTP 503" in result.error
    assert result.warnings == []  # partial failure: the photos it found still count


async def test_base_source_with_nothing_gathered_warns(
    settings: Settings, http: httpx.AsyncClient
) -> None:
    class Empty(BaseSource):
        name = "empty"
        source_type = SourceType.web_search

        async def collect(self, ctx: SourceContext, result: SourceResult) -> None:
            raise RuntimeError("down")

    result = await Empty().fetch(make_ctx(settings, http, mit_resolved()))
    assert result.candidates == []
    assert [w.code for w in result.warnings] == [WarningCode.source_unavailable]
    assert result.warnings[0].detail == "empty"


# ----------------------------------------------------------------------------- Wikidata P18


async def test_wikidata_p18_source(settings: Settings, http: httpx.AsyncClient) -> None:
    fake = CommonsFake()
    with respx.mock(assert_all_called=False) as router:
        router.get(COMMONS_API).mock(side_effect=fake)
        result = await WikidataP18Source().fetch(make_ctx(settings, http, mit_resolved()))
    assert result.error is None and result.warnings == []
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.source_type is SourceType.wikidata_p18
    assert candidate.filename == "MIT Dome night1 Edit.jpg"
    assert candidate.page_title == "File:MIT Dome night1 Edit.jpg"
    assert candidate.geo is None and candidate.distance_m is None
    assert fake.calls[0]["titles"] == "File:MIT Dome night1 Edit.jpg"
    assert len(fake.calls) == 1


async def test_wikidata_p18_source_without_main_image(
    settings: Settings, http: httpx.AsyncClient
) -> None:
    fake = CommonsFake()
    with respx.mock(assert_all_called=False) as router:
        router.get(COMMONS_API).mock(side_effect=fake)
        result = await WikidataP18Source().fetch(
            make_ctx(settings, http, mit_resolved(main_image_filename=None))
        )
    assert result.candidates == [] and result.warnings == [] and result.error is None
    assert fake.calls == []


async def test_wikidata_p18_source_missing_file_and_logo_info(
    settings: Settings, http: httpx.AsyncClient
) -> None:
    fake = CommonsFake()
    with respx.mock(assert_all_called=False) as router:
        router.get(COMMONS_API).mock(side_effect=fake)
        result = await WikidataP18Source().fetch(
            make_ctx(settings, http, mit_resolved(main_image_filename="Does not exist.jpg"))
        )
        info = await fetch_file_info(http, "MIT 2023 red logo.svg")
    assert result.candidates == [] and result.error is None
    assert info is not None
    assert info["mime"] == "image/svg+xml"
    assert info["thumburl"].endswith(
        ".svg.png?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail"
    )
    assert info["url"].startswith("https://upload.wikimedia.org/")


# ----------------------------------------------------------------------------- Commons search


async def test_commons_search_source_with_local_name(
    settings: Settings, http: httpx.AsyncClient
) -> None:
    fake = CommonsFake()
    with respx.mock(assert_all_called=False) as router:
        router.get(COMMONS_API).mock(side_effect=fake)
        result = await CommonsSearchSource().fetch(make_ctx(settings, http, nu_resolved()))
    assert result.error is None
    searches = fake.with_params(generator="search")
    assert len(fake.calls) == 2 and len(searches) == 2
    assert {c["gsrsearch"] for c in searches} == {NU_CATEGORY, NU_LOCAL_NAME}
    assert len(result.candidates) == 40  # 35 + 35 with 30 shared URLs
    assert all(c.source_type is SourceType.commons_search for c in result.candidates)
    assert all(c.page_title for c in result.candidates)


async def test_commons_search_source_single_name(
    settings: Settings, http: httpx.AsyncClient
) -> None:
    fake = CommonsFake()
    with respx.mock(assert_all_called=False) as router:
        router.get(COMMONS_API).mock(side_effect=fake)
        result = await CommonsSearchSource().fetch(make_ctx(settings, http, mit_resolved()))
    assert len(fake.calls) == 1
    assert len(result.candidates) == 33


# ----------------------------------------------------------------------------- Commons geosearch


async def test_commons_geo_source(settings: Settings, http: httpx.AsyncClient) -> None:
    fake = CommonsFake()
    with respx.mock(assert_all_called=False) as router:
        router.get(COMMONS_API).mock(side_effect=fake)
        result = await CommonsGeoSource().fetch(make_ctx(settings, http, mit_resolved()))
    assert result.error is None and result.warnings == []
    assert result.source_type is SourceType.commons_geo
    assert len(result.candidates) == 50
    assert sum(1 for c in result.candidates if c.distance_m is not None) == 47
    assert all(c.source_type is SourceType.commons_geo for c in result.candidates)
    assert all(c.source_label == "Wikimedia Commons" for c in result.candidates)
    call = fake.calls[0]
    assert call["generator"] == "geosearch"
    assert call["ggscoord"] == "42.359722|-71.091944"
    assert call["ggsradius"] == "1000" and call["ggsnamespace"] == "6"
    assert call["ggslimit"] == "50" and call["ggsprimary"] == "all"
    assert call["prop"] == "imageinfo|coordinates"
    assert call["colimit"] == "50"
    assert call["iiextmetadatafilter"] == (
        "DateTimeOriginal|LicenseShortName|Artist|ImageDescription|ObjectName"
    )


async def test_commons_geo_source_without_coords(
    settings: Settings, http: httpx.AsyncClient
) -> None:
    fake = CommonsFake()
    resolved = mit_resolved(header=mit_resolved().header.model_copy(update={"coords": None}))
    with respx.mock(assert_all_called=False) as router:
        router.get(COMMONS_API).mock(side_effect=fake)
        result = await CommonsGeoSource().fetch(make_ctx(settings, http, resolved))
    assert result.candidates == [] and result.warnings == [] and result.error is None
    assert fake.calls == []


@pytest.mark.usefixtures("fast_retries")
async def test_commons_geo_source_503(settings: Settings, http: httpx.AsyncClient) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(COMMONS_API).mock(return_value=httpx.Response(503))
        result = await CommonsGeoSource().fetch(make_ctx(settings, http, mit_resolved()))
    assert result.candidates == []
    assert result.error is not None and "HTTP 503" in result.error
    assert [(w.code, w.detail) for w in result.warnings] == [
        (WarningCode.source_unavailable, "commons_geo")
    ]


async def test_commons_api_error_object_is_a_failure(
    settings: Settings, http: httpx.AsyncClient
) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(COMMONS_API).mock(
            return_value=httpx.Response(
                200, json={"error": {"code": "badvalue", "info": "Unrecognized value"}}
            )
        )
        result = await CommonsGeoSource().fetch(make_ctx(settings, http, mit_resolved()))
    assert result.candidates == []
    assert result.error is not None and "badvalue" in result.error


# ----------------------------------------------------------------------------- Flickr


async def test_flickr_source_without_key_is_silent(
    settings: Settings, http: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    assert settings.flickr_api_key is None
    with respx.mock(assert_all_called=False) as router:
        route = router.route().mock(side_effect=httpx.ConnectError("no network expected"))
        with caplog.at_level("INFO"):
            result = await FlickrSource().fetch(make_ctx(settings, http, mit_resolved()))
    assert result.candidates == [] and result.warnings == [] and result.error is None
    assert result.name == "flickr" and result.source_type is SourceType.flickr_geo
    assert not route.called
    assert not [r for r in caplog.records if "flickr" in r.getMessage().lower() and r.levelno > 10]


class FlickrFake:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.calls.append(params)
        assert params["format"] == "json" and params["nojsoncallback"] == "1"
        assert params["api_key"] == "fake-key"
        if params["method"] == "flickr.photos.licenses.getInfo":
            return json_response(
                {
                    "licenses": {
                        "license": [
                            {"id": 0, "name": "All Rights Reserved", "url": ""},
                            {"id": 4, "name": "Attribution License", "url": "https://cc/by"},
                        ]
                    },
                    "stat": "ok",
                }
            )
        assert params["method"] == "flickr.photos.search"
        return json_response(read_fixture("flickr_photos_search_sample.json"))


async def test_flickr_source_with_key(http: httpx.AsyncClient) -> None:
    settings = Settings(flickr_api_key="fake-key", disable_sources="")
    fake = FlickrFake()
    source = FlickrSource()
    with respx.mock(assert_all_called=False) as router:
        router.get(FLICKR_API).mock(side_effect=fake)
        result = await source.fetch(make_ctx(settings, http, mit_resolved()))
        again = await source.fetch(make_ctx(settings, http, mit_resolved()))
    assert result.error is None and result.warnings == []
    assert len(result.candidates) == 3  # geo + text searches return the same sample -> deduped
    assert result.candidates[0].license == "Attribution License"  # from licenses.getInfo
    assert result.candidates[1].license == "All Rights Reserved"
    assert result.candidates[0].distance_m == 0.0
    methods = [c["method"] for c in fake.calls]
    assert methods.count("flickr.photos.licenses.getInfo") == 1  # cached on the instance
    assert methods.count("flickr.photos.search") == 4
    assert len(again.candidates) == 3
    geo = next(c for c in fake.calls if c["method"] == "flickr.photos.search" and "text" not in c)
    assert geo["min_taken_date"] == "2008-01-01"
    assert geo["has_geo"] == "1"
    assert geo["radius_units"] == "km" and geo["radius"] == "1"
    assert geo["nojsoncallback"] == "1"
    assert geo["lat"] == "42.359722" and geo["lon"] == "-71.091944"
    assert geo["per_page"] == "60" and geo["page"] == "1"
    assert geo["content_type"] == "1" and geo["media"] == "photos" and geo["safe_search"] == "1"
    assert geo["sort"] == "relevance"
    assert geo["extras"].endswith("description,tags")
    text = next(c for c in fake.calls if c["method"] == "flickr.photos.search" and "text" in c)
    assert text["text"] == MIT_CATEGORY
    assert text["radius"] == "5" and text["per_page"] == "40"
    assert text["min_taken_date"] == "2008-01-01" and text["has_geo"] == "1"


async def test_flickr_source_without_coords_runs_text_search_only(
    http: httpx.AsyncClient,
) -> None:
    settings = Settings(flickr_api_key="fake-key", disable_sources="")
    fake = FlickrFake()
    resolved = mit_resolved(header=mit_resolved().header.model_copy(update={"coords": None}))
    with respx.mock(assert_all_called=False) as router:
        router.get(FLICKR_API).mock(side_effect=fake)
        result = await FlickrSource().fetch(make_ctx(settings, http, resolved))
    searches = [c for c in fake.calls if c["method"] == "flickr.photos.search"]
    assert len(searches) == 1 and "lat" not in searches[0] and searches[0]["text"] == MIT_CATEGORY
    assert len(result.candidates) == 3
    assert all(c.distance_m is None for c in result.candidates)


@pytest.mark.usefixtures("fast_retries")
async def test_flickr_source_failures(http: httpx.AsyncClient) -> None:
    settings = Settings(flickr_api_key="fake-key", disable_sources="")
    with respx.mock(assert_all_called=False) as router:
        router.get(FLICKR_API).mock(side_effect=httpx.ConnectError("down"))
        result = await FlickrSource().fetch(make_ctx(settings, http, mit_resolved()))
    assert result.candidates == []
    assert result.error is not None and "ConnectError" in result.error
    assert [(w.code, w.detail) for w in result.warnings] == [
        (WarningCode.source_unavailable, "flickr")
    ]
    with respx.mock(assert_all_called=False) as router:
        router.get(FLICKR_API).mock(
            return_value=httpx.Response(
                200, json={"stat": "fail", "code": 100, "message": "Invalid API Key"}
            )
        )
        result = await FlickrSource().fetch(make_ctx(settings, http, mit_resolved()))
    assert result.candidates == []
    assert result.error is not None and "Invalid API Key" in result.error


# ----------------------------------------------------------------------------- registry


def test_build_sources_default_without_flickr_key() -> None:
    sources = build_sources(Settings(flickr_api_key=None, disable_sources=""))
    assert [s.name for s in sources] == [
        "wikidata_p18",
        "official_site",
        "commons_category",
        "commons_geo",
        "commons_search",
        "city_commons",
    ]
    assert [s.source_type for s in sources] == [
        SourceType.wikidata_p18,
        SourceType.official_site,
        SourceType.commons_category,
        SourceType.commons_geo,
        SourceType.commons_search,
        SourceType.city_commons,
    ]
    assert SOURCE_NAMES == (
        "wikidata_p18",
        "official_site",
        "commons_category",
        "commons_geo",
        "flickr",
        "commons_search",
        "city_commons",
    )


def test_build_sources_with_flickr_key() -> None:
    sources = build_sources(Settings(flickr_api_key="fake-key", disable_sources=""))
    assert [s.name for s in sources] == list(SOURCE_NAMES)


def test_build_sources_honours_disable_sources() -> None:
    settings = Settings(flickr_api_key="fake-key", disable_sources="commons_category,commons_geo")
    assert [s.name for s in build_sources(settings)] == [
        "wikidata_p18",
        "official_site",
        "flickr",
        "commons_search",
        "city_commons",
    ]
    settings = Settings(
        flickr_api_key=None, disable_sources=" Commons_Category , commons_geo ,nope"
    )
    assert [s.name for s in build_sources(settings)] == [
        "wikidata_p18",
        "official_site",
        "commons_search",
        "city_commons",
    ]
    settings = Settings(flickr_api_key="fake-key", disable_sources="flickr")
    assert "flickr" not in [s.name for s in build_sources(settings)]


async def test_all_registry_sources_run_on_fixtures(http: httpx.AsyncClient) -> None:
    # official_site and city_commons need hosts the Commons fixtures do not cover
    settings = Settings(flickr_api_key=None, disable_sources="official_site,city_commons")
    fake = CommonsFake()
    with respx.mock(assert_all_called=False) as router:
        router.get(COMMONS_API).mock(side_effect=fake)
        results = [
            await s.fetch(make_ctx(settings, http, mit_resolved())) for s in build_sources(settings)
        ]
    counts = {r.name: len(r.candidates) for r in results}
    assert counts == {
        "wikidata_p18": 1,
        "commons_category": 110,
        "commons_geo": 50,
        "commons_search": 33,
    }
    assert all(r.error is None for r in results)
    # every candidate is JSON-serialisable and carries a stable photo id
    for r in results:
        for c in r.candidates:
            assert len(c.photo_id) == 16
            json.dumps(c.model_dump(mode="json"))
