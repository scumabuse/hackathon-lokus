"""Shared test fixtures."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("CACHE_DIR", os.path.join(os.path.dirname(__file__), "_data"))

from app.config import Settings
from app.main import create_app

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def read_fixture(name: str) -> Any:
    """Parse a saved real API response from tests/fixtures/."""
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def settings() -> Settings:
    return Settings(gemini_api_key=None, flickr_api_key=None)


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.fixture(scope="session")
def load_fixture() -> Callable[[str], Any]:
    """Loader for the real saved responses in tests/fixtures/ (parsed fresh on every call)."""
    return read_fixture


@pytest.fixture
def fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable the Section 7 retry/backoff so failure tests do not wait on tenacity."""
    monkeypatch.setattr("app.http.MAX_ATTEMPTS", 1)
