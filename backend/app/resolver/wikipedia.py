"""Wikipedia: opensearch + pageprops (Section 7.1 fallback 1) and the REST summary (Section 7.2).

Every call goes through ``app.http.get_json`` (service ``wikipedia``); failures degrade into a
warning and an empty result.
"""

from __future__ import annotations

import logging
import unicodedata
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel

from app.http import get_json

log = logging.getLogger("app.resolver.wikipedia")

SERVICE = "wikipedia"
WIKIPEDIA_API = "https://{lang}.wikipedia.org/w/api.php"
REST_SUMMARY = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
# Section 7.1 gives no timeout for opensearch / pageprops: the Wikidata value (5 s) is reused.
API_TIMEOUT_S = 5.0
SUMMARY_TIMEOUT_S = 4.0
OPENSEARCH_LIMIT = 5


class WikiSummary(BaseModel):
    lang: str
    title: str
    extract: str
    page_url: str


def encode_title(title: str) -> str:
    """Spaces -> ``_``, then percent-encoded (``quote(safe="")``) for the REST path."""
    return quote(title.strip().replace(" ", "_"), safe="")


async def opensearch(client: httpx.AsyncClient, lang: str, q: str) -> list[str]:
    """Page titles from ``action=opensearch`` (response is ``[query, titles, descs, urls]``)."""
    params: dict[str, Any] = {
        "action": "opensearch",
        "search": q,
        "limit": OPENSEARCH_LIMIT,
        "namespace": 0,
        "format": "json",
    }
    try:
        data = await get_json(
            client,
            WIKIPEDIA_API.format(lang=lang),
            service=SERVICE,
            params=params,
            timeout=API_TIMEOUT_S,
        )
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("%s.wikipedia opensearch %r failed: %s", lang, q, exc)
        return []
    if not isinstance(data, list) or len(data) < 2 or not isinstance(data[1], list):
        log.warning("%s.wikipedia opensearch %r returned an unexpected shape", lang, q)
        return []
    return [title for title in data[1] if isinstance(title, str) and title.strip()]


async def titles_to_qids(client: httpx.AsyncClient, lang: str, titles: list[str]) -> list[str]:
    """``prop=pageprops&ppprop=wikibase_item``: QIDs in title order; pages without one skipped.

    ``redirects=1`` is added to the Section 7.1 parameters (recorded in DECISIONS.md): opensearch
    returns redirect titles, and without it the redirect page itself comes back with no
    ``pageprops``, so its QID would be lost. ``query.redirects[]`` (from -> to) is applied after
    ``query.normalized[]`` to map each requested title to the page that carries the QID.
    """
    wanted = list(dict.fromkeys(t.strip() for t in titles if t.strip()))
    if not wanted:
        return []
    params: dict[str, Any] = {
        "action": "query",
        "prop": "pageprops",
        "ppprop": "wikibase_item",
        "titles": "|".join(wanted),
        "redirects": 1,
        "format": "json",
    }
    try:
        data = await get_json(
            client,
            WIKIPEDIA_API.format(lang=lang),
            service=SERVICE,
            params=params,
            timeout=API_TIMEOUT_S,
        )
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("%s.wikipedia pageprops for %d titles failed: %s", lang, len(wanted), exc)
        return []
    query = data.get("query") if isinstance(data, dict) else None
    if not isinstance(query, dict):
        return []
    # the API may normalize titles (e.g. underscores) and then resolve redirects; map the
    # requested title through both to the title of the page that carries the QID
    normalized = _title_map(query.get("normalized"))
    redirects = _title_map(query.get("redirects"))
    # pages is keyed by pageid (order differs from the titles); formatversion=2 would be a list
    pages = query.get("pages", {})
    page_items: list[Any] = []
    if isinstance(pages, dict):
        page_items = list(pages.values())
    elif isinstance(pages, list):
        page_items = pages
    by_title: dict[str, str] = {}
    for page in page_items:
        if not isinstance(page, dict):
            continue
        props = page.get("pageprops")
        qid = props.get("wikibase_item") if isinstance(props, dict) else None
        if isinstance(qid, str) and isinstance(page.get("title"), str):
            by_title[page["title"]] = qid
    qids: list[str] = []
    for title in wanted:
        page_title = normalized.get(title, title)
        page_title = redirects.get(page_title, page_title)
        qid = by_title.get(page_title)
        if qid and qid not in qids:
            qids.append(qid)
    return qids


def _title_map(items: Any) -> dict[str, str]:
    """``[{"from": ..., "to": ...}, ...]`` (query.normalized / query.redirects) -> {from: to}."""
    mapping: dict[str, str] = {}
    if not isinstance(items, list):
        return mapping
    for item in items:
        if not isinstance(item, dict):
            continue
        source, target = item.get("from"), item.get("to")
        if isinstance(source, str) and isinstance(target, str) and target:
            mapping[source] = target
    return mapping


def clean_extract(text: Any) -> str:
    """NFC-normalize, turn non-breaking spaces into spaces, collapse blanks, strip."""
    if not isinstance(text, str):
        return ""
    normalized = unicodedata.normalize("NFC", text).replace(" ", " ")
    lines = [" ".join(line.split()) for line in normalized.splitlines()]
    return "\n".join(line for line in lines if line).strip()


async def rest_summary(client: httpx.AsyncClient, lang: str, title: str) -> WikiSummary | None:
    """Section 7.2 REST summary: ``extract`` + ``content_urls.desktop.page``; None on any failure."""
    encoded = encode_title(title)
    if not encoded:
        return None
    url = REST_SUMMARY.format(lang=lang, title=encoded)
    try:
        data = await get_json(client, url, service=SERVICE, timeout=SUMMARY_TIMEOUT_S)
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("%s.wikipedia summary for %r failed: %s", lang, title, exc)
        return None
    if not isinstance(data, dict):
        return None
    extract = clean_extract(data.get("extract"))
    if not extract:
        log.info("%s.wikipedia summary for %r has no extract", lang, title)
        return None
    content_urls = data.get("content_urls", {})
    desktop = content_urls.get("desktop", {}) if isinstance(content_urls, dict) else {}
    page_url = desktop.get("page") if isinstance(desktop, dict) else None
    if not isinstance(page_url, str) or not page_url:
        page_url = f"https://{lang}.wikipedia.org/wiki/{encoded}"
    page_title = data.get("title")
    return WikiSummary(
        lang=lang,
        title=page_title if isinstance(page_title, str) and page_title else title,
        extract=extract,
        page_url=page_url,
    )
