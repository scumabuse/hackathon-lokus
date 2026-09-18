"""Probe the REAL Wikimedia Commons API exactly as SPEC Section 7.3 describes it and save fixtures.

What it probes (every call goes through app.http so the Wikimedia User-Agent policy is honoured):
  (a) category files  -- generator=categorymembers&gcmtype=file&gcmlimit=50 + the common prop block
      for the MIT and Nazarbayev University P373 categories; the MIT continuation is followed once
      and the continuation shape (continue.gcmcontinue / continue.continue) is reported;
  (b) subcategories   -- list=categorymembers&cmtype=subcat&cmlimit=50 for both, with the
      Section 7.3 (b) title regex and the source_hint_category mapping; (a) is then run with
      gcmlimit=30 on two chosen MIT subcategories;
  (c) search          -- generator=search&gsrnamespace=6&gsrlimit=40 for the English labels and the
      NU local name;
  (d) single file     -- titles=File:{P18} and titles=File:{P154} (the logo is an SVG);
  (e) city category   -- (a) with gcmlimit=30 on the city P373 ("Cambridge, Massachusetts" and
      the P373 of Astana Q1520, fetched live from Wikidata).
  For every response it prints the first 8 files (title, descriptionurl, thumburl, url, width,
  height, mime, timestamp, extmetadata keys, raw DateTimeOriginal / LicenseShortName / Artist /
  ImageDescription), every anomaly (no imageinfo, no thumburl, mime outside jpeg/png/webp,
  missing width/height), every distinct DateTimeOriginal shape against the spec regex, the
  Section 7.3 exclusion regex against every filename seen (with in-word false positives), and a
  download test against upload.wikimedia.org (12 thumbnails at concurrency 8 and 16, Pillow
  decode + imagehash.phash of three, phash distance between two sizes of the same file).
  Finally it saves unmodified responses (pretty-printed, UTF-8) into backend/tests/fixtures/ and
  three small real thumbnails (<= 60 KB) into backend/tests/fixtures/images/ with SOURCES.txt.

How to run:
  cd backend && python ../scripts/probe_commons.py

No API key is needed. Every external failure is printed as a warning; the script never crashes.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from collections import Counter
from collections.abc import Awaitable
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, TypeVar

import httpx
import imagehash
from bs4 import BeautifulSoup
from PIL import Image, ImageOps

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.config import Settings
from app.http import create_client, get_json
from app.resolver.wikidata import string_value

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
FIXTURES_DIR = BACKEND_DIR / "tests" / "fixtures"
IMAGES_DIR = FIXTURES_DIR / "images"
COMMONS_TIMEOUT_S = 8.0  # Section 7.3: "timeout 8 s"
WIKIDATA_TIMEOUT_S = 5.0  # Section 7.1
DOWNLOAD_TIMEOUT_S = 6.0  # Section 8: "Per image: timeout 6 s"
MAX_DOWNLOAD_BYTES = 4 * 1024 * 1024  # Section 8: "> 4 MB" abort
MAX_FIXTURE_IMAGE_BYTES = 60 * 1024
FIXTURE_IMAGE_COUNT = 3
DOWNLOAD_SAMPLE = 12
PRINT_LIMIT = 8
Image.MAX_IMAGE_PIXELS = 40_000_000  # Section 8

# Section 7.3 common prop block. The spec text is clipped after "Obj"; "ObjectName" is the
# reconstruction (the only Commons extmetadata key starting with "Obj").
PROP_BLOCK: dict[str, str] = {
    "prop": "imageinfo",
    "iiprop": "url|extmetadata|size|mime|timestamp",
    "iiurlwidth": "640",
    "iiextmetadatafilter": "DateTimeOriginal|LicenseShortName|Artist|ImageDescription|ObjectName",
}
REQUESTED_EXT_KEYS = (
    "DateTimeOriginal",
    "LicenseShortName",
    "Artist",
    "ImageDescription",
    "ObjectName",
)
ALLOWED_MIMES = frozenset({"image/jpeg", "image/png", "image/webp"})

# Known Wikidata facts (Phase 1 probe).
MIT_NAME = "Massachusetts Institute of Technology"
MIT_CATEGORY = "Massachusetts Institute of Technology"  # P373 of Q49108
MIT_P18 = "MIT Dome night1 Edit.jpg"
MIT_P154 = "MIT 2023 red logo.svg"
CAMBRIDGE_CATEGORY = "Cambridge, Massachusetts"  # P373 of Cambridge
NU_NAME = "Nazarbayev University"
NU_CATEGORY = "Nazarbayev University"  # P373 of Q2783344
NU_LOCAL_NAME = "Назарбаев Университет"
ASTANA_QID = "Q1520"

# Section 7.3 (b), verbatim, case-insensitive.
SUBCAT_RE = re.compile(
    r"building|campus|librar|dormitor|hostel|residen|student|sport|stadium|laborator|facult"
    r"|interior|hall|auditorium|здани|кампус|общежит|библиотек",
    re.IGNORECASE,
)
HINT_RULES: tuple[tuple[str, str], ...] = (
    ("librar", "library"),
    ("dormitor|hostel|residen", "dormitory"),
    ("sport|stadium", "sport"),
    ("laborator", "lab"),
    ("student", "student_life"),
)
# Section 7.3 exclusion regex, verbatim except the clipped tail: "\.t" -> "\.tiff?$".
EXCLUDE_RE = re.compile(
    r"logo|emblem|coat[_ ]of[_ ]arms|seal|crest|flag|\bmap\b|plan|scheme|diagram|chart|icon"
    r"|screenshot|poster|document|certificate|diploma|portrait|passport|table|graph"
    r"|\.svg$|\.pdf$|\.tiff?$",
    re.IGNORECASE,
)
# Section 7.3 DateTimeOriginal regex.
DATE_RE = re.compile(r"^(\d{4})[-:/](\d{2})[-:/](\d{2})")

T = TypeVar("T")


# ----------------------------------------------------------------------------- helpers
def banner(text: str) -> None:
    print()
    print("=" * 100)
    print(text)
    print("=" * 100)


def clip(value: Any, limit: int = 160) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


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


def strip_html(html: str) -> str:
    return BeautifulSoup(html, "lxml").get_text(" ", strip=True)


def date_shape(value: str) -> str:
    """Digits -> 'd', letters -> 'a', keeps punctuation: a fingerprint of a date string."""
    shape = re.sub(r"\d", "d", value)
    shape = re.sub(r"[^\W\d_]+", "a", shape)
    return shape if len(shape) <= 60 else shape[:57] + "..."


async def run_step(name: str, coro: Awaitable[T]) -> T | None:
    """Run one probe step; any failure becomes a warning (the script never crashes)."""
    result = (await asyncio.gather(coro, return_exceptions=True))[0]
    if isinstance(result, BaseException):
        print(f"\nWARNING: step {name!r} failed: {describe_error(result)}")
        return None
    return result


# ----------------------------------------------------------------------------- data model
@dataclass
class FileFacts:
    """What Section 7.3 parsing reads from one query.pages[*] entry."""

    title: str
    pageid: Any
    has_imageinfo: bool
    descriptionurl: str | None = None
    thumburl: str | None = None
    thumbwidth: int | None = None
    thumbheight: int | None = None
    thumbmime: str | None = None
    url: str | None = None
    width: int | None = None
    height: int | None = None
    size: int | None = None
    mime: str | None = None
    timestamp: str | None = None
    ext_keys: list[str] = field(default_factory=list)
    date_time_original: str | None = None
    license_short_name: str | None = None
    artist: str | None = None
    image_description: str | None = None
    object_name: str | None = None
    extra_page_keys: list[str] = field(default_factory=list)

    @property
    def filename(self) -> str:
        return self.title.removeprefix("File:")


@dataclass
class Report:
    """Cross-response observations collected while parsing."""

    ext_key_counts: Counter[str] = field(default_factory=Counter)
    files_seen: int = 0
    date_values: dict[str, str] = field(default_factory=dict)  # raw value -> example title
    artist_samples: list[tuple[str, str]] = field(default_factory=list)
    description_samples: list[tuple[str, str]] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)
    filenames: dict[str, str] = field(default_factory=dict)  # filename -> response label
    responses: dict[str, Any] = field(default_factory=dict)  # label -> raw response
    facts: dict[str, list[FileFacts]] = field(default_factory=dict)  # label -> parsed files


def parse_page(page: dict[str, Any]) -> FileFacts:
    infos = page.get("imageinfo")
    facts = FileFacts(
        title=str(page.get("title")),
        pageid=page.get("pageid"),
        has_imageinfo=isinstance(infos, list) and len(infos) > 0,
    )
    known = {"pageid", "ns", "title", "imageinfo", "imagerepository", "index"}
    facts.extra_page_keys = sorted(k for k in page if k not in known)
    if not facts.has_imageinfo:
        return facts
    info = infos[0]
    facts.descriptionurl = info.get("descriptionurl")
    facts.thumburl = info.get("thumburl")
    facts.thumbwidth = info.get("thumbwidth")
    facts.thumbheight = info.get("thumbheight")
    facts.thumbmime = info.get("thumbmime")
    facts.url = info.get("url")
    facts.width = info.get("width")
    facts.height = info.get("height")
    facts.size = info.get("size")
    facts.mime = info.get("mime")
    facts.timestamp = info.get("timestamp")
    ext = info.get("extmetadata") or {}
    facts.ext_keys = list(ext)
    facts.date_time_original = _ext_value(ext, "DateTimeOriginal")
    facts.license_short_name = _ext_value(ext, "LicenseShortName")
    facts.artist = _ext_value(ext, "Artist")
    facts.image_description = _ext_value(ext, "ImageDescription")
    facts.object_name = _ext_value(ext, "ObjectName")
    return facts


def _ext_value(ext: dict[str, Any], key: str) -> str | None:
    entry = ext.get(key)
    if isinstance(entry, dict) and "value" in entry:
        return str(entry["value"])
    return None


def pages_of(response: dict[str, Any]) -> list[dict[str, Any]]:
    pages = response.get("query", {}).get("pages", {})
    if isinstance(pages, dict):
        items = list(pages.values())
    elif isinstance(pages, list):
        items = pages
    else:
        items = []
    # generator=search adds "index" (search rank); keep API order otherwise.
    return sorted(items, key=lambda p: p.get("index", 0))


def record(report: Report, label: str, response: dict[str, Any]) -> list[FileFacts]:
    """Parse every page of a response, print the first 8, collect cross-response observations."""
    report.responses[label] = response
    pages = pages_of(response)
    facts_list = [parse_page(p) for p in pages]
    report.facts[label] = facts_list
    top_keys = sorted(k for k in response if k != "query")
    print(f"\n[{label}] {len(pages)} pages; top-level keys besides query: {top_keys}")
    if "continue" in response:
        print(f"  continue = {response['continue']!r}")
    if "warnings" in response:
        print(f"  warnings = {clip(response['warnings'], 300)}")
    for index, facts in enumerate(facts_list, 1):
        report.files_seen += 1
        report.filenames.setdefault(facts.filename, label)
        _collect(report, label, facts)
        if index <= PRINT_LIMIT:
            print_facts(index, facts)
    hidden = len(facts_list) - PRINT_LIMIT
    if hidden > 0:
        print(f"  ... {hidden} more files not printed")
    return facts_list


def _collect(report: Report, label: str, facts: FileFacts) -> None:
    where = f"{label}: {facts.title}"
    if not facts.has_imageinfo:
        report.anomalies.append(f"NO imageinfo -> {where} (page keys: {facts.extra_page_keys})")
        return
    report.ext_key_counts.update(facts.ext_keys)
    if facts.thumburl is None:
        report.anomalies.append(f"NO thumburl -> {where} (mime={facts.mime})")
    if facts.mime not in ALLOWED_MIMES:
        report.anomalies.append(f"mime {facts.mime} outside jpeg/png/webp -> {where}")
    if not facts.width or not facts.height:
        report.anomalies.append(f"width/height missing -> {where} ({facts.width}x{facts.height})")
    if facts.extra_page_keys:
        report.anomalies.append(f"extra page keys {facts.extra_page_keys} -> {where}")
    if facts.date_time_original is not None:
        report.date_values.setdefault(facts.date_time_original, facts.title)
    if facts.artist is not None and len(report.artist_samples) < 40:
        report.artist_samples.append((facts.title, facts.artist))
    if facts.image_description is not None and len(report.description_samples) < 40:
        report.description_samples.append((facts.title, facts.image_description))


def print_facts(index: int, facts: FileFacts) -> None:
    print(f"  [{index}] {facts.title} (pageid={facts.pageid})")
    if not facts.has_imageinfo:
        print(f"      !! no imageinfo; extra page keys: {facts.extra_page_keys}")
        return
    print(f"      descriptionurl={facts.descriptionurl}")
    print(
        f"      thumburl={facts.thumburl} ({facts.thumbwidth}x{facts.thumbheight},"
        f" thumbmime={facts.thumbmime})"
    )
    print(f"      url={facts.url}")
    print(
        f"      width={facts.width} height={facts.height} size={facts.size} mime={facts.mime}"
        f" timestamp={facts.timestamp}"
    )
    print(f"      extmetadata keys={facts.ext_keys}")
    print(f"      DateTimeOriginal={clip(facts.date_time_original)}")
    print(f"      LicenseShortName={clip(facts.license_short_name)}")
    print(f"      Artist={clip(facts.artist)}")
    print(f"      ImageDescription={clip(facts.image_description, 220)}")
    print(f"      ObjectName={clip(facts.object_name)}")


# ----------------------------------------------------------------------------- API calls
async def commons(client: httpx.AsyncClient, **params: str) -> Any:
    """One call to the Commons action API; always adds format=json (Section 7.3)."""
    query = {**params, "format": "json"}
    return await get_json(
        client, COMMONS_API, service="commons", params=query, timeout=COMMONS_TIMEOUT_S
    )


async def category_files(
    client: httpx.AsyncClient,
    category: str,
    limit: int,
    continuation: dict[str, str] | None = None,
) -> Any:
    """Section 7.3 (a). `continuation` is the previous response's `continue` object, verbatim."""
    params: dict[str, str] = {
        "action": "query",
        "generator": "categorymembers",
        "gcmtitle": f"Category:{category}",
        "gcmtype": "file",
        "gcmlimit": str(limit),
        **PROP_BLOCK,
    }
    if continuation:
        params.update(continuation)
    return await commons(client, **params)


async def subcategories(client: httpx.AsyncClient, category: str) -> Any:
    """Section 7.3 (b)."""
    return await commons(
        client,
        action="query",
        list="categorymembers",
        cmtitle=f"Category:{category}",
        cmtype="subcat",
        cmlimit="50",
    )


async def search_files(client: httpx.AsyncClient, name: str) -> Any:
    """Section 7.3 (c)."""
    return await commons(
        client,
        action="query",
        generator="search",
        gsrsearch=name,
        gsrnamespace="6",
        gsrlimit="40",
        **PROP_BLOCK,
    )


async def single_file(client: httpx.AsyncClient, filename: str) -> Any:
    """Section 7.3 (d)."""
    return await commons(client, action="query", titles=f"File:{filename}", **PROP_BLOCK)


async def astana_commons_category(client: httpx.AsyncClient) -> str | None:
    """P373 of Astana (Q1520) through the Section 7.1 entity fetch."""
    response = await get_json(
        client,
        WIKIDATA_API,
        service="wikidata",
        params={"action": "wbgetentities", "ids": ASTANA_QID, "props": "claims", "format": "json"},
        timeout=WIKIDATA_TIMEOUT_S,
    )
    entity = response.get("entities", {}).get(ASTANA_QID, {})
    return string_value(entity, "P373")


# ----------------------------------------------------------------------------- steps
async def step_categories(client: httpx.AsyncClient, report: Report) -> None:
    banner("STEP (a): category files (gcmlimit=50) for MIT and NU; MIT continuation followed once")
    mit, nu = await asyncio.gather(
        category_files(client, MIT_CATEGORY, 50),
        category_files(client, NU_CATEGORY, 50),
        return_exceptions=True,
    )
    if isinstance(mit, BaseException):
        print(f"  WARNING: MIT category failed: {describe_error(mit)}")
    else:
        first = record(report, "category_mit", mit)
        continuation = mit.get("continue")
        if not isinstance(continuation, dict):
            print("  MIT category: no continue object -> fewer than 50 files, nothing to follow")
        else:
            print(f"  following continuation once with params {continuation!r}")
            try:
                page2 = await category_files(client, MIT_CATEGORY, 50, continuation)
            except (httpx.HTTPError, ValueError) as exc:
                print(f"  WARNING: MIT continuation failed: {describe_error(exc)}")
            else:
                second = record(report, "category_mit_page2", page2)
                overlap = {f.title for f in first} & {f.title for f in second}
                print(
                    f"  MIT total files over two pages: {len(first) + len(second)}"
                    f" (overlap {len(overlap)}); page2 continue = {page2.get('continue')!r}"
                )
    if isinstance(nu, BaseException):
        print(f"  WARNING: NU category failed: {describe_error(nu)}")
    else:
        record(report, "category_nu", nu)


def hint_for(title: str) -> str | None:
    for pattern, hint in HINT_RULES:
        if re.search(pattern, title, re.IGNORECASE):
            return hint
    return None


def choose_subcategories(titles: list[str]) -> list[str]:
    """Section 7.3 (b): up to 8 regex matches; if fewer than 3 match, the first 8 in API order."""
    matches = [t for t in titles if SUBCAT_RE.search(t)]
    chosen = matches[:8] if len(matches) >= 3 else titles[:8]
    return chosen


async def step_subcategories(client: httpx.AsyncClient, report: Report) -> None:
    banner("STEP (b): subcategories (cmtype=subcat&cmlimit=50) for MIT and NU + regex + hints")
    responses = await asyncio.gather(
        subcategories(client, MIT_CATEGORY),
        subcategories(client, NU_CATEGORY),
        return_exceptions=True,
    )
    chosen_mit: list[str] = []
    for label, response in zip(("subcats_mit", "subcats_nu"), responses, strict=True):
        print(f"\n[{label}]")
        if isinstance(response, BaseException):
            print(f"  WARNING: {describe_error(response)}")
            continue
        report.responses[label] = response
        members = response.get("query", {}).get("categorymembers", [])
        titles = [str(m.get("title")) for m in members]
        top_keys = sorted(k for k in response if k != "query")
        print(f"  {len(titles)} subcategories; top-level keys besides query: {top_keys}")
        if members:
            print(f"  member keys: {sorted(members[0])}")
        for title in titles:
            match = SUBCAT_RE.search(title)
            hint = hint_for(title)
            flag = f"MATCH {match.group(0)!r}" if match else "-"
            print(f"    {title!s:<70} {flag:<22} hint={hint}")
        chosen = choose_subcategories(titles)
        matched = [t for t in titles if SUBCAT_RE.search(t)]
        print(f"  regex matches: {len(matched)} / {len(titles)}; chosen (spec rule): {chosen}")
        if label == "subcats_mit":
            chosen_mit = chosen
    if not chosen_mit:
        print("\n  no MIT subcategory to probe")
        return
    targets = chosen_mit[:2]
    print(f"\n  running (a) with gcmlimit=30 on {targets}")
    responses = await asyncio.gather(
        *(category_files(client, t.removeprefix("Category:"), 30) for t in targets),
        return_exceptions=True,
    )
    for index, (title, response) in enumerate(zip(targets, responses, strict=True), 1):
        if isinstance(response, BaseException):
            print(f"  WARNING: subcategory {title!r} failed: {describe_error(response)}")
            continue
        record(report, f"subcat_files_mit_{index} ({title})", response)
        if index == 1:
            report.responses["subcat_files_mit"] = response


async def step_search(client: httpx.AsyncClient, report: Report) -> None:
    banner("STEP (c): search (gsrnamespace=6&gsrlimit=40) for MIT, NU and the NU local name")
    queries = (("search_mit", MIT_NAME), ("search_nu", NU_NAME), ("search_nu_local", NU_LOCAL_NAME))
    responses = await asyncio.gather(
        *(search_files(client, name) for _, name in queries), return_exceptions=True
    )
    for (label, name), response in zip(queries, responses, strict=True):
        if isinstance(response, BaseException):
            print(f"\n[{label}] {name!r} WARNING: {describe_error(response)}")
            continue
        print(f"\n[{label}] gsrsearch={name!r}")
        record(report, label, response)


async def step_single_files(client: httpx.AsyncClient, report: Report) -> None:
    banner("STEP (d): single file (titles=File:...) for the MIT P18 photo and the P154 logo")
    responses = await asyncio.gather(
        single_file(client, MIT_P18), single_file(client, MIT_P154), return_exceptions=True
    )
    for label, response in zip(("file_mit_p18", "file_mit_logo"), responses, strict=True):
        if isinstance(response, BaseException):
            print(f"\n[{label}] WARNING: {describe_error(response)}")
            continue
        facts = record(report, label, response)
        for f in facts:
            thumb_is_png = bool(f.thumburl and f.thumburl.lower().endswith(".png"))
            print(
                f"  -> mime={f.mime} thumbmime={f.thumbmime} thumburl is PNG rendering: "
                f"{thumb_is_png}; excluded by regex: {bool(EXCLUDE_RE.search(f.filename))}"
            )


async def step_city(client: httpx.AsyncClient, report: Report) -> None:
    banner("STEP (e): city category (gcmlimit=30) for Cambridge, Massachusetts and Astana (P373)")
    try:
        astana_category = await astana_commons_category(client)
    except (httpx.HTTPError, ValueError) as exc:
        astana_category = None
        print(f"  WARNING: Astana P373 fetch failed: {describe_error(exc)}")
    print(f"  Astana (Q1520) P373 = {astana_category!r}")
    targets = [("category_cambridge", CAMBRIDGE_CATEGORY)]
    if astana_category:
        targets.append(("category_astana", astana_category))
    responses = await asyncio.gather(
        *(category_files(client, category, 30) for _, category in targets),
        return_exceptions=True,
    )
    for (label, category), response in zip(targets, responses, strict=True):
        if isinstance(response, BaseException):
            print(f"\n[{label}] {category!r} WARNING: {describe_error(response)}")
            continue
        record(report, label, response)


def step_observations(report: Report) -> None:
    banner("OBSERVATIONS: prop block keys, anomalies, date formats, artist/description shapes")
    print(f"\nfiles parsed: {report.files_seen}")
    print("extmetadata keys returned (count of files carrying each):")
    for key, count in report.ext_key_counts.most_common():
        requested = "requested" if key in REQUESTED_EXT_KEYS else "NOT REQUESTED"
        print(f"  {key:<20} {count:>4}  ({requested})")
    for key in REQUESTED_EXT_KEYS:
        if key not in report.ext_key_counts:
            print(f"  {key:<20} {0:>4}  (requested, NEVER returned)")
    print(f"ObjectName present: {report.ext_key_counts.get('ObjectName', 0) > 0}")

    print(f"\nanomalies ({len(report.anomalies)}):")
    for anomaly in report.anomalies:
        print(f"  - {anomaly}")
    if not report.anomalies:
        print("  none")

    print(f"\ndistinct DateTimeOriginal values ({len(report.date_values)}), grouped by shape:")
    by_shape: dict[str, list[str]] = {}
    for value in report.date_values:
        by_shape.setdefault(date_shape(value), []).append(value)
    for shape, values in sorted(by_shape.items(), key=lambda kv: -len(kv[1])):
        matches = sum(1 for v in values if DATE_RE.match(v))
        print(f"  shape {shape!r}: {len(values)} value(s), spec regex matches {matches}")
        for value in values[:3]:
            hit = DATE_RE.match(value)
            parsed = "-".join(hit.groups()) if hit else None
            print(f"      {clip(value, 140)} -> {parsed}  ({report.date_values[value]})")
    html_dates = [v for v in report.date_values if "<" in v]
    print(f"  values containing HTML tags: {len(html_dates)}")

    print("\nArtist raw values (first 12):")
    for title, artist in report.artist_samples[:12]:
        kind = "HTML" if "<" in artist else "plain"
        print(
            f"  [{kind}] {clip(artist, 150)} -> stripped {clip(strip_html(artist), 80)}  ({title})"
        )
    html_artists = sum(1 for _, a in report.artist_samples if "<" in a)
    print(f"  Artist samples with HTML: {html_artists} / {len(report.artist_samples)}")

    print("\nImageDescription raw values (first 12):")
    for title, desc in report.description_samples[:12]:
        kind = "HTML" if "<" in desc else "plain"
        langs = sorted(set(re.findall(r'lang="([^"]+)"', desc)))
        print(f"  [{kind} langs={langs}] {clip(desc, 200)}")
        print(f"      stripped: {clip(strip_html(desc), 120)}  ({title})")
    html_descs = sum(1 for _, d in report.description_samples if "<" in d)
    print(f"  ImageDescription samples with HTML: {html_descs} / {len(report.description_samples)}")


def step_exclusion_regex(report: Report) -> None:
    banner("EXCLUSION REGEX: Section 7.3 filename filter against every filename seen")
    excluded: list[tuple[str, str, str]] = []
    for filename in report.filenames:
        match = EXCLUDE_RE.search(filename)
        if match is None:
            continue
        start, end = match.span()
        before = filename[start - 1] if start > 0 else ""
        after = filename[end] if end < len(filename) else ""
        inside_word = before.isalpha() or after.isalpha()
        verdict = "FALSE POSITIVE? (in-word)" if inside_word else "ok"
        excluded.append((filename, match.group(0), verdict))
    print(f"filenames seen: {len(report.filenames)}; excluded: {len(excluded)}")
    for filename, token, verdict in excluded:
        print(f"  {verdict:<26} {token!r:<18} {filename}")
    suspicious = [e for e in excluded if e[2] != "ok"]
    print(f"\nin-word (suspicious) matches: {len(suspicious)}")


# ----------------------------------------------------------------------------- downloads
@dataclass
class Download:
    url: str
    status: int | None = None
    content_type: str | None = None
    content_length: str | None = None
    received: int = 0
    elapsed_ms: int = 0
    error: str | None = None
    body: bytes = b""


async def download(client: httpx.AsyncClient, url: str, semaphore: asyncio.Semaphore) -> Download:
    """Streamed GET with Accept: image/* under a semaphore (Section 7.3 / Section 8 rules)."""
    result = Download(url=url)
    async with semaphore:
        started = time.monotonic()
        try:
            async with client.stream(
                "GET", url, headers={"Accept": "image/*"}, timeout=DOWNLOAD_TIMEOUT_S
            ) as response:
                result.status = response.status_code
                result.content_type = response.headers.get("content-type")
                result.content_length = response.headers.get("content-length")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_DOWNLOAD_BYTES:
                        result.error = "aborted: > 4 MB"
                        break
                result.received = len(body)
                result.body = bytes(body)
        except httpx.HTTPError as exc:
            result.error = describe_error(exc)
        result.elapsed_ms = int((time.monotonic() - started) * 1000)
    return result


def decode(body: bytes) -> tuple[tuple[int, int], str, str]:
    """Section 8 decode: open, load, exif_transpose, RGB; returns (size, mode, phash hex)."""
    img = Image.open(BytesIO(body))
    img.load()
    img = ImageOps.exif_transpose(img).convert("RGB")
    return img.size, img.mode, str(imagehash.phash(img))


async def download_round(
    client: httpx.AsyncClient, urls: list[str], concurrency: int
) -> list[Download]:
    semaphore = asyncio.Semaphore(concurrency)
    started = time.monotonic()
    results = await asyncio.gather(*(download(client, u, semaphore) for u in urls))
    total_ms = int((time.monotonic() - started) * 1000)
    statuses = Counter(r.status for r in results)
    print(
        f"\nconcurrency {concurrency}: {len(urls)} downloads in {total_ms} ms; statuses {dict(statuses)}"
    )
    print(f"  429 responses: {statuses.get(429, 0)}")
    for r in results:
        name = r.url.rsplit("/", 1)[-1]
        print(
            f"  {r.status} {r.content_type!s:<12} content-length={r.content_length!s:<8}"
            f" bytes={r.received:<7} {r.elapsed_ms:>5} ms  {name[:60]}"
            + (f"  ERROR {r.error}" if r.error else "")
        )
    return results


def download_candidates(report: Report) -> list[FileFacts]:
    """JPEG files with a thumburl, category files first (the same order the pipeline would use)."""
    seen: set[str] = set()
    chosen: list[FileFacts] = []
    for label in ("category_mit", "category_mit_page2", "category_cambridge", "search_mit"):
        for f in report.facts.get(label, []):
            if f.mime == "image/jpeg" and f.thumburl and f.thumburl not in seen:
                seen.add(f.thumburl)
                chosen.append(f)
    return chosen


async def step_downloads(client: httpx.AsyncClient, report: Report) -> list[Download]:
    banner("DOWNLOADS: 12 thumburls from upload.wikimedia.org at concurrency 8, then 16")
    candidates = download_candidates(report)[:DOWNLOAD_SAMPLE]
    urls = [f.thumburl for f in candidates if f.thumburl]
    if not urls:
        print("  no thumburls available")
        return []
    round8 = await download_round(client, urls, 8)
    await download_round(client, urls, 16)

    print("\nPillow decode + phash of three downloads:")
    good = [r for r in round8 if r.status == 200 and r.body and not r.error]
    for r in good[:3]:
        try:
            size, mode, phash = await asyncio.to_thread(decode, r.body)
        except (OSError, ValueError) as exc:
            print(f"  decode failed for {r.url}: {describe_error(exc)}")
            continue
        print(f"  {r.url.rsplit('/', 1)[-1][:60]}: size={size} mode={mode} phash={phash}")

    print("\nphash distance between two sizes of the same file (640 px thumb vs original):")
    pair = next(
        (f for f in candidates if f.size and f.size <= 3_000_000 and f.url and f.url != f.thumburl),
        None,
    )
    if pair is None or pair.thumburl is None or pair.url is None:
        print("  no file with an original <= 3 MB to compare")
    else:
        semaphore = asyncio.Semaphore(8)
        thumb, original = await asyncio.gather(
            download(client, pair.thumburl, semaphore), download(client, pair.url, semaphore)
        )
        await compare_pair(pair.title, thumb, original, "640 thumb", "original")
        small_url = pair.thumburl.replace("/640px-", "/320px-")
        if small_url != pair.thumburl:
            small = await download(client, small_url, semaphore)
            await compare_pair(pair.title, thumb, small, "640 thumb", "320 thumb")
    return round8


async def compare_pair(title: str, a: Download, b: Download, name_a: str, name_b: str) -> None:
    if a.error or b.error or a.status != 200 or b.status != 200:
        print(f"  {title}: download failed ({a.status} {a.error} / {b.status} {b.error})")
        return
    try:
        size_a, _, hash_a = await asyncio.to_thread(decode, a.body)
        size_b, _, hash_b = await asyncio.to_thread(decode, b.body)
    except (OSError, ValueError) as exc:
        print(f"  {title}: decode failed: {describe_error(exc)}")
        return
    distance = imagehash.hex_to_hash(hash_a) - imagehash.hex_to_hash(hash_b)
    print(
        f"  {title}: {name_a} {size_a} ({a.received} B, {a.elapsed_ms} ms) phash={hash_a} vs"
        f" {name_b} {size_b} ({b.received} B, {b.elapsed_ms} ms) phash={hash_b}"
        f" -> distance {distance}"
    )


# ----------------------------------------------------------------------------- fixtures
FIXTURE_FILES: tuple[tuple[str, str], ...] = (
    ("commons_category_mit.json", "category_mit"),
    ("commons_category_mit_page2.json", "category_mit_page2"),
    ("commons_subcats_mit.json", "subcats_mit"),
    ("commons_subcat_files_mit.json", "subcat_files_mit"),
    ("commons_search_mit.json", "search_mit"),
    ("commons_search_nu_local.json", "search_nu_local"),
    ("commons_file_mit_p18.json", "file_mit_p18"),
    ("commons_file_mit_logo.json", "file_mit_logo"),
    ("commons_category_cambridge.json", "category_cambridge"),
    ("commons_category_nu.json", "category_nu"),
    # extras beyond the task list, useful for NU / city tests
    ("commons_subcats_nu.json", "subcats_nu"),
    ("commons_search_nu.json", "search_nu"),
    ("commons_category_astana.json", "category_astana"),
)


def step_fixtures(report: Report) -> None:
    banner("FIXTURES: save real responses")
    for filename, label in FIXTURE_FILES:
        data = report.responses.get(label)
        if data is None:
            print(f"  SKIPPED {filename}: no real response for {label!r}")
            continue
        save_fixture(filename, data)


def slug(filename: str) -> str:
    base = filename.rsplit(".", 1)[0]
    text = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")
    return text[:40] or "image"


async def step_image_fixtures(
    client: httpx.AsyncClient, report: Report, downloads: list[Download]
) -> None:
    banner("IMAGE FIXTURES: three real thumbnails <= 60 KB + SOURCES.txt")
    facts_by_url = {
        f.thumburl: f for label in report.facts for f in report.facts[label] if f.thumburl
    }
    small = [
        d
        for d in downloads
        if d.status == 200
        and not d.error
        and 0 < d.received <= MAX_FIXTURE_IMAGE_BYTES
        and (d.content_type or "").startswith("image/jpeg")
    ]
    print(f"  640 px thumbnails <= 60 KB among the downloads: {len(small)}")
    if len(small) < FIXTURE_IMAGE_COUNT:
        # Real Commons thumbnails at 320 px (same URL scheme, smaller width) for the larger ones.
        semaphore = asyncio.Semaphore(8)
        larger = [d for d in downloads if d.status == 200 and d.url not in {s.url for s in small}]
        extra = await asyncio.gather(
            *(download(client, d.url.replace("/640px-", "/320px-"), semaphore) for d in larger)
        )
        for d in extra:
            if d.status == 200 and not d.error and 0 < d.received <= MAX_FIXTURE_IMAGE_BYTES:
                facts_by_url[d.url] = facts_by_url.get(d.url.replace("/320px-", "/640px-"))
                small.append(d)
        print(f"  after adding 320 px renderings: {len(small)} candidates")
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "Real thumbnails downloaded from upload.wikimedia.org by scripts/probe_commons.py.",
        (
            "Each line: fixture -> Commons file page | license | author (Artist, HTML stripped)"
            " | thumbnail URL"
        ),
        "",
    ]
    saved = 0
    used_slugs: set[str] = set()
    for d in small:
        if saved >= FIXTURE_IMAGE_COUNT:
            break
        facts = facts_by_url.get(d.url)
        if facts is None:
            continue
        name = slug(facts.filename)
        if name in used_slugs:
            continue
        used_slugs.add(name)
        path = IMAGES_DIR / f"commons_{name}.jpg"
        path.write_bytes(d.body)
        saved += 1
        author = strip_html(facts.artist) if facts.artist else "unknown"
        lines.append(
            f"commons_{name}.jpg -> {facts.descriptionurl} | {facts.license_short_name}"
            f" | {author[:80]} | {d.url}"
        )
        print(f"  saved {path} ({d.received} bytes, {facts.title})")
    if saved < FIXTURE_IMAGE_COUNT:
        print(f"  WARNING: only {saved} thumbnail fixtures saved")
    (IMAGES_DIR / "SOURCES.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"  saved {IMAGES_DIR / 'SOURCES.txt'}")


# ----------------------------------------------------------------------------- main
async def main() -> int:
    settings = Settings()
    report = Report()
    async with create_client(settings) as client:
        await run_step("categories", step_categories(client, report))
        await run_step("subcategories", step_subcategories(client, report))
        await run_step("search", step_search(client, report))
        await run_step("single files", step_single_files(client, report))
        await run_step("city", step_city(client, report))
        step_observations(report)
        step_exclusion_regex(report)
        downloads = await run_step("downloads", step_downloads(client, report)) or []
        step_fixtures(report)
        await run_step("image fixtures", step_image_fixtures(client, report, downloads))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(asyncio.run(main()))
