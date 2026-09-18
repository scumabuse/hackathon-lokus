"""GET /api/thumb/{id}.jpg (SPEC Section 12): served by us, cacheable, 404 with the envelope."""

from __future__ import annotations

from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.config import Settings
from app.main import create_app

PHOTO_ID = "0123456789abcdef"


@pytest.fixture
async def thumb_client(tmp_path: Path) -> AsyncIterator[tuple[AsyncClient, Path]]:
    settings = Settings(gemini_api_key=None, flickr_api_key=None, cache_dir=tmp_path)
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac,
    ):
        yield ac, settings.thumbs_dir


def _jpeg_bytes() -> bytes:
    out = BytesIO()
    Image.new("RGB", (64, 48), (120, 80, 40)).save(out, format="JPEG")
    return out.getvalue()


async def test_thumb_served_with_cache_headers(
    thumb_client: tuple[AsyncClient, Path],
) -> None:
    client, thumbs_dir = thumb_client
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    (thumbs_dir / f"{PHOTO_ID}.jpg").write_bytes(_jpeg_bytes())
    response = await client.get(f"/api/thumb/{PHOTO_ID}.jpg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "public, max-age=86400"
    assert response.content == _jpeg_bytes()


async def test_missing_thumb_is_404_envelope(thumb_client: tuple[AsyncClient, Path]) -> None:
    client, _ = thumb_client
    response = await client.get("/api/thumb/ffffffffffffffff.jpg")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    "bad_id",
    ["short", "0123456789ABCDEF", "..%2F..%2Fpyproject", "0123456789abcdef0", "zzzzzzzzzzzzzzzz"],
)
async def test_bad_ids_are_rejected(thumb_client: tuple[AsyncClient, Path], bad_id: str) -> None:
    client, _ = thumb_client
    response = await client.get(f"/api/thumb/{bad_id}.jpg")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_path_traversal_cannot_escape_thumbs_dir(
    thumb_client: tuple[AsyncClient, Path],
) -> None:
    client, thumbs_dir = thumb_client
    secret = thumbs_dir.parent / "secret.jpg"
    secret.write_bytes(_jpeg_bytes())
    response = await client.get("/api/thumb/../secret.jpg")
    assert response.status_code == 404
