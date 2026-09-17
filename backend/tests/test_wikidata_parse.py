"""Entity parsing, filter, ranking and city resolution on real saved Wikidata responses (7.1)."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import httpx
import pytest
import respx

from app.config import Settings
from app.http import create_client
from app.resolver import wikidata
from app.resolver.search import rank_pairs
from app.resolver.wikidata import (
    DESCRIPTION_RE,
    ResolverUnavailableError,
    build_resolved,
    claim_values,
    country_candidates,
    entity_label,
    first_claim_value,
    is_place_like,
    is_university,
    parse_header,
    pick_country_id,
    resolve_city,
    resolve_university,
    string_value,
)

MIT = "Q49108"
CAMBRIDGE = "Q49111"
MIDDLESEX = "Q54073"
UNITED_STATES = "Q30"
NU = "Q2783344"
NU_REPOSITORY = "Q28223830"
NU_LIBRARY = "Q73784445"
COLUMBIA_UNIVERSITY = "Q49088"
COLUMBIA_RECORDS = "Q183387"
COLUMBIA_SC = "Q38453"
ASTEROID = "Q151167"
ETH_ZURICH = "Q11942"
ZURICH = "Q72"
ZURICH_DISTRICT = "Q660732"
ETH_MAIN_BUILDING = "Q14565994"
ASTANA_MEDICAL = "Q4287774"
ASTANA = "Q1520"
SOVIET_UNION = "Q15180"
KAZAKHSTAN = "Q232"
HUMAN = "Q102291105"
BIG_CITY = "Q1549591"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"


def _p31(*ranked: tuple[str, str]) -> dict[str, Any]:
    """Synthetic entity with the given (qid, rank) P31 claims."""
    return {
        "id": "Q1",
        "claims": {
            "P31": [
                {
                    "mainsnak": {"snaktype": "value", "datavalue": {"value": {"id": qid}}},
                    "rank": rank,
                }
                for qid, rank in ranked
            ]
        },
    }


@pytest.fixture
def mit(load_fixture: Callable[[str], Any]) -> dict[str, Any]:
    return load_fixture("wikidata_entities_mit.json")["entities"][MIT]


@pytest.fixture
def cambridge(load_fixture: Callable[[str], Any]) -> dict[str, Any]:
    return load_fixture("wikidata_entities_cambridge.json")["entities"][CAMBRIDGE]


@pytest.fixture
def columbia_entities(load_fixture: Callable[[str], Any]) -> dict[str, dict[str, Any]]:
    return load_fixture("wikidata_entities_columbia.json")["entities"]


@pytest.fixture
def eth_zurich(load_fixture: Callable[[str], Any]) -> dict[str, Any]:
    return load_fixture("wikidata_entities_eth_zurich.json")["entities"][ETH_ZURICH]


@pytest.fixture
def zurich_hops(load_fixture: Callable[[str], Any]) -> dict[str, dict[str, Any]]:
    """Zurich (Q72) and the ETH main building (Q14565994) with the city-hop props."""
    return load_fixture("wikidata_hops_zurich.json")["entities"]


@pytest.fixture
def astana_medical(load_fixture: Callable[[str], Any]) -> dict[str, Any]:
    return load_fixture("wikidata_entities_astana_medical.json")["entities"][ASTANA_MEDICAL]


@pytest.fixture
def astana(load_fixture: Callable[[str], Any]) -> dict[str, Any]:
    return load_fixture("wikidata_hops_astana.json")["entities"][ASTANA]


@pytest.fixture
def human(load_fixture: Callable[[str], Any]) -> dict[str, Any]:
    return load_fixture("wikidata_entities_human.json")["entities"][HUMAN]


@pytest.fixture
def nazarbayev_entities(load_fixture: Callable[[str], Any]) -> dict[str, dict[str, Any]]:
    return load_fixture("wikidata_entities_nazarbayev.json")["entities"]


# ----------------------------------------------------------------------------- header parsing


def test_parse_header_mit(mit: dict[str, Any]) -> None:
    header = parse_header(mit, country_label="United States")
    assert header.qid == MIT
    assert header.name == "Massachusetts Institute of Technology"
    assert header.local_name == "Массачусетский технологический институт"
    assert header.country == "United States"
    assert header.coords is not None
    assert header.coords.lat == pytest.approx(42.3597, abs=1e-3)
    assert header.coords.lon == pytest.approx(-71.0919, abs=1e-3)
    assert header.official_website == "https://mit.edu"
    assert header.commons_category == "Massachusetts Institute of Technology"
    assert (
        header.wikipedia_url
        == "https://en.wikipedia.org/wiki/Massachusetts_Institute_of_Technology"
    )
    assert header.city is None
    assert header.distance_to_city_center_km is None


def test_parse_header_mit_aliases(mit: dict[str, Any]) -> None:
    aliases = parse_header(mit).aliases
    assert "MIT" in aliases
    assert "Mass Tech" in aliases
    assert "МТИ" in aliases
    assert "Boston Tech" in aliases  # P1813 normal rank next to the preferred "MIT"
    assert len(aliases) == len({a.casefold() for a in aliases})
    assert all(len(a) >= 3 for a in aliases)


def test_build_resolved_mit(mit: dict[str, Any]) -> None:
    resolved = build_resolved(mit)
    assert resolved.main_image_filename == "MIT Dome night1 Edit.jpg"
    assert resolved.logo_filename == "MIT 2023 red logo.svg"
    assert resolved.wiki_titles == {
        "en": "Massachusetts Institute of Technology",
        "ru": "Массачусетский технологический институт",
    }
    assert resolved.raw["id"] == MIT
    assert resolved.header.name == "Massachusetts Institute of Technology"


def test_parse_header_nazarbayev_missing_optional_claims(
    nazarbayev_entities: dict[str, dict[str, Any]],
) -> None:
    resolved = build_resolved(nazarbayev_entities[NU])
    header = resolved.header
    assert header.name == "Nazarbayev University"
    assert header.local_name == "Назарбаев Университет"
    assert header.official_website == "http://nu.edu.kz"
    assert header.commons_category == "Nazarbayev University"
    assert header.coords is not None
    assert resolved.main_image_filename is None
    assert resolved.logo_filename is None
    assert "NU" not in header.aliases  # 2 chars -> dropped
    assert "Назарбаев Университетi" in header.aliases


def test_entity_label_fallbacks(columbia_entities: dict[str, dict[str, Any]]) -> None:
    assert entity_label(columbia_entities[ASTEROID]) == "(327) Колумбия"  # no en label
    assert entity_label(columbia_entities[COLUMBIA_UNIVERSITY]) == "Columbia University"
    assert entity_label({"labels": {}}) is None


# ----------------------------------------------------------------------------- claims


def test_claim_values_prefers_preferred_and_skips_novalue_and_deprecated() -> None:
    def claim(rank: str, text: str | None) -> dict[str, Any]:
        if text is None:
            return {"mainsnak": {"snaktype": "novalue"}, "rank": rank}
        return {
            "mainsnak": {"snaktype": "value", "datavalue": {"value": {"text": text}}},
            "rank": rank,
        }

    entity = {
        "claims": {
            "P1813": [
                claim("normal", "normal one"),
                claim("preferred", None),
                claim("preferred", "preferred one"),
                claim("deprecated", "dead one"),
            ]
        }
    }
    assert claim_values(entity, "P1813") == [{"text": "preferred one"}]
    assert claim_values(entity, "P1813", all_ranks=True) == [
        {"text": "normal one"},
        {"text": "preferred one"},
    ]
    assert first_claim_value(entity, "P1813") == {"text": "preferred one"}
    assert claim_values(entity, "P999") == []
    assert first_claim_value({}, "P31") is None


def test_claim_values_on_real_entity(mit: dict[str, Any], cambridge: dict[str, Any]) -> None:
    assert first_claim_value(mit, "P1813") == {"text": "MIT", "language": "en"}
    # Cambridge P31 = [Q1093829 preferred, Q1549591 normal, Q515 preferred]
    assert wikidata.item_ids(cambridge, "P31") == ["Q1093829", "Q515"]
    assert wikidata.item_ids(cambridge, "P31", all_ranks=True) == ["Q1093829", "Q1549591", "Q515"]


def test_item_ids_all_ranks_keeps_normal_city_class(zurich_hops: dict[str, dict[str, Any]]) -> None:
    # Zurich P31: four preferred non-city classes + "big city" (Q1549591) with rank normal
    zurich = zurich_hops[ZURICH]
    assert BIG_CITY not in wikidata.item_ids(zurich, "P31")
    assert BIG_CITY in wikidata.item_ids(zurich, "P31", all_ranks=True)
    assert wikidata.CITY_QIDS & set(wikidata.item_ids(zurich, "P31", all_ranks=True))


def test_country_candidates_drop_former_countries_by_end_time() -> None:
    def claim(qid: str, rank: str, ended: bool) -> dict[str, Any]:
        out: dict[str, Any] = {
            "mainsnak": {"snaktype": "value", "datavalue": {"value": {"id": qid}}},
            "rank": rank,
        }
        if ended:
            out["qualifiers"] = {"P582": [{"snaktype": "value"}]}
        return out

    former_first = {
        "claims": {"P17": [claim("Q15180", "normal", True), claim("Q232", "normal", False)]}
    }
    assert country_candidates(former_first) == ["Q232"]
    preferred_wins = {
        "claims": {"P17": [claim("Q15180", "preferred", True), claim("Q232", "normal", False)]}
    }
    assert country_candidates(preferred_wins) == ["Q15180"]
    all_ended = {
        "claims": {"P17": [claim("Q15180", "normal", True), claim("Q232", "normal", True)]}
    }
    assert country_candidates(all_ended) == ["Q15180", "Q232"]
    assert country_candidates({}) == []
    assert pick_country_id({}) is None


def test_pick_country_id_uses_the_city_country(
    astana_medical: dict[str, Any], astana: dict[str, Any]
) -> None:
    # Astana Medical University P17 = [Soviet Union, Kazakhstan], both rank normal, no qualifiers
    assert country_candidates(astana_medical) == [SOVIET_UNION, KAZAKHSTAN]
    assert pick_country_id(astana_medical) == SOVIET_UNION  # literal "else first" without a city
    assert pick_country_id(astana_medical, astana) == KAZAKHSTAN  # Astana's preferred P17
    unrelated_city = {"claims": {"P17": []}}
    assert pick_country_id(astana_medical, unrelated_city) == SOVIET_UNION


def test_deprecated_website_is_not_used(columbia_entities: dict[str, dict[str, Any]]) -> None:
    city = columbia_entities[COLUMBIA_SC]
    deprecated = [
        c["mainsnak"]["datavalue"]["value"]
        for c in city["claims"]["P856"]
        if c.get("rank") == "deprecated"
    ]
    assert deprecated
    assert string_value(city, "P856") not in deprecated


# ----------------------------------------------------------------------------- filter


def test_description_re() -> None:
    for text in (
        "Казахский национальный университет",
        "Institute of Technology",
        "school of medicine",
        "Костанайский региональный институты",
    ):
        assert DESCRIPTION_RE.search(text), text
    for text in ("river", "police agency", "American record label"):
        assert not DESCRIPTION_RE.search(text), text


def test_is_university_rule_a(mit: dict[str, Any]) -> None:
    assert is_university(mit)


def test_is_university_rule_a_counts_any_rank() -> None:
    # a normal-rank "university" class next to a preferred non-university class still counts
    assert is_university(_p31(("Q41176", "preferred"), ("Q3918", "normal")))
    assert not is_university(_p31(("Q41176", "preferred"), ("Q3918", "deprecated")))


def test_is_university_rejects_humans(human: dict[str, Any]) -> None:
    # real entity: P31 = human, en description "Ph.D. Lomonosov Moscow State University, 1984"
    assert wikidata.item_ids(human, "P31") == [wikidata.HUMAN_QID]
    assert DESCRIPTION_RE.search(human["descriptions"]["en"]["value"])
    assert not is_university(human)
    assert not is_university(human, query="МГУ")


def test_is_place_like(zurich_hops: dict[str, dict[str, Any]]) -> None:
    assert is_place_like(zurich_hops[ZURICH])
    assert not is_place_like(zurich_hops[ETH_MAIN_BUILDING])  # P31 = building
    assert is_place_like({})


def test_is_university_rejects_non_universities(
    columbia_entities: dict[str, dict[str, Any]],
) -> None:
    assert is_university(columbia_entities[COLUMBIA_UNIVERSITY])
    assert not is_university(columbia_entities[COLUMBIA_RECORDS])  # record label
    assert not is_university(columbia_entities[COLUMBIA_SC])  # a city
    river = {
        "id": "Q1",
        "claims": {
            "P31": [
                {
                    "mainsnak": {"snaktype": "value", "datavalue": {"value": {"id": "Q4022"}}},
                    "rank": "normal",
                }
            ]
        },
        "descriptions": {"en": {"language": "en", "value": "river in Siberia"}},
    }
    assert not is_university(river)
    assert not is_university({})


def test_is_university_rule_b_ignores_parent_name(
    nazarbayev_entities: dict[str, dict[str, Any]],
) -> None:
    repository = nazarbayev_entities[NU_REPOSITORY]  # no P31; "research archive for NU"
    assert is_university(repository)  # the literal Section 7.1 (b) would keep it ...
    assert not is_university(repository, query="Nazarbayev University")  # ... the query-aware
    assert is_university(nazarbayev_entities[NU], query="Nazarbayev University")
    assert not is_university(nazarbayev_entities[NU_LIBRARY], query="Nazarbayev University")
    by_description = {"descriptions": {"ru": {"language": "ru", "value": "вуз в Астане"}}}
    assert is_university(by_description, query="Astana")


# ----------------------------------------------------------------------------- ranking


def test_ranking_puts_exact_label_match_first(
    load_fixture: Callable[[str], Any], nazarbayev_entities: dict[str, dict[str, Any]]
) -> None:
    hits = load_fixture("wikidata_search_nazarbayev_en.json")["search"]
    pairs = [(hit, nazarbayev_entities[hit["id"]]) for hit in reversed(hits)]  # NU last
    ranked = rank_pairs(pairs, "  nazarbayev   UNIVERSITY ")
    assert ranked[0][0]["id"] == NU
    rest = [hit["id"] for hit, _ in ranked[1:]]
    assert rest == [hit["id"] for hit, _ in pairs if hit["id"] != NU]  # stable otherwise


def test_ranking_matches_aliases(mit: dict[str, Any]) -> None:
    other = {"id": "Q1", "labels": {"en": {"language": "en", "value": "Something"}}}
    pairs = [({"id": "Q1"}, other), ({"id": MIT}, mit)]
    assert rank_pairs(pairs, "mit")[0][0]["id"] == MIT
    assert rank_pairs(pairs, "Massachusetts")[0][0]["id"] == "Q1"


# ----------------------------------------------------------------------------- city resolution


async def test_resolve_city_mit_cambridge(
    mit: dict[str, Any], cambridge: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], str, str, str | None]] = []

    async def fake_get_entities(
        client: httpx.AsyncClient,
        ids: list[str],
        *,
        props: str,
        languages: str,
        sitefilter: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        calls.append((list(ids), props, languages, sitefilter))
        return {CAMBRIDGE: cambridge} if CAMBRIDGE in ids else {}

    monkeypatch.setattr(wikidata, "get_entities", fake_get_entities)
    async with httpx.AsyncClient() as client:
        place = await resolve_city(client, mit)
    assert place is not None
    assert place.qid == CAMBRIDGE
    assert place.name == "Cambridge"
    assert place.coords is not None
    assert place.coords.lat == pytest.approx(42.375, abs=1e-3)
    assert place.coords.lon == pytest.approx(-71.1061, abs=1e-3)
    assert place.commons_category == "Cambridge, Massachusetts"
    assert place.wikipedia_url == "https://en.wikipedia.org/wiki/Cambridge,_Massachusetts"
    assert calls == [([CAMBRIDGE], "claims|labels|sitelinks", "en|ru", "enwiki|ruwiki")]


async def test_resolve_city_falls_back_to_first_geo_hop(
    mit: dict[str, Any], cambridge: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    not_a_city = copy.deepcopy(cambridge)
    del not_a_city["claims"]["P31"]
    university = copy.deepcopy(mit)
    del university["claims"]["P159"]
    requested: list[str] = []

    async def fake_get_entities(
        client: httpx.AsyncClient,
        ids: list[str],
        *,
        props: str,
        languages: str,
        sitefilter: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        requested.extend(ids)
        return {CAMBRIDGE: not_a_city} if CAMBRIDGE in ids else {}

    monkeypatch.setattr(wikidata, "get_entities", fake_get_entities)
    async with httpx.AsyncClient() as client:
        place = await resolve_city(client, university)
    assert requested == [CAMBRIDGE, MIDDLESEX]  # chain stops when a hop cannot be fetched
    assert place is not None
    assert place.name == "Cambridge"
    assert place.coords is not None


def _entity_server(
    known: dict[str, dict[str, Any]], requested: list[list[str]] | None = None
) -> Callable[..., Any]:
    """A ``wikidata.get_entities`` stand-in answering from ``known`` and recording the ids."""

    async def fake_get_entities(
        client: httpx.AsyncClient,
        ids: list[str],
        *,
        props: str,
        languages: str,
        sitefilter: str | None = None,
        strict: bool = False,
    ) -> dict[str, dict[str, Any]]:
        if requested is not None:
            requested.append(list(ids))
        return {qid: known[qid] for qid in ids if qid in known}

    return fake_get_entities


async def test_resolve_city_eth_zurich(
    eth_zurich: dict[str, Any],
    zurich_hops: dict[str, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ETH Zurich: P131 = Zurich whose city class is normal-rank; P159 = its main building."""
    requested: list[list[str]] = []
    monkeypatch.setattr(wikidata, "get_entities", _entity_server(zurich_hops, requested))
    async with httpx.AsyncClient() as client:
        place = await resolve_city(client, eth_zurich)
    assert place is not None
    assert place.qid == ZURICH
    assert place.name == "Zurich"
    assert place.commons_category == "Zürich"
    assert place.coords is not None
    assert place.coords.lat == pytest.approx(47.374, abs=1e-3)
    # the P131 hop and the P159 fallback entity are fetched together, in one call
    assert requested == [[ZURICH, ETH_MAIN_BUILDING]]
    header = parse_header(eth_zurich, city=place)
    assert header.distance_to_city_center_km == pytest.approx(0.6, abs=0.15)


async def test_resolve_city_never_returns_a_building(
    eth_zurich: dict[str, Any],
    zurich_hops: dict[str, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no hop is a city, the P159 building is skipped for the first geo hop with a sitelink."""
    not_a_city = copy.deepcopy(zurich_hops[ZURICH])
    del not_a_city["claims"]["P31"]
    known = {ZURICH: not_a_city, ETH_MAIN_BUILDING: zurich_hops[ETH_MAIN_BUILDING]}
    requested: list[list[str]] = []
    monkeypatch.setattr(wikidata, "get_entities", _entity_server(known, requested))
    async with httpx.AsyncClient() as client:
        place = await resolve_city(client, eth_zurich)
    assert requested == [[ZURICH, ETH_MAIN_BUILDING], [ZURICH_DISTRICT]]
    assert place is not None
    assert place.qid == ZURICH
    assert place.name == "Zurich"


async def test_resolve_city_accepts_a_place_headquarters(
    eth_zurich: dict[str, Any],
    zurich_hops: dict[str, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A P159 that is a place (not a building) with coordinates is still used (Section 7.1)."""
    not_a_city = copy.deepcopy(zurich_hops[ZURICH])
    del not_a_city["claims"]["P31"]
    del not_a_city["sitelinks"]
    hq = copy.deepcopy(zurich_hops[ETH_MAIN_BUILDING])
    del hq["claims"]["P31"]
    known = {ZURICH: not_a_city, ETH_MAIN_BUILDING: hq}
    monkeypatch.setattr(wikidata, "get_entities", _entity_server(known))
    async with httpx.AsyncClient() as client:
        place = await resolve_city(client, eth_zurich)
    assert place is not None
    assert place.qid == ETH_MAIN_BUILDING


async def test_resolve_city_without_p131(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(*args: Any, **kwargs: Any) -> dict[str, dict[str, Any]]:
        raise AssertionError("no fetch expected")

    monkeypatch.setattr(wikidata, "get_entities", fail)
    async with httpx.AsyncClient() as client:
        assert await resolve_city(client, {"id": "Q1", "claims": {}}) is None


async def test_resolve_university_mit(
    settings: Settings,
    mit: dict[str, Any],
    cambridge: dict[str, Any],
    load_fixture: Callable[[str], Any],
) -> None:
    labels = load_fixture("wikidata_labels_country_city.json")["entities"]
    known = {MIT: mit, CAMBRIDGE: cambridge, **labels}

    def wikidata_api(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        assert params.get("action") == "wbgetentities"
        assert params.get("format") == "json"
        ids = params.get("ids", "").split("|")
        entities = {qid: known.get(qid, {"id": qid, "missing": ""}) for qid in ids}
        return httpx.Response(200, json={"entities": entities, "success": 1})

    with respx.mock(assert_all_called=False) as router:
        router.get(WIKIDATA_API).mock(side_effect=wikidata_api)
        async with create_client(settings) as client:
            resolved = await resolve_university(client, MIT)
            assert await resolve_university(client, "Q999999999") is None
    assert resolved is not None
    header = resolved.header
    assert header.country == "United States"
    assert header.city is not None
    assert header.city.name == "Cambridge"
    assert header.distance_to_city_center_km == pytest.approx(2.1, abs=0.15)
    assert header.official_website == "https://mit.edu"


async def test_resolve_university_astana_medical_country_tie_break(
    settings: Settings,
    astana_medical: dict[str, Any],
    astana: dict[str, Any],
    load_fixture: Callable[[str], Any],
) -> None:
    """P17 = [Soviet Union, Kazakhstan] (same rank): the city's country wins over "first"."""
    labels = load_fixture("wikidata_labels_soviet_union_kazakhstan.json")["entities"]
    known = {ASTANA_MEDICAL: astana_medical, ASTANA: astana, **labels}

    def wikidata_api(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        assert params.get("action") == "wbgetentities"
        ids = params.get("ids", "").split("|")
        entities = {qid: known.get(qid, {"id": qid, "missing": ""}) for qid in ids}
        return httpx.Response(200, json={"entities": entities, "success": 1})

    with respx.mock(assert_all_called=False) as router:
        router.get(WIKIDATA_API).mock(side_effect=wikidata_api)
        async with create_client(settings) as client:
            resolved = await resolve_university(client, ASTANA_MEDICAL)
    assert resolved is not None
    header = resolved.header
    assert header.country == "Kazakhstan"
    assert header.city is not None
    assert header.city.qid == ASTANA
    assert header.city.name == "Astana"
    assert header.distance_to_city_center_km == pytest.approx(5.5, abs=0.5)


@pytest.mark.usefixtures("fast_retries")
async def test_resolve_university_reports_wikidata_unavailable(settings: Settings) -> None:
    """Transport failure -> ResolverUnavailableError (503), never the "not found" None (404)."""
    with respx.mock(assert_all_called=False) as router:
        router.get(WIKIDATA_API).mock(side_effect=httpx.ConnectError("down"))
        async with create_client(settings) as client:
            with pytest.raises(ResolverUnavailableError):
                await resolve_university(client, MIT)
    with respx.mock(assert_all_called=False) as router:
        router.get(WIKIDATA_API).mock(return_value=httpx.Response(503))
        async with create_client(settings) as client:
            with pytest.raises(ResolverUnavailableError):
                await resolve_university(client, MIT)
