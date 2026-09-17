"""GET /api/search flow with every external call mocked by respx over real saved responses."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.http import create_client
from app.main import create_app
from app.models import SearchResponse
from app.resolver import search as search_module
from app.resolver import wikipedia
from app.resolver.search import search_universities

MIT = "Q49108"
NU = "Q2783344"
COLUMBIA_UNIVERSITY = "Q49088"
KOSTANAY_REGIONAL = "Q123694980"
GUMILYOV = "Q127745"
WIKIPEDIA_EN_API = "https://en.wikipedia.org/w/api.php"

ENTITY_FIXTURES = (
    "wikidata_entities_mit.json",
    "wikidata_entities_mit_subunits.json",
    "wikidata_entities_cambridge.json",
    "wikidata_entities_columbia.json",
    "wikidata_entities_nazarbayev.json",
    "wikidata_entities_kostanay.json",
    "wikidata_entities_human.json",
    "wikidata_labels_country_city.json",
    "wikidata_labels_kazakhstan_astana.json",
    "wikidata_labels_soviet_union_kazakhstan.json",
)
EMPTY_FULLTEXT = {"batchcomplete": "", "query": {"searchinfo": {"totalhits": 0}, "search": []}}


class FakeWeb:
    """Answers Wikidata / Wikipedia requests from saved responses, keyed by query parameters."""

    def __init__(
        self,
        load: Callable[[str], Any],
        *,
        searches: dict[str, str] | None = None,
        fulltext: dict[str, str] | None = None,
        opensearch: dict[str, str] | None = None,
        pageprops: dict[str, str] | None = None,
    ) -> None:
        self.entities: dict[str, dict[str, Any]] = {}
        for name in ENTITY_FIXTURES:
            self.entities.update(load(name)["entities"])
        self.searches = {text: load(name) for text, name in (searches or {}).items()}
        self.empty_search = load("wikidata_search_nonsense_en.json")
        self.fulltext = {text: load(name) for text, name in (fulltext or {}).items()}
        self.opensearch = {lang: load(name) for lang, name in (opensearch or {}).items()}
        self.pageprops = {lang: load(name) for lang, name in (pageprops or {}).items()}
        self.calls: list[httpx.URL] = []

    def wikidata(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request.url)
        params = request.url.params
        assert params.get("format") == "json"
        action = params.get("action")
        if action == "wbsearchentities":
            assert params.get("type") == "item"
            assert params.get("uselang") == "en"
            data = self.searches.get(params.get("search", ""), self.empty_search)
            return httpx.Response(200, json=data)
        if action == "wbgetentities":
            ids = params.get("ids", "").split("|")
            assert len(ids) <= 50
            entities = {qid: self.entities.get(qid, {"id": qid, "missing": ""}) for qid in ids}
            return httpx.Response(200, json={"entities": entities, "success": 1})
        if action == "query" and params.get("list") == "search":
            assert params.get("srnamespace") == "0"
            data = self.fulltext.get(params.get("srsearch", ""), EMPTY_FULLTEXT)
            return httpx.Response(200, json=data)
        return httpx.Response(400, json={"error": {"code": "unknown_action"}})

    def wikipedia(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request.url)
        params = request.url.params
        lang = request.url.host.split(".")[0]
        assert params.get("format") == "json"
        if params.get("action") == "opensearch":
            empty = [params.get("search", ""), [], [], []]
            return httpx.Response(200, json=self.opensearch.get(lang, empty))
        if params.get("action") == "query" and params.get("prop") == "pageprops":
            assert params.get("redirects") == "1"
            empty = {"batchcomplete": "", "query": {"pages": {}}}
            return httpx.Response(200, json=self.pageprops.get(lang, empty))
        return httpx.Response(400, json={"error": {"code": "unknown_action"}})

    def install(self, router: respx.Router) -> None:
        router.get(host="www.wikidata.org", path="/w/api.php").mock(side_effect=self.wikidata)
        router.get(host__regex=r"^[a-z]+\.wikipedia\.org$", path="/w/api.php").mock(
            side_effect=self.wikipedia
        )

    def wikidata_calls(self, action: str) -> list[httpx.URL]:
        return [url for url in self.calls if url.params.get("action") == action]


class FakeCache:
    def __init__(self, stored: dict[str, Any] | None = None) -> None:
        self.stored = stored
        self.reads: list[str] = []
        self.writes: list[tuple[str, dict[str, Any]]] = []

    async def get_search(self, q_norm: str) -> dict[str, Any] | None:
        self.reads.append(q_norm)
        return self.stored

    async def set_search(self, q_norm: str, data: dict[str, Any]) -> None:
        self.writes.append((q_norm, data))


@pytest.fixture
async def http(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    async with create_client(settings) as client:
        yield client


async def test_normal_search_columbia(
    load_fixture: Callable[[str], Any], http: httpx.AsyncClient
) -> None:
    web = FakeWeb(
        load_fixture,
        searches={
            "Columbia": "wikidata_search_columbia_en.json",
            "Columbia university": "wikidata_search_columbia_university_en.json",
        },
    )
    with respx.mock(assert_all_called=False) as router:
        web.install(router)
        response = await search_universities(http, "Columbia")
    assert response.query == "Columbia"
    assert response.candidates
    first = response.candidates[0]
    assert first.qid == COLUMBIA_UNIVERSITY
    assert first.label == "Columbia University"
    assert first.description == "private university in New York City, New York, US"
    assert first.country == "United States"
    assert first.city == "Manhattan"
    assert response.suggestions_used is False
    assert response.corrected_query is None
    qids = [c.qid for c in response.candidates]
    assert len(qids) == len(set(qids))
    assert len(qids) <= 8
    # en/ru/kk + the extra "<q> university" search, one entity fetch, ONE labels call
    assert len(web.wikidata_calls("wbsearchentities")) == 4
    fetches = web.wikidata_calls("wbgetentities")
    assert [url.params.get("props") for url in fetches].count("labels") == 1
    assert not web.wikidata_calls("opensearch")


async def test_normal_search_nazarbayev_exactly_one(
    load_fixture: Callable[[str], Any], http: httpx.AsyncClient
) -> None:
    web = FakeWeb(
        load_fixture, searches={"Nazarbayev University": "wikidata_search_nazarbayev_en.json"}
    )
    cache = FakeCache()
    with respx.mock(assert_all_called=False) as router:
        web.install(router)
        response = await search_universities(http, "Nazarbayev University", cache=cache)
    assert [c.qid for c in response.candidates] == [NU]
    candidate = response.candidates[0]
    assert candidate.label == "Nazarbayev University"
    assert candidate.description == "international research university based in Astana, Kazakhstan"
    assert candidate.country == "Kazakhstan"
    assert candidate.city == "Astana"
    assert len(web.wikidata_calls("wbsearchentities")) == 3  # query already names a university
    assert cache.reads == ["nazarbayev university"]
    assert len(cache.writes) == 1
    assert cache.writes[0][0] == "nazarbayev university"
    assert cache.writes[0][1]["candidates"][0]["qid"] == NU


async def test_opensearch_fallback(
    load_fixture: Callable[[str], Any], http: httpx.AsyncClient
) -> None:
    web = FakeWeb(
        load_fixture,
        opensearch={"en": "wikipedia_opensearch_en_misspelled.json"},
        pageprops={"en": "wikipedia_pageprops_en.json"},
    )
    with respx.mock(assert_all_called=False) as router:
        web.install(router)
        response = await search_universities(http, "Massachusets Institut of Technology")
    assert response.candidates
    assert response.candidates[0].qid == MIT
    assert response.candidates[0].label == "Massachusetts Institute of Technology"
    assert response.candidates[0].country == "United States"
    assert response.corrected_query == "Massachusetts Institute of Technology"
    assert response.suggestions_used is False
    assert all(c.label for c in response.candidates)
    assert "Q6784299" not in [c.qid for c in response.candidates]  # MIT Libraries filtered out
    assert "Q17020544" not in [c.qid for c in response.candidates]  # MIT Police filtered out
    hosts = {url.host for url in web.calls if url.params.get("action") == "opensearch"}
    assert hosts == {"en.wikipedia.org", "ru.wikipedia.org"}


async def test_spelling_fallback(
    load_fixture: Callable[[str], Any], http: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []

    async def fake_suggest(ai: object, q: str) -> list[str]:
        asked.append(q)
        return ["Nazarbaev Univ", "Nazarbayev University", "Astana University"]

    monkeypatch.setattr(search_module, "suggest_official_names", fake_suggest)
    web = FakeWeb(
        load_fixture, searches={"Nazarbayev University": "wikidata_search_nazarbayev_en.json"}
    )
    with respx.mock(assert_all_called=False) as router:
        web.install(router)
        response = await search_universities(http, "Nazarbaev Univercity", ai=object())
    assert asked == ["Nazarbaev Univercity"]
    assert response.suggestions_used is True
    assert response.corrected_query == "Nazarbayev University"  # first name (in order) that worked
    assert [c.qid for c in response.candidates] == [NU]
    searched = [url.params.get("search") for url in web.wikidata_calls("wbsearchentities")]
    # the three suggested names are searched together (en only), not one after another
    assert searched[-3:] == ["Nazarbaev Univ", "Nazarbayev University", "Astana University"]
    assert all(
        url.params.get("language") == "en" for url in web.wikidata_calls("wbsearchentities")[-3:]
    )


async def test_fulltext_fallback_finds_label_containing_the_query(
    load_fixture: Callable[[str], Any], http: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Section 13 chip: the label only *contains* the query and the entity has no Wikipedia page."""

    async def fake_suggest(ai: object, q: str) -> list[str]:
        raise AssertionError("the full-text step must run before the LLM step")

    monkeypatch.setattr(search_module, "suggest_official_names", fake_suggest)
    query = "Kostanay Regional University"
    web = FakeWeb(load_fixture, fulltext={query: "wikidata_fulltext_search_kostanay_en.json"})
    with respx.mock(assert_all_called=False) as router:
        web.install(router)
        response = await search_universities(http, query, ai=object())
    assert [c.qid for c in response.candidates] == [KOSTANAY_REGIONAL]
    candidate = response.candidates[0]
    assert candidate.label == "Akhmet Baitursynuly Kostanay Regional University"
    assert candidate.country == "Kazakhstan"
    assert response.corrected_query == candidate.label
    assert response.suggestions_used is False
    # order of the chain: wbsearchentities (en/ru/kk) -> opensearch (en, ru) -> full text ->
    # entity fetch; the query already contains "University", so no augmented search is made
    actions = [(url.host, url.params.get("action"), url.params.get("list")) for url in web.calls]
    fulltext_at = actions.index(("www.wikidata.org", "query", "search"))
    assert all(a[1] == "wbsearchentities" for a in actions[:3])
    assert {a[0] for a in actions[3:fulltext_at]} == {"en.wikipedia.org", "ru.wikipedia.org"}
    assert actions[fulltext_at + 1][1] == "wbgetentities"


async def test_titles_to_qids_follows_redirects(
    load_fixture: Callable[[str], Any], http: httpx.AsyncClient
) -> None:
    """A redirect title (as opensearch returns them) maps to the QID of its target page."""
    title = "L.N. Gumilyov Eurasian National University"
    seen: list[httpx.QueryParams] = []

    def pageprops(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params)
        return httpx.Response(200, json=load_fixture("wikipedia_pageprops_en_redirect.json"))

    with respx.mock(assert_all_called=True) as router:
        router.get(WIKIPEDIA_EN_API).mock(side_effect=pageprops)
        qids = await wikipedia.titles_to_qids(http, "en", [title])
    assert qids == [GUMILYOV]
    assert seen[0].get("redirects") == "1"
    assert seen[0].get("titles") == title
    assert seen[0].get("ppprop") == "wikibase_item"


async def test_blank_query_makes_no_network_calls(http: httpx.AsyncClient) -> None:
    cache = FakeCache()
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=httpx.ConnectError("no network expected"))
        for raw in ("   ", " a ", "", "\t\n"):
            response = await search_universities(http, raw, cache=cache)
            assert response.candidates == []
        assert router.calls.call_count == 0
    assert cache.reads == []
    assert cache.writes == []


async def test_search_deadline_returns_empty(
    http: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slow / unreachable backend can never hold /api/search beyond SEARCH_DEADLINE_S."""
    monkeypatch.setattr(search_module, "SEARCH_DEADLINE_S", 0.05)
    cache = FakeCache()

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.5)
        return httpx.Response(200, json={"search": []})

    with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=slow)
        started = time.monotonic()
        response = await search_universities(http, "Nazarbayev University", cache=cache)
        elapsed = time.monotonic() - started
    assert response == SearchResponse(query="Nazarbayev University", candidates=[])
    assert elapsed < 0.4
    assert cache.writes == []  # a timeout must not be cached for 6 h


async def test_spelling_fallback_not_used_without_ai(
    load_fixture: Callable[[str], Any], http: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_suggest(ai: object, q: str) -> list[str]:
        raise AssertionError("must not be called without an AI client")

    monkeypatch.setattr(search_module, "suggest_official_names", fake_suggest)
    web = FakeWeb(load_fixture)
    with respx.mock(assert_all_called=False) as router:
        web.install(router)
        response = await search_universities(http, "asdkjhqwe")
    assert response == SearchResponse(query="asdkjhqwe", candidates=[])


@pytest.mark.usefixtures("fast_retries")
async def test_all_http_failures_degrade_to_empty(
    http: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_suggest(ai: object, q: str) -> list[str]:
        return ["Massachusetts Institute of Technology"]

    monkeypatch.setattr(search_module, "suggest_official_names", fake_suggest)
    cache = FakeCache()
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=httpx.ConnectError("boom"))
        response = await search_universities(
            http, "Nazarbayev University", ai=object(), cache=cache
        )
        assert router.calls.call_count > 0
    assert response.candidates == []
    assert response.suggestions_used is False
    assert response.corrected_query is None
    assert cache.writes == []  # a transient failure must not be cached for 6 h


async def test_cache_hit_skips_the_network(http: httpx.AsyncClient) -> None:
    cached = SearchResponse(
        query="old spelling",
        candidates=[{"qid": "Q1", "label": "Cached University", "description": "cached"}],
    ).model_dump(mode="json")
    cache = FakeCache(stored=cached)
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=httpx.ConnectError("no network expected"))
        response = await search_universities(http, "  Cached   University ", cache=cache)
        assert router.calls.call_count == 0
    assert response.query == "Cached University"
    assert response.candidates[0].label == "Cached University"
    assert cache.reads == ["cached university"]
    assert cache.writes == []


async def test_search_param_validation(client: AsyncClient) -> None:
    too_short = await client.get("/api/search", params={"q": "a"})
    assert too_short.status_code == 422
    assert too_short.json()["error"]["code"] == "validation_error"
    missing = await client.get("/api/search")
    assert missing.status_code == 422
    assert "error" in missing.json()
    too_long = await client.get("/api/search", params={"q": "x" * 121})
    assert too_long.status_code == 422


@pytest.mark.parametrize("raw", ["   ", " a ", "\t\n", " " * 120, " " * 60 + "a" + " " * 59])
async def test_search_rejects_blank_or_padded_queries(client: AsyncClient, raw: str) -> None:
    """The 2-120 rule applies to the whitespace-collapsed query (Section 12).

    Every input here passes FastAPI's raw-length check (<= 120 chars) and is rejected by the
    route itself with the Section 12 envelope; longer raw inputs are already rejected upstream.
    """
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=httpx.ConnectError("no network expected"))
        response = await client.get("/api/search", params={"q": raw})
        assert router.calls.call_count == 0
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert "2-120" in body["error"]["message"]


async def test_search_endpoint_through_the_app(
    load_fixture: Callable[[str], Any], tmp_path: Path
) -> None:
    settings = Settings(anthropic_api_key=None, flickr_api_key=None, cache_dir=tmp_path)
    app = create_app(settings)
    web = FakeWeb(
        load_fixture, searches={"Nazarbayev University": "wikidata_search_nazarbayev_en.json"}
    )
    with respx.mock(assert_all_called=False) as router:
        web.install(router)
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.get("/api/search", params={"q": "Nazarbayev University"})
                assert response.status_code == 200
                body = response.json()
                assert body["query"] == "Nazarbayev University"
                assert [c["qid"] for c in body["candidates"]] == [NU]
                assert body["candidates"][0]["country"] == "Kazakhstan"
                assert body["suggestions_used"] is False
                assert body["corrected_query"] is None
                # second request: served by the sqlite cache, no new Wikidata calls
                web.calls.clear()
                again = await ac.get("/api/search", params={"q": "nazarbayev   university"})
                assert again.status_code == 200
                assert again.json()["candidates"] == body["candidates"]
                assert web.calls == []
