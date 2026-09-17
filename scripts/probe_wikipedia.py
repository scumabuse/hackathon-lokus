"""Probe the REAL Wikipedia APIs used by the resolver fallback (SPEC Sections 7.1, 7.2).

What it probes (all calls go through app.http so the Wikimedia User-Agent policy is honoured):
  1. opensearch (action=opensearch&search={q}&limit=5&namespace=0&format=json) on en and ru
     for a misspelled English name and a Russian name;
  2. titles -> QIDs with action=query&prop=pageprops&ppprop=wikibase_item&titles=t1|t2&format=json
     for every title opensearch returned;
  3. the REST summary https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title} for the MIT
     en title and its ru title (titles taken from the Q49108 sitelinks);
  4. saves unmodified responses (pretty-printed, UTF-8) into backend/tests/fixtures/.

How to run:
  cd backend && python ../scripts/probe_wikipedia.py

No API key is needed. Every external failure is printed as a warning; the script never crashes.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.config import Settings
from app.http import create_client, get_json

FIXTURES_DIR = BACKEND_DIR / "tests" / "fixtures"
WIKIPEDIA_API = "https://{lang}.wikipedia.org/w/api.php"
REST_SUMMARY = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
# Section 7.1 gives no timeout for opensearch / pageprops: the Wikidata 5 s is reused.
ACTION_TIMEOUT_S = 5.0
SUMMARY_TIMEOUT_S = 4.0  # Section 7.2: "Timeout 4 s"
MIT_QID = "Q49108"

LANGS = ("en", "ru")
MISSPELLED_QUERY = "Massachusets Institut of Technology"
RUSSIAN_QUERY = "Костанайский региональный университет"
QUERIES = (MISSPELLED_QUERY, RUSSIAN_QUERY)

OpenSearchKey = tuple[str, str]


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


def encode_title(title: str) -> str:
    """Section 7.2: title URL-encoded, spaces as underscores."""
    return quote(title.replace(" ", "_"), safe="")


# ----------------------------------------------------------------------------- API calls
async def opensearch(client: httpx.AsyncClient, lang: str, query: str) -> Any:
    params = {
        "action": "opensearch",
        "search": query,
        "limit": "5",
        "namespace": "0",
        "format": "json",
    }
    return await get_json(
        client,
        WIKIPEDIA_API.format(lang=lang),
        service="wikipedia",
        params=params,
        timeout=ACTION_TIMEOUT_S,
    )


async def pageprops(client: httpx.AsyncClient, lang: str, titles: list[str]) -> Any:
    params = {
        "action": "query",
        "prop": "pageprops",
        "ppprop": "wikibase_item",
        "titles": "|".join(titles),
        "format": "json",
    }
    return await get_json(
        client,
        WIKIPEDIA_API.format(lang=lang),
        service="wikipedia",
        params=params,
        timeout=ACTION_TIMEOUT_S,
    )


async def rest_summary(client: httpx.AsyncClient, lang: str, title: str) -> Any:
    url = REST_SUMMARY.format(lang=lang, title=encode_title(title))
    return await get_json(client, url, service="wikipedia", timeout=SUMMARY_TIMEOUT_S)


async def mit_sitelinks(client: httpx.AsyncClient) -> dict[str, str]:
    """{site: title} for Q49108 from Wikidata (props=sitelinks&sitefilter=enwiki|ruwiki)."""
    params = {
        "action": "wbgetentities",
        "ids": MIT_QID,
        "props": "sitelinks",
        "sitefilter": "enwiki|ruwiki",
        "format": "json",
    }
    response = await get_json(
        client, WIKIDATA_API, service="wikidata", params=params, timeout=ACTION_TIMEOUT_S
    )
    sitelinks = response.get("entities", {}).get(MIT_QID, {}).get("sitelinks", {})
    return {site: str(link.get("title")) for site, link in sitelinks.items()}


# ----------------------------------------------------------------------------- steps
def opensearch_titles(response: Any) -> list[str]:
    """opensearch returns a JSON array: [query, [titles], [descriptions], [urls]]."""
    if isinstance(response, list) and len(response) >= 2 and isinstance(response[1], list):
        return [str(t) for t in response[1]]
    return []


async def step_opensearch(client: httpx.AsyncClient) -> dict[OpenSearchKey, Any]:
    banner("STEP 1: opensearch (exact spec params) on en / ru")
    keys: list[OpenSearchKey] = [(q, lang) for q in QUERIES for lang in LANGS]
    responses = await asyncio.gather(
        *(opensearch(client, lang, q) for q, lang in keys), return_exceptions=True
    )
    results: dict[OpenSearchKey, Any] = dict(zip(keys, responses, strict=True))
    for query in QUERIES:
        print(f"\nquery: {query!r}")
        for lang in LANGS:
            response = results[(query, lang)]
            if isinstance(response, BaseException):
                print(f"  [{lang}] WARNING: {describe_error(response)}")
                continue
            shape = type(response).__name__
            length = len(response) if isinstance(response, list | dict) else "?"
            print(f"  [{lang}] response type={shape} len={length}")
            titles = opensearch_titles(response)
            print(f"  [{lang}] titles: {titles!r}")
            if isinstance(response, list) and len(response) >= 4:
                print(f"  [{lang}] descriptions: {response[2]!r}")
                print(f"  [{lang}] urls: {response[3]!r}")
    return results


async def step_pageprops(
    client: httpx.AsyncClient, results: dict[OpenSearchKey, Any]
) -> dict[str, Any]:
    banner("STEP 2: pageprops titles -> QIDs for every opensearch title")
    titles_by_lang: dict[str, list[str]] = {lang: [] for lang in LANGS}
    for (_query, lang), response in results.items():
        if isinstance(response, BaseException):
            continue
        for title in opensearch_titles(response):
            if title not in titles_by_lang[lang]:
                titles_by_lang[lang].append(title)
    responses: dict[str, Any] = {}
    for lang, titles in titles_by_lang.items():
        if not titles:
            print(f"\n[{lang}] no titles to map")
            continue
        print(f"\n[{lang}] titles={titles!r}")
        try:
            response = await pageprops(client, lang, titles)
        except httpx.HTTPError as exc:
            print(f"  WARNING: {describe_error(exc)}")
            continue
        responses[lang] = response
        query = response.get("query", {})
        for key in ("normalized", "redirects"):
            if key in query:
                print(f"  query.{key}: {query[key]!r}")
        for page_id, page in query.get("pages", {}).items():
            qid = page.get("pageprops", {}).get("wikibase_item")
            flags = [k for k in ("missing", "invalid") if k in page]
            print(f"  page {page_id}: title={page.get('title')!r} wikibase_item={qid!r} {flags}")
    return responses


async def step_summaries(client: httpx.AsyncClient) -> dict[str, Any]:
    banner("STEP 3: REST summary for the MIT en title and its ru title")
    try:
        sitelinks = await mit_sitelinks(client)
    except httpx.HTTPError as exc:
        print(f"  WARNING: sitelinks fetch failed: {describe_error(exc)}")
        return {}
    print(f"  Q49108 sitelinks: {sitelinks!r}")
    titles = {"en": sitelinks.get("enwiki"), "ru": sitelinks.get("ruwiki")}
    summaries: dict[str, Any] = {}
    for lang, title in titles.items():
        if not title:
            print(f"  [{lang}] no sitelink -> skipped")
            continue
        print(f"\n  [{lang}] title={title!r} path={encode_title(title)!r}")
        try:
            summary = await rest_summary(client, lang, title)
        except httpx.HTTPError as exc:
            print(f"  WARNING: {describe_error(exc)}")
            continue
        summaries[lang] = summary
        print(f"    keys: {sorted(summary)}")
        print(f"    type={summary.get('type')!r} title={summary.get('title')!r}")
        extract = str(summary.get("extract", ""))
        print(f"    extract[:200]={extract[:200]!r} (len={len(extract)})")
        page = summary.get("content_urls", {}).get("desktop", {}).get("page")
        print(f"    content_urls.desktop.page={page!r}")
        print(f"    wikibase_item={summary.get('wikibase_item')!r} lang={summary.get('lang')!r}")
    return summaries


def step_fixtures(
    results: dict[OpenSearchKey, Any], props: dict[str, Any], summaries: dict[str, Any]
) -> None:
    banner("STEP 4: save real responses as fixtures")
    fixtures: dict[str, Any] = {
        "wikipedia_opensearch_en_misspelled.json": results.get((MISSPELLED_QUERY, "en")),
        "wikipedia_pageprops_en.json": props.get("en"),
        "wikipedia_summary_mit_en.json": summaries.get("en"),
    }
    for name, data in fixtures.items():
        if data is None or isinstance(data, BaseException):
            print(f"  SKIPPED {name}: no real response available")
            continue
        save_fixture(name, data)


async def main() -> int:
    settings = Settings()
    async with create_client(settings) as client:
        results = await step_opensearch(client)
        props = await step_pageprops(client, results)
        summaries = await step_summaries(client)
    step_fixtures(results, props, summaries)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(asyncio.run(main()))
