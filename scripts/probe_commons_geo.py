"""Probe the REAL Wikimedia Commons geosearch ("Section 7.4A", keyless Flickr replacement).

What it probes (every call goes through app.http so the Wikimedia User-Agent policy is honoured):
  action=query&generator=geosearch&ggscoord={lat}|{lon}&ggsradius=1000&ggsnamespace=6&ggslimit=50
  &ggsprimary=all&prop=imageinfo|coordinates&<Section 7.3 prop block>&format=json
  for the MIT campus (42.359722, -71.091944) and Nazarbayev University (51.09, 71.399444),
  first exactly as amended (no colimit) and then with colimit=50 -- the coordinates prop has its
  own default limit of 10 per request, so without it only 10 of 50 pages carry coordinates.
  For each response it prints the number of pages, the top-level keys, the shape of
  page.coordinates (keys, distinct "primary" and "globe" values, how many entries per page,
  how many pages have no coordinates at all), the mime distribution, the first 8 files and the
  haversine distance from the campus for every page with coordinates.
  Finally it saves the unmodified colimit=50 responses (the request the source makes) into
  backend/tests/fixtures/ as commons_geosearch_mit.json and commons_geosearch_nu.json.

How to run:
  cd backend && python ../scripts/probe_commons_geo.py

No API key is needed. Every external failure is printed as a warning; the script never crashes.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.config import Settings
from app.geo import haversine_m
from app.http import create_client, get_json

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
FIXTURES_DIR = BACKEND_DIR / "tests" / "fixtures"
COMMONS_TIMEOUT_S = 8.0
PRINT_LIMIT = 8

# Section 7.3 common prop block (ObjectName reconstructs the clipped "Obj").
PROP_BLOCK: dict[str, str] = {
    "iiprop": "url|extmetadata|size|mime|timestamp",
    "iiurlwidth": "640",
    "iiextmetadatafilter": "DateTimeOriginal|LicenseShortName|Artist|ImageDescription|ObjectName",
}

TARGETS: list[tuple[str, str, float, float]] = [
    ("commons_geosearch_mit.json", "MIT", 42.359722, -71.091944),
    ("commons_geosearch_nu.json", "Nazarbayev University", 51.09, 71.399444),
]


def banner(text: str) -> None:
    print()
    print("=" * 100)
    print(text)
    print("=" * 100)


def describe_error(exc: BaseException) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return f"{type(exc).__name__}: {exc}"


def save_fixture(name: str, data: Any) -> None:
    """Write an unmodified API response as pretty-printed UTF-8 JSON (LF line endings)."""
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURES_DIR / name
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"  saved {path}")


async def geosearch(
    client: httpx.AsyncClient, lat: float, lon: float, *, colimit: str | None = None
) -> Any:
    """Section 7.4A call, parameters exactly as amended, plus colimit when given."""
    params: dict[str, str] = {
        "action": "query",
        "generator": "geosearch",
        "ggscoord": f"{lat}|{lon}",
        "ggsradius": "1000",
        "ggsnamespace": "6",
        "ggslimit": "50",
        "ggsprimary": "all",
        "prop": "imageinfo|coordinates",
        **PROP_BLOCK,
        "format": "json",
    }
    if colimit is not None:
        params["colimit"] = colimit
    return await get_json(
        client, COMMONS_API, service="commons", params=params, timeout=COMMONS_TIMEOUT_S
    )


def pages_of(response: dict[str, Any]) -> list[dict[str, Any]]:
    pages = response.get("query", {}).get("pages", {})
    if isinstance(pages, dict):
        return [p for p in pages.values() if isinstance(p, dict)]
    return [p for p in pages if isinstance(p, dict)]


def report(label: str, lat: float, lon: float, response: dict[str, Any]) -> None:
    pages = pages_of(response)
    print(f"[{label}] {len(pages)} pages; top-level keys: {sorted(response)}")
    if "continue" in response:
        print(f"  continue = {response['continue']!r}")
    coord_keys: Counter[str] = Counter()
    primary_values: Counter[str] = Counter()
    globe_values: Counter[str] = Counter()
    entries_per_page: Counter[int] = Counter()
    mimes: Counter[str] = Counter()
    without_coords = 0
    without_imageinfo = 0
    distances: list[float] = []
    for page in pages:
        coords = page.get("coordinates")
        if not isinstance(coords, list) or not coords:
            without_coords += 1
            entries_per_page[0] += 1
        else:
            entries_per_page[len(coords)] += 1
            for entry in coords:
                coord_keys.update(entry.keys())
                primary_values[repr(entry.get("primary", "<absent>"))] += 1
                globe_values[repr(entry.get("globe", "<absent>"))] += 1
            first = coords[0]
            if isinstance(first.get("lat"), int | float) and isinstance(
                first.get("lon"), int | float
            ):
                distances.append(haversine_m(lat, lon, first["lat"], first["lon"]))
        info = page.get("imageinfo")
        if not isinstance(info, list) or not info:
            without_imageinfo += 1
        else:
            mimes[str(info[0].get("mime"))] += 1
    print(f"  pages without coordinates: {without_coords}; without imageinfo: {without_imageinfo}")
    print(f"  coordinates entries per page: {dict(sorted(entries_per_page.items()))}")
    print(f"  coordinates keys (count over entries): {dict(coord_keys)}")
    print(f"  'primary' values: {dict(primary_values)}")
    print(f"  'globe' values: {dict(globe_values)}")
    print(f"  mime distribution: {dict(mimes)}")
    if distances:
        print(
            f"  distance_m from campus: min={min(distances):.0f} max={max(distances):.0f}"
            f" over {len(distances)} pages"
        )
    for index, page in enumerate(pages[:PRINT_LIMIT], start=1):
        info = (page.get("imageinfo") or [{}])[0]
        coords = page.get("coordinates") or [{}]
        print(
            f"  [{index}] {page.get('title')} (pageid={page.get('pageid')})"
            f" coords={coords[0]!r} mime={info.get('mime')} {info.get('width')}x{info.get('height')}"
        )


async def main() -> int:
    settings = Settings()
    async with create_client(settings) as client:
        banner("Section 7.4A as amended (no colimit): coordinates prop default limit applies")
        plain = await asyncio.gather(
            *(geosearch(client, lat, lon) for _, _, lat, lon in TARGETS), return_exceptions=True
        )
        for (_, label, lat, lon), result in zip(TARGETS, plain, strict=True):
            if isinstance(result, BaseException):
                print(f"  WARNING: {label} geosearch failed: {describe_error(result)}")
                continue
            report(label, lat, lon, result)
        banner("Section 7.4A + colimit=50 (what app.sources.commons.geosearch_files sends)")
        full = await asyncio.gather(
            *(geosearch(client, lat, lon, colimit="50") for _, _, lat, lon in TARGETS),
            return_exceptions=True,
        )
    for (filename, label, lat, lon), result in zip(TARGETS, full, strict=True):
        if isinstance(result, BaseException):
            print(f"  WARNING: {label} geosearch (colimit=50) failed: {describe_error(result)}")
            continue
        report(label, lat, lon, result)
        save_fixture(filename, result)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(asyncio.run(main()))
