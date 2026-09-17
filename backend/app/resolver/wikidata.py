"""Wikidata resolver: search, entity fetch, university filter, entity parsing, city chain.

SPEC Section 7.1. Every network call goes through ``app.http.get_json`` with the 5 s Wikidata
timeout and ``format=json``; every failure degrades into a warning plus an empty result, so
nothing in this module raises on external problems.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.geo import haversine_km
from app.http import get_json
from app.models import Coordinates, Place, UniversityHeader

log = logging.getLogger("app.resolver.wikidata")

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIDATA_TIMEOUT_S = 5.0
SERVICE = "wikidata"
MAX_IDS_PER_CALL = 50
SEARCH_LIMIT = 10
SEARCH_LANGS: tuple[str, ...] = ("en", "ru", "kk")
LABEL_LANGS: tuple[str, ...] = ("en", "ru", "kk")

# Full entity fetch for candidates / the profile header (Section 7.1 "Entity fetch").
ENTITY_PROPS = "claims|labels|descriptions|aliases|sitelinks"
ENTITY_LANGUAGES = "en|ru|kk"
ENTITY_SITEFILTER = "enwiki|ruwiki|kkwiki"
# City-chain hops (Section 7.1 "City resolution").
HOP_PROPS = "claims|labels|sitelinks"
HOP_LANGUAGES = "en|ru"
HOP_SITEFILTER = "enwiki|ruwiki"
MAX_CITY_HOPS = 4
MIN_ALIAS_LEN = 3
MIN_STRIP_LEN = 3

# Section 7.1 (a). Labels verified against the live API in Phase 1 -- every QID matched:
# university, higher education institution, public university, private university,
# research university, college, institute of technology, academic institution,
# educational institution. Nothing was dropped.
UNIVERSITY_QIDS: frozenset[str] = frozenset(
    {
        "Q3918",
        "Q38723",
        "Q875538",
        "Q902104",
        "Q15936437",
        "Q189004",
        "Q1371037",
        "Q4671277",
        "Q2385804",
    }
)
# Section 7.1 city resolution. Verified labels: city, big city, town, capital city, metropolis,
# "city or town" (spec: city/town) and "city in the United States" (spec: city of the US).
CITY_QIDS: frozenset[str] = frozenset(
    {"Q515", "Q1549591", "Q3957", "Q5119", "Q200250", "Q7930989", "Q1093829"}
)
# A P159 (headquarters) entity of one of these classes is a building, not a place, and is never
# used as the "city" (DECISIONS.md, Phase 1 review). Labels verified against the live API:
# building, built structure, campus, architectural ensemble.
NON_PLACE_QIDS: frozenset[str] = frozenset({"Q41176", "Q811979", "Q209465", "Q1497375"})
# P31 = human: rule (b) is never evaluated for people (a biography mentioning a university is
# not a university). Label verified against the live API.
HUMAN_QID = "Q5"
# Qualifier "end time": a P17 claim carrying it names a former country.
END_TIME_QUALIFIER = "P582"

# Section 7.1 (b), verbatim, case-insensitive.
DESCRIPTION_RE = re.compile(
    r"university|universit|college|institute|polytechnic|academy|school of|conservator"
    r"|университет|институт|академия|колледж|вуз|консерватор|университеті|институты",
    re.IGNORECASE,
)

WIKI_SITES: tuple[tuple[str, str], ...] = (("enwiki", "en"), ("ruwiki", "ru"))
QID_RE = re.compile(r"Q\d+")


class ResolverUnavailableError(RuntimeError):
    """Wikidata could not be reached (transport failure / bad status after the retries).

    Distinct from "entity missing / not a university" (None) so that the profile route can answer
    503 instead of 404 (Section 12).
    """


class ResolvedEntity(BaseModel):
    """A university entity after parsing: the public header plus what later stages need."""

    header: UniversityHeader
    main_image_filename: str | None = None  # P18, bare Commons filename
    logo_filename: str | None = None  # P154
    wiki_titles: dict[str, str] = Field(default_factory=dict)  # "en"/"ru" -> sitelink title
    raw: dict[str, Any] = Field(default_factory=dict)


# ----------------------------------------------------------------------------- HTTP wrappers


def _search_hits(data: Any) -> list[dict[str, Any]]:
    search = data.get("search") if isinstance(data, dict) else None
    if not isinstance(search, list):
        return []
    return [hit for hit in search if isinstance(hit, dict) and isinstance(hit.get("id"), str)]


async def search_entities(client: httpx.AsyncClient, q: str, lang: str) -> list[dict[str, Any]]:
    """``wbsearchentities`` hits (``id``, ``label``, ``description``, ``match``); [] on failure."""
    params: dict[str, Any] = {
        "action": "wbsearchentities",
        "search": q,
        "language": lang,
        "uselang": "en",
        "type": "item",
        "limit": SEARCH_LIMIT,
        "format": "json",
    }
    try:
        data = await get_json(
            client, WIKIDATA_API, service=SERVICE, params=params, timeout=WIKIDATA_TIMEOUT_S
        )
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("wikidata search %r (%s) failed: %s", q, lang, exc)
        return []
    if isinstance(data, dict) and "error" in data:
        log.warning("wikidata search %r (%s) returned an API error: %s", q, lang, data["error"])
    return _search_hits(data)


async def search_fulltext(client: httpx.AsyncClient, q: str) -> list[str]:
    """Full-text item search (``action=query&list=search``): QIDs in result order; [] on failure.

    Not in Section 7.1 (recorded in DECISIONS.md): ``wbsearchentities`` is a label/alias prefix
    matcher and misses entities whose label merely contains the query, while this CirrusSearch
    endpoint matches anywhere in labels, aliases and descriptions.
    """
    params: dict[str, Any] = {
        "action": "query",
        "list": "search",
        "srsearch": q,
        "srnamespace": 0,
        "srlimit": SEARCH_LIMIT,
        "format": "json",
    }
    try:
        data = await get_json(
            client, WIKIDATA_API, service=SERVICE, params=params, timeout=WIKIDATA_TIMEOUT_S
        )
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("wikidata full-text search %r failed: %s", q, exc)
        return []
    if not isinstance(data, dict):
        return []
    if "error" in data:
        log.warning("wikidata full-text search %r returned an API error: %s", q, data["error"])
    query = data.get("query")
    hits = query.get("search") if isinstance(query, dict) else None
    if not isinstance(hits, list):
        return []
    qids: list[str] = []
    for hit in hits:
        title = hit.get("title") if isinstance(hit, dict) else None
        if isinstance(title, str) and QID_RE.fullmatch(title) and title not in qids:
            qids.append(title)
    return qids


async def _fetch_batch(
    client: httpx.AsyncClient,
    ids: list[str],
    *,
    props: str,
    languages: str,
    sitefilter: str | None,
) -> dict[str, dict[str, Any]]:
    params: dict[str, Any] = {
        "action": "wbgetentities",
        "ids": "|".join(ids),
        "props": props,
        "languages": languages,
        "format": "json",
    }
    if sitefilter:
        params["sitefilter"] = sitefilter
    try:
        data = await get_json(
            client, WIKIDATA_API, service=SERVICE, params=params, timeout=WIKIDATA_TIMEOUT_S
        )
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("wikidata entity fetch (%d ids) failed: %s", len(ids), exc)
        raise ResolverUnavailableError(f"wikidata entity fetch failed: {exc}") from exc
    if not isinstance(data, dict):
        return {}
    if "error" in data:
        log.warning("wikidata entity fetch returned an API error: %s", data["error"])
    raw = data.get("entities")
    if not isinstance(raw, dict):
        return {}
    return {
        qid: entity
        for qid, entity in raw.items()
        if isinstance(entity, dict) and "missing" not in entity
    }


async def get_entities(
    client: httpx.AsyncClient,
    ids: list[str],
    *,
    props: str,
    languages: str,
    sitefilter: str | None = None,
    strict: bool = False,
) -> dict[str, dict[str, Any]]:
    """``wbgetentities`` for any number of ids (<= 50 per call); entities flagged missing skipped.

    A failed batch is logged and skipped, unless ``strict`` is set: then the transport failure is
    reported as ResolverUnavailableError so that the caller can tell "unreachable" from "missing".
    """
    unique = list(dict.fromkeys(qid for qid in ids if qid))
    if not unique:
        return {}
    batches = [unique[i : i + MAX_IDS_PER_CALL] for i in range(0, len(unique), MAX_IDS_PER_CALL)]
    results = await asyncio.gather(
        *(
            _fetch_batch(client, batch, props=props, languages=languages, sitefilter=sitefilter)
            for batch in batches
        ),
        return_exceptions=True,
    )
    entities: dict[str, dict[str, Any]] = {}
    for result in results:
        if isinstance(result, BaseException):
            if strict:
                raise ResolverUnavailableError(f"wikidata entity fetch failed: {result!r}")
            log.warning("wikidata entity batch failed: %r", result)
            continue
        entities.update(result)
    return entities


async def fetch_labels(
    client: httpx.AsyncClient, ids: list[str], *, languages: str = HOP_LANGUAGES
) -> dict[str, str]:
    """One ``props=labels`` call: qid -> label in the first language that has one (en first)."""
    entities = await get_entities(client, ids, props="labels", languages=languages)
    langs = tuple(languages.split("|"))
    labels: dict[str, str] = {}
    for qid, entity in entities.items():
        label = entity_label(entity, langs)
        if label:
            labels[qid] = label
    return labels


# ----------------------------------------------------------------------------- pure helpers


def usable_claims(
    entity: dict[str, Any], prop: str, *, all_ranks: bool = False
) -> list[dict[str, Any]]:
    """Claims of ``prop`` with ``snaktype == "value"`` and a datavalue, deprecated ones skipped.

    If any claim has rank ``preferred`` only those are returned (Section 7.1 "prefer preferred,
    else first"), unless ``all_ranks`` is set, which keeps every non-deprecated claim in API order.
    """
    claims = entity.get("claims", {}).get(prop, [])
    if not isinstance(claims, list):
        return []
    usable: list[dict[str, Any]] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        mainsnak = claim.get("mainsnak", {})
        if not isinstance(mainsnak, dict) or mainsnak.get("snaktype") != "value":
            continue
        if str(claim.get("rank", "normal")) == "deprecated":
            continue
        datavalue = mainsnak.get("datavalue")
        if not isinstance(datavalue, dict) or "value" not in datavalue:
            continue
        usable.append(claim)
    if all_ranks:
        return usable
    preferred = [claim for claim in usable if claim.get("rank") == "preferred"]
    return preferred or usable


def claim_values(entity: dict[str, Any], prop: str, *, all_ranks: bool = False) -> list[Any]:
    """``mainsnak.datavalue.value`` of each usable claim of ``prop`` (see ``usable_claims``)."""
    return [
        claim["mainsnak"]["datavalue"]["value"]
        for claim in usable_claims(entity, prop, all_ranks=all_ranks)
    ]


def first_claim_value(entity: dict[str, Any], prop: str) -> Any | None:
    values = claim_values(entity, prop)
    return values[0] if values else None


def _item_id(value: Any) -> str | None:
    if isinstance(value, dict) and isinstance(value.get("id"), str):
        return value["id"]
    return None


def item_ids(entity: dict[str, Any], prop: str, *, all_ranks: bool = False) -> list[str]:
    """QIDs of an item-valued property (``value.id``): preferred rank only when one exists.

    ``all_ranks`` keeps every non-deprecated claim -- required for the "any P31 is in ..." and
    "P31 intersects ..." membership checks of Section 7.1, where a normal-rank class next to a
    preferred one still counts.
    """
    ids: list[str] = []
    for value in claim_values(entity, prop, all_ranks=all_ranks):
        qid = _item_id(value)
        if qid is not None:
            ids.append(qid)
    return ids


def has_qualifier(claim: dict[str, Any], prop: str) -> bool:
    qualifiers = claim.get("qualifiers")
    return isinstance(qualifiers, dict) and prop in qualifiers


def string_value(entity: dict[str, Any], prop: str) -> str | None:
    """First non-empty string value (url / string / commonsMedia datatypes)."""
    for value in claim_values(entity, prop):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def monolingual_texts(entity: dict[str, Any], prop: str) -> list[str]:
    """``value.text`` of every non-deprecated monolingual-text claim (P1448, P1813)."""
    texts: list[str] = []
    for value in claim_values(entity, prop, all_ranks=True):
        if isinstance(value, dict) and isinstance(value.get("text"), str):
            texts.append(value["text"])
    return texts


def coordinates(entity: dict[str, Any]) -> Coordinates | None:
    """P625 -> Coordinates, or None when absent or malformed."""
    for value in claim_values(entity, "P625"):
        if not isinstance(value, dict):
            continue
        lat, lon = value.get("latitude"), value.get("longitude")
        if isinstance(lat, int | float) and isinstance(lon, int | float):
            return Coordinates(lat=float(lat), lon=float(lon))
    return None


def label_map(entity: dict[str, Any]) -> dict[str, str]:
    """lang -> label value, in the API's order."""
    labels = entity.get("labels", {})
    if not isinstance(labels, dict):
        return {}
    out: dict[str, str] = {}
    for lang, item in labels.items():
        value = item.get("value") if isinstance(item, dict) else None
        if isinstance(value, str) and value.strip():
            out[str(lang)] = value.strip()
    return out


def entity_label(entity: dict[str, Any], langs: tuple[str, ...] = LABEL_LANGS) -> str | None:
    """Label in the first of ``langs`` that exists, else the first label at all, else None."""
    labels = label_map(entity)
    for lang in langs:
        if lang in labels:
            return labels[lang]
    return next(iter(labels.values()), None)


def entity_description(entity: dict[str, Any], langs: tuple[str, ...] = ("en", "ru")) -> str | None:
    descriptions = entity.get("descriptions", {})
    if not isinstance(descriptions, dict):
        return None
    for lang in langs:
        item = descriptions.get(lang)
        value = item.get("value") if isinstance(item, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def alias_values(entity: dict[str, Any], langs: tuple[str, ...] = LABEL_LANGS) -> list[str]:
    """``aliases.{lang}[*].value`` for the given languages, in order."""
    aliases = entity.get("aliases", {})
    if not isinstance(aliases, dict):
        return []
    values: list[str] = []
    for lang in langs:
        items = aliases.get(lang, [])
        if not isinstance(items, list):
            continue
        for item in items:
            value = item.get("value") if isinstance(item, dict) else None
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
    return values


def sitelink_titles(entity: dict[str, Any]) -> dict[str, str]:
    """``{"en": <enwiki title>, "ru": <ruwiki title>}`` for the sitelinks that exist."""
    sitelinks = entity.get("sitelinks", {})
    if not isinstance(sitelinks, dict):
        return {}
    titles: dict[str, str] = {}
    for site, lang in WIKI_SITES:
        item = sitelinks.get(site)
        title = item.get("title") if isinstance(item, dict) else None
        if isinstance(title, str) and title.strip():
            titles[lang] = title.strip()
    return titles


def wikipedia_url(entity: dict[str, Any]) -> str | None:
    """enwiki sitelink -> https://en.wikipedia.org/wiki/{title, spaces -> _}; else ruwiki."""
    titles = sitelink_titles(entity)
    for _, lang in WIKI_SITES:
        title = titles.get(lang)
        if title:
            return f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"
    return None


def _strip_names(text: str, names: list[str]) -> str:
    """Remove whole-word, case-insensitive occurrences of each name (>= 3 chars) from text."""
    for name in names:
        cleaned = " ".join(name.split())
        if len(cleaned) < MIN_STRIP_LEN:
            continue
        text = re.sub(rf"(?<!\w){re.escape(cleaned)}(?!\w)", " ", text, flags=re.IGNORECASE)
    return text


def is_university(entity: dict[str, Any], *, query: str | None = None) -> bool:
    """Section 7.1 university filter: (a) any P31 in UNIVERSITY_QIDS or (b) description regex.

    Rule (a) looks at every non-deprecated P31 claim ("any"), whatever its rank. Humans (P31 =
    Q5) never pass: a biography that mentions a university is not a university (rule (b) would
    otherwise match "Ph.D. <University>" descriptions). Rule (b) is evaluated on the en/ru
    description with the search query and the entity's own labels removed first, so that
    sub-units described as "<something> of <University>" (library, repository, department,
    school ...) do not pass because of the parent's name.
    """
    classes = item_ids(entity, "P31", all_ranks=True)
    if any(qid in UNIVERSITY_QIDS for qid in classes):
        return True
    if HUMAN_QID in classes:
        return False
    names = [query or "", *label_map(entity).values()]
    descriptions = entity.get("descriptions", {})
    if not isinstance(descriptions, dict):
        return False
    for lang in ("en", "ru"):
        item = descriptions.get(lang)
        text = item.get("value") if isinstance(item, dict) else None
        if isinstance(text, str) and DESCRIPTION_RE.search(_strip_names(text, names)):
            return True
    return False


def parse_aliases(entity: dict[str, Any]) -> list[str]:
    """aliases.en/ru/kk + P1448 + P1813 texts, deduped (case-insensitive), entries < 3 chars dropped."""
    raw = [
        *alias_values(entity),
        *monolingual_texts(entity, "P1448"),
        *monolingual_texts(entity, "P1813"),
    ]
    aliases: list[str] = []
    seen: set[str] = set()
    for value in raw:
        cleaned = " ".join(value.split())
        key = cleaned.casefold()
        if len(cleaned) < MIN_ALIAS_LEN or key in seen:
            continue
        seen.add(key)
        aliases.append(cleaned)
    return aliases


def place_from_entity(entity: dict[str, Any]) -> Place:
    """City Place: name (en label, ru fallback), coords P625, commons category P373, wiki url."""
    qid = str(entity.get("id", "")) or None
    return Place(
        qid=qid,
        name=entity_label(entity, ("en", "ru")) or qid or "?",
        coords=coordinates(entity),
        wikipedia_url=wikipedia_url(entity),
        commons_category=string_value(entity, "P373"),
    )


def is_place_like(entity: dict[str, Any]) -> bool:
    """False when any P31 (all ranks) is a building / campus class: unusable as the city."""
    return not (NON_PLACE_QIDS & set(item_ids(entity, "P31", all_ranks=True)))


def country_candidates(entity: dict[str, Any]) -> list[str]:
    """P17 ids worth considering: preferred rank if any; else the claims without an end time
    (P582) if any; else every non-deprecated claim, in API order."""
    claims = usable_claims(entity, "P17")
    if not any(claim.get("rank") == "preferred" for claim in claims):
        current = [claim for claim in claims if not has_qualifier(claim, END_TIME_QUALIFIER)]
        claims = current or claims
    ids: list[str] = []
    for claim in claims:
        qid = _item_id(claim["mainsnak"]["datavalue"]["value"])
        if qid is not None and qid not in ids:
            ids.append(qid)
    return ids


def pick_country_id(entity: dict[str, Any], city: dict[str, Any] | None = None) -> str | None:
    """Section 7.1 country (P17): preferred, else first -- with one tie-break (DECISIONS.md).

    When several same-rank P17 claims remain (typically a former country listed next to the
    current one), the one the resolved city also lists as its country wins, in the city's own
    preferred-first order; without a city match the first claim is used as the spec says.
    """
    ids = country_candidates(entity)
    if len(ids) > 1 and city is not None:
        for qid in item_ids(city, "P17"):
            if qid in ids:
                return qid
    return ids[0] if ids else None


def parse_header(
    entity: dict[str, Any], *, country_label: str | None = None, city: Place | None = None
) -> UniversityHeader:
    """Section 7.1 "Entity parsing" -> UniversityHeader (country/city supplied by the caller)."""
    qid = str(entity.get("id", ""))
    labels = label_map(entity)
    name = entity_label(entity) or qid
    local_name = next(
        (labels[lang] for lang in ("ru", "kk") if lang in labels and labels[lang] != name), None
    )
    coords = coordinates(entity)
    distance: float | None = None
    if coords is not None and city is not None and city.coords is not None:
        distance = haversine_km(coords.lat, coords.lon, city.coords.lat, city.coords.lon)
    return UniversityHeader(
        qid=qid,
        name=name,
        local_name=local_name,
        aliases=parse_aliases(entity),
        country=country_label,
        city=city,
        coords=coords,
        official_website=string_value(entity, "P856"),
        wikipedia_url=wikipedia_url(entity),
        commons_category=string_value(entity, "P373"),
        distance_to_city_center_km=distance,
    )


def build_resolved(
    entity: dict[str, Any], *, country_label: str | None = None, city: Place | None = None
) -> ResolvedEntity:
    """ResolvedEntity from an already fetched entity (P18 / P154 filenames, wiki titles, raw)."""
    return ResolvedEntity(
        header=parse_header(entity, country_label=country_label, city=city),
        main_image_filename=string_value(entity, "P18"),
        logo_filename=string_value(entity, "P154"),
        wiki_titles=sitelink_titles(entity),
        raw=entity,
    )


# ----------------------------------------------------------------------------- resolution


async def _fetch_hop(client: httpx.AsyncClient, qid: str) -> dict[str, Any] | None:
    fetched = await get_entities(
        client, [qid], props=HOP_PROPS, languages=HOP_LANGUAGES, sitefilter=HOP_SITEFILTER
    )
    return fetched.get(qid)


async def resolve_city_entity(
    client: httpx.AsyncClient, entity: dict[str, Any]
) -> dict[str, Any] | None:
    """Section 7.1 city chain: follow P131 up to 4 hops; P159 / first geo hop as fallbacks.

    Returns the hop entity (claims|labels|sitelinks) so that the caller can also use its claims.
    The P159 entity is fetched in the same call as the first hop (no extra round trip when the
    chain fails), and it is only accepted when it is a place, not a building (``is_place_like``).
    """
    hops: list[dict[str, Any]] = []
    fetched: dict[str, dict[str, Any]] = {}
    start = item_ids(entity, "P131")
    cur: str | None = start[0] if start else None
    headquarters = item_ids(entity, "P159")
    hq_id: str | None = headquarters[0] if headquarters else None
    prefetch = list(dict.fromkeys(qid for qid in (cur, hq_id) if qid))
    if prefetch:
        fetched.update(
            await get_entities(
                client,
                prefetch,
                props=HOP_PROPS,
                languages=HOP_LANGUAGES,
                sitefilter=HOP_SITEFILTER,
            )
        )
    walked: set[str] = set()
    while cur and cur not in walked and len(hops) < MAX_CITY_HOPS:
        hop = fetched.get(cur)
        if hop is None and cur not in prefetch:
            hop = await _fetch_hop(client, cur)
        if hop is None:
            break
        fetched[cur] = hop
        walked.add(cur)
        hops.append(hop)
        if CITY_QIDS & set(item_ids(hop, "P31", all_ranks=True)):
            return hop
        parents = item_ids(hop, "P131")
        cur = parents[0] if parents else None
    hq = fetched.get(hq_id) if hq_id else None
    if hq is not None and coordinates(hq) is not None and is_place_like(hq):
        return hq
    for hop in hops:
        if coordinates(hop) is not None and sitelink_titles(hop):
            return hop
    return None


async def resolve_city(client: httpx.AsyncClient, entity: dict[str, Any]) -> Place | None:
    """``resolve_city_entity`` as a Place (None when no hop qualifies)."""
    city = await resolve_city_entity(client, entity)
    return place_from_entity(city) if city is not None else None


async def resolve_university(client: httpx.AsyncClient, qid: str) -> ResolvedEntity | None:
    """Fetch one entity by QID; None when it is missing or fails the university filter.

    Raises ResolverUnavailableError when Wikidata itself could not be reached (the caller maps
    it to 503, not to the 404 "unknown qid / not a university" case).
    """
    entities = await get_entities(
        client,
        [qid],
        props=ENTITY_PROPS,
        languages=ENTITY_LANGUAGES,
        sitefilter=ENTITY_SITEFILTER,
        strict=True,
    )
    entity = entities.get(qid)
    if entity is None:
        log.info("wikidata entity %s not found", qid)
        return None
    if not is_university(entity):
        log.info("wikidata entity %s is not a university", qid)
        return None
    country_ids = country_candidates(entity)
    city_result, labels_result = await asyncio.gather(
        resolve_city_entity(client, entity),
        fetch_labels(client, country_ids),
        return_exceptions=True,
    )
    city_entity: dict[str, Any] | None = None
    if isinstance(city_result, BaseException):
        log.warning("city resolution for %s failed: %r", qid, city_result)
    else:
        city_entity = city_result
    labels: dict[str, str] = {}
    if isinstance(labels_result, BaseException):
        log.warning("country label fetch for %s failed: %r", qid, labels_result)
    else:
        labels = labels_result
    country_id = pick_country_id(entity, city_entity)
    city = place_from_entity(city_entity) if city_entity is not None else None
    country_label = labels.get(country_id) if country_id else None
    return build_resolved(entity, country_label=country_label, city=city)
