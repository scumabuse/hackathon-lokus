"""Probe the REAL Wikidata API exactly as SPEC Section 7.1 describes it and save real fixtures.

What it probes (all calls go through app.http so the Wikimedia User-Agent policy is honoured):
  1. labels of UNIVERSITY_QIDS and CITY_QIDS (one wbgetentities&props=labels&languages=en each)
     and whether every label matches the concept the spec expects;
  2. wbsearchentities with the exact spec parameters for six queries in en / ru / kk;
  3. wbgetentities (full spec props, <= 50 ids per call) for every search hit: P31 ids,
     en/ru descriptions and the outcome of the Section 7.1 university filter (a) / (b);
  4. the facts used by UniversityHeader for MIT (Q49108) and Nazarbayev University plus the
     city chain walk (P131, up to 4 hops, city-hop props), noting non-"value" snaks and
     rank == "preferred" claims;
  5. saves unmodified responses (pretty-printed, UTF-8) into backend/tests/fixtures/.

How to run:
  cd backend && python ../scripts/probe_wikidata.py

No API key is needed. Every external failure is printed as a warning; the script never crashes.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.config import Settings
from app.http import create_client, get_json

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
FIXTURES_DIR = BACKEND_DIR / "tests" / "fixtures"
TIMEOUT_S = 5.0  # Section 7.1: "Timeout 5 s"
MAX_IDS_PER_CALL = 50

ENTITY_PROPS = "claims|labels|descriptions|aliases|sitelinks"
ENTITY_LANGUAGES = "en|ru|kk"
ENTITY_SITEFILTER = "enwiki|ruwiki|kkwiki"
HOP_PROPS = "claims|labels|sitelinks"
HOP_LANGUAGES = "en|ru"
HOP_SITEFILTER = "enwiki|ruwiki"
LABEL_LANGUAGES = "en|ru"
MAX_CITY_HOPS = 4

# Expected labels straight from Section 7.1 (verified against the real API in step 1).
UNIVERSITY_QIDS: dict[str, str] = {
    "Q3918": "university",
    "Q38723": "higher education institution",
    "Q875538": "public university",
    "Q902104": "private university",
    "Q15936437": "research university",
    "Q189004": "college",
    "Q1371037": "institute of technology",
    "Q4671277": "academic institution",
    "Q2385804": "educational institution",
}
CITY_QIDS: dict[str, str] = {
    "Q515": "city",
    "Q1549591": "big city",
    "Q3957": "town",
    "Q5119": "capital city",
    "Q200250": "metropolis",
    "Q7930989": "city/town",
    "Q1093829": "city of the United States",
}
DESCRIPTION_RE = re.compile(
    r"university|universit|college|institute|polytechnic|academy|school of|conservator"
    r"|университет|институт|академия|колледж|вуз|консерватор|университеті|институты",
    re.IGNORECASE,
)

SEARCH_LANGS = ("en", "ru", "kk")
SEARCH_QUERIES = (
    "Nazarbayev University",
    "Columbia",
    "Massachusets Institut of Technology",
    "Костанайский региональный университет",
    "asdkjhqwe",
    "Massachusetts Institute of Technology",
)
NU_QUERY = "Nazarbayev University"
COLUMBIA_QUERY = "Columbia"
NONSENSE_QUERY = "asdkjhqwe"
MIT_QID = "Q49108"
HEADER_PROPS = ("P625", "P856", "P373", "P18", "P154", "P131", "P17", "P159", "P1448", "P1813")

SearchKey = tuple[str, str]
SearchResults = dict[SearchKey, Any]


# ----------------------------------------------------------------------------- helpers
def banner(text: str) -> None:
    print()
    print("=" * 100)
    print(text)
    print("=" * 100)


def chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def save_fixture(name: str, data: Any) -> None:
    """Write an unmodified API response as pretty-printed UTF-8 JSON (LF line endings)."""
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURES_DIR / name
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"  saved {path}")


def ordered_claims(entity: dict[str, Any], prop: str) -> list[dict[str, Any]]:
    """Claims of `prop` with snaktype == "value", rank == "preferred" first (Section 7.1)."""
    claims = [c for c in entity.get("claims", {}).get(prop, []) if _is_value(c)]
    preferred = [c for c in claims if c.get("rank") == "preferred"]
    others = [c for c in claims if c.get("rank") != "preferred"]
    return [*preferred, *others]


def _is_value(claim: dict[str, Any]) -> bool:
    return claim.get("mainsnak", {}).get("snaktype") == "value"


def claim_values(entity: dict[str, Any], prop: str) -> list[Any]:
    return [c["mainsnak"]["datavalue"]["value"] for c in ordered_claims(entity, prop)]


def claim_ids(entity: dict[str, Any], prop: str) -> list[str]:
    return [v["id"] for v in claim_values(entity, prop) if isinstance(v, dict) and "id" in v]


def label(entity: dict[str, Any], lang: str) -> str | None:
    value = entity.get("labels", {}).get(lang)
    return value.get("value") if isinstance(value, dict) else None


def description(entity: dict[str, Any], lang: str) -> str | None:
    value = entity.get("descriptions", {}).get(lang)
    return value.get("value") if isinstance(value, dict) else None


def passes_filter(entity: dict[str, Any]) -> tuple[bool, bool]:
    """Section 7.1 university filter: (a) P31 in UNIVERSITY_QIDS, (b) description regex."""
    p31 = claim_ids(entity, "P31")
    rule_a = any(qid in UNIVERSITY_QIDS for qid in p31)
    texts = [t for t in (description(entity, "en"), description(entity, "ru")) if t]
    rule_b = any(DESCRIPTION_RE.search(t) for t in texts)
    return rule_a, rule_b


def snak_notes(entity: dict[str, Any]) -> list[str]:
    """Every claim whose mainsnak.snaktype != "value" and every rank == "preferred" claim."""
    notes: list[str] = []
    for prop, claims in entity.get("claims", {}).items():
        for claim in claims:
            snaktype = claim.get("mainsnak", {}).get("snaktype")
            if snaktype != "value":
                notes.append(f"{prop}: snaktype={snaktype!r} (skipped by the parser)")
            if claim.get("rank") == "preferred":
                notes.append(f"{prop}: rank=preferred (parser prefers it)")
    return notes


def label_match(actual: str | None, expected: str) -> str:
    if actual is None:
        return "MISSING"
    a, b = actual.casefold().strip(), expected.casefold().strip()
    if a == b:
        return "exact"
    words_a = set(re.findall(r"\w+", a))
    words_b = set(re.findall(r"\w+", b))
    return "synonym?" if words_a & words_b else "MISMATCH"


def describe_error(exc: BaseException) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return f"{type(exc).__name__}: {exc}"


# ----------------------------------------------------------------------------- API calls
async def wikidata(client: httpx.AsyncClient, **params: str) -> Any:
    """One call to the Wikidata action API; always adds format=json (Section 7.1)."""
    query = {**params, "format": "json"}
    return await get_json(client, WIKIDATA_API, service="wikidata", params=query, timeout=TIMEOUT_S)


async def search_entities(client: httpx.AsyncClient, query: str, lang: str) -> Any:
    return await wikidata(
        client,
        action="wbsearchentities",
        search=query,
        language=lang,
        uselang="en",
        type="item",
        limit="10",
    )


async def get_entities(
    client: httpx.AsyncClient, ids: list[str], props: str, languages: str, sitefilter: str
) -> Any:
    """wbgetentities for <= 50 ids with the given props (one HTTP call)."""
    return await wikidata(
        client,
        action="wbgetentities",
        ids="|".join(ids),
        props=props,
        languages=languages,
        sitefilter=sitefilter,
    )


async def get_labels(client: httpx.AsyncClient, ids: list[str], languages: str) -> Any:
    return await wikidata(
        client, action="wbgetentities", ids="|".join(ids), props="labels", languages=languages
    )


async def fetch_entities_map(
    client: httpx.AsyncClient, ids: list[str], props: str, languages: str, sitefilter: str
) -> dict[str, dict[str, Any]]:
    """Fetch any number of ids (chunks of 50, in parallel) into {qid: entity}."""
    chunks = chunked(ids, MAX_IDS_PER_CALL)
    responses = await asyncio.gather(
        *(get_entities(client, chunk, props, languages, sitefilter) for chunk in chunks),
        return_exceptions=True,
    )
    entities: dict[str, dict[str, Any]] = {}
    for chunk, response in zip(chunks, responses, strict=True):
        if isinstance(response, BaseException):
            print(f"  WARNING: wbgetentities for {chunk} failed: {describe_error(response)}")
            continue
        entities.update(response.get("entities", {}))
    return entities


# ----------------------------------------------------------------------------- steps
async def step_labels(client: httpx.AsyncClient) -> None:
    banner("STEP 1: verify UNIVERSITY_QIDS and CITY_QIDS labels (props=labels&languages=en)")
    for title, expected in (("UNIVERSITY_QIDS", UNIVERSITY_QIDS), ("CITY_QIDS", CITY_QIDS)):
        print(f"\n{title}:")
        try:
            response = await get_labels(client, list(expected), "en")
        except httpx.HTTPError as exc:
            print(f"  WARNING: label check failed: {describe_error(exc)}")
            continue
        entities = response.get("entities", {})
        for qid, want in expected.items():
            entity = entities.get(qid, {})
            got = label(entity, "en")
            missing = "missing" in entity
            verdict = "MISSING ENTITY" if missing else label_match(got, want)
            flag = "" if verdict == "exact" else "   <-- CHECK"
            print(f"  {qid:<10}| {got!s:<32}| expected {want!r:<32}| {verdict}{flag}")


async def step_search(client: httpx.AsyncClient) -> SearchResults:
    banner("STEP 2: wbsearchentities (exact spec params) for every query in en / ru / kk")
    keys: list[SearchKey] = [(q, lang) for q in SEARCH_QUERIES for lang in SEARCH_LANGS]
    responses = await asyncio.gather(
        *(search_entities(client, q, lang) for q, lang in keys), return_exceptions=True
    )
    results: SearchResults = dict(zip(keys, responses, strict=True))
    for query in SEARCH_QUERIES:
        print(f"\nquery: {query!r}")
        for lang in SEARCH_LANGS:
            response = results[(query, lang)]
            if isinstance(response, BaseException):
                print(f"  [{lang}] WARNING: {describe_error(response)}")
                continue
            hits = response.get("search", [])
            print(f"  [{lang}] {len(hits)} hits")
            for hit in hits:
                match = hit.get("match", {})
                print(
                    f"    {hit.get('id'):<11} label={hit.get('label')!r} "
                    f"description={hit.get('description')!r} "
                    f"match={match.get('type')}/{match.get('language')}/{match.get('text')!r}"
                )
    return results


def hit_ids(results: SearchResults, queries: tuple[str, ...]) -> list[str]:
    ids: list[str] = []
    for query in queries:
        for lang in SEARCH_LANGS:
            response = results.get((query, lang))
            if isinstance(response, BaseException) or response is None:
                continue
            for hit in response.get("search", []):
                if hit.get("id") and hit["id"] not in ids:
                    ids.append(hit["id"])
    return ids


async def step_entities(
    client: httpx.AsyncClient, results: SearchResults
) -> dict[str, dict[str, Any]]:
    banner("STEP 3: wbgetentities (full spec props) for every search hit + university filter")
    ids = hit_ids(results, SEARCH_QUERIES)
    print(f"{len(ids)} distinct ids in {len(chunked(ids, MAX_IDS_PER_CALL))} call(s)")
    entities = await fetch_entities_map(
        client, ids, ENTITY_PROPS, ENTITY_LANGUAGES, ENTITY_SITEFILTER
    )
    for qid in ids:
        entity = entities.get(qid)
        if entity is None:
            print(f"  {qid}: not returned")
            continue
        if "missing" in entity:
            print(f"  {qid}: entity marked missing")
            continue
        rule_a, rule_b = passes_filter(entity)
        p31 = claim_ids(entity, "P31")
        p31_text = ", ".join(f"{p}({UNIVERSITY_QIDS.get(p, '-')})" for p in p31) or "-"
        print(f"\n  {qid} {label(entity, 'en')!r}")
        print(f"    P31: {p31_text}")
        print(f"    en: {description(entity, 'en')!r}")
        print(f"    ru: {description(entity, 'ru')!r}")
        verdict = "KEEP" if (rule_a or rule_b) else "drop"
        print(f"    filter: (a)={rule_a} (b)={rule_b} -> {verdict}")
    return entities


def find_nu_qid(results: SearchResults) -> str | None:
    """QID of Nazarbayev University from the en search: exact label match first, else top hit."""
    response = results.get((NU_QUERY, "en"))
    if isinstance(response, BaseException) or response is None:
        return None
    hits = response.get("search", [])
    for hit in hits:
        if str(hit.get("label", "")).casefold() == NU_QUERY.casefold():
            return str(hit["id"])
    return str(hits[0]["id"]) if hits else None


def print_header_facts(qid: str, entity: dict[str, Any]) -> None:
    print(
        f"\n{qid} labels: en={label(entity, 'en')!r} ru={label(entity, 'ru')!r} "
        f"kk={label(entity, 'kk')!r}"
    )
    for prop in HEADER_PROPS:
        raw = entity.get("claims", {}).get(prop, [])
        values = claim_values(entity, prop)
        ranks = [c.get("rank") for c in raw]
        print(f"  {prop}: {len(raw)} claim(s) ranks={ranks} values={values!r}")
    for lang in ("en", "ru", "kk"):
        aliases = [a.get("value") for a in entity.get("aliases", {}).get(lang, [])]
        print(f"  aliases[{lang}]: {aliases!r}")
    sitelinks = {k: v.get("title") for k, v in entity.get("sitelinks", {}).items()}
    print(f"  sitelinks: {sitelinks!r}")
    notes = snak_notes(entity)
    print(f"  snak/rank notes ({len(notes)}):")
    for note in notes:
        print(f"    - {note}")


async def walk_city_chain(
    client: httpx.AsyncClient, entity: dict[str, Any]
) -> tuple[list[dict[str, Any]], str | None]:
    """Section 7.1 city resolution; returns (hop responses, matched city qid)."""
    p131 = claim_ids(entity, "P131")
    print(f"\n  city chain: P131 (preferred first) = {p131}")
    hops: list[dict[str, Any]] = []
    cur = p131[0] if p131 else None
    matched: str | None = None
    for hop in range(MAX_CITY_HOPS):
        if cur is None:
            print("    no further P131 -> chain ends")
            break
        try:
            response = await get_entities(client, [cur], HOP_PROPS, HOP_LANGUAGES, HOP_SITEFILTER)
        except httpx.HTTPError as exc:
            print(f"    hop {hop + 1}: {cur} WARNING {describe_error(exc)}")
            break
        hops.append(response)
        hop_entity = response.get("entities", {}).get(cur, {})
        p31 = claim_ids(hop_entity, "P31")
        hit = [q for q in p31 if q in CITY_QIDS]
        coords = claim_values(hop_entity, "P625")
        sites = {k: v.get("title") for k, v in hop_entity.get("sitelinks", {}).items()}
        print(
            f"    hop {hop + 1}: {cur} label={label(hop_entity, 'en')!r} P31={p31} "
            f"city_match={hit or False} P625={coords!r} P373={claim_values(hop_entity, 'P373')!r} "
            f"sitelinks={sites!r}"
        )
        for note in snak_notes(hop_entity):
            print(f"      - {note}")
        if hit:
            matched = cur
            break
        next_p131 = claim_ids(hop_entity, "P131")
        cur = next_p131[0] if next_p131 else None
    if matched is None:
        p159 = claim_ids(entity, "P159")
        print(f"    no hop matched CITY_QIDS; fallback P159 (headquarters) = {p159}")
    return hops, matched


async def step_facts(
    client: httpx.AsyncClient, qid: str, name: str
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    banner(f"STEP 4: header facts + city chain for {name} ({qid})")
    try:
        response = await get_entities(
            client, [qid], ENTITY_PROPS, ENTITY_LANGUAGES, ENTITY_SITEFILTER
        )
    except httpx.HTTPError as exc:
        print(f"  WARNING: entity fetch failed: {describe_error(exc)}")
        return None, []
    entity = response.get("entities", {}).get(qid, {})
    print_header_facts(qid, entity)
    hops, matched = await walk_city_chain(client, entity)
    print(f"  resolved city qid: {matched}")
    return response, hops


async def step_fixtures(
    client: httpx.AsyncClient,
    results: SearchResults,
    entities: dict[str, dict[str, Any]],
    mit_response: dict[str, Any] | None,
    mit_hops: list[dict[str, Any]],
) -> None:
    banner("STEP 5: save real responses as fixtures")
    fixtures: dict[str, Any] = {
        "wikidata_search_nazarbayev_en.json": results.get((NU_QUERY, "en")),
        "wikidata_entities_mit.json": mit_response,
        "wikidata_entities_cambridge.json": mit_hops[0] if mit_hops else None,
        "wikidata_search_columbia_en.json": results.get((COLUMBIA_QUERY, "en")),
        "wikidata_search_nonsense_en.json": results.get((NONSENSE_QUERY, "en")),
    }
    columbia_ids = hit_ids(results, (COLUMBIA_QUERY,))
    if columbia_ids:
        try:
            fixtures["wikidata_entities_columbia.json"] = await get_entities(
                client,
                columbia_ids[:MAX_IDS_PER_CALL],
                ENTITY_PROPS,
                ENTITY_LANGUAGES,
                ENTITY_SITEFILTER,
            )
        except httpx.HTTPError as exc:
            print(f"  WARNING: Columbia entity fetch failed: {describe_error(exc)}")
    kept = [q for q in columbia_ids if q in entities and any(passes_filter(entities[q]))]
    place_ids: list[str] = []
    for qid in kept:
        for pid in [*claim_ids(entities[qid], "P17"), *claim_ids(entities[qid], "P131")]:
            if pid not in place_ids:
                place_ids.append(pid)
    print(f"  Columbia: {len(columbia_ids)} hits, {len(kept)} kept -> P17/P131 ids {place_ids}")
    if place_ids:
        try:
            fixtures["wikidata_labels_country_city.json"] = await get_labels(
                client, place_ids[:MAX_IDS_PER_CALL], LABEL_LANGUAGES
            )
        except httpx.HTTPError as exc:
            print(f"  WARNING: label fetch failed: {describe_error(exc)}")
    for name, data in fixtures.items():
        if data is None or isinstance(data, BaseException):
            print(f"  SKIPPED {name}: no real response available")
            continue
        save_fixture(name, data)


async def main() -> int:
    settings = Settings()
    async with create_client(settings) as client:
        await step_labels(client)
        results = await step_search(client)
        entities = await step_entities(client, results)
        mit_response, mit_hops = await step_facts(client, MIT_QID, "MIT")
        nu_qid = find_nu_qid(results)
        if nu_qid is None:
            print("\nWARNING: Nazarbayev University not found in the en search; skipping its facts")
        else:
            await step_facts(client, nu_qid, "Nazarbayev University")
        await step_fixtures(client, results, entities, mit_response, mit_hops)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(asyncio.run(main()))
