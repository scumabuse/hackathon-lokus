"""Wikimedia Commons sources (SPEC Section 7.3 and the keyless geosearch amendment "7.4A").

Every call goes through ``app.http.get_json`` (Wikimedia User-Agent policy, retries, logging),
adds ``format=json`` and uses the 8 s Section 7.3 timeout. The async helpers never raise: a
failure is recorded in the ``RequestBudget`` and an empty result is returned; a helper is skipped
without an error when the deadline is closer than one second.

Real-response facts the parser relies on (see ``scripts/probe_commons.py`` output, Phase 2):
``query.pages`` is a pageid-keyed object; search results carry an ``index`` (rank) per page;
``thumburl`` for scaled files lives on thumb.wikimedia.org with tracking query parameters;
``DateTimeOriginal`` is free text and frequently HTML; ``Artist`` is often an ``<a>`` link;
``ImageDescription`` is HTML; categories mix in .ogg/.pdf/.svg/.tif; ``continue`` is
``{"gcmcontinue": ..., "continue": "gcmcontinue||"}`` for categories; geosearch pages carry
``coordinates: [{"lat", "lon", "primary": "", "globe": "earth"}]`` and only ten of them per
request unless ``colimit`` is raised (hence ``colimit=50`` next to ``ggslimit=50``).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from app.enums import Category, SourceType, WarningCode
from app.geo import haversine_m
from app.http import get_json
from app.models import Coordinates, DateKind, RawCandidate, Warning
from app.sources.base import (
    BaseSource,
    RequestBudget,
    SourceContext,
    SourceResult,
    apply_budget,
    build_candidate,
    dedupe_by_url,
)

log = logging.getLogger("app.sources.commons")

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
COMMONS_TIMEOUT_S = 8.0
SERVICE = "commons"
SOURCE_LABEL = "Wikimedia Commons"
COMMONS_FILE_PAGE = "https://commons.wikimedia.org/wiki/"

# Section 7.3 common prop block. The PDF clips the filter list after "Obj"; ObjectName is the
# reconstruction (the only Commons extmetadata key starting with "Obj", and the probe returned it).
PROP_BLOCK: dict[str, str] = {
    "prop": "imageinfo",
    "iiprop": "url|extmetadata|size|mime|timestamp",
    "iiurlwidth": "640",
    "iiextmetadatafilter": "DateTimeOriginal|LicenseShortName|Artist|ImageDescription|ObjectName",
}
ALLOWED_MIMES: frozenset[str] = frozenset({"image/jpeg", "image/png", "image/webp"})
MIN_WIDTH = 400
MIN_HEIGHT = 300
CATEGORY_LIMIT = 50
SUBCATEGORY_LIMIT = 50
SUBCATEGORY_FILE_LIMIT = 30
MAX_SUBCATEGORIES = 8
MIN_SUBCATEGORY_MATCHES = 3
SEARCH_LIMIT = 40
GEOSEARCH_RADIUS_M = 1000
GEOSEARCH_LIMIT = 50
FILE_NAMESPACE = "6"

# Section 7.3 filename exclusion. The PDF clips the regex after "\.t"; "\.tiff?$" is the
# reconstruction (TIFF is the only image type starting with "t" that Commons hosts).
EXCLUSION_RE = re.compile(
    r"logo|emblem|coat[_ ]of[_ ]arms|seal|crest|flag|\bmap\b|plan|scheme|diagram|chart|icon"
    r"|screenshot|poster|document|certificate|diploma|portrait|passport|table|graph"
    r"|\.svg$|\.pdf$|\.tiff?$",
    re.IGNORECASE,
)
SUBCAT_RE = re.compile(
    r"building|campus|librar|dormitor|hostel|residen|student|sport|stadium|laborator|facult"
    r"|interior|hall|auditorium|здани|кампус|общежит|библиотек",
    re.IGNORECASE,
)
# Section 7.3 (b) hint mapping, checked in this order (a title can match several).
SUBCAT_HINTS: tuple[tuple[re.Pattern[str], Category], ...] = (
    (re.compile(r"librar", re.IGNORECASE), Category.library),
    (re.compile(r"dormitor|hostel|residen", re.IGNORECASE), Category.dormitory),
    (re.compile(r"sport|stadium", re.IGNORECASE), Category.sport),
    (re.compile(r"laborator", re.IGNORECASE), Category.lab),
    (re.compile(r"student", re.IGNORECASE), Category.student_life),
)
DATE_RE = re.compile(r"^(\d{4})[-:/](\d{2})[-:/](\d{2})")
TIMESTAMP_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


# ----------------------------------------------------------------------------- parsing helpers


def strip_html(value: object) -> str | None:
    """HTML -> text (BeautifulSoup/lxml), whitespace collapsed; ``None`` when empty."""
    if not isinstance(value, str):
        return None
    text = value
    if "<" in text or "&" in text:
        text = BeautifulSoup(text, "lxml").get_text(" ", strip=True)
    text = " ".join(text.split())
    return text or None


def _valid_ymd(year: str, month: str, day: str) -> bool:
    return 1 <= int(month) <= 12 and 1 <= int(day) <= 31 and int(year) > 0


def parse_date(date_time_original: object, timestamp: object) -> tuple[str | None, DateKind]:
    """Section 7.3 date rule: regex on the HTML-stripped DateTimeOriginal, else upload timestamp.

    Only ``^(\\d{4})[-:/](\\d{2})[-:/](\\d{2})`` may produce a *taken* date; any other free-text
    value ("1969", "circa 1890-1900", "Taken on 25 April 1918", "11 March 2018 (Exif)") falls back
    to the upload ``timestamp[:10]`` labelled *uploaded*. Nothing is ever guessed.
    """
    text = strip_html(date_time_original)
    if text:
        match = DATE_RE.match(text)
        if match and _valid_ymd(*match.groups()):
            return "-".join(match.groups()), "taken"
    if isinstance(timestamp, str):
        match = TIMESTAMP_RE.match(timestamp)
        if match and _valid_ymd(*match.groups()):
            return "-".join(match.groups()), "uploaded"
    return None, "unknown"


def _ext_value(extmetadata: Any, key: str) -> str | None:
    if not isinstance(extmetadata, dict):
        return None
    entry = extmetadata.get(key)
    if isinstance(entry, dict):
        value = entry.get("value")
        return value if isinstance(value, str) else None
    return None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float | str):
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def page_coordinates(page: dict[str, Any]) -> Coordinates | None:
    """Section 7.4A: ``page.coordinates[0]``, preferring the primary entry, Earth only."""
    entries = page.get("coordinates")
    if not isinstance(entries, list):
        return None
    usable = [
        e
        for e in entries
        if isinstance(e, dict)
        and _number(e.get("lat")) is not None
        and _number(e.get("lon")) is not None
        and e.get("globe", "earth") == "earth"
    ]
    if not usable:
        return None
    # format=json renders the boolean "primary" flag as ""; formatversion=2 would send true.
    primary = [e for e in usable if e.get("primary") in ("", True)]
    chosen = primary[0] if primary else usable[0]
    lat, lon = _number(chosen["lat"]), _number(chosen["lon"])
    if lat is None or lon is None or not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return Coordinates(lat=lat, lon=lon)


def distance_to(campus: Coordinates | None, geo: Coordinates | None) -> float | None:
    if campus is None or geo is None:
        return None
    return round(haversine_m(campus.lat, campus.lon, geo.lat, geo.lon), 1)


def commons_pages(data: Any) -> list[dict[str, Any]]:
    """``query.pages`` as a list in API order (search results are ordered by their ``index``)."""
    if not isinstance(data, dict):
        return []
    query = data.get("query")
    if not isinstance(query, dict):
        return []
    raw = query.get("pages")
    if isinstance(raw, dict):
        pages = [p for p in raw.values() if isinstance(p, dict)]
    elif isinstance(raw, list):
        pages = [p for p in raw if isinstance(p, dict)]
    else:
        return []
    if pages and all(isinstance(p.get("index"), int) for p in pages):
        pages.sort(key=lambda p: p["index"])
    return pages


def parse_commons_page(
    page: dict[str, Any],
    *,
    source_type: SourceType,
    source_hint: Category | None = None,
    campus: Coordinates | None = None,
    size_filter: bool = True,
    name_filter: bool = True,
) -> RawCandidate | None:
    """Section 7.3 parsing + filters for one ``query.pages[*]`` entry; ``None`` when filtered."""
    if "missing" in page or "invalid" in page:
        return None
    title = page.get("title")
    if not isinstance(title, str) or not title:
        return None
    filename = title.removeprefix("File:")
    infos = page.get("imageinfo")
    if not isinstance(infos, list) or not infos or not isinstance(infos[0], dict):
        return None
    info = infos[0]
    mime = info.get("mime")
    if mime not in ALLOWED_MIMES:
        return None
    width, height = _int_or_none(info.get("width")), _int_or_none(info.get("height"))
    if size_filter and (
        width is None or height is None or width < MIN_WIDTH or height < MIN_HEIGHT
    ):
        return None
    if name_filter and EXCLUSION_RE.search(filename):
        return None
    ext = info.get("extmetadata")
    date, date_kind = parse_date(_ext_value(ext, "DateTimeOriginal"), info.get("timestamp"))
    description = strip_html(_ext_value(ext, "ImageDescription"))
    caption = description if description is not None else strip_html(_ext_value(ext, "ObjectName"))
    geo = page_coordinates(page)
    return build_candidate(
        source_type=source_type,
        image_url=info.get("thumburl") or info.get("url"),
        source_page_url=info.get("descriptionurl") or COMMONS_FILE_PAGE + quote(title),
        source_label=SOURCE_LABEL,
        title=caption,
        author=strip_html(_ext_value(ext, "Artist")),
        license=strip_html(_ext_value(ext, "LicenseShortName")),
        date=date,
        date_kind=date_kind,
        geo=geo,
        distance_m=distance_to(campus, geo),
        page_title=title,
        filename=filename,
        width=width,
        height=height,
        source_hint_category=source_hint,
    )


def parse_commons_pages(
    data: Any,
    *,
    source_type: SourceType,
    source_hint: Category | None = None,
    campus: Coordinates | None = None,
) -> list[RawCandidate]:
    """Section 7.3 parsing + all pre-download filters over ``query.pages``."""
    candidates: list[RawCandidate] = []
    for page in commons_pages(data):
        candidate = parse_commons_page(
            page, source_type=source_type, source_hint=source_hint, campus=campus
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def subcategory_hint(title: str) -> Category | None:
    """Section 7.3 (b) hint for a subcategory title (``None`` when no hint word matches)."""
    name = title.removeprefix("Category:")
    for pattern, category in SUBCAT_HINTS:
        if pattern.search(name):
            return category
    return None


def choose_subcategories(titles: list[str]) -> list[tuple[str, Category | None]]:
    """Section 7.3 (b): up to 8 titles matching SUBCAT_RE; if fewer than 3 match, fill to 8 in
    API order (the matching ones stay first). Each title comes with its hint."""
    clean = [t for t in titles if isinstance(t, str) and t.strip()]
    matching = [t for t in clean if SUBCAT_RE.search(t.removeprefix("Category:"))]
    chosen = matching[:MAX_SUBCATEGORIES]
    if len(matching) < MIN_SUBCATEGORY_MATCHES:
        for title in clean:
            if len(chosen) >= MAX_SUBCATEGORIES:
                break
            if title not in chosen:
                chosen.append(title)
    return [(title, subcategory_hint(title)) for title in chosen]


def _category_title(category: str) -> str:
    name = category.strip()
    return name if name.startswith("Category:") else f"Category:{name}"


def continuation_params(data: Any) -> dict[str, str] | None:
    """The verbatim ``continue`` object of a category page when it carries ``gcmcontinue``."""
    if not isinstance(data, dict):
        return None
    cont = data.get("continue")
    if not isinstance(cont, dict) or not isinstance(cont.get("gcmcontinue"), str):
        return None
    return {k: str(v) for k, v in cont.items()}


# ----------------------------------------------------------------------------- HTTP helpers


async def commons_query(
    client: httpx.AsyncClient,
    params: dict[str, Any],
    *,
    what: str,
    budget: RequestBudget | None = None,
) -> dict[str, Any] | None:
    """One Commons action-API call; ``None`` on failure (recorded) or when the deadline is near."""
    if budget is not None and not budget.can_start_request():
        budget.skip(what)
        return None
    query = {**params, "format": "json"}
    try:
        data = await get_json(
            client, COMMONS_API, service=SERVICE, params=query, timeout=COMMONS_TIMEOUT_S
        )
    except (httpx.HTTPError, ValueError) as exc:
        if budget is not None:
            budget.fail(what, exc)
        else:
            log.warning("%s failed: %s", what, exc)
        return None
    if not isinstance(data, dict):
        if budget is not None:
            budget.fail(what, ValueError("response is not a JSON object"))
        return None
    error = data.get("error")
    if isinstance(error, dict):
        exc = ValueError(f"API error {error.get('code')}: {error.get('info')}")
        if budget is not None:
            budget.fail(what, exc)
        else:
            log.warning("%s failed: %s", what, exc)
        return None
    return data


async def fetch_category_files(
    client: httpx.AsyncClient,
    category: str,
    *,
    limit: int = CATEGORY_LIMIT,
    follow_continue_once: bool = False,
    source_type: SourceType = SourceType.commons_category,
    hint: Category | None = None,
    campus: Coordinates | None = None,
    budget: RequestBudget | None = None,
) -> list[RawCandidate]:
    """Section 7.3 (a): category files, ``continue.gcmcontinue`` followed at most once."""
    title = _category_title(category)
    params: dict[str, Any] = {
        "action": "query",
        "generator": "categorymembers",
        "gcmtitle": title,
        "gcmtype": "file",
        "gcmlimit": str(limit),
        **PROP_BLOCK,
    }
    data = await commons_query(client, params, what=f"commons category {title!r}", budget=budget)
    if data is None:
        return []
    candidates = parse_commons_pages(data, source_type=source_type, source_hint=hint, campus=campus)
    continuation = continuation_params(data)
    if follow_continue_once and continuation:
        page2 = await commons_query(
            client,
            {**params, **continuation},
            what=f"commons category {title!r} (continuation)",
            budget=budget,
        )
        if page2 is not None:
            candidates.extend(
                parse_commons_pages(page2, source_type=source_type, source_hint=hint, campus=campus)
            )
    return dedupe_by_url(candidates)


async def fetch_subcategories(
    client: httpx.AsyncClient, category: str, *, budget: RequestBudget | None = None
) -> list[str]:
    """Section 7.3 (b): subcategory titles ("Category:...") in API order."""
    title = _category_title(category)
    params: dict[str, Any] = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": title,
        "cmtype": "subcat",
        "cmlimit": str(SUBCATEGORY_LIMIT),
    }
    data = await commons_query(
        client, params, what=f"commons subcategories of {title!r}", budget=budget
    )
    if data is None:
        return []
    members = data.get("query", {}).get("categorymembers") if isinstance(data, dict) else None
    if not isinstance(members, list):
        return []
    return [
        m["title"]
        for m in members
        if isinstance(m, dict) and isinstance(m.get("title"), str) and m["title"]
    ]


async def search_files(
    client: httpx.AsyncClient,
    name: str,
    *,
    source_type: SourceType = SourceType.commons_search,
    campus: Coordinates | None = None,
    budget: RequestBudget | None = None,
) -> list[RawCandidate]:
    """Section 7.3 (c): full-text search in the File namespace."""
    params: dict[str, Any] = {
        "action": "query",
        "generator": "search",
        "gsrsearch": name,
        "gsrnamespace": FILE_NAMESPACE,
        "gsrlimit": str(SEARCH_LIMIT),
        **PROP_BLOCK,
    }
    data = await commons_query(client, params, what=f"commons search {name!r}", budget=budget)
    if data is None:
        return []
    return dedupe_by_url(parse_commons_pages(data, source_type=source_type, campus=campus))


async def fetch_file_page(
    client: httpx.AsyncClient, filename: str, *, budget: RequestBudget | None = None
) -> dict[str, Any] | None:
    """Section 7.3 (d): the single ``query.pages[*]`` entry for ``File:{filename}``."""
    name = filename.removeprefix("File:")
    params: dict[str, Any] = {"action": "query", "titles": f"File:{name}", **PROP_BLOCK}
    data = await commons_query(client, params, what=f"commons file {name!r}", budget=budget)
    if data is None:
        return None
    pages = commons_pages(data)
    return pages[0] if pages else None


async def fetch_single_file(
    client: httpx.AsyncClient,
    filename: str,
    *,
    source_type: SourceType,
    campus: Coordinates | None = None,
    budget: RequestBudget | None = None,
) -> RawCandidate | None:
    """Section 7.3 (d) as a candidate. Only the mime filter applies: a file named explicitly
    (the Wikidata P18 main image) must not be lost to the size or filename heuristics."""
    page = await fetch_file_page(client, filename, budget=budget)
    if page is None:
        return None
    return parse_commons_page(
        page, source_type=source_type, campus=campus, size_filter=False, name_filter=False
    )


async def fetch_file_info(
    client: httpx.AsyncClient, filename: str, *, budget: RequestBudget | None = None
) -> dict[str, Any] | None:
    """Raw ``imageinfo[0]`` (thumburl/url/mime/...) of a file, e.g. the P154 logo the pipeline
    downloads for hash exclusion. No filters."""
    page = await fetch_file_page(client, filename, budget=budget)
    if page is None:
        return None
    infos = page.get("imageinfo")
    if isinstance(infos, list) and infos and isinstance(infos[0], dict):
        return infos[0]
    return None


def geosearch_params(coords: Coordinates) -> dict[str, Any]:
    """Section 7.4A parameters (+ ``colimit`` so every page gets its coordinates)."""
    return {
        "action": "query",
        "generator": "geosearch",
        "ggscoord": f"{coords.lat}|{coords.lon}",
        "ggsradius": str(GEOSEARCH_RADIUS_M),
        "ggsnamespace": FILE_NAMESPACE,
        "ggslimit": str(GEOSEARCH_LIMIT),
        "ggsprimary": "all",
        **PROP_BLOCK,
        "prop": "imageinfo|coordinates",
        "colimit": str(GEOSEARCH_LIMIT),
    }


async def geosearch_files(
    client: httpx.AsyncClient,
    coords: Coordinates,
    *,
    source_type: SourceType = SourceType.commons_geo,
    budget: RequestBudget | None = None,
) -> list[RawCandidate]:
    """Section 7.4A: files geotagged within 1 km of the campus, with ``geo`` and ``distance_m``."""
    data = await commons_query(
        client,
        geosearch_params(coords),
        what=f"commons geosearch {coords.lat}|{coords.lon}",
        budget=budget,
    )
    if data is None:
        return []
    return dedupe_by_url(parse_commons_pages(data, source_type=source_type, campus=coords))


# ----------------------------------------------------------------------------- sources


class WikidataP18Source(BaseSource):
    """The Wikidata main image (P18) as the highest-priority candidate."""

    name = "wikidata_p18"
    source_type = SourceType.wikidata_p18

    async def collect(self, ctx: SourceContext, result: SourceResult) -> None:
        filename = ctx.resolved.main_image_filename
        if not filename:
            return
        budget = ctx.budget()
        candidate = await fetch_single_file(
            ctx.http,
            filename,
            source_type=self.source_type,
            campus=ctx.resolved.header.coords,
            budget=budget,
        )
        if candidate is not None:
            result.candidates.append(candidate)
        apply_budget(result, budget)


class CommonsCategorySource(BaseSource):
    """Section 7.3 (a) + (b): the P373 category, its continuation and chosen subcategories."""

    name = "commons_category"
    source_type = SourceType.commons_category

    async def collect(self, ctx: SourceContext, result: SourceResult) -> None:
        category = ctx.resolved.header.commons_category
        if not category:
            result.warnings.append(Warning(code=WarningCode.no_commons_category))
            return
        budget = ctx.budget()
        campus = ctx.resolved.header.coords
        main_files, subcat_titles = await asyncio.gather(
            fetch_category_files(
                ctx.http,
                category,
                limit=CATEGORY_LIMIT,
                follow_continue_once=True,
                source_type=self.source_type,
                campus=campus,
                budget=budget,
            ),
            fetch_subcategories(ctx.http, category, budget=budget),
        )
        candidates = list(main_files)
        chosen = choose_subcategories(subcat_titles)
        if chosen:
            batches = await asyncio.gather(
                *(
                    fetch_category_files(
                        ctx.http,
                        title,
                        limit=SUBCATEGORY_FILE_LIMIT,
                        source_type=self.source_type,
                        hint=hint,
                        campus=campus,
                        budget=budget,
                    )
                    for title, hint in chosen
                ),
                return_exceptions=True,
            )
            for (title, _), batch in zip(chosen, batches, strict=True):
                if isinstance(batch, BaseException):
                    budget.fail(f"commons subcategory {title!r}", batch)
                    continue
                candidates.extend(batch)
        result.candidates.extend(dedupe_by_url(candidates))
        apply_budget(result, budget)


class CommonsSearchSource(BaseSource):
    """Section 7.3 (c): full-text search for the English label and the local name."""

    name = "commons_search"
    source_type = SourceType.commons_search

    async def collect(self, ctx: SourceContext, result: SourceResult) -> None:
        header = ctx.resolved.header
        names: list[str] = []
        for name in (header.name, header.local_name):
            if (
                name
                and name.strip()
                and name.strip().casefold() not in {n.casefold() for n in names}
            ):
                names.append(name.strip())
        if not names:
            return
        budget = ctx.budget()
        batches = await asyncio.gather(
            *(
                search_files(
                    ctx.http,
                    name,
                    source_type=self.source_type,
                    campus=header.coords,
                    budget=budget,
                )
                for name in names[:2]
            ),
            return_exceptions=True,
        )
        candidates: list[RawCandidate] = []
        for name, batch in zip(names[:2], batches, strict=True):
            if isinstance(batch, BaseException):
                budget.fail(f"commons search {name!r}", batch)
                continue
            candidates.extend(batch)
        result.candidates.extend(dedupe_by_url(candidates))
        apply_budget(result, budget)


class CommonsGeoSource(BaseSource):
    """Section 7.4A: geotagged Commons files around the campus (keyless Flickr replacement)."""

    name = "commons_geo"
    source_type = SourceType.commons_geo

    async def collect(self, ctx: SourceContext, result: SourceResult) -> None:
        coords = ctx.resolved.header.coords
        if coords is None:
            return  # the pipeline emits no_coordinates itself
        budget = ctx.budget()
        result.candidates.extend(
            await geosearch_files(ctx.http, coords, source_type=self.source_type, budget=budget)
        )
        apply_budget(result, budget)


class CityCommonsSource(BaseSource):
    """Section 7.3(e): city Commons category images (source_type=city_commons)."""

    name = "city_commons"
    source_type = SourceType.city_commons

    async def collect(self, ctx: SourceContext, result: SourceResult) -> None:
        city = ctx.resolved.header.city
        if city is None or not city.commons_category:
            return
        budget = ctx.budget()
        candidates = await fetch_category_files(
            ctx.http,
            city.commons_category,
            limit=30,
            follow_continue_once=False,
            source_type=self.source_type,
            campus=ctx.resolved.header.coords,
            budget=budget,
        )
        result.candidates.extend(candidates)
        apply_budget(result, budget)
