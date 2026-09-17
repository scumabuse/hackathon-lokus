"""Probe the REAL Wikidata / Wikipedia APIs for the Phase 1 review findings and save fixtures.

What it probes (all calls go through app.http so the Wikimedia User-Agent policy is honoured):
  1. ETH Zurich (Q11942) + its P131 hop Zurich (Q72) + its P159 (Q14565994): ranks of the P31
     claims of Zurich (a city-class claim with rank "normal" next to "preferred" claims) and the
     P31 of the headquarters entity (a building, not a place);
  2. Astana Medical University (Q4287774) + its city hop Astana (Q1520): several P17 claims with
     the same rank (a former country first) and their qualifiers;
  3. a human entity (Q102291105) whose description mentions a university (rule (b) false hit);
  4. Kostanay Regional University (Q123694980): wbsearchentities (prefix matcher) vs the
     full-text search action=query&list=search&srsearch=... (not in Section 7.1);
  5. labels of the building classes used to reject a P159 headquarters as the "city";
  6. Wikipedia pageprops for a redirect title, with and without redirects=1 (Section 7.1 does not
     mention redirects; without the parameter the QID of a redirect title is lost);
  7. saves unmodified responses (pretty-printed, UTF-8) into backend/tests/fixtures/.

How to run:
  cd backend && python ../scripts/probe_resolver_review.py

No API key is needed. Every external failure is printed as a warning; the script never crashes.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.config import Settings
from app.http import create_client, get_json

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIPEDIA_API = "https://{lang}.wikipedia.org/w/api.php"
FIXTURES_DIR = BACKEND_DIR / "tests" / "fixtures"
TIMEOUT_S = 5.0

ENTITY_PROPS = "claims|labels|descriptions|aliases|sitelinks"
ENTITY_LANGUAGES = "en|ru|kk"
ENTITY_SITEFILTER = "enwiki|ruwiki|kkwiki"
HOP_PROPS = "claims|labels|sitelinks"
HOP_LANGUAGES = "en|ru"
HOP_SITEFILTER = "enwiki|ruwiki"

ETH_ZURICH = "Q11942"
ZURICH = "Q72"
ETH_MAIN_BUILDING = "Q14565994"
ASTANA_MEDICAL = "Q4287774"
ASTANA = "Q1520"
SOVIET_UNION = "Q15180"
KAZAKHSTAN = "Q232"
HUMAN_ENTITY = "Q102291105"
KOSTANAY_REGIONAL = "Q123694980"
KOSTANAY_QUERY = "Kostanay Regional University"
REDIRECT_QUERY = "L.N. Gumilyov Eurasian National University"
BUILDING_CLASSES = ("Q41176", "Q209465", "Q1497375", "Q811979", "Q5")


# ----------------------------------------------------------------------------- helpers
def banner(text: str) -> None:
    print()
    print("=" * 100)
    print(text)
    print("=" * 100)


def save_fixture(name: str, data: Any) -> None:
    """Write an unmodified API response as pretty-printed UTF-8 JSON (LF line endings)."""
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURES_DIR / name
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"  saved {path}")


def describe_error(exc: BaseException) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return f"{type(exc).__name__}: {exc}"


def claims_of(entity: dict[str, Any], prop: str) -> list[dict[str, Any]]:
    return [c for c in entity.get("claims", {}).get(prop, []) if isinstance(c, dict)]


def claim_summary(claim: dict[str, Any]) -> str:
    mainsnak = claim.get("mainsnak", {})
    value = mainsnak.get("datavalue", {}).get("value")
    shown = value.get("id") if isinstance(value, dict) and "id" in value else value
    qualifiers = sorted(claim.get("qualifiers", {}).keys())
    return f"{shown!r} rank={claim.get('rank')} snak={mainsnak.get('snaktype')} quals={qualifiers}"


def print_claims(entity: dict[str, Any], prop: str) -> None:
    label = entity.get("labels", {}).get("en", {}).get("value")
    print(f"  {entity.get('id')} ({label!r}) {prop}:")
    for claim in claims_of(entity, prop):
        print(f"    - {claim_summary(claim)}")


# ----------------------------------------------------------------------------- API calls
async def wikidata(client: httpx.AsyncClient, **params: str) -> Any:
    query = {**params, "format": "json"}
    return await get_json(client, WIKIDATA_API, service="wikidata", params=query, timeout=TIMEOUT_S)


async def entities(client: httpx.AsyncClient, ids: list[str], props: str, languages: str) -> Any:
    params: dict[str, str] = {
        "action": "wbgetentities",
        "ids": "|".join(ids),
        "props": props,
        "languages": languages,
    }
    if props == ENTITY_PROPS:
        params["sitefilter"] = ENTITY_SITEFILTER
    elif props == HOP_PROPS:
        params["sitefilter"] = HOP_SITEFILTER
    return await wikidata(client, **params)


async def wikipedia(client: httpx.AsyncClient, lang: str, **params: str) -> Any:
    query = {**params, "format": "json"}
    return await get_json(
        client,
        WIKIPEDIA_API.format(lang=lang),
        service="wikipedia",
        params=query,
        timeout=TIMEOUT_S,
    )


async def safe(coro: Any, what: str) -> Any:
    try:
        return await coro
    except (httpx.HTTPError, ValueError) as exc:
        print(f"  WARNING: {what} failed: {describe_error(exc)}")
        return None


# ----------------------------------------------------------------------------- steps
async def step_city_chain(client: httpx.AsyncClient) -> dict[str, Any]:
    banner("STEP 1: ETH Zurich (Q11942) -> P131 Zurich (Q72), P159 ETH main building (Q14565994)")
    eth = await safe(entities(client, [ETH_ZURICH], ENTITY_PROPS, ENTITY_LANGUAGES), "ETH fetch")
    hops = await safe(
        entities(client, [ZURICH, ETH_MAIN_BUILDING], HOP_PROPS, HOP_LANGUAGES), "hop fetch"
    )
    if eth:
        entity = eth["entities"][ETH_ZURICH]
        print_claims(entity, "P131")
        print_claims(entity, "P159")
        print_claims(entity, "P17")
    if hops:
        for qid in (ZURICH, ETH_MAIN_BUILDING):
            print_claims(hops["entities"][qid], "P31")
            print_claims(hops["entities"][qid], "P131")
            print(f"    P625 present: {bool(claims_of(hops['entities'][qid], 'P625'))}")
    return {"wikidata_entities_eth_zurich.json": eth, "wikidata_hops_zurich.json": hops}


async def step_country(client: httpx.AsyncClient) -> dict[str, Any]:
    banner("STEP 2: Astana Medical University (Q4287774) P17 claims + city hop Astana (Q1520)")
    amu = await safe(entities(client, [ASTANA_MEDICAL], ENTITY_PROPS, ENTITY_LANGUAGES), "AMU")
    hop = await safe(entities(client, [ASTANA], HOP_PROPS, HOP_LANGUAGES), "Astana hop")
    labels = await safe(
        wikidata(
            client,
            action="wbgetentities",
            ids=f"{SOVIET_UNION}|{KAZAKHSTAN}",
            props="labels",
            languages=HOP_LANGUAGES,
        ),
        "country labels",
    )
    if amu:
        entity = amu["entities"][ASTANA_MEDICAL]
        print_claims(entity, "P17")
        for claim in claims_of(entity, "P17"):
            for qual_prop, snaks in claim.get("qualifiers", {}).items():
                for snak in snaks:
                    print(
                        f"      qualifier {qual_prop}: {snak.get('datavalue', {}).get('value')!r}"
                    )
        print_claims(entity, "P131")
    if hop:
        print_claims(hop["entities"][ASTANA], "P31")
        print_claims(hop["entities"][ASTANA], "P17")
    return {
        "wikidata_entities_astana_medical.json": amu,
        "wikidata_hops_astana.json": hop,
        "wikidata_labels_soviet_union_kazakhstan.json": labels,
    }


async def step_human(client: httpx.AsyncClient) -> dict[str, Any]:
    banner("STEP 3: human entity (Q102291105) with a university in its description")
    human = await safe(entities(client, [HUMAN_ENTITY], ENTITY_PROPS, ENTITY_LANGUAGES), "human")
    if human:
        entity = human["entities"][HUMAN_ENTITY]
        print_claims(entity, "P31")
        print(f"  descriptions: {entity.get('descriptions')!r}")
    return {"wikidata_entities_human.json": human}


async def step_kostanay(client: httpx.AsyncClient) -> dict[str, Any]:
    banner("STEP 4: Kostanay Regional University: wbsearchentities vs list=search (full text)")
    prefix = await safe(
        wikidata(
            client,
            action="wbsearchentities",
            search=KOSTANAY_QUERY,
            language="en",
            uselang="en",
            type="item",
            limit="10",
        ),
        "wbsearchentities",
    )
    if prefix is not None:
        print(f"  wbsearchentities en hits: {[h.get('id') for h in prefix.get('search', [])]}")
    fulltext = await safe(
        wikidata(
            client,
            action="query",
            list="search",
            srsearch=KOSTANAY_QUERY,
            srnamespace="0",
            srlimit="10",
        ),
        "list=search",
    )
    if fulltext is not None:
        hits = fulltext.get("query", {}).get("search", [])
        print(
            f"  list=search keys: {sorted(fulltext.keys())} / query keys: {sorted(fulltext.get('query', {}).keys())}"
        )
        for hit in hits:
            print(f"    - title={hit.get('title')!r} pageid={hit.get('pageid')} ns={hit.get('ns')}")
    entity = await safe(
        entities(client, [KOSTANAY_REGIONAL], ENTITY_PROPS, ENTITY_LANGUAGES), "Kostanay entity"
    )
    if entity:
        item = entity["entities"][KOSTANAY_REGIONAL]
        print_claims(item, "P31")
        print(f"  labels: {item.get('labels')!r}")
        print(f"  aliases.en: {[a['value'] for a in item.get('aliases', {}).get('en', [])]!r}")
        print(f"  sitelinks: {item.get('sitelinks')!r}")
    return {
        "wikidata_fulltext_search_kostanay_en.json": fulltext,
        "wikidata_entities_kostanay.json": entity,
    }


async def step_building_labels(client: httpx.AsyncClient) -> None:
    banner("STEP 5: labels of the building / human classes")
    data = await safe(
        wikidata(
            client,
            action="wbgetentities",
            ids="|".join(BUILDING_CLASSES),
            props="labels",
            languages="en",
        ),
        "class labels",
    )
    if data:
        for qid, entity in data.get("entities", {}).items():
            print(f"  {qid}: {entity.get('labels', {}).get('en', {}).get('value')!r}")


async def step_redirects(client: httpx.AsyncClient) -> dict[str, Any]:
    banner("STEP 6: en.wikipedia pageprops for a redirect title, without and with redirects=1")
    opensearch = await safe(
        wikipedia(
            client, "en", action="opensearch", search=REDIRECT_QUERY, limit="5", namespace="0"
        ),
        "opensearch",
    )
    titles = list(opensearch[1]) if isinstance(opensearch, list) and len(opensearch) > 1 else []
    print(f"  opensearch titles: {titles!r}")
    if not titles:
        titles = [REDIRECT_QUERY]
    plain = await safe(
        wikipedia(
            client,
            "en",
            action="query",
            prop="pageprops",
            ppprop="wikibase_item",
            titles="|".join(titles),
        ),
        "pageprops (spec params)",
    )
    with_redirects = await safe(
        wikipedia(
            client,
            "en",
            action="query",
            prop="pageprops",
            ppprop="wikibase_item",
            titles="|".join(titles),
            redirects="1",
        ),
        "pageprops (redirects=1)",
    )
    for name, data in (("spec params", plain), ("redirects=1", with_redirects)):
        if not data:
            continue
        query = data.get("query", {})
        print(f"  [{name}] query keys: {sorted(query.keys())}")
        for key in ("normalized", "redirects"):
            if key in query:
                print(f"  [{name}] query.{key}: {query[key]!r}")
        for page_id, page in query.get("pages", {}).items():
            qid = page.get("pageprops", {}).get("wikibase_item")
            print(f"  [{name}] page {page_id}: title={page.get('title')!r} wikibase_item={qid!r}")
    return {
        "wikipedia_opensearch_en_redirect.json": opensearch,
        "wikipedia_pageprops_en_redirect.json": with_redirects,
    }


async def main() -> int:
    settings = Settings()
    fixtures: dict[str, Any] = {}
    async with create_client(settings) as client:
        fixtures.update(await step_city_chain(client))
        fixtures.update(await step_country(client))
        fixtures.update(await step_human(client))
        fixtures.update(await step_kostanay(client))
        await step_building_labels(client)
        fixtures.update(await step_redirects(client))
    banner("STEP 7: save real responses as fixtures")
    for name, data in fixtures.items():
        if data is None:
            print(f"  SKIPPED {name}: no real response available")
            continue
        save_fixture(name, data)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(asyncio.run(main()))
