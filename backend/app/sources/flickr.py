"""Flickr source (SPEC Section 7.4) -- optional, only when ``FLICKR_API_KEY`` is configured.

Customer amendment: the key is optional and off by default. Without it the source is disabled
SILENTLY (no warning, nothing above debug level) -- geotagged photos then come from the keyless
Commons geosearch (``app.sources.commons.CommonsGeoSource``). With a key, this is the Section 7.4
implementation: geo search + text search near the campus, license names from
``flickr.photos.licenses.getInfo`` (cached on the source instance, hardcoded map as fallback).

No real Flickr response was available to record (no key in this environment); the parser is
tested on ``tests/fixtures/flickr_photos_search_sample.json``, a clearly labelled synthetic
sample of the documented ``flickr.photos.search`` JSON shape.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.enums import SourceType
from app.geo import haversine_m
from app.http import get_json
from app.models import Coordinates, DateKind, RawCandidate
from app.sources.base import (
    BaseSource,
    RequestBudget,
    SourceContext,
    SourceResult,
    apply_budget,
    build_candidate,
    dedupe_by_url,
)
from app.sources.commons import DATE_RE, EXCLUSION_RE, _valid_ymd

log = logging.getLogger("app.sources.flickr")

FLICKR_API = "https://www.flickr.com/services/rest/"
FLICKR_TIMEOUT_S = 8.0
SERVICE = "flickr"
SOURCE_LABEL = "Flickr"
GEO_RADIUS_KM = 1
GEO_PER_PAGE = 60
TEXT_RADIUS_KM = 5
TEXT_PER_PAGE = 40
MIN_TAKEN_DATE = "2008-01-01"
# The PDF clips the extras list after "descrip"; "description,tags" is the reconstruction because
# Section 7.4 parses description._content and tags.
EXTRAS = "date_taken,license,geo,url_m,url_z,url_l,owner_name,o_dims,description,tags"
DEFAULT_LICENSES: dict[int, str] = {
    0: "All Rights Reserved",
    1: "CC BY-NC-SA 2.0",
    2: "CC BY-NC 2.0",
    3: "CC BY-NC-ND 2.0",
    4: "CC BY 2.0",
    5: "CC BY-SA 2.0",
    6: "CC BY-ND 2.0",
    7: "No known copyright restrictions",
    8: "US Government Work",
    9: "CC0",
    10: "Public Domain Mark",
}
COMMON_PARAMS: dict[str, str] = {"format": "json", "nojsoncallback": "1"}
SEARCH_PARAMS: dict[str, str] = {
    "method": "flickr.photos.search",
    "has_geo": "1",
    "min_taken_date": MIN_TAKEN_DATE,
    "content_type": "1",
    "media": "photos",
    "safe_search": "1",
    "sort": "relevance",
    "page": "1",
    "extras": EXTRAS,
}


# ----------------------------------------------------------------------------- parameters


def geo_search_params(api_key: str, coords: Coordinates) -> dict[str, str]:
    """Section 7.4 (a)."""
    return {
        **SEARCH_PARAMS,
        "api_key": api_key,
        "lat": str(coords.lat),
        "lon": str(coords.lon),
        "radius": str(GEO_RADIUS_KM),
        "radius_units": "km",
        "per_page": str(GEO_PER_PAGE),
        **COMMON_PARAMS,
    }


def text_search_params(api_key: str, text: str, coords: Coordinates | None) -> dict[str, str]:
    """Section 7.4 (b): same as (a) plus ``text``, radius 5 km, 40 per page.

    Without campus coordinates the position parameters are simply omitted (Flickr then searches
    geotagged photos by text alone); ``has_geo`` and ``min_taken_date`` stay.
    """
    params = {
        **SEARCH_PARAMS,
        "api_key": api_key,
        "text": text,
        "per_page": str(TEXT_PER_PAGE),
        **COMMON_PARAMS,
    }
    if coords is not None:
        params.update(
            {
                "lat": str(coords.lat),
                "lon": str(coords.lon),
                "radius": str(TEXT_RADIUS_KM),
                "radius_units": "km",
            }
        )
    return params


# ----------------------------------------------------------------------------- parsing


def _text(value: Any) -> str | None:
    if isinstance(value, dict):  # {"_content": "..."} (description)
        value = value.get("_content")
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str | float):
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def _coordinate(value: Any) -> float | None:
    """Flickr sends latitude/longitude as strings; 0 / "0" / "" mean "no position"."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip() or "0")
        except ValueError:
            return None
    else:
        return None
    return None if number == 0.0 else number


def parse_taken_date(value: Any, *, unknown_flag: Any = None) -> tuple[str | None, DateKind]:
    """``datetaken`` "YYYY-MM-DD HH:MM:SS" -> date[:10] *taken*; anything else -> unknown.

    Flickr documents ``datetakenunknown=1`` as "datetaken is set to the upload date": such a
    date is kept but labelled *uploaded*, never *taken*.
    """
    if not isinstance(value, str):
        return None, "unknown"
    match = DATE_RE.match(value.strip())
    if not match or not _valid_ymd(*match.groups()):
        return None, "unknown"
    date = "-".join(match.groups())
    if str(unknown_flag) in ("1", "True", "true"):
        return date, "uploaded"
    return date, "taken"


def license_name(value: Any, license_names: dict[int, str]) -> str | None:
    license_id = _int_or_none(value)
    if license_id is None:
        return None
    return license_names.get(license_id) or DEFAULT_LICENSES.get(license_id)


def parse_flickr_photo(
    photo: dict[str, Any], *, campus: Coordinates | None, license_names: dict[int, str]
) -> RawCandidate | None:
    """Section 7.4 parsing + filters for one ``photos.photo[*]``; unknown keys are ignored."""
    photo_id, owner = photo.get("id"), photo.get("owner")
    if not isinstance(photo_id, str | int) or not isinstance(owner, str) or not owner:
        return None
    image_url = photo.get("url_z") or photo.get("url_m")
    if not isinstance(image_url, str) or not image_url:
        return None  # no usable URL
    if photo.get("url_z"):
        width, height = _int_or_none(photo.get("width_z")), _int_or_none(photo.get("height_z"))
    else:
        width, height = _int_or_none(photo.get("width_m")), _int_or_none(photo.get("height_m"))
    title = _text(photo.get("title"))
    description = _text(photo.get("description"))
    tags = _text(photo.get("tags"))
    for text in (title, tags, description):
        if text and EXCLUSION_RE.search(text):
            return None
    lat, lon = _coordinate(photo.get("latitude")), _coordinate(photo.get("longitude"))
    geo = Coordinates(lat=lat, lon=lon) if lat is not None and lon is not None else None
    distance_m = None
    if geo is not None and campus is not None:
        distance_m = round(haversine_m(campus.lat, campus.lon, geo.lat, geo.lon), 1)
    date, date_kind = parse_taken_date(
        photo.get("datetaken"), unknown_flag=photo.get("datetakenunknown")
    )
    return build_candidate(
        source_type=SourceType.flickr_geo,
        image_url=image_url,
        source_page_url=f"https://www.flickr.com/photos/{owner}/{photo_id}/",
        source_label=SOURCE_LABEL,
        title=title,
        description=description,
        alt=tags,
        author=_text(photo.get("ownername")),
        license=license_name(photo.get("license"), license_names),
        date=date,
        date_kind=date_kind,
        geo=geo,
        distance_m=distance_m,
        width=width,
        height=height,
    )


def parse_flickr_photos(
    data: Any, *, campus: Coordinates | None, license_names: dict[int, str] | None = None
) -> list[RawCandidate]:
    """Section 7.4 parsing of a ``flickr.photos.search`` response (``photos.photo[*]``)."""
    names = license_names if license_names is not None else DEFAULT_LICENSES
    if not isinstance(data, dict):
        return []
    photos = data.get("photos")
    if not isinstance(photos, dict):
        return []
    entries = photos.get("photo")
    if not isinstance(entries, list):
        return []
    candidates: list[RawCandidate] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        candidate = parse_flickr_photo(entry, campus=campus, license_names=names)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def parse_license_names(data: Any) -> dict[int, str]:
    """``licenses.license[*]`` -> {id: name}; empty when the shape is unexpected."""
    if not isinstance(data, dict):
        return {}
    licenses = data.get("licenses")
    if not isinstance(licenses, dict):
        return {}
    entries = licenses.get("license")
    if not isinstance(entries, list):
        return {}
    names: dict[int, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        license_id = _int_or_none(entry.get("id"))
        name = _text(entry.get("name"))
        if license_id is not None and name:
            names[license_id] = name
    return names


# ----------------------------------------------------------------------------- HTTP helpers


async def flickr_query(
    client: httpx.AsyncClient,
    params: dict[str, str],
    *,
    what: str,
    budget: RequestBudget | None = None,
) -> dict[str, Any] | None:
    """One Flickr REST call; ``None`` on failure (recorded) or when the deadline is near."""
    if budget is not None and not budget.can_start_request():
        budget.skip(what)
        return None
    try:
        data = await get_json(
            client, FLICKR_API, service=SERVICE, params=params, timeout=FLICKR_TIMEOUT_S
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
    if data.get("stat") == "fail":
        exc = ValueError(f"API error {data.get('code')}: {data.get('message')}")
        if budget is not None:
            budget.fail(what, exc)
        else:
            log.warning("%s failed: %s", what, exc)
        return None
    return data


async def load_license_names(
    client: httpx.AsyncClient, api_key: str, *, budget: RequestBudget | None = None
) -> dict[int, str]:
    """``flickr.photos.licenses.getInfo`` -> {id: name}; the hardcoded map when it fails."""
    params = {"method": "flickr.photos.licenses.getInfo", "api_key": api_key, **COMMON_PARAMS}
    data = await flickr_query(client, params, what="flickr licenses", budget=budget)
    names = parse_license_names(data)
    return names or dict(DEFAULT_LICENSES)


# ----------------------------------------------------------------------------- source


class FlickrSource(BaseSource):
    """Section 7.4 geo + text search. Silent no-op without ``FLICKR_API_KEY``."""

    name = "flickr"
    source_type = SourceType.flickr_geo

    def __init__(self) -> None:
        self._license_names: dict[int, str] | None = None

    async def license_names(
        self, client: httpx.AsyncClient, api_key: str, *, budget: RequestBudget | None = None
    ) -> dict[int, str]:
        if self._license_names is None:
            self._license_names = await load_license_names(client, api_key, budget=budget)
        return self._license_names

    async def fetch(self, ctx: SourceContext) -> SourceResult:
        if not ctx.settings.flickr_api_key:
            log.debug("flickr: no FLICKR_API_KEY, source disabled")
            return SourceResult(name=self.name, source_type=self.source_type)
        return await super().fetch(ctx)

    async def collect(self, ctx: SourceContext, result: SourceResult) -> None:
        api_key = ctx.settings.flickr_api_key
        if not api_key:
            return
        header = ctx.resolved.header
        campus = header.coords
        budget = ctx.budget()
        names = await self.license_names(ctx.http, api_key, budget=RequestBudget(ctx.deadline))
        calls: list[tuple[str, dict[str, str]]] = []
        if campus is not None:
            calls.append(("flickr geo search", geo_search_params(api_key, campus)))
        calls.append(("flickr text search", text_search_params(api_key, header.name, campus)))
        responses = await asyncio.gather(
            *(flickr_query(ctx.http, params, what=what, budget=budget) for what, params in calls),
            return_exceptions=True,
        )
        candidates: list[RawCandidate] = []
        for (what, _), data in zip(calls, responses, strict=True):
            if isinstance(data, BaseException):
                budget.fail(what, data)
                continue
            if data is None:
                continue
            candidates.extend(parse_flickr_photos(data, campus=campus, license_names=names))
        result.candidates.extend(dedupe_by_url(candidates))
        apply_budget(result, budget)
