"""GET /api/profile/{qid} end to end (SPEC Sections 6, 11, 12) with the network mocked.

The resolver and the sources are replaced by fakes (their own tests cover the real API calls);
download, dedup, scoring, selection, stats and the routes run for real against respx-served
Pillow images.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
import respx
from httpx import ASGITransport, AsyncClient
from PIL import Image, ImageDraw

from app import pipeline
from app.config import Settings
from app.enums import Category, ReasonCode, SourceType, Verification, WarningCode
from app.main import create_app
from app.models import Coordinates, RawCandidate, UniversityHeader
from app.pipeline import normalize_candidates
from app.resolver.wikidata import ResolvedEntity, ResolverUnavailableError
from app.sources.base import SourceContext, SourceResult

QID = "Q1"
NAME = "Testville Institute of Technology"
IMG_A = "https://images.example.org/campus_a.jpg"
IMG_A_COPY = "https://images.example.org/copy/campus_a_again.jpg"
IMG_B = "https://images.example.org/library_b.jpg"
IMG_C = "https://images.example.org/dorm_c.jpg"
IMG_BROKEN = "https://images.example.org/broken.jpg"


def photo_bytes(seed: int, *, label: str) -> bytes:
    """Structurally different photo-like images per seed so their pHashes are far apart."""
    width, height = 640, 480
    ys, xs = np.mgrid[0:height, 0:width]
    if seed % 3 == 1:  # diagonal gradient with a soft wave
        base = (xs / width * 180 + ys / height * 60 + 15 * np.sin(xs / 25)).astype(np.uint8)
        rgb = np.stack([base, (base * 0.7).astype(np.uint8), 255 - base], axis=-1)
    elif seed % 3 == 0:  # coarse checkerboard
        cells = ((xs // 80 + ys // 80) % 2) * 200 + 30
        rgb = np.stack([cells, 255 - cells, (cells // 2)], axis=-1).astype(np.uint8)
    else:  # concentric rings
        radius = np.sqrt((xs - width / 2) ** 2 + (ys - height / 2) ** 2)
        rings = ((radius // 40) % 2) * 220 + 20
        rgb = np.stack([(rings // 3), rings, (255 - rings)], axis=-1).astype(np.uint8)
    img = Image.fromarray(rgb, "RGB")
    draw = ImageDraw.Draw(img)
    draw.rectangle([40 + 60 * seed, 60, 140 + 60 * seed, 220], fill=(20 * seed, 200, 90))
    draw.text((20, 440), label, fill=(255, 255, 255))
    out = BytesIO()
    img.save(out, format="JPEG", quality=88)
    return out.getvalue()


def candidate(
    url: str, source_type: SourceType, *, filename: str, page: str, hint: Category | None = None
) -> RawCandidate:
    return RawCandidate(
        source_type=source_type,
        image_url=url,
        source_page_url=page,
        source_label="Wikimedia Commons",
        title=None,
        date="2019-05-04",
        date_kind="taken",
        page_title=f"File:{filename}",
        filename=filename,
        source_hint_category=hint,
    )


class FakeSource:
    def __init__(
        self,
        name: str,
        source_type: SourceType,
        candidates: list[RawCandidate],
        *,
        fail: BaseException | None = None,
        sleep: float = 0.0,
    ) -> None:
        self.name = name
        self.source_type = source_type
        self._candidates = candidates
        self._fail = fail
        self._sleep = sleep

    async def fetch(self, ctx: SourceContext) -> SourceResult:
        if self._sleep:
            await asyncio.sleep(self._sleep)
        if self._fail is not None:
            raise self._fail
        return SourceResult(
            name=self.name, source_type=self.source_type, candidates=list(self._candidates)
        )


def resolved_entity(*, coords: bool = True) -> ResolvedEntity:
    header = UniversityHeader(
        qid=QID,
        name=NAME,
        local_name="Тествилльский технологический институт",
        aliases=["TIT", "Testville Tech"],
        country="Testland",
        coords=Coordinates(lat=10.0, lon=20.0) if coords else None,
        official_website="https://tit.example.org",
        commons_category="Testville Institute of Technology",
    )
    return ResolvedEntity(
        header=header, main_image_filename=None, logo_filename=None, wiki_titles={}, raw={}
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(gemini_api_key=None, flickr_api_key=None, cache_dir=tmp_path)


@pytest.fixture
async def api(settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac,
    ):
        yield ac


def mock_images() -> None:
    a = photo_bytes(1, label="campus a")
    respx.get(IMG_A).mock(
        return_value=httpx.Response(200, content=a, headers={"Content-Type": "image/jpeg"})
    )
    respx.get(IMG_A_COPY).mock(
        return_value=httpx.Response(200, content=a, headers={"Content-Type": "image/jpeg"})
    )
    respx.get(IMG_B).mock(
        return_value=httpx.Response(
            200, content=photo_bytes(3, label="library b"), headers={"Content-Type": "image/jpeg"}
        )
    )
    respx.get(IMG_C).mock(
        return_value=httpx.Response(
            200, content=photo_bytes(5, label="dorm c"), headers={"Content-Type": "image/jpeg"}
        )
    )
    respx.get(IMG_BROKEN).mock(return_value=httpx.Response(500))


def fake_sources(monkeypatch: pytest.MonkeyPatch, *, timeout_source: bool = False) -> None:
    page = "https://commons.wikimedia.org/wiki/File:{}"
    category = [
        candidate(
            IMG_A,
            SourceType.commons_category,
            filename="Testville Institute of Technology main building.jpg",
            page=page.format("A.jpg"),
        ),
        candidate(
            IMG_B,
            SourceType.commons_category,
            filename="Reading room.jpg",
            page=page.format("B.jpg"),
            hint=Category.library,
        ),
        candidate(
            IMG_BROKEN,
            SourceType.commons_category,
            filename="Broken.jpg",
            page=page.format("X.jpg"),
        ),
    ]
    search = [
        candidate(
            IMG_A_COPY,
            SourceType.commons_search,
            filename="Testville Tech campus again.jpg",
            page=page.format("A2.jpg"),
        ),
        candidate(
            IMG_C,
            SourceType.commons_search,
            filename="Student dormitory block.jpg",
            page=page.format("C.jpg"),
        ),
    ]
    sources: list[Any] = [
        FakeSource("commons_category", SourceType.commons_category, category),
        FakeSource("commons_search", SourceType.commons_search, search),
        FakeSource("commons_geo", SourceType.commons_geo, [], fail=RuntimeError("boom")),
    ]
    if timeout_source:
        sources.append(FakeSource("wikidata_p18", SourceType.wikidata_p18, [], sleep=2.0))
        monkeypatch.setattr(pipeline, "SOURCE_TIMEOUT_S", 0.2)
    monkeypatch.setattr(pipeline, "build_sources", lambda settings: sources)


async def fake_resolve(client: httpx.AsyncClient, qid: str) -> ResolvedEntity | None:
    if qid == QID:
        return resolved_entity()
    if qid == "Q503":
        raise ResolverUnavailableError("wikidata down")
    return None


@respx.mock
async def test_profile_end_to_end(
    api: AsyncClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_images()
    fake_sources(monkeypatch, timeout_source=True)
    monkeypatch.setattr(pipeline, "resolve_university", fake_resolve)

    response = await api.get(f"/api/profile/{QID}", params={"refresh": 1})
    assert response.status_code == 200, response.text
    profile = response.json()

    header = profile["header"]
    assert header["name"] == NAME and header["cached"] is False
    stats = profile["stats"]
    assert stats["found"] == 5  # 5 distinct URLs after normalization
    assert stats["duplicates_removed"] == 1  # A and its byte-identical copy
    assert stats["per_source"] == {
        "commons_category": 3,
        "commons_search": 2,
        "commons_geo": 0,
        "wikidata_p18": 0,
    }
    assert set(stats["timings_ms"]) == {
        "resolve",
        "collect",
        "download",
        "dedup",
        "vision",
        "describe",
        "total",
    }
    assert stats["total_ms"] == stats["timings_ms"]["total"]

    photos = profile["photos"]
    assert len(photos) == 3  # A (representative), B, C; the broken download is gone
    assert stats["shown"] + stats["hidden_unverified"] == len(photos)
    by_url = {p["image_url"]: p for p in photos}
    assert IMG_A in by_url and IMG_A_COPY not in by_url  # commons_category wins the group
    for photo in photos:
        assert photo["source_page_url"].startswith("https://commons.wikimedia.org/wiki/File:")
        assert photo["thumb_url"] == f"/api/thumb/{photo['id']}.jpg"
        assert (settings.thumbs_dir / f"{photo['id']}.jpg").is_file()
        assert photo["verification"] in ("likely", "unverified")  # no vision -> never verified
        assert "vision_unavailable" in photo["reasons"]
        assert "category_heuristic" in photo["reasons"]
        assert photo["date"] == "2019-05-04" and photo["date_kind"] == "taken"
        assert photo["width"] == 640 and photo["height"] == 480
    assert by_url[IMG_A]["confidence"] == 0.75  # 0.55 + 0.20 name in filename
    assert by_url[IMG_A]["verification"] == "likely"
    assert by_url[IMG_A]["category"] == "campus"
    assert (
        by_url[IMG_B]["category"] == "library" and by_url[IMG_B]["category_source"] == "source_hint"
    )
    assert (
        by_url[IMG_C]["category"] == "dormitory" and by_url[IMG_C]["category_source"] == "heuristic"
    )
    assert by_url[IMG_C]["confidence"] == 0.25 and by_url[IMG_C]["verification"] == "unverified"

    codes = {(w["code"], w.get("detail")) for w in profile["warnings"]}
    assert (WarningCode.vision_unavailable.value, "GEMINI_API_KEY is not set") in codes
    assert (WarningCode.source_unavailable.value, "commons_geo") in codes
    assert (WarningCode.source_unavailable.value, "wikidata_p18") in codes  # timed out
    assert (WarningCode.low_data.value, None) in codes
    assert (WarningCode.missing_category.value, "classroom") in codes
    assert (WarningCode.missing_category.value, "city") in codes
    assert (WarningCode.missing_category.value, "dormitory") in codes  # C is hidden
    assert (WarningCode.no_coordinates.value, None) not in codes

    thumb = await api.get(by_url[IMG_A]["thumb_url"])
    assert thumb.status_code == 200
    assert thumb.headers["content-type"] == "image/jpeg"
    assert thumb.headers["cache-control"] == "public, max-age=86400"
    assert thumb.content[:2] == b"\xff\xd8"


@respx.mock
async def test_profile_without_coords_warns(
    api: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_images()
    fake_sources(monkeypatch)

    async def resolve(client: httpx.AsyncClient, qid: str) -> ResolvedEntity | None:
        return resolved_entity(coords=False)

    monkeypatch.setattr(pipeline, "resolve_university", resolve)
    response = await api.get(f"/api/profile/{QID}")
    assert response.status_code == 200
    codes = {w["code"] for w in response.json()["warnings"]}
    assert "no_coordinates" in codes


async def test_profile_404_and_503_and_422(
    api: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "resolve_university", fake_resolve)
    not_found = await api.get("/api/profile/Q999")
    assert not_found.status_code == 404
    assert not_found.json()["error"]["code"] == "not_found"
    unavailable = await api.get("/api/profile/Q503")
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "resolver_unavailable"
    bad = await api.get("/api/profile/abc")
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "validation_error"
    bad_refresh = await api.get(f"/api/profile/{QID}", params={"refresh": 2})
    assert bad_refresh.status_code == 422


def test_normalize_candidates_caps_and_merge() -> None:
    page = "https://commons.wikimedia.org/wiki/File:{}"
    geo = Coordinates(lat=1.0, lon=2.0)
    category = SourceResult(
        name="commons_category",
        source_type=SourceType.commons_category,
        candidates=[
            candidate(
                f"https://x/{i}.jpg",
                SourceType.commons_category,
                filename=f"{i}.jpg",
                page=page.format(i),
            )
            for i in range(130)
        ],
    )
    dup = candidate(
        "https://x/3.jpg", SourceType.commons_geo, filename="3.jpg", page=page.format(3)
    )
    dup.geo, dup.distance_m = geo, 120.0
    geo_result = SourceResult(
        name="commons_geo", source_type=SourceType.commons_geo, candidates=[dup]
    )
    city = SourceResult(
        name="city_commons",
        source_type=SourceType.city_commons,
        candidates=[
            candidate(
                f"https://c/{i}.jpg",
                SourceType.city_commons,
                filename=f"c{i}.jpg",
                page=page.format(f"c{i}"),
            )
            for i in range(25)
        ],
    )
    result = normalize_candidates([city, geo_result, category], max_candidates=120)
    assert result.found == 140  # 120 non-city + 20 city
    assert result.dropped_duplicate_urls == 1
    assert result.dropped_by_caps == 15  # 10 category + 5 city
    kept_types = [c.source_type for c in result.candidates]
    assert kept_types[:120] == [SourceType.commons_category] * 120  # priority order preserved
    merged = next(c for c in result.candidates if c.image_url == "https://x/3.jpg")
    assert merged.source_type is SourceType.commons_category  # higher priority wins...
    assert merged.geo == geo and merged.distance_m == 120.0  # ...but the geo signal is borrowed
    assert Verification.likely is not None and ReasonCode.category_heuristic is not None
