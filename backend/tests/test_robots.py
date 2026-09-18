"""RobotsRules (official_site source): RFC 9309 matching.

The real robots.txt of ksu.edu.kz (Kostanay Regional University, a Section 13 example) carries
``Disallow: /?`` under ``User-Agent: *``. urllib.robotparser normalizes that rule into
``Disallow: /`` and thereby hid the whole official site; RobotsRules must keep the site open and
block only what the file actually blocks.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest
import respx

from app.config import Settings
from app.http import create_client
from app.models import UniversityHeader
from app.resolver.wikidata import ResolvedEntity
from app.sources.base import SourceContext
from app.sources.official_site import OfficialSiteSource, RobotsRules

FIXTURES = Path(__file__).parent / "fixtures"
KSU_ROBOTS = (FIXTURES / "robots_ksu_edu_kz.txt").read_text(encoding="utf-8")
KSU_HOME = """<html><head><title>KRU</title></head><body>
<img src="/images/HomeSliderImage/univer.jpg" alt="Main building of the university">
<img src="/images/news/campus-spring.jpg" alt="Campus in spring">
</body></html>"""


def ksu_resolved() -> ResolvedEntity:
    header = UniversityHeader(
        qid="Q123694980",
        name="Akhmet Baitursynuly Kostanay Regional University",
        official_website="https://ksu.edu.kz",
    )
    return ResolvedEntity(header=header)


async def run_official_site(robots_text: str) -> list[str]:
    settings = Settings(gemini_api_key=None, flickr_api_key=None)
    with respx.mock(assert_all_called=False) as router:
        router.get("https://ksu.edu.kz/robots.txt").mock(
            return_value=httpx.Response(200, text=robots_text)
        )
        router.get(url__regex=r"https://ksu\.edu\.kz/?$").mock(
            return_value=httpx.Response(200, text=KSU_HOME, headers={"content-type": "text/html"})
        )
        async with create_client(settings) as http:
            ctx = SourceContext(
                settings=settings, http=http, resolved=ksu_resolved(), deadline=time.monotonic() + 30
            )
            result = await OfficialSiteSource().fetch(ctx)
    return [candidate.image_url for candidate in result.candidates]


@pytest.mark.asyncio
async def test_official_site_scrapes_ksu_despite_disallow_root_query() -> None:
    urls = await run_official_site(KSU_ROBOTS)
    assert "https://ksu.edu.kz/images/news/campus-spring.jpg" in urls


@pytest.mark.asyncio
async def test_official_site_respects_a_real_disallow_all() -> None:
    assert await run_official_site("User-agent: *\nDisallow: /\n") == []


def test_real_ksu_robots_keeps_the_site_open() -> None:
    rules = RobotsRules.parse(KSU_ROBOTS)
    assert rules.allows("https://ksu.edu.kz")
    assert rules.allows("https://ksu.edu.kz/")
    assert rules.allows("https://ksu.edu.kz/kz/")
    assert rules.allows("https://ksu.edu.kz/kz/campus/")


def test_real_ksu_robots_blocks_only_the_listed_paths() -> None:
    rules = RobotsRules.parse(KSU_ROBOTS)
    assert not rules.allows("https://ksu.edu.kz/?page=2")
    assert not rules.allows("https://ksu.edu.kz/admin")
    assert not rules.allows("https://ksu.edu.kz/admin/login")
    assert not rules.allows("https://ksu.edu.kz/search?q=x")
    assert not rules.allows("https://ksu.edu.kz/index.php")
    assert not rules.allows("https://ksu.edu.kz/biblioteka-report/2024")


def test_disallow_root_blocks_everything_and_empty_disallow_nothing() -> None:
    assert not RobotsRules.parse("User-agent: *\nDisallow: /\n").allows("https://x.kz/any")
    assert RobotsRules.parse("User-agent: *\nDisallow:\n").allows("https://x.kz/any")
    assert RobotsRules.parse("").allows("https://x.kz/any")
    assert RobotsRules.parse("Sitemap: https://x.kz/sitemap.xml\n").allows("https://x.kz/")


def test_wildcard_and_end_anchor() -> None:
    rules = RobotsRules.parse("User-agent: *\nDisallow: /*.pdf$\nDisallow: /private*\n")
    assert not rules.allows("https://x.kz/docs/a.pdf")
    assert rules.allows("https://x.kz/docs/a.pdf?download=1")
    assert rules.allows("https://x.kz/docs/a.pdfx")
    assert not rules.allows("https://x.kz/private-area/")
    assert rules.allows("https://x.kz/public/")


def test_longest_match_wins_and_allow_beats_disallow_on_ties() -> None:
    rules = RobotsRules.parse("User-agent: *\nDisallow: /kz\nAllow: /kz/campus\n")
    assert rules.allows("https://x.kz/kz/campus/photos")
    assert not rules.allows("https://x.kz/kz/news")
    tie = RobotsRules.parse("User-agent: *\nDisallow: /kz\nAllow: /kz\n")
    assert tie.allows("https://x.kz/kz/news")


def test_group_for_our_product_token_wins_over_the_star_group() -> None:
    text = (
        "User-agent: *\nDisallow: /admin\n\n"
        "User-agent: Googlebot\nUser-agent: VisualCampusBot/1.0\nDisallow: /\n"
    )
    ours = RobotsRules.parse(text)
    assert not ours.allows("https://x.kz/")
    other = RobotsRules.parse(text, agent="yandex")
    assert other.allows("https://x.kz/")
    assert not other.allows("https://x.kz/admin")


def test_groups_with_the_same_agent_are_merged() -> None:
    text = "User-agent: *\nDisallow: /a\n\nUser-agent: *\nDisallow: /b\n"
    rules = RobotsRules.parse(text)
    assert not rules.allows("https://x.kz/a")
    assert not rules.allows("https://x.kz/b")
    assert rules.allows("https://x.kz/c")


def test_comments_blank_lines_and_key_case_are_tolerated() -> None:
    text = "# banner\n\nUSER-AGENT: *   # all bots\nDISALLOW: /secret   # hidden\nCrawl-delay: 30\n"
    rules = RobotsRules.parse(text)
    assert not rules.allows("https://x.kz/secret/1")
    assert rules.allows("https://x.kz/")
