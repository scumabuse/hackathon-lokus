"""Section 8 dedup on synthetic images (Section 15.1): one group of three + one single,
representative choice, kept order, logo exclusion, bad hashes."""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageOps

from app.enums import SourceType
from app.models import ProcessedImage, RawCandidate
from app.processing.dedup import (
    LOGO_MAX_DISTANCE,
    NEAR_DUPLICATE_MAX_DISTANCE,
    DedupResult,
    dedupe,
    parse_phash,
    phash_distance,
)
from app.processing.download import decode_image, make_thumbnail

WIDTH, HEIGHT = 600, 400

# ---------------------------------------------------------------------------- synthetic images


def gradient() -> Image.Image:
    """600x400 two-axis gradient with a soft wave.

    A purely linear gradient has almost no DCT content, so its pHash bits are decided by noise
    and a re-encoded copy lands 30 bits away; the wave gives the hash something to hold on to.
    """
    x = np.linspace(0, 1, WIDTH, dtype=np.float32)[None, :].repeat(HEIGHT, 0)
    y = np.linspace(0, 1, HEIGHT, dtype=np.float32)[:, None].repeat(WIDTH, 1)
    red = 255 * x
    green = 255 * (0.5 + 0.5 * np.sin(8 * x) * np.cos(5 * y)) * (0.4 + 0.6 * y)
    blue = 255 * (1 - y)
    array = np.clip(np.stack([red, green, blue], axis=-1), 0, 255).astype(np.uint8)
    return Image.fromarray(array, "RGB")


def jpeg_bytes(img: Image.Image, quality: int) -> bytes:
    out = BytesIO()
    img.save(out, format="JPEG", quality=quality)
    return out.getvalue()


def as_image(data: bytes) -> Image.Image:
    return Image.open(BytesIO(data)).convert("RGB")


@pytest.fixture(scope="module")
def image_bytes() -> dict[str, bytes]:
    """original, re-encoded (q60), 5 %-cropped, 2x larger, and a clearly different image."""
    original = jpeg_bytes(gradient(), 95)
    base = as_image(original)
    reencoded = jpeg_bytes(base, 60)
    dx, dy = WIDTH * 5 // 100, HEIGHT * 5 // 100
    cropped_box = base.crop((dx, dy, WIDTH - dx, HEIGHT - dy))
    cropped = jpeg_bytes(cropped_box.resize((WIDTH, HEIGHT), Image.LANCZOS), 90)
    larger = jpeg_bytes(base.resize((WIDTH * 2, HEIGHT * 2), Image.LANCZOS), 90)
    other = ImageOps.invert(base)
    draw = ImageDraw.Draw(other)
    draw.rectangle((50, 50, 250, 200), fill=(255, 0, 0))
    draw.ellipse((300, 150, 550, 380), fill=(0, 0, 255))
    different = jpeg_bytes(other, 90)
    return {
        "original": original,
        "reencoded": reencoded,
        "cropped": cropped,
        "larger": larger,
        "different": different,
    }


def processed(
    data: bytes,
    name: str,
    thumbs_dir: Path,
    source_type: SourceType = SourceType.commons_search,
) -> ProcessedImage:
    """Build a ProcessedImage through the real download-side helpers."""
    decoded = decode_image(data)
    thumb = make_thumbnail(decoded.image)
    candidate = RawCandidate(
        source_type=source_type,
        image_url=f"https://example.org/{name}.jpg",
        source_page_url=f"https://example.org/{name}",
        source_label="example.org",
    )
    thumb_path = thumbs_dir / f"{candidate.photo_id}.jpg"
    thumb_path.write_bytes(thumb)
    return ProcessedImage(
        candidate=candidate,
        photo_id=candidate.photo_id,
        sha1=decoded.sha1,
        phash=decoded.phash,
        thumb_path=str(thumb_path),
        thumb_b64=base64.b64encode(thumb).decode("ascii"),
        width=decoded.width,
        height=decoded.height,
    )


def fake(
    name: str,
    *,
    phash: str,
    sha1: str | None = None,
    source_type: SourceType = SourceType.commons_search,
    width: int = WIDTH,
    height: int = HEIGHT,
) -> ProcessedImage:
    """A ProcessedImage with hand-made hashes (no real pixels) for threshold tests."""
    candidate = RawCandidate(
        source_type=source_type,
        image_url=f"https://example.org/{name}.jpg",
        source_page_url=f"https://example.org/{name}",
        source_label="example.org",
    )
    return ProcessedImage(
        candidate=candidate,
        photo_id=candidate.photo_id,
        sha1=sha1 or f"{name:0>40}"[:40],
        phash=phash,
        thumb_path=f"/nonexistent/{name}.jpg",
        thumb_b64="",
        width=width,
        height=height,
    )


@pytest.fixture
def four(image_bytes: dict[str, bytes], tmp_path: Path) -> dict[str, ProcessedImage]:
    return {
        key: processed(image_bytes[key], key, tmp_path)
        for key in ("original", "reencoded", "cropped", "different")
    }


# ----------------------------------------------------------------------------- fixture sanity


def test_synthetic_images_are_as_expected(four: dict[str, ProcessedImage]) -> None:
    hashes = {key: parse_phash(img.phash) for key, img in four.items()}
    assert all(h is not None for h in hashes.values())
    assert phash_distance(hashes["original"], hashes["reencoded"]) <= 6  # spec: duplicate
    assert phash_distance(hashes["original"], hashes["cropped"]) <= 12  # near-duplicate
    for key in ("original", "reencoded", "cropped"):
        assert phash_distance(hashes[key], hashes["different"]) > NEAR_DUPLICATE_MAX_DISTANCE
    assert len({img.sha1 for img in four.values()}) == 4  # every byte stream is distinct
    assert all(len(img.sha1) == 40 and len(img.phash) == 16 for img in four.values())
    assert all((img.width, img.height) == (WIDTH, HEIGHT) for img in four.values())


# --------------------------------------------------------------------------- Section 15.1 case


def test_one_group_of_three_plus_one_single(four: dict[str, ProcessedImage]) -> None:
    result = dedupe([four["original"], four["reencoded"], four["cropped"], four["different"]])
    assert len(result.kept) == 2
    assert result.removed == 2
    assert result.logo_removed == 0
    # equal priority and equal area -> the first seen represents the group
    assert result.kept == [four["original"], four["different"]]


def test_representative_prefers_higher_priority_source(
    image_bytes: dict[str, bytes], tmp_path: Path
) -> None:
    original = processed(image_bytes["original"], "o", tmp_path, SourceType.commons_search)
    reencoded = processed(image_bytes["reencoded"], "r", tmp_path, SourceType.commons_category)
    cropped = processed(image_bytes["cropped"], "c", tmp_path, SourceType.commons_search)
    result = dedupe([original, reencoded, cropped])
    assert result.kept == [reencoded]
    assert result.removed == 2


def test_representative_prefers_larger_area_at_equal_priority(
    image_bytes: dict[str, bytes], tmp_path: Path
) -> None:
    original = processed(image_bytes["original"], "o", tmp_path)
    larger = processed(image_bytes["larger"], "l", tmp_path)
    cropped = processed(image_bytes["cropped"], "c", tmp_path)
    assert (larger.width, larger.height) == (WIDTH * 2, HEIGHT * 2)
    result = dedupe([original, larger, cropped])
    assert result.kept == [larger]
    assert result.removed == 2


def test_priority_beats_area(image_bytes: dict[str, bytes], tmp_path: Path) -> None:
    small_p18 = processed(image_bytes["original"], "o", tmp_path, SourceType.wikidata_p18)
    larger_search = processed(image_bytes["larger"], "l", tmp_path, SourceType.commons_search)
    assert dedupe([larger_search, small_p18]).kept == [small_p18]


def test_kept_order_is_input_order(image_bytes: dict[str, bytes], tmp_path: Path) -> None:
    original = processed(image_bytes["original"], "o", tmp_path, SourceType.commons_search)
    reencoded = processed(image_bytes["reencoded"], "r", tmp_path, SourceType.commons_category)
    cropped = processed(image_bytes["cropped"], "c", tmp_path, SourceType.commons_search)
    different = processed(image_bytes["different"], "d", tmp_path, SourceType.commons_search)
    assert dedupe([different, original, reencoded, cropped]).kept == [different, reencoded]
    assert dedupe([original, different, reencoded, cropped]).kept == [different, reencoded]
    assert dedupe([reencoded, cropped, different, original]).kept == [reencoded, different]


# ------------------------------------------------------------------------ thresholds and sha1


def test_identical_sha1_merges_even_with_unparseable_phash() -> None:
    a = fake("a", phash="not-a-hash", sha1="a" * 40)
    b = fake("b", phash="", sha1="a" * 40)
    result = dedupe([a, b])
    assert result.kept == [a]
    assert result.removed == 1


def test_near_duplicate_threshold_is_12_bits() -> None:
    zero = "0" * 16
    twelve = "0" * 13 + "fff"
    thirteen = "0" * 12 + "1fff"
    assert dedupe([fake("a", phash=zero), fake("b", phash=twelve)]).removed == 1
    result = dedupe([fake("a", phash=zero), fake("c", phash=thirteen)])
    assert result.removed == 0
    assert len(result.kept) == 2


def test_unparseable_phash_strings_do_not_crash() -> None:
    images = [
        fake("a", phash="zz"),
        fake("b", phash="abc"),
        fake("c", phash=""),
        fake("d", phash="0" * 16),
    ]
    result = dedupe(images, logo_sha1="f" * 40, logo_phash="garbage")
    assert result.kept == images  # nothing comparable, nothing merged
    assert result.removed == 0
    assert result.logo_removed == 0


def test_hash_size_mismatch_is_not_a_match() -> None:
    result = dedupe([fake("a", phash="0" * 16), fake("b", phash="0000")])
    assert result.removed == 0
    assert len(result.kept) == 2


# ------------------------------------------------------------------------------ logo exclusion


def test_logo_exclusion_by_sha1(four: dict[str, ProcessedImage]) -> None:
    images = [four["original"], four["reencoded"], four["cropped"], four["different"]]
    result = dedupe(images, logo_sha1=four["different"].sha1)
    assert result.logo_removed == 1
    assert result.kept == [four["original"]]
    assert result.removed == 2  # the logo does not count as a duplicate


def test_logo_exclusion_by_phash_distance_on_real_images(four: dict[str, ProcessedImage]) -> None:
    images = [four["original"], four["reencoded"], four["cropped"], four["different"]]
    # original / re-encoded / cropped are all within 8 bits of the "logo" (the original's hash)
    result = dedupe(images, logo_phash=four["original"].phash)
    assert result.logo_removed == 3
    assert result.kept == [four["different"]]
    assert result.removed == 0


def test_logo_phash_threshold_is_8_bits() -> None:
    assert LOGO_MAX_DISTANCE == 8
    eight = "0" * 14 + "ff"
    nine = "0" * 13 + "1ff"
    result = dedupe([fake("a", phash=eight), fake("b", phash=nine)], logo_phash="0" * 16)
    assert result.logo_removed == 1
    assert [img.phash for img in result.kept] == [nine]
    assert result.removed == 0


def test_logo_without_hashes_removes_nothing(four: dict[str, ProcessedImage]) -> None:
    images = [four["original"], four["different"]]
    assert dedupe(images, logo_sha1=None, logo_phash=None).logo_removed == 0
    assert dedupe(images, logo_sha1="", logo_phash="").logo_removed == 0


# -------------------------------------------------------------------------------------- empty


def test_empty_input() -> None:
    assert dedupe([]) == DedupResult()
    assert dedupe([], logo_sha1="a" * 40, logo_phash="0" * 16) == DedupResult(kept=[])


# ---------------------------------------------------------------------------- helper functions


def test_parse_phash_and_distance_helpers() -> None:
    assert parse_phash(None) is None
    assert parse_phash("") is None
    assert parse_phash("zz") is None
    hash_a = parse_phash("0" * 16)
    hash_b = parse_phash("f" * 16)
    assert hash_a is not None and hash_b is not None
    assert phash_distance(hash_a, hash_b) == 64
    assert phash_distance(hash_a, hash_a) == 0
    assert phash_distance(hash_a, None) is None
    assert phash_distance(None, hash_b) is None
    # imagehash parses odd lengths into non-square hashes; a shape mismatch is "no distance"
    assert phash_distance(hash_a, parse_phash("0000")) is None  # 4x4 vs 8x8
    assert phash_distance(hash_a, parse_phash("abc")) is None  # 4x3 vs 8x8
