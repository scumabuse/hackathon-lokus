"""aiosqlite cache (SPEC Section 12.4): roundtrips, TTLs, corruption tolerance, lifespan wiring."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai.client import AIClient
from app.cache import Cache, normalize_query
from app.config import Settings
from app.main import create_app


@pytest.fixture
async def cache(tmp_path: Path) -> AsyncIterator[Cache]:
    instance = Cache(tmp_path / "data" / "cache.sqlite")
    await instance.init()
    yield instance
    await instance.close()


def _insert(
    path: Path, table: str, key_column: str, key: str, json_text: str, created: str
) -> None:
    """Write a row directly (bypassing Cache) to simulate old or damaged data."""
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            f"INSERT OR REPLACE INTO {table} ({key_column}, json, created_at) VALUES (?, ?, ?)",
            (key, json_text, created),
        )
        conn.commit()
    finally:
        conn.close()


def _hours_ago(hours: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours)).isoformat()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Nazarbayev   University ", "nazarbayev university"),
        ("MIT", "mit"),
        ("Straße\tUniversität", "strasse universität"),
        ("КазНУ", "казну"),
        ("", ""),
    ],
)
def test_normalize_query(raw: str, expected: str) -> None:
    assert normalize_query(raw) == expected


async def test_init_creates_file_and_parent_dir(cache: Cache) -> None:
    assert cache.path.is_file()
    assert cache.path.parent.is_dir()


async def test_search_roundtrip_and_miss(cache: Cache) -> None:
    data = {"query": "казну", "candidates": [{"qid": "Q1", "label": "Университет"}]}
    await cache.set_search("казну", data)
    assert await cache.get_search("казну") == data
    assert await cache.get_search("missing") is None
    conn = sqlite3.connect(cache.path)
    try:
        stored = conn.execute("SELECT json FROM searches WHERE q_norm = ?", ("казну",)).fetchone()
    finally:
        conn.close()
    assert stored is not None
    assert "Университет" in stored[0]  # ensure_ascii=False: no \\u escapes


async def test_search_upsert_overwrites(cache: Cache) -> None:
    await cache.set_search("q", {"v": 1})
    await cache.set_search("q", {"v": 2})
    assert await cache.get_search("q") == {"v": 2}
    conn = sqlite3.connect(cache.path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM searches").fetchone()[0]
    finally:
        conn.close()
    assert count == 1


async def test_search_ttl_six_hours(cache: Cache) -> None:
    _insert(cache.path, "searches", "q_norm", "old", '{"v": "old"}', _hours_ago(7))
    _insert(cache.path, "searches", "q_norm", "fresh", '{"v": "fresh"}', _hours_ago(5))
    assert await cache.get_search("old") is None
    assert await cache.get_search("fresh") == {"v": "fresh"}


async def test_profile_roundtrip_returns_created_at(cache: Cache) -> None:
    data = {"header": {"qid": "Q1", "name": "Example University"}, "photos": []}
    before = datetime.now(UTC)
    await cache.set_profile("Q1", data)
    found = await cache.get_profile("Q1", 24)
    assert found is not None
    got, created_at = found
    assert got == data
    assert created_at.tzinfo is not None
    assert before - timedelta(seconds=1) <= created_at <= datetime.now(UTC) + timedelta(seconds=1)
    assert await cache.get_profile("Q404", 24) is None


async def test_profile_ttl_is_caller_defined(cache: Cache) -> None:
    _insert(cache.path, "profiles", "qid", "Q1", '{"v": 1}', _hours_ago(25))
    assert await cache.get_profile("Q1", 24) is None
    found = await cache.get_profile("Q1", 48)
    assert found is not None
    assert found[0] == {"v": 1}


async def test_naive_created_at_is_treated_as_utc(cache: Cache) -> None:
    naive = (datetime.now(UTC) - timedelta(hours=1)).replace(tzinfo=None).isoformat()
    _insert(cache.path, "profiles", "qid", "Q1", '{"v": 1}', naive)
    found = await cache.get_profile("Q1", 24)
    assert found is not None
    assert found[1].tzinfo is not None


@pytest.mark.parametrize(
    ("json_text", "created"),
    [
        ('{"v": 1}', "not-a-date"),
        ("{not json", None),
        ('["a list", "not an object"]', None),
    ],
)
async def test_damaged_rows_are_ignored(cache: Cache, json_text: str, created: str | None) -> None:
    _insert(cache.path, "profiles", "qid", "Q1", json_text, created or _hours_ago(0))
    assert await cache.get_profile("Q1", 24) is None


async def test_non_json_serializable_value_is_stringified(cache: Cache) -> None:
    stamp = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    await cache.set_search("q", {"when": stamp})
    assert await cache.get_search("q") == {"when": str(stamp)}


async def test_reopens_lazily_after_close(cache: Cache) -> None:
    await cache.set_search("q", {"v": 1})
    await cache.close()
    assert await cache.get_search("q") == {"v": 1}


async def test_corrupted_path_never_raises(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    broken = Cache(blocker / "cache.sqlite")
    await broken.init()
    assert await broken.set_search("q", {"v": 1}) is None
    assert await broken.get_search("q") is None
    assert await broken.set_profile("Q1", {"v": 1}) is None
    assert await broken.get_profile("Q1", 24) is None
    await broken.close()


async def test_lifespan_wires_ai_and_cache(tmp_path: Path) -> None:
    settings = Settings(gemini_api_key=None, flickr_api_key=None, cache_dir=tmp_path)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        assert isinstance(app.state.ai, AIClient)
        assert app.state.ai.available is False
        assert isinstance(app.state.cache, Cache)
        await app.state.cache.set_search("x", {"query": "x"})
        assert await app.state.cache.get_search("x") == {"query": "x"}
        assert (tmp_path / "cache.sqlite").is_file()


async def test_app_starts_with_unwritable_cache_dir(tmp_path: Path) -> None:
    """CACHE_DIR under a regular file: no thumbs dir, no sqlite -- the app still serves."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    settings = Settings(gemini_api_key=None, flickr_api_key=None, cache_dir=blocker / "cache")
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        assert not settings.thumbs_dir.exists()
        assert isinstance(app.state.cache, Cache)
        await app.state.cache.set_search("x", {"query": "x"})  # no-op, never raises
        assert await app.state.cache.get_search("x") is None
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
