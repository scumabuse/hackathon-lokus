"""aiosqlite cache for /api/search results and profiles (SPEC Section 12.4).

Tables: ``profiles(qid TEXT PRIMARY KEY, json TEXT, created_at TEXT)`` and
``searches(q_norm TEXT PRIMARY KEY, json TEXT, created_at TEXT)``; ``created_at`` is ISO 8601 UTC.
TTL: searches 6 h, profiles PROFILE_TTL_HOURS (passed by the caller). Every method swallows
sqlite / JSON errors into a warning and behaves like a miss: the cache must never break a request.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

log = logging.getLogger("app.cache")

SEARCH_TTL_HOURS = 6.0

_CACHE_ERRORS = (sqlite3.Error, OSError, ValueError, TypeError)
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS profiles (qid TEXT PRIMARY KEY, json TEXT, created_at TEXT)",
    "CREATE TABLE IF NOT EXISTS searches (q_norm TEXT PRIMARY KEY, json TEXT, created_at TEXT)",
)
_SELECT_SEARCH = "SELECT json, created_at FROM searches WHERE q_norm = ?"
_UPSERT_SEARCH = "INSERT OR REPLACE INTO searches (q_norm, json, created_at) VALUES (?, ?, ?)"
_SELECT_PROFILE = "SELECT json, created_at FROM profiles WHERE qid = ?"
_UPSERT_PROFILE = "INSERT OR REPLACE INTO profiles (qid, json, created_at) VALUES (?, ?, ?)"


def normalize_query(q: str) -> str:
    """Cache key for a search: casefold, collapse whitespace, strip."""
    return " ".join(q.casefold().split())


def _parse_created_at(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


class Cache:
    """One lazily opened aiosqlite connection guarded by an asyncio.Lock."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def init(self) -> None:
        """Create the parent directory, the file and the tables; failure degrades to a no-op."""
        async with self._lock:
            try:
                await self._connection()
            except _CACHE_ERRORS as exc:
                log.warning("cache unavailable at %s (%s); serving without cache", self.path, exc)

    async def close(self) -> None:
        """Close the connection; a later call reopens it lazily."""
        async with self._lock:
            conn, self._conn = self._conn, None
            if conn is None:
                return
            try:
                await conn.close()
            except _CACHE_ERRORS as exc:
                log.warning("cache close failed: %s", exc)

    async def get_search(self, q_norm: str) -> dict[str, Any] | None:
        """Cached SearchResponse dict for a normalized query, or None (missing/expired/error)."""
        found = await self._read("search", _SELECT_SEARCH, q_norm, SEARCH_TTL_HOURS)
        return found[0] if found is not None else None

    async def set_search(self, q_norm: str, data: dict[str, Any]) -> None:
        """Upsert a SearchResponse dict under its normalized query."""
        await self._write("search", _UPSERT_SEARCH, q_norm, data)

    async def get_profile(
        self, qid: str, ttl_hours: float
    ) -> tuple[dict[str, Any], datetime] | None:
        """Cached profile dict and its creation time, or None (missing/expired/error)."""
        return await self._read("profile", _SELECT_PROFILE, qid, ttl_hours)

    async def set_profile(self, qid: str, data: dict[str, Any]) -> None:
        """Upsert a profile dict under its QID."""
        await self._write("profile", _UPSERT_PROFILE, qid, data)

    async def _connection(self) -> aiosqlite.Connection:
        """Open lazily; the caller holds the lock. Raises when sqlite cannot open the file."""
        if self._conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = await aiosqlite.connect(self.path)
            try:
                for statement in _SCHEMA:
                    await conn.execute(statement)
                await conn.commit()
            except Exception:
                await conn.close()
                raise
            self._conn = conn
        return self._conn

    async def _read(
        self, kind: str, sql: str, key: str, ttl_hours: float
    ) -> tuple[dict[str, Any], datetime] | None:
        async with self._lock:
            try:
                conn = await self._connection()
                async with conn.execute(sql, (key,)) as cursor:
                    row = await cursor.fetchone()
            except _CACHE_ERRORS as exc:
                log.warning("cache %s read failed for %r (%s); treating as a miss", kind, key, exc)
                return None
        if row is None:
            return None
        created_at = _parse_created_at(row[1])
        if created_at is None:
            log.warning("cache %s row for %r has an unreadable created_at; ignored", kind, key)
            return None
        if datetime.now(UTC) - created_at > timedelta(hours=ttl_hours):
            return None
        try:
            data = json.loads(row[0])
        except (TypeError, ValueError) as exc:
            log.warning("cache %s row for %r is not valid JSON (%s); ignored", kind, key, exc)
            return None
        if not isinstance(data, dict):
            log.warning("cache %s row for %r is not a JSON object; ignored", kind, key)
            return None
        return data, created_at

    async def _write(self, kind: str, sql: str, key: str, data: dict[str, Any]) -> None:
        async with self._lock:
            try:
                encoded = json.dumps(data, ensure_ascii=False, default=str)
                conn = await self._connection()
                await conn.execute(sql, (key, encoded, datetime.now(UTC).isoformat()))
                await conn.commit()
            except _CACHE_ERRORS as exc:
                log.warning("cache %s write failed for %r (%s); ignored", kind, key, exc)
