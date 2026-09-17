from __future__ import annotations

from httpx import AsyncClient


async def test_health_ok(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert body["time"].endswith("+00:00")


async def test_unknown_api_path_uses_error_envelope(client: AsyncClient) -> None:
    response = await client.get("/api/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
