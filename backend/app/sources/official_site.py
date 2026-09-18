"""Official website image source (SPEC Section 7.5, Stage B).

Scrapes the university's P856 official website for images: homepage first, then up to 6
internal pages whose href or anchor text signals campus/facilities/student life.

Rules:
- robots.txt respected (urllib.robotparser; fetch failure → assume allowed)
- User-Agent: Mozilla/5.0 (compatible; VisualCampusBot/1.0; +mailto:{CONTACT_EMAIL})
- Per-page budget 6 s; source budget 8 s; max pages = 7 (homepage + 6)
- Concurrency 4 for the sub-pages
- Filters: URL not matching exclusion regex; after download: min side ≥ 300, ≥ 15 KB, aspect 0.4-2.6
- Cap 40 candidates (homepage og:image first, then discovery order)
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from app.enums import SourceType, WarningCode
from app.models import RawCandidate, Warning
from app.sources.base import BaseSource, SourceContext, SourceResult, build_candidate, clip_text

log = logging.getLogger("app.sources.official_site")

OFFICIAL_SITE_NAME = "official_site"
SOURCE_BUDGET_S = 8.0
PAGE_TIMEOUT_S = 6.0
ROBOTS_TIMEOUT_S = 3.0
MAX_PAGES = 7  # homepage + 6 internal
SUB_PAGE_CONCURRENCY = 4
MAX_CANDIDATES = 40

# Image URL exclusion pattern (Section 7.5 step 5)
_IMG_EXCLUDE = re.compile(
    r"logo|icon|sprite|avatar|flag|badge|button|arrow|pixel|track|banner|adv|favicon|"
    r"loader|spinner|placeholder|blank|\.svg|\.gif",
    re.IGNORECASE,
)

# Internal link patterns for relevant campus/facility pages (Section 7.5 step 3)
_LINK_PATTERN = re.compile(
    r"campus|dorm|hostel|residen|housing|accommodation|library|student.?life|sport|gym|"
    r"about|tour|gallery|photo|facilit|"
    r"кампус|общежит|библиотек|студенческ|спорт|галере|жатақхана|кітапхана",
    re.IGNORECASE,
)

# inline style url() extraction
_CSS_URL_RE = re.compile(r"""url\(\s*(['"]?)([^'")\s]+)\1\s*\)""")

# published date from <meta> tags
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _registrable_domain(host: str) -> str:
    """Return the last two labels of the host (e.g. nu.edu.kz → edu.kz? no → nu.edu.kz)."""
    labels = host.split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def _same_domain(base_host: str, link_host: str) -> bool:
    return _registrable_domain(base_host) == _registrable_domain(link_host)


def _parse_date(tag_value: str | None) -> tuple[str | None, str]:
    if not tag_value:
        return None, "unknown"
    m = _DATE_RE.search(tag_value)
    if m:
        return m.group(1), "published"
    return None, "unknown"


def _extract_images(soup: BeautifulSoup, page_url: str) -> list[str]:
    """Collect all candidate image URLs from a parsed page."""
    urls: list[str] = []

    def add(raw: str | None) -> None:
        if not raw:
            return
        absolute = urljoin(page_url, raw.strip())
        parsed = urlparse(absolute)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            urls.append(absolute)

    # og:image / twitter:image (highest priority)
    for tag in soup.find_all("meta", attrs={"property": "og:image"}):
        add(tag.get("content"))
    for tag in soup.find_all("meta", attrs={"name": "twitter:image"}):
        add(tag.get("content"))

    # <img> attributes
    for tag in soup.find_all("img"):
        for attr in ("src", "data-src", "data-lazy-src", "data-original"):
            val = tag.get(attr)
            if val:
                add(val)
                break
        # srcset: take the largest candidate
        srcset = tag.get("srcset", "")
        if srcset:
            candidates = [part.strip().split()[0] for part in srcset.split(",") if part.strip()]
            if candidates:
                add(candidates[-1])

    # <source srcset>
    for tag in soup.find_all("source"):
        srcset = tag.get("srcset", "")
        if srcset:
            candidates = [part.strip().split()[0] for part in srcset.split(",") if part.strip()]
            if candidates:
                add(candidates[-1])

    # inline style url()
    for tag in soup.find_all(style=True):
        for m in _CSS_URL_RE.finditer(str(tag.get("style", ""))):
            add(m.group(2))

    return urls


def _extract_internal_links(soup: BeautifulSoup, page_url: str, base_host: str) -> list[str]:
    """Collect internal links matching the campus/facilities/gallery pattern."""
    seen: set[str] = set()
    result: list[str] = []
    for tag in soup.find_all("a", href=True):
        href = str(tag.get("href", "")).strip()
        if not href or href.startswith("#"):
            continue
        absolute = urljoin(page_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue
        if not _same_domain(base_host, parsed.netloc):
            continue
        anchor_text = tag.get_text(" ", strip=True)
        if not (_LINK_PATTERN.search(href) or _LINK_PATTERN.search(anchor_text)):
            continue
        # normalise
        key = parsed._replace(fragment="").geturl()
        if key in seen:
            continue
        seen.add(key)
        result.append(absolute)
    return result


def _page_date(soup: BeautifulSoup, response: httpx.Response) -> tuple[str | None, str]:
    """Try meta[article:published_time] → meta[name=date] → Last-Modified."""
    for meta_sel in (
        {"property": "article:published_time"},
        {"name": "date"},
    ):
        tag = soup.find("meta", attrs=meta_sel)
        if tag:
            date, kind = _parse_date(tag.get("content"))
            if date:
                return date, kind
    last_modified = response.headers.get("Last-Modified")
    if last_modified:
        try:
            parsed = parsedate_to_datetime(last_modified)
        except (TypeError, ValueError):
            parsed = None
        if parsed is not None:
            return parsed.date().isoformat(), "published"
    return None, "unknown"


def _page_title(soup: BeautifulSoup) -> str | None:
    tag = soup.find("title")
    if tag and tag.get_text(strip=True):
        return tag.get_text(strip=True)[:300]
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return str(og.get("content"))[:300]
    return None


class OfficialSiteSource(BaseSource):
    """Section 7.5 official website image scraper."""

    name = OFFICIAL_SITE_NAME
    source_type = SourceType.official_site

    async def collect(self, ctx: SourceContext, result: SourceResult) -> None:
        header = ctx.resolved.header
        if not header.official_website:
            result.warnings.append(Warning(code=WarningCode.no_official_site))
            return

        site_url = header.official_website.rstrip("/")
        parsed_base = urlparse(site_url)
        base_host = parsed_base.netloc
        source_label = base_host
        stage_deadline = time.monotonic() + SOURCE_BUDGET_S

        bot_ua = (
            f"Mozilla/5.0 (compatible; VisualCampusBot/1.0; +mailto:{ctx.settings.contact_email})"
        )
        headers = {"User-Agent": bot_ua, "Accept": "text/html,*/*"}

        # robots.txt check (Section 7.5): a missing or unreadable file means "allowed"
        self._robots = None
        robots_url = f"{parsed_base.scheme}://{base_host}/robots.txt"
        try:
            robots_resp = await asyncio.wait_for(
                ctx.http.get(robots_url, headers=headers),
                timeout=ROBOTS_TIMEOUT_S,
            )
            if robots_resp.status_code == 200:
                rp = RobotFileParser()
                rp.set_url(robots_url)
                rp.parse(robots_resp.text.splitlines())
                self._robots = rp
        except (httpx.HTTPError, TimeoutError, ValueError) as exc:
            log.debug("official_site: robots.txt unavailable for %s (%s)", base_host, exc)

        def is_allowed(url: str) -> bool:
            if self._robots is None:
                return True
            try:
                return self._robots.can_fetch("*", url)
            except (ValueError, KeyError, AttributeError):
                return True

        candidates: list[RawCandidate] = []

        async def scrape_page(page_url: str, *, is_homepage: bool = False) -> None:
            if time.monotonic() > stage_deadline:
                return
            if not is_allowed(page_url):
                log.debug("official_site: robots.txt disallows %s", page_url)
                return
            try:
                resp = await asyncio.wait_for(
                    ctx.http.get(page_url, headers=headers),
                    timeout=PAGE_TIMEOUT_S,
                )
                resp.raise_for_status()
            except (httpx.HTTPError, TimeoutError, ValueError) as exc:
                if is_homepage:
                    result.warnings.append(
                        Warning(code=WarningCode.source_unavailable, detail=self.name)
                    )
                    result.error = f"homepage fetch failed: {exc}"
                log.warning("official_site page %s failed: %s", page_url, exc)
                return

            ct = resp.headers.get("content-type", "")
            if "html" not in ct and "xml" not in ct:
                return

            soup = BeautifulSoup(resp.text, "lxml")

            date, date_kind = _page_date(soup, resp)
            pg_title = _page_title(soup)

            for img_url in _extract_images(soup, page_url):
                if len(candidates) >= MAX_CANDIDATES:
                    break
                if _IMG_EXCLUDE.search(img_url):
                    continue
                # alt from the matching <img> tag (best effort)
                alt_text: str | None = None
                for img_tag in soup.find_all("img"):
                    for attr in ("src", "data-src", "data-lazy-src", "data-original"):
                        if (
                            img_tag.get(attr)
                            and urljoin(page_url, str(img_tag.get(attr))) == img_url
                        ):
                            alt_text = clip_text(img_tag.get("alt"), 300)
                            break

                candidate = build_candidate(
                    source_type=self.source_type,
                    image_url=img_url,
                    source_page_url=page_url,
                    source_label=source_label,
                    title=alt_text or pg_title,
                    date=date,
                    date_kind=date_kind,
                    page_title=pg_title,
                )
                if candidate is not None:
                    candidates.append(candidate)

            if is_homepage:
                # collect internal links for the 6 sub-pages
                links = _extract_internal_links(soup, page_url, base_host)
                sub_urls = [lnk for lnk in links if lnk != site_url][:6]
                if sub_urls:
                    sem = asyncio.Semaphore(SUB_PAGE_CONCURRENCY)

                    async def _sub(url: str) -> None:
                        async with sem:
                            await scrape_page(url, is_homepage=False)

                    await asyncio.gather(*(_sub(u) for u in sub_urls), return_exceptions=True)

        await scrape_page(site_url, is_homepage=True)

        # dedupe by URL (preserve first occurrence)
        seen_urls: set[str] = set()
        for c in candidates:
            if c.image_url not in seen_urls:
                seen_urls.add(c.image_url)
                result.candidates.append(c)
