"""Section 7.2 REST summary parsing on the real saved MIT response."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.resolver.wikipedia import encode_title, rest_summary
from tests.conftest import read_fixture


@respx.mock
async def test_rest_summary_mit_uses_extract_and_desktop_page() -> None:
    fixture = read_fixture("wikipedia_summary_mit_en.json")
    route = respx.get(
        "https://en.wikipedia.org/api/rest_v1/page/summary/Massachusetts_Institute_of_Technology"
    ).mock(return_value=httpx.Response(200, json=fixture))
    async with httpx.AsyncClient() as client:
        summary = await rest_summary(client, "en", "Massachusetts Institute of Technology")
    assert route.called
    assert summary is not None
    assert summary.lang == "en"
    assert summary.extract == summary.extract.strip()
    assert len(summary.extract) > 50
    assert summary.page_url == fixture["content_urls"]["desktop"]["page"]


@respx.mock
async def test_rest_summary_failure_returns_none() -> None:
    respx.get(url__regex=r"https://ru\.wikipedia\.org/api/rest_v1/page/summary/.*").mock(
        side_effect=httpx.ConnectError("down")
    )
    async with httpx.AsyncClient() as client:
        assert await rest_summary(client, "ru", "Массачусетский технологический институт") is None


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Massachusetts Institute of Technology", "Massachusetts_Institute_of_Technology"),
        ("Cambridge, Massachusetts", "Cambridge%2C_Massachusetts"),
    ],
)
def test_encode_title(title: str, expected: str) -> None:
    assert encode_title(title) == expected
