"""Stage D: parallel image download, validation, hashing and 512 px thumbnails (SPEC Section 8).

Rules encoded here (Section 8 and the Section 20 pitfalls):

* global ``Semaphore(concurrency)`` plus a dedicated 8-slot semaphore shared by every Wikimedia
  media host -- ``upload.wikimedia.org`` and ``thumb.wikimedia.org`` (where Commons thumburls are
  served from) with their subdomains -- because they answer 429 under higher parallelism;
* per image: 6 s timeout (httpx read/write and a wall-clock guard), streamed body, abort when
  ``Content-Length`` or the accumulated bytes exceed 4 MB, ``Content-Type`` must start with
  ``image/`` when present (missing header -> try to decode anyway);
* decode in a thread with ``MAX_IMAGE_PIXELS`` set, EXIF-transpose, RGB; reject ``min(w, h) < 250``
  or an aspect ratio outside ``[0.28, 3.5]``;
* sha1 of the raw bytes, pHash (hash_size 8), JPEG thumbnail (long side 512, quality 82) written
  atomically (``{photo_id}.jpg.tmp-<random>`` then ``os.replace``) to ``thumbs_dir/{photo_id}.jpg``
  so ``/api/thumb`` never serves a half-written file, and kept as base64 for the vision batch;
* the stage returns whatever finished within its budget; the rest is cancelled and counted.

Nothing here raises for an external problem: every per-image failure is logged and counted.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import logging
import os
import re
import secrets
import time
import weakref
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

import httpx
import imagehash
from PIL import Image, ImageOps

from app.models import ProcessedImage, RawCandidate

log = logging.getLogger("app.processing.download")

# Section 8 / Section 20: decompression-bomb guard, set once for the whole process.
MAX_IMAGE_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

IMAGE_TIMEOUT_S = 6.0  # per image: httpx read/write/pool timeout AND the wall-clock guard
IMAGE_CONNECT_TIMEOUT_S = 4.0
MAX_BYTES = 4 * 1024 * 1024
MIN_SIDE_PX = 250
MAX_ASPECT = 3.5
MIN_ASPECT = 0.28
THUMB_LONG_SIDE = 512
THUMB_QUALITY = 82
DEFAULT_STAGE_TIMEOUT_S = 8.0
ACCEPT_HEADER = "image/*,*/*;q=0.8"
# hosts (and their subdomains) that share the 8-slot semaphore (Section 8 / Section 20)
WIKIMEDIA_MEDIA_HOSTS: tuple[str, ...] = ("upload.wikimedia.org", "thumb.wikimedia.org")
WIKIMEDIA_CONCURRENCY = 8
# upload.wikimedia.org enforces the robot policy against generic contacts (HTTP 403); the
# thumbnailer on thumb.wikimedia.org still serves a scaled rendering (500 px is accepted).
FALLBACK_THUMB_WIDTH = 500
_COMMONS_FILE_PATH_RE = re.compile(
    r"^/wikipedia/commons/(?:thumb/)?([0-9a-f])/([0-9a-f]{2})/([^/]+)"
)
SERVICE = "image"

_wikimedia_semaphores: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


@dataclass(slots=True)
class DownloadResult:
    """What Stage D produced: validated images (input order), plus the failure counters."""

    images: list[ProcessedImage] = field(default_factory=list)
    failed: int = 0  # HTTP error, timeout, size/type rejection, decode error, thumbnail error
    timed_out: int = 0  # still running when the stage budget ran out (cancelled)


@dataclass(slots=True)
class DecodedImage:
    """Result of the thread-side decode: the RGB image and the hashes of the raw bytes."""

    image: Image.Image
    sha1: str
    phash: str
    width: int
    height: int


class DownloadRejected(Exception):
    """A download or decode that violated a Section 8 rule (never propagates out of the stage)."""


def wikimedia_semaphore() -> asyncio.Semaphore:
    """The 8-slot semaphore shared by the Wikimedia media hosts, one per event loop.

    asyncio primitives bind to the loop that first waits on them, so a module-level instance
    would break under a second loop (tests); one instance per running loop is equivalent in
    production (``--workers 1``, one loop).
    """
    loop = asyncio.get_running_loop()
    semaphore = _wikimedia_semaphores.get(loop)
    if semaphore is None:
        semaphore = asyncio.Semaphore(WIKIMEDIA_CONCURRENCY)
        _wikimedia_semaphores[loop] = semaphore
    return semaphore


def is_wikimedia_upload(url: str) -> bool:
    """True when the URL's host is one of ``WIKIMEDIA_MEDIA_HOSTS`` or a subdomain of one.

    Query strings (``?utm_source=...`` on Commons thumburls) and case do not matter; anything
    unparseable is simply not Wikimedia.
    """
    try:
        host = httpx.URL(url).host.lower()
    except (httpx.InvalidURL, TypeError, ValueError):
        return False
    return any(host == known or host.endswith(f".{known}") for known in WIKIMEDIA_MEDIA_HOSTS)


def blocked_fallback_url(url: str) -> str | None:
    """A 500 px rendering on thumb.wikimedia.org for a Commons file that upload.wikimedia.org refused.

    Works for both original paths (``/wikipedia/commons/h/hh/File.jpg``) and scaled ones
    (``/wikipedia/commons/thumb/h/hh/File.jpg/640px-File.jpg``); ``None`` for any other URL.
    """
    try:
        parsed = httpx.URL(url)
    except (httpx.InvalidURL, TypeError, ValueError):
        return None
    if parsed.host.lower() != "upload.wikimedia.org":
        return None
    match = _COMMONS_FILE_PATH_RE.match(parsed.path)
    if match is None:
        return None
    h1, h2, name = match.groups()
    return (
        f"https://thumb.wikimedia.org/wikipedia/commons/thumb/{h1}/{h2}/{name}/"
        f"{FALLBACK_THUMB_WIDTH}px-{name}"
    )


def image_timeout() -> httpx.Timeout:
    return httpx.Timeout(IMAGE_TIMEOUT_S, connect=IMAGE_CONNECT_TIMEOUT_S)


# ----------------------------------------------------------------------------- network


async def fetch_image_bytes(client: httpx.AsyncClient, url: str) -> bytes:
    """Stream one image body under the Section 8 size / type rules; raises on any violation."""
    started = time.monotonic()
    try:
        async with asyncio.timeout(IMAGE_TIMEOUT_S):
            async with client.stream(
                "GET", url, headers={"Accept": ACCEPT_HEADER}, timeout=image_timeout()
            ) as response:
                if response.status_code != 200:
                    raise DownloadRejected(f"http {response.status_code}")
                content_type = response.headers.get("content-type")
                if content_type is not None and not content_type.strip().lower().startswith(
                    "image/"
                ):
                    raise DownloadRejected(f"content-type {content_type.split(';')[0]!r}")
                declared = response.headers.get("content-length")
                if declared is not None:
                    try:
                        declared_length = int(declared)
                    except ValueError:
                        declared_length = -1
                    if declared_length > MAX_BYTES:
                        raise DownloadRejected(f"content-length {declared_length} > {MAX_BYTES}")
                buffer = bytearray()
                async for chunk in response.aiter_bytes():
                    buffer += chunk
                    if len(buffer) > MAX_BYTES:
                        raise DownloadRejected(f"body exceeds {MAX_BYTES} bytes")
    except TimeoutError as exc:
        raise DownloadRejected(f"timeout after {IMAGE_TIMEOUT_S:.1f}s") from exc
    except httpx.HTTPError as exc:
        raise DownloadRejected(f"{type(exc).__name__}: {exc}") from exc
    if not buffer:
        raise DownloadRejected("empty body")
    log.debug(
        "%s GET %s -> 200 %d bytes %dms",
        SERVICE,
        url,
        len(buffer),
        int((time.monotonic() - started) * 1000),
    )
    return bytes(buffer)


# ----------------------------------------------------------------------------- image work (threads)


def decode_image(data: bytes) -> DecodedImage:
    """Section 8 decode: open, pixel-count guard, load, EXIF transpose, RGB, sha1 + pHash.

    Runs in a worker thread.  Pillow raises a zoo of exception types on hostile input
    (OSError, ValueError, SyntaxError, DecompressionBombError, ...); every one of them is turned
    into ``DownloadRejected`` so the caller has a single failure type.
    """
    try:
        img = Image.open(BytesIO(data))
        width, height = img.size
        if width * height > MAX_IMAGE_PIXELS:
            raise DownloadRejected(f"{width}x{height} exceeds {MAX_IMAGE_PIXELS} pixels")
        img.load()
        if img.mode == "P":  # palette + transparency: go through RGBA (Pillow warns otherwise)
            img = img.convert("RGBA")
        transposed = ImageOps.exif_transpose(img)
        rgb = (transposed if transposed is not None else img).convert("RGB")
    except DownloadRejected:
        raise
    except Exception as exc:
        log.debug("decode failed", exc_info=True)
        raise DownloadRejected(f"decode error: {type(exc).__name__}") from exc
    width, height = rgb.size
    return DecodedImage(
        image=rgb,
        sha1=hashlib.sha1(data).hexdigest(),
        phash=str(imagehash.phash(rgb)),
        width=width,
        height=height,
    )


def validate_size(width: int, height: int) -> None:
    """Section 8 rejection rules: min side 250 px, aspect ratio within [0.28, 3.5]."""
    if min(width, height) < MIN_SIDE_PX:
        raise DownloadRejected(f"too small: {width}x{height}")
    ratio = width / height
    if ratio > MAX_ASPECT or ratio < MIN_ASPECT:
        raise DownloadRejected(f"extreme aspect ratio {ratio:.2f}: {width}x{height}")


def make_thumbnail(img: Image.Image) -> bytes:
    """JPEG (quality 82) with the long side at most 512 px, LANCZOS, never upscaled."""
    width, height = img.size
    longest = max(width, height)
    thumb = img if img.mode == "RGB" else img.convert("RGB")
    if longest > THUMB_LONG_SIDE:
        scale = THUMB_LONG_SIDE / longest
        new_size = (
            max(1, round(width * scale)) if width < longest else THUMB_LONG_SIDE,
            max(1, round(height * scale)) if height < longest else THUMB_LONG_SIDE,
        )
        thumb = thumb.resize(new_size, Image.LANCZOS)
    out = BytesIO()
    thumb.save(out, format="JPEG", quality=THUMB_QUALITY, optimize=True)
    return out.getvalue()


def write_atomic(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` through a sibling ``<name>.tmp-<random>`` file + ``os.replace``.

    ``os.replace`` is atomic on POSIX and on NTFS, so a concurrent ``/api/thumb`` reader sees
    either no file or the complete one, never a partial write.  The temporary file is removed
    again when anything fails.
    """
    tmp_path = path.with_name(f"{path.name}.tmp-{secrets.token_hex(4)}")
    try:
        tmp_path.write_bytes(data)
        os.replace(tmp_path, path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp_path.unlink()
        raise


def _process_bytes(candidate: RawCandidate, data: bytes, thumbs_dir: Path) -> ProcessedImage:
    """Thread-side part of one candidate: decode, validate, thumbnail, write, build the model."""
    decoded = decode_image(data)
    validate_size(decoded.width, decoded.height)
    thumb_bytes = make_thumbnail(decoded.image)
    thumb_path = thumbs_dir / f"{candidate.photo_id}.jpg"
    try:
        write_atomic(thumb_path, thumb_bytes)
    except OSError as exc:
        raise DownloadRejected(f"cannot write thumbnail: {exc}") from exc
    return ProcessedImage(
        candidate=candidate,
        photo_id=candidate.photo_id,
        sha1=decoded.sha1,
        phash=decoded.phash,
        thumb_path=str(thumb_path),
        thumb_b64=base64.b64encode(thumb_bytes).decode("ascii"),
        width=decoded.width,
        height=decoded.height,
    )


# ----------------------------------------------------------------------------- stage


async def _download_one(
    client: httpx.AsyncClient,
    candidate: RawCandidate,
    *,
    thumbs_dir: Path,
    limiter: asyncio.Semaphore,
) -> ProcessedImage | None:
    """One candidate end to end; ``None`` (already logged) on any failure."""
    url = candidate.image_url
    host_limiter = wikimedia_semaphore() if is_wikimedia_upload(url) else contextlib.nullcontext()
    try:
        async with limiter, host_limiter:
            try:
                data = await fetch_image_bytes(client, url)
            except DownloadRejected as exc:
                fallback = blocked_fallback_url(url) if str(exc) == "http 403" else None
                if fallback is None:
                    raise
                log.info("%s 403 for %s; retrying the 500 px rendering %s", SERVICE, url, fallback)
                data = await fetch_image_bytes(client, fallback)
        return await asyncio.to_thread(_process_bytes, candidate, data, thumbs_dir)
    except DownloadRejected as exc:
        log.debug("%s skipped %s (%s): %s", SERVICE, url, candidate.source_type.value, exc)
        return None


def _stage_budget(stage_timeout_s: float, deadline: float | None) -> float:
    budget = max(0.0, stage_timeout_s)
    if deadline is not None:
        budget = min(budget, max(0.0, deadline - time.monotonic()))
    return budget


async def download_candidates(
    client: httpx.AsyncClient,
    candidates: list[RawCandidate],
    *,
    thumbs_dir: Path,
    concurrency: int,
    stage_timeout_s: float = DEFAULT_STAGE_TIMEOUT_S,
    deadline: float | None = None,
) -> DownloadResult:
    """Download, validate and thumbnail every candidate within the stage budget.

    ``deadline`` is a ``time.monotonic()`` value; when it is closer than ``stage_timeout_s`` the
    smaller budget is used.  Images come back in input order.  Never raises.
    """
    result = DownloadResult()
    if not candidates:
        return result
    budget = _stage_budget(stage_timeout_s, deadline)
    if budget <= 0:
        result.timed_out = len(candidates)
        log.warning("download stage skipped: no time budget left (%d candidates)", len(candidates))
        return result
    try:
        thumbs_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("cannot create thumbs dir %s: %s", thumbs_dir, exc)
    limiter = asyncio.Semaphore(max(1, concurrency))
    started = time.monotonic()
    tasks = [
        asyncio.create_task(
            _download_one(client, candidate, thumbs_dir=thumbs_dir, limiter=limiter),
            name=f"download:{candidate.photo_id}",
        )
        for candidate in candidates
    ]
    _done, pending = await asyncio.wait(tasks, timeout=budget)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    for task in tasks:
        if task.cancelled():
            result.timed_out += 1
            continue
        error = task.exception()
        if error is not None:
            # _download_one catches everything it expects; anything else is a bug worth seeing.
            log.warning("download task failed unexpectedly: %r", error)
            result.failed += 1
            continue
        image = task.result()
        if image is None:
            result.failed += 1
        else:
            result.images.append(image)
    log.info(
        "download stage: %d ok, %d failed, %d timed out of %d in %dms (budget %.1fs)",
        len(result.images),
        result.failed,
        result.timed_out,
        len(candidates),
        int((time.monotonic() - started) * 1000),
        budget,
    )
    return result


async def fetch_logo_hashes(client: httpx.AsyncClient, image_url: str) -> tuple[str, str] | None:
    """(sha1, phash) of the university logo (P154) for Section 8 logo exclusion.

    Same download and decode rules as a candidate, but no size rejection and no thumbnail.
    ``None`` on any failure (logged).
    """
    host_limiter = (
        wikimedia_semaphore() if is_wikimedia_upload(image_url) else contextlib.nullcontext()
    )
    try:
        async with host_limiter:
            data = await fetch_image_bytes(client, image_url)
        decoded = await asyncio.to_thread(decode_image, data)
    except DownloadRejected as exc:
        log.info("logo unavailable %s: %s", image_url, exc)
        return None
    return decoded.sha1, decoded.phash
