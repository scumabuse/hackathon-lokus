"""Stage D download (Section 8): size / type / aspect rules, hashing, thumbnails, timeouts,
stage budget, Wikimedia semaphore, logo hashes and the atomic thumbnail write.

Every HTTP call is mocked with respx (httpcore level), so ``client.stream`` really streams the
mocked body and an un-iterated body generator proves the body was never read.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import time
from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from PIL import Image

from app.enums import SourceType
from app.models import RawCandidate
from app.processing import download
from app.processing.download import (
    MAX_BYTES,
    THUMB_LONG_SIDE,
    WIKIMEDIA_CONCURRENCY,
    DownloadResult,
    download_candidates,
    fetch_logo_hashes,
    is_wikimedia_upload,
    wikimedia_semaphore,
    write_atomic,
)

HOST = "https://images.example.org"
JPEG_HEADERS = {"Content-Type": "image/jpeg"}

# ------------------------------------------------------------------------------------ helpers


def image_bytes(
    width: int, height: int, *, fmt: str = "JPEG", mode: str = "RGB", **save_kwargs: Any
) -> bytes:
    """Pillow-generated image bytes: a gradient so the JPEG has real content."""
    img = Image.linear_gradient("L").resize((width, height), Image.BILINEAR).convert(mode)
    out = BytesIO()
    img.save(out, format=fmt, **save_kwargs)
    return out.getvalue()


def candidate(url: str, source_type: SourceType = SourceType.commons_search) -> RawCandidate:
    return RawCandidate(
        source_type=source_type,
        image_url=url,
        source_page_url=url.rsplit("/", 1)[0],
        source_label="example",
    )


async def run(
    client: httpx.AsyncClient, candidates: list[RawCandidate], thumbs_dir: Path, **kwargs: Any
) -> DownloadResult:
    return await download_candidates(
        client, candidates, thumbs_dir=thumbs_dir, concurrency=4, **kwargs
    )


def no_temp_files(thumbs_dir: Path) -> bool:
    return not list(thumbs_dir.glob("*.tmp*"))


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as ac:
        yield ac


# --------------------------------------------------------------------------------- happy path


async def test_success_path_builds_processed_image(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    data = image_bytes(600, 400, quality=90)
    url = f"{HOST}/campus/main.jpg"
    cand = candidate(url)
    with respx.mock(assert_all_called=True) as router:
        router.get(url).mock(return_value=httpx.Response(200, content=data, headers=JPEG_HEADERS))
        result = await run(client, [cand], tmp_path)

    assert (result.failed, result.timed_out) == (0, 0)
    assert len(result.images) == 1
    image = result.images[0]
    assert image.candidate == cand
    assert image.photo_id == cand.photo_id
    assert (image.width, image.height) == (600, 400)
    assert image.sha1 == hashlib.sha1(data).hexdigest()
    assert len(image.sha1) == 40
    assert len(image.phash) == 16
    int(image.phash, 16)  # hex

    thumb_path = tmp_path / f"{cand.photo_id}.jpg"
    assert image.thumb_path == str(thumb_path)
    assert thumb_path.is_file()
    thumb_bytes = thumb_path.read_bytes()
    assert base64.b64decode(image.thumb_b64) == thumb_bytes
    with Image.open(BytesIO(thumb_bytes)) as thumb:
        assert thumb.format == "JPEG"
        assert max(thumb.size) == THUMB_LONG_SIDE == 512
        assert thumb.size == (512, 341)
    assert no_temp_files(tmp_path)


async def test_small_image_is_not_upscaled(client: httpx.AsyncClient, tmp_path: Path) -> None:
    url = f"{HOST}/small.jpg"
    with respx.mock() as router:
        router.get(url).mock(
            return_value=httpx.Response(200, content=image_bytes(300, 260), headers=JPEG_HEADERS)
        )
        result = await run(client, [candidate(url)], tmp_path)
    assert len(result.images) == 1
    with Image.open(BytesIO(base64.b64decode(result.images[0].thumb_b64))) as thumb:
        assert thumb.size == (300, 260)


async def test_images_come_back_in_input_order(client: httpx.AsyncClient, tmp_path: Path) -> None:
    data = image_bytes(400, 300)
    delays = {f"{HOST}/{i}.jpg": delay for i, delay in enumerate((0.15, 0.0, 0.05))}

    async def serve(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(delays[str(request.url)])
        return httpx.Response(200, content=data, headers=JPEG_HEADERS)

    cands = [candidate(url) for url in delays]
    with respx.mock() as router:
        router.get(url__startswith=HOST).mock(side_effect=serve)
        result = await run(client, cands, tmp_path)
    assert [img.photo_id for img in result.images] == [c.photo_id for c in cands]


async def test_empty_candidate_list(client: httpx.AsyncClient, tmp_path: Path) -> None:
    assert await run(client, [], tmp_path / "unused") == DownloadResult()
    assert not (tmp_path / "unused").exists()


# ------------------------------------------------------------------------- Section 8 rejections


@pytest.mark.parametrize(
    ("width", "height", "why"),
    [
        (200, 200, "min side < 250"),
        (249, 600, "min side < 250"),
        (2000, 300, "aspect > 3.5"),
        (300, 2000, "aspect < 0.28"),
    ],
)
async def test_size_and_aspect_rejections(
    client: httpx.AsyncClient, tmp_path: Path, width: int, height: int, why: str
) -> None:
    url = f"{HOST}/{width}x{height}.jpg"
    with respx.mock() as router:
        router.get(url).mock(
            return_value=httpx.Response(
                200, content=image_bytes(width, height), headers=JPEG_HEADERS
            )
        )
        result = await run(client, [candidate(url)], tmp_path)
    assert result.images == [], why
    assert (result.failed, result.timed_out) == (1, 0)
    assert list(tmp_path.iterdir()) == []


async def test_boundary_sizes_are_accepted(client: httpx.AsyncClient, tmp_path: Path) -> None:
    urls = {f"{HOST}/250x250.jpg": (250, 250), f"{HOST}/875x250.jpg": (875, 250)}  # 3.5 exactly
    with respx.mock() as router:
        for url, (w, h) in urls.items():
            router.get(url).mock(
                return_value=httpx.Response(200, content=image_bytes(w, h), headers=JPEG_HEADERS)
            )
        result = await run(client, [candidate(u) for u in urls], tmp_path)
    assert len(result.images) == 2


async def test_text_html_content_type_is_rejected(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    url = f"{HOST}/page.jpg"
    with respx.mock() as router:
        router.get(url).mock(
            return_value=httpx.Response(
                200, content=image_bytes(600, 400), headers={"Content-Type": "text/html"}
            )
        )
        result = await run(client, [candidate(url)], tmp_path)
    assert result.images == []
    assert result.failed == 1


async def test_missing_content_type_with_valid_jpeg_is_accepted(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    url = f"{HOST}/no-type.jpg"
    with respx.mock() as router:
        router.get(url).mock(return_value=httpx.Response(200, content=image_bytes(600, 400)))
        result = await run(client, [candidate(url)], tmp_path)
    assert len(result.images) == 1
    assert result.failed == 0


async def test_missing_content_type_with_garbage_is_rejected(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    url = f"{HOST}/garbage.jpg"
    with respx.mock() as router:
        router.get(url).mock(return_value=httpx.Response(200, content=b"<html>not an image"))
        result = await run(client, [candidate(url)], tmp_path)
    assert result.images == []
    assert result.failed == 1


async def test_content_length_over_4mb_rejected_before_reading_body(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    consumed = False

    async def body() -> AsyncIterator[bytes]:
        nonlocal consumed
        consumed = True
        yield b"\xff"

    url = f"{HOST}/huge.jpg"
    headers = {"Content-Type": "image/jpeg", "Content-Length": str(MAX_BYTES + 1)}
    with respx.mock() as router:
        router.get(url).mock(return_value=httpx.Response(200, content=body(), headers=headers))
        result = await run(client, [candidate(url)], tmp_path)
    assert result.images == []
    assert result.failed == 1
    assert consumed is False


async def test_content_length_exactly_4mb_is_read(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    # the limit is "> 4 MB": a declared 4 MB body is streamed (and then fails to decode)
    url = f"{HOST}/four-mb.jpg"
    headers = {"Content-Type": "image/jpeg", "Content-Length": str(MAX_BYTES)}
    consumed = False

    async def body() -> AsyncIterator[bytes]:
        nonlocal consumed
        consumed = True
        yield b"\xff" * MAX_BYTES

    with respx.mock() as router:
        router.get(url).mock(return_value=httpx.Response(200, content=body(), headers=headers))
        result = await run(client, [candidate(url)], tmp_path)
    assert consumed is True
    assert result.failed == 1  # not decodable


async def test_body_growing_past_4mb_is_aborted(client: httpx.AsyncClient, tmp_path: Path) -> None:
    chunks_served = 0
    chunk = b"\xff" * (1024 * 1024)

    async def body() -> AsyncIterator[bytes]:
        nonlocal chunks_served
        for _ in range(8):
            chunks_served += 1
            yield chunk

    url = f"{HOST}/growing.jpg"
    with respx.mock() as router:
        router.get(url).mock(return_value=httpx.Response(200, content=body(), headers=JPEG_HEADERS))
        result = await run(client, [candidate(url)], tmp_path)
    assert result.images == []
    assert result.failed == 1
    assert chunks_served == 5  # aborted as soon as the accumulated bytes exceeded 4 MB


async def test_http_404_is_rejected(client: httpx.AsyncClient, tmp_path: Path) -> None:
    url = f"{HOST}/missing.jpg"
    with respx.mock() as router:
        router.get(url).mock(return_value=httpx.Response(404, content=b"gone"))
        result = await run(client, [candidate(url)], tmp_path)
    assert result.images == []
    assert result.failed == 1


async def test_connect_error_is_rejected(client: httpx.AsyncClient, tmp_path: Path) -> None:
    url = f"{HOST}/unreachable.jpg"
    with respx.mock() as router:
        router.get(url).mock(side_effect=httpx.ConnectError)
        result = await run(client, [candidate(url)], tmp_path)
    assert result.images == []
    assert (result.failed, result.timed_out) == (1, 0)


async def test_truncated_image_bytes_are_rejected(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    url = f"{HOST}/truncated.jpg"
    data = image_bytes(600, 400)[:2000]
    with respx.mock() as router:
        router.get(url).mock(return_value=httpx.Response(200, content=data, headers=JPEG_HEADERS))
        result = await run(client, [candidate(url)], tmp_path)
    assert result.images == []
    assert result.failed == 1


# ------------------------------------------------------------------------------- decode rules


async def test_exif_rotated_jpeg_is_transposed(client: httpx.AsyncClient, tmp_path: Path) -> None:
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90 CW to display -> width/height swap
    data = image_bytes(600, 300, exif=exif)
    url = f"{HOST}/rotated.jpg"
    with respx.mock() as router:
        router.get(url).mock(return_value=httpx.Response(200, content=data, headers=JPEG_HEADERS))
        result = await run(client, [candidate(url)], tmp_path)
    assert len(result.images) == 1
    image = result.images[0]
    assert (image.width, image.height) == (300, 600)
    with Image.open(BytesIO(base64.b64decode(image.thumb_b64))) as thumb:
        assert thumb.size == (256, 512)


async def test_png_with_alpha_is_converted(client: httpx.AsyncClient, tmp_path: Path) -> None:
    data = image_bytes(400, 400, fmt="PNG", mode="RGBA")
    url = f"{HOST}/alpha.png"
    with respx.mock() as router:
        router.get(url).mock(
            return_value=httpx.Response(200, content=data, headers={"Content-Type": "image/png"})
        )
        result = await run(client, [candidate(url)], tmp_path)
    assert len(result.images) == 1
    with Image.open(BytesIO(base64.b64decode(result.images[0].thumb_b64))) as thumb:
        assert thumb.format == "JPEG"
        assert thumb.mode == "RGB"
        assert thumb.size == (400, 400)


# ---------------------------------------------------------------------------------- timeouts


async def test_per_image_timeout_is_enforced(
    client: httpx.AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(download, "IMAGE_TIMEOUT_S", 0.2)
    data = image_bytes(600, 400)

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1.0)
        return httpx.Response(200, content=data, headers=JPEG_HEADERS)

    url = f"{HOST}/slow.jpg"
    # a side effect cancelled mid-sleep never records its call -> no assert_all_called
    with respx.mock(assert_all_called=False) as router:
        router.get(url).mock(side_effect=slow)
        started = time.monotonic()
        result = await run(client, [candidate(url)], tmp_path)
    assert time.monotonic() - started < 0.9
    assert result.images == []
    assert (result.failed, result.timed_out) == (1, 0)


async def test_stage_timeout_returns_partial_results(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    data = image_bytes(600, 400)

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(2.0)
        return httpx.Response(200, content=data, headers=JPEG_HEADERS)

    fast_url, slow_url = f"{HOST}/fast.jpg", f"{HOST}/slow.jpg"
    with respx.mock(assert_all_called=False) as router:
        router.get(fast_url).mock(
            return_value=httpx.Response(200, content=data, headers=JPEG_HEADERS)
        )
        router.get(slow_url).mock(side_effect=slow)
        started = time.monotonic()
        result = await run(
            client, [candidate(fast_url), candidate(slow_url)], tmp_path, stage_timeout_s=0.3
        )
    assert time.monotonic() - started < 1.5
    assert [img.candidate.image_url for img in result.images] == [fast_url]
    assert (result.failed, result.timed_out) == (0, 1)


async def test_deadline_already_passed_skips_every_download(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    urls = [f"{HOST}/{i}.jpg" for i in range(3)]
    with respx.mock(assert_all_called=False) as router:
        route = router.get(url__startswith=HOST).mock(
            return_value=httpx.Response(200, content=image_bytes(600, 400), headers=JPEG_HEADERS)
        )
        result = await run(
            client, [candidate(u) for u in urls], tmp_path, deadline=time.monotonic() - 1.0
        )
    assert result.images == []
    assert (result.failed, result.timed_out) == (0, 3)
    assert route.called is False
    assert router.calls.call_count == 0


async def test_deadline_closer_than_stage_timeout_wins(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(2.0)
        return httpx.Response(200, content=image_bytes(600, 400), headers=JPEG_HEADERS)

    url = f"{HOST}/slow.jpg"
    with respx.mock(assert_all_called=False) as router:
        router.get(url).mock(side_effect=slow)
        started = time.monotonic()
        result = await run(
            client,
            [candidate(url)],
            tmp_path,
            stage_timeout_s=30.0,
            deadline=time.monotonic() + 0.2,
        )
    assert time.monotonic() - started < 1.5
    assert result.timed_out == 1


# ------------------------------------------------------------------------------- concurrency


def test_wikimedia_concurrency_constant() -> None:
    assert WIKIMEDIA_CONCURRENCY == 8


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://thumb.wikimedia.org/x.jpg?utm_source=a", True),
        ("https://upload.wikimedia.org/wikipedia/commons/a/ab/X.jpg", True),
        ("https://UPLOAD.wikimedia.org/x.jpg", True),
        ("http://upload.wikimedia.org/x.jpg", True),
        ("https://cdn.upload.wikimedia.org/x.jpg", True),
        ("https://commons.wikimedia.org/wiki/File:X.jpg", False),
        ("https://www.wikimedia.org/x.jpg", False),
        ("https://notupload.wikimedia.org/x.jpg", False),
        ("https://example.org/upload.wikimedia.org/x.jpg", False),
        ("https://images.example.org/x.jpg", False),
        ("not a url", False),
        ("", False),
    ],
)
def test_is_wikimedia_upload(url: str, expected: bool) -> None:
    assert is_wikimedia_upload(url) is expected


async def test_wikimedia_semaphore_is_one_per_loop_and_host_with_8_slots() -> None:
    semaphore = wikimedia_semaphore()
    assert wikimedia_semaphore() is semaphore
    assert wikimedia_semaphore("upload.wikimedia.org") is semaphore
    assert wikimedia_semaphore("cdn.upload.wikimedia.org") is semaphore  # subdomains fold in
    assert wikimedia_semaphore("thumb.wikimedia.org") is not semaphore  # a separate service
    assert semaphore._value == WIKIMEDIA_CONCURRENCY


@pytest.mark.parametrize(
    ("upload_count", "thumb_count", "expected_peak"),
    [(12, 0, 8), (0, 12, 8), (6, 6, 12)],  # 8 slots per Wikimedia host, not shared
)
async def test_each_wikimedia_host_has_its_own_8_slot_limit(
    client: httpx.AsyncClient,
    tmp_path: Path,
    upload_count: int,
    thumb_count: int,
    expected_peak: int,
) -> None:
    data = image_bytes(400, 300)
    in_flight = 0
    peak = 0

    async def serve(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1
        return httpx.Response(200, content=data, headers=JPEG_HEADERS)

    urls = [f"https://upload.wikimedia.org/wikipedia/commons/{i}.jpg" for i in range(upload_count)]
    urls += [f"https://thumb.wikimedia.org/{i}.jpg?utm_source=x" for i in range(thumb_count)]
    with respx.mock() as router:
        router.get(url__regex=r"https://(upload|thumb)\.wikimedia\.org/.*").mock(side_effect=serve)
        result = await download_candidates(
            client, [candidate(u) for u in urls], thumbs_dir=tmp_path, concurrency=16
        )
    assert len(result.images) == 12
    assert peak == expected_peak


async def test_global_concurrency_limit_applies_to_other_hosts(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    data = image_bytes(400, 300)
    in_flight = 0
    peak = 0

    async def serve(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1
        return httpx.Response(200, content=data, headers=JPEG_HEADERS)

    urls = [f"{HOST}/{i}.jpg" for i in range(9)]
    with respx.mock() as router:
        router.get(url__startswith=HOST).mock(side_effect=serve)
        result = await download_candidates(
            client, [candidate(u) for u in urls], thumbs_dir=tmp_path, concurrency=3
        )
    assert len(result.images) == 9
    assert peak == 3


# ------------------------------------------------------------------------------- logo hashes


async def test_fetch_logo_hashes_accepts_a_tiny_image(client: httpx.AsyncClient) -> None:
    data = image_bytes(100, 100, fmt="PNG")
    url = "https://upload.wikimedia.org/wikipedia/commons/l/l0/Logo.png"
    with respx.mock() as router:
        router.get(url).mock(
            return_value=httpx.Response(200, content=data, headers={"Content-Type": "image/png"})
        )
        hashes = await fetch_logo_hashes(client, url)
    assert hashes is not None
    sha1, phash = hashes
    assert sha1 == hashlib.sha1(data).hexdigest()
    assert len(phash) == 16
    int(phash, 16)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404, content=b"gone"),
        httpx.Response(200, content=b"not an image", headers={"Content-Type": "image/png"}),
        httpx.Response(200, content=b"<html>", headers={"Content-Type": "text/html"}),
    ],
)
async def test_fetch_logo_hashes_returns_none_on_failure(
    client: httpx.AsyncClient, response: httpx.Response
) -> None:
    url = f"{HOST}/logo.png"
    with respx.mock() as router:
        router.get(url).mock(return_value=response)
        assert await fetch_logo_hashes(client, url) is None


async def test_fetch_logo_hashes_returns_none_on_connect_error(client: httpx.AsyncClient) -> None:
    url = f"{HOST}/logo.png"
    with respx.mock() as router:
        router.get(url).mock(side_effect=httpx.ConnectError)
        assert await fetch_logo_hashes(client, url) is None


# -------------------------------------------------------------------------------- atomic write


def test_write_atomic_writes_and_leaves_no_temp_file(tmp_path: Path) -> None:
    target = tmp_path / "abc.jpg"
    write_atomic(target, b"first")
    assert target.read_bytes() == b"first"
    write_atomic(target, b"second")  # overwrite an existing thumbnail
    assert target.read_bytes() == b"second"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["abc.jpg"]


def test_write_atomic_cleans_up_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_replace(src: Any, dst: Any) -> None:
        raise OSError("disk went away")

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError, match="disk went away"):
        write_atomic(tmp_path / "abc.jpg", b"data")
    assert list(tmp_path.iterdir()) == []


async def test_failed_thumbnail_write_is_counted_and_leaves_nothing(
    client: httpx.AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_replace(src: Any, dst: Any) -> None:
        raise OSError("read-only")

    monkeypatch.setattr(os, "replace", failing_replace)
    url = f"{HOST}/main.jpg"
    with respx.mock() as router:
        router.get(url).mock(
            return_value=httpx.Response(200, content=image_bytes(600, 400), headers=JPEG_HEADERS)
        )
        result = await run(client, [candidate(url)], tmp_path)
    assert result.images == []
    assert result.failed == 1
    assert list(tmp_path.iterdir()) == []


async def test_thumbnail_name_is_photo_id_and_no_temp_files_remain(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    data = image_bytes(600, 400)
    cands = [candidate(f"{HOST}/{i}.jpg") for i in range(4)]
    with respx.mock() as router:
        router.get(url__startswith=HOST).mock(
            return_value=httpx.Response(200, content=data, headers=JPEG_HEADERS)
        )
        result = await run(client, cands, tmp_path)
    assert len(result.images) == 4
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(f"{c.photo_id}.jpg" for c in cands)
    assert no_temp_files(tmp_path)


# --------------------------------------------------------------------------------- 403 fallback


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://upload.wikimedia.org/wikipedia/commons/4/43/Building62and64.jpg?utm_source=x",
            (
                "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/43/Building62and64.jpg/"
                "500px-Building62and64.jpg"
            ),
        ),
        (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/5/55/BEC1.1.jpg/640px-BEC1.1.jpg",
            "https://thumb.wikimedia.org/wikipedia/commons/thumb/5/55/BEC1.1.jpg/500px-BEC1.1.jpg",
        ),
        (
            "https://thumb.wikimedia.org/wikipedia/commons/thumb/5/55/BEC1.1.jpg/960px-BEC1.1.jpg",
            None,
        ),
        ("https://example.org/wikipedia/commons/4/43/x.jpg", None),
        ("https://upload.wikimedia.org/other/path.jpg", None),
        ("not a url", None),
    ],
)
def test_blocked_fallback_url(url: str, expected: str | None) -> None:
    assert download.blocked_fallback_url(url) == expected


@respx.mock
async def test_403_from_upload_host_falls_back_to_thumb_host(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    original = "https://upload.wikimedia.org/wikipedia/commons/4/43/Building62and64.jpg"
    fallback = download.blocked_fallback_url(original)
    assert fallback is not None
    respx.get(original).mock(return_value=httpx.Response(403, text="Please honor our robot policy"))
    fallback_route = respx.get(fallback).mock(
        return_value=httpx.Response(
            200, content=image_bytes(600, 400), headers={"Content-Type": "image/jpeg"}
        )
    )
    result = await run(client, [candidate(original)], tmp_path)
    assert fallback_route.called
    assert len(result.images) == 1
    assert result.images[0].candidate.image_url == original  # the photo keeps its original URL
    assert result.failed == 0


@respx.mock
async def test_403_elsewhere_is_not_retried(client: httpx.AsyncClient, tmp_path: Path) -> None:
    url = "https://cdn.example.org/campus.jpg"
    route = respx.get(url).mock(return_value=httpx.Response(403))
    result = await run(client, [candidate(url)], tmp_path)
    assert route.call_count == 1
    assert result.images == [] and result.failed == 1
