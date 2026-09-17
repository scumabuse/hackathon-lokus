"""GET /api/search flow: Wikidata search + filter + ranking, then the fallbacks (SPEC 7.1, 12).

``search_universities`` never raises: every external failure is logged and treated as "no results
from that step", and the last resort is an empty candidate list.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import httpx

from app.cache import normalize_query
from app.models import Candidate, SearchResponse
from app.resolver import wikidata, wikipedia
from app.resolver.spelling import suggest_official_names

if TYPE_CHECKING:
    from app.ai.client import AIClient
    from app.cache import Cache

log = logging.getLogger("app.resolver.search")

MAX_CANDIDATES = 8
MAX_SUGGESTIONS = 3
MIN_QUERY_LEN = 2  # Section 12: q is 2-120 chars (measured after whitespace collapsing)
OPENSEARCH_LANGS: tuple[str, ...] = ("en", "ru")
# Rank offset for hits of the extra "<q> university" search so that they always sort after
# every direct hit (see DECISIONS.md: gate "Columbia -> several candidates").
AUGMENTED_RANK_OFFSET = 100
AUGMENT_SUFFIX = " university"
# Overall deadline for one uncached search, all fallbacks included (DECISIONS.md): the Section 6
# Stage A hard limit is 5 s, but the fallback chain contains a 6 s LLM call, so the search
# endpoint gets 12 s; on expiry it answers candidates=[] instead of hanging on retries.
SEARCH_DEADLINE_S = 12.0

Pair = tuple[dict[str, Any], dict[str, Any]]  # (search hit, entity)


async def search_universities(
    client: httpx.AsyncClient,
    q: str,
    *,
    ai: AIClient | None = None,
    cache: Cache | None = None,
) -> SearchResponse:
    """Section 7.1 search with fallbacks; cached 6 h by normalized query (Section 12)."""
    query = " ".join(q.split())
    if len(query) < MIN_QUERY_LEN:
        log.info("search query %r is blank or too short; no candidates", q)
        return SearchResponse(query=query, candidates=[])
    q_norm = normalize_query(query)
    cached = await _cache_get(cache, q_norm, query)
    if cached is not None:
        return cached
    try:
        response = await asyncio.wait_for(
            _search_uncached(client, query, ai), timeout=SEARCH_DEADLINE_S
        )
    except TimeoutError:
        log.warning("search for %r exceeded %.1f s; no candidates", query, SEARCH_DEADLINE_S)
        return SearchResponse(query=query, candidates=[])
    except Exception:  # the endpoint must never fail because of a resolver bug
        log.warning("search for %r failed unexpectedly; no candidates", query, exc_info=True)
        return SearchResponse(query=query, candidates=[])
    if response.candidates:
        await _cache_set(cache, q_norm, response)
    return response


def _corrected(candidates: list[Candidate], query: str) -> str | None:
    """Top label as ``corrected_query`` when it differs from what the user typed."""
    top = candidates[0].label
    return top if top.casefold() != query.casefold() else None


async def _search_uncached(
    client: httpx.AsyncClient, query: str, ai: AIClient | None
) -> SearchResponse:
    hits = await wikidata_search(client, query)
    candidates = await candidates_from_hits(client, hits, query)
    if candidates:
        return SearchResponse(query=query, candidates=candidates)

    log.info("no wikidata candidates for %r; trying wikipedia opensearch", query)
    candidates = await opensearch_fallback(client, query)
    if candidates:
        return SearchResponse(
            query=query, candidates=candidates, corrected_query=_corrected(candidates, query)
        )

    log.info("no opensearch candidates for %r; trying wikidata full-text search", query)
    candidates = await fulltext_fallback(client, query)
    if candidates:
        return SearchResponse(
            query=query, candidates=candidates, corrected_query=_corrected(candidates, query)
        )

    if ai is not None:
        found = await suggestions_fallback(client, ai, query)
        if found is not None:
            name, candidates = found
            return SearchResponse(
                query=query,
                candidates=candidates,
                suggestions_used=True,
                corrected_query=name,
            )
    return SearchResponse(query=query, candidates=[])


# ----------------------------------------------------------------------------- step 1: Wikidata


def merge_hits(results: list[list[dict[str, Any]]], offsets: list[int]) -> list[dict[str, Any]]:
    """Merge per-language hit lists by id keeping the lowest rank (position + list offset)."""
    best: dict[str, tuple[int, int, dict[str, Any]]] = {}
    order = 0
    for hits, offset in zip(results, offsets, strict=True):
        for position, hit in enumerate(hits):
            rank = offset + position
            qid = hit["id"]
            current = best.get(qid)
            if current is None or rank < current[0]:
                best[qid] = (rank, current[1] if current else order, hit)
            order += 1
    return [hit for _, _, hit in sorted(best.values(), key=lambda item: (item[0], item[1]))]


async def wikidata_search(client: httpx.AsyncClient, query: str) -> list[dict[str, Any]]:
    """``wbsearchentities`` in en/ru/kk in parallel (+ "<q> university" when q has no such word)."""
    queries: list[tuple[str, str, int]] = [(query, lang, 0) for lang in wikidata.SEARCH_LANGS]
    if not wikidata.DESCRIPTION_RE.search(query):
        queries.append((query + AUGMENT_SUFFIX, "en", AUGMENTED_RANK_OFFSET))
    results = await asyncio.gather(
        *(wikidata.search_entities(client, text, lang) for text, lang, _ in queries),
        return_exceptions=True,
    )
    lists: list[list[dict[str, Any]]] = []
    offsets: list[int] = []
    for (text, lang, offset), result in zip(queries, results, strict=True):
        if isinstance(result, BaseException):
            log.warning("wikidata search %r (%s) raised: %r", text, lang, result)
            continue
        lists.append(result)
        offsets.append(offset)
    return merge_hits(lists, offsets)


def names_of(hit: dict[str, Any], entity: dict[str, Any]) -> list[str]:
    names = [*wikidata.label_map(entity).values(), *wikidata.alias_values(entity)]
    if isinstance(hit.get("label"), str):
        names.append(hit["label"])
    return names


def is_exact_match(hit: dict[str, Any], entity: dict[str, Any], query: str) -> bool:
    wanted = " ".join(query.split()).casefold()
    return any(" ".join(name.split()).casefold() == wanted for name in names_of(hit, entity))


def rank_pairs(pairs: list[Pair], query: str) -> list[Pair]:
    """Search order, with exact case-insensitive label/alias matches moved to the top."""
    return sorted(pairs, key=lambda pair: 0 if is_exact_match(pair[0], pair[1], query) else 1)


def _candidate(hit: dict[str, Any], entity: dict[str, Any], labels: dict[str, str]) -> Candidate:
    qid = str(entity.get("id") or hit["id"])
    hit_label = hit.get("label") if isinstance(hit.get("label"), str) else None
    hit_description = hit.get("description") if isinstance(hit.get("description"), str) else None
    country_ids = wikidata.country_candidates(entity)
    city_ids = wikidata.item_ids(entity, "P131")
    return Candidate(
        qid=qid,
        label=wikidata.entity_label(entity) or hit_label or qid,
        description=wikidata.entity_description(entity) or hit_description,
        country=labels.get(country_ids[0]) if country_ids else None,
        city=labels.get(city_ids[0]) if city_ids else None,
    )


async def candidates_from_hits(
    client: httpx.AsyncClient, hits: list[dict[str, Any]], query: str
) -> list[Candidate]:
    """Entity fetch -> university filter -> ranking -> up to 8 Candidates with country/city."""
    if not hits:
        return []
    entities = await wikidata.get_entities(
        client,
        [hit["id"] for hit in hits],
        props=wikidata.ENTITY_PROPS,
        languages=wikidata.ENTITY_LANGUAGES,
        sitefilter=wikidata.ENTITY_SITEFILTER,
    )
    kept: list[Pair] = []
    for hit in hits:
        entity = entities.get(hit["id"])
        if entity is not None and wikidata.is_university(entity, query=query):
            kept.append((hit, entity))
    kept = rank_pairs(kept, query)[:MAX_CANDIDATES]
    if not kept:
        return []
    place_ids: list[str] = []
    for _, entity in kept:
        place_ids.extend(wikidata.country_candidates(entity)[:1])
        place_ids.extend(wikidata.item_ids(entity, "P131")[:1])
    labels = await wikidata.fetch_labels(client, place_ids)
    return [_candidate(hit, entity, labels) for hit, entity in kept]


async def candidates_from_ids(
    client: httpx.AsyncClient, qids: list[str], query: str
) -> list[Candidate]:
    return await candidates_from_hits(client, [{"id": qid} for qid in qids], query)


# ----------------------------------------------------------------------------- step 2: Wikipedia


async def _opensearch_qids(client: httpx.AsyncClient, lang: str, query: str) -> list[str]:
    titles = await wikipedia.opensearch(client, lang, query)
    if not titles:
        return []
    return await wikipedia.titles_to_qids(client, lang, titles)


async def opensearch_fallback(client: httpx.AsyncClient, query: str) -> list[Candidate]:
    """Fallback 1: en + ru opensearch (parallel) -> pageprops -> entity fetch + filter."""
    results = await asyncio.gather(
        *(_opensearch_qids(client, lang, query) for lang in OPENSEARCH_LANGS),
        return_exceptions=True,
    )
    qids: list[str] = []
    for lang, result in zip(OPENSEARCH_LANGS, results, strict=True):
        if isinstance(result, BaseException):
            log.warning("wikipedia opensearch fallback (%s) raised: %r", lang, result)
            continue
        qids.extend(qid for qid in result if qid not in qids)
    if not qids:
        return []
    return await candidates_from_ids(client, qids, query)


# ----------------------------------------------------------------------------- step 3: full text


async def fulltext_fallback(client: httpx.AsyncClient, query: str) -> list[Candidate]:
    """Extra fallback (DECISIONS.md): Wikidata full-text search -> entity fetch + filter.

    Rescues entities whose label only *contains* the query (wbsearchentities is a prefix matcher)
    and which have no Wikipedia article (so opensearch cannot find them either).
    """
    qids = await wikidata.search_fulltext(client, query)
    if not qids:
        return []
    return await candidates_from_ids(client, qids, query)


# ----------------------------------------------------------------------------- step 4: spelling


async def _suggest(ai: AIClient, query: str) -> list[str]:
    try:
        names = await suggest_official_names(ai, query)
    except Exception:
        log.warning("spelling suggestions for %r failed", query, exc_info=True)
        return []
    cleaned = [" ".join(name.split()) for name in names if isinstance(name, str)]
    return [name for name in cleaned if name][:MAX_SUGGESTIONS]


async def _search_name(client: httpx.AsyncClient, name: str) -> list[Candidate]:
    hits = await wikidata.search_entities(client, name, "en")
    return await candidates_from_hits(client, hits, name)


async def suggestions_fallback(
    client: httpx.AsyncClient, ai: AIClient, query: str
) -> tuple[str, list[Candidate]] | None:
    """Fallback 2: up to 3 LLM names searched in parallel; the first (in order) that works wins."""
    names = await _suggest(ai, query)
    if not names:
        return None
    log.info("trying suggested official names %r for %r", names, query)
    results = await asyncio.gather(
        *(_search_name(client, name) for name in names), return_exceptions=True
    )
    for name, result in zip(names, results, strict=True):
        if isinstance(result, BaseException):
            log.warning("search for suggested name %r raised: %r", name, result)
            continue
        if result:
            return name, result
    return None


# ----------------------------------------------------------------------------- cache (best effort)


async def _cache_get(cache: Cache | None, q_norm: str, query: str) -> SearchResponse | None:
    if cache is None:
        return None
    try:
        data = await cache.get_search(q_norm)
        if data is None:
            return None
        response = SearchResponse.model_validate(data)
    except Exception:
        log.warning("search cache read for %r failed", q_norm, exc_info=True)
        return None
    log.info("search %r served from cache", query)
    return response.model_copy(update={"query": query})


async def _cache_set(cache: Cache | None, q_norm: str, response: SearchResponse) -> None:
    if cache is None:
        return
    try:
        await cache.set_search(q_norm, response.model_dump(mode="json"))
    except Exception:
        log.warning("search cache write for %r failed", q_norm, exc_info=True)
