from __future__ import annotations

from pathlib import Path

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app


async def test_spa_fallback_and_api_404(tmp_path: Path, settings: Settings) -> None:
    (tmp_path / "index.html").write_text("<html><body>spa</body></html>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    app = create_app(settings, static_dir=tmp_path)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            deep = await ac.get("/u/Q49108")
            assert deep.status_code == 200
            assert "spa" in deep.text
            root = await ac.get("/")
            assert root.status_code == 200
            asset = await ac.get("/assets/app.js")
            assert asset.status_code == 200
            assert "console" in asset.text
            unknown_api = await ac.get("/api/does-not-exist")
            assert unknown_api.status_code == 404
            assert unknown_api.json()["error"]["code"] == "not_found"
            health = await ac.get("/api/health")
            assert health.status_code == 200
            escape = await ac.get("/../pyproject.toml")
            assert escape.status_code == 200
            assert "spa" in escape.text
