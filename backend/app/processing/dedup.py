"""Stage E: exact + near-duplicate grouping and logo exclusion (SPEC Section 8).

Union-find over all pairs (<= ~140 images, trivial): two images join the same group when their
sha1 is identical or the pHash Hamming distance is <= 12 (spec: <= 6 duplicate, 7..12
near-duplicate, both merge).  Each group keeps one representative: best SOURCE_PRIORITY, then
larger ``width*height``, then the first seen.  Before grouping, images matching the university
logo (same sha1 or pHash distance <= 8) are dropped and counted separately.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import imagehash

from app.enums import source_rank
from app.models import ProcessedImage

log = logging.getLogger("app.processing.dedup")

DUPLICATE_MAX_DISTANCE = 6  # informational: the spec's "duplicate" band
NEAR_DUPLICATE_MAX_DISTANCE = 12  # merge threshold (covers both bands)
LOGO_MAX_DISTANCE = 8


@dataclass(slots=True)
class DedupResult:
    """Kept representatives (input order) and the two removal counters."""

    kept: list[ProcessedImage] = field(default_factory=list)
    removed: int = 0  # non-representatives -> stats.duplicates_removed
    logo_removed: int = 0  # matched the university logo (P154)


def parse_phash(value: str | None) -> imagehash.ImageHash | None:
    """``imagehash.hex_to_hash`` that tolerates bad input (``None`` -> compare by sha1 only)."""
    if not value:
        return None
    try:
        return imagehash.hex_to_hash(value)
    except (ValueError, TypeError):
        log.debug("unparseable phash %r", value)
        return None


def phash_distance(a: imagehash.ImageHash | None, b: imagehash.ImageHash | None) -> int | None:
    """Hamming distance, or ``None`` when either hash is missing or the sizes differ."""
    if a is None or b is None:
        return None
    try:
        return int(a - b)
    except (TypeError, ValueError):
        return None


def _matches_logo(
    image: ProcessedImage,
    image_hash: imagehash.ImageHash | None,
    logo_sha1: str | None,
    logo_hash: imagehash.ImageHash | None,
) -> bool:
    if logo_sha1 and image.sha1 == logo_sha1:
        return True
    distance = phash_distance(image_hash, logo_hash)
    return distance is not None and distance <= LOGO_MAX_DISTANCE


def _same_group(
    a: ProcessedImage,
    a_hash: imagehash.ImageHash | None,
    b: ProcessedImage,
    b_hash: imagehash.ImageHash | None,
) -> bool:
    if a.sha1 == b.sha1:
        return True
    distance = phash_distance(a_hash, b_hash)
    return distance is not None and distance <= NEAR_DUPLICATE_MAX_DISTANCE


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, index: int) -> int:
        root = index
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[index] != root:  # path compression
            self.parent[index], index = root, self.parent[index]
        return root

    def union(self, a: int, b: int) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self.parent[max(root_a, root_b)] = min(root_a, root_b)


def _representative_key(index: int, image: ProcessedImage) -> tuple[int, int, int]:
    """Lower is better: best source priority, then larger area, then first seen."""
    return (source_rank(image.candidate.source_type), -(image.width * image.height), index)


def dedupe(
    images: list[ProcessedImage],
    *,
    logo_sha1: str | None = None,
    logo_phash: str | None = None,
) -> DedupResult:
    """Section 8 dedup.  Pure CPU, no I/O, never raises on bad hashes."""
    result = DedupResult()
    if not images:
        return result
    logo_hash = parse_phash(logo_phash)
    survivors: list[ProcessedImage] = []
    hashes: list[imagehash.ImageHash | None] = []
    for image in images:
        image_hash = parse_phash(image.phash)
        if _matches_logo(image, image_hash, logo_sha1, logo_hash):
            result.logo_removed += 1
            log.debug("logo match dropped %s (%s)", image.photo_id, image.candidate.image_url)
            continue
        survivors.append(image)
        hashes.append(image_hash)

    count = len(survivors)
    groups = _UnionFind(count)
    for i in range(count):
        for j in range(i + 1, count):
            if _same_group(survivors[i], hashes[i], survivors[j], hashes[j]):
                groups.union(i, j)

    best_by_root: dict[int, int] = {}
    for index, image in enumerate(survivors):
        root = groups.find(index)
        current = best_by_root.get(root)
        if current is None or _representative_key(index, image) < _representative_key(
            current, survivors[current]
        ):
            best_by_root[root] = index
    representatives = set(best_by_root.values())
    result.kept = [image for index, image in enumerate(survivors) if index in representatives]
    result.removed = count - len(result.kept)
    log.info(
        "dedup: %d in -> %d kept, %d duplicates removed, %d logo matches, %d groups",
        len(images),
        len(result.kept),
        result.removed,
        result.logo_removed,
        len(best_by_root),
    )
    return result


def drop_duplicates_of(
    images: list[ProcessedImage], *, against: list[ProcessedImage]
) -> tuple[list[ProcessedImage], int]:
    """Drop images that duplicate any image in ``against`` (sha1 equal or pHash distance <= 12).

    Used for the second download wave: representatives already emitted keep precedence.
    Returns ``(kept, dropped)``.
    """
    reference = [(other, parse_phash(other.phash)) for other in against]
    kept: list[ProcessedImage] = []
    dropped = 0
    for image in images:
        image_hash = parse_phash(image.phash)
        if any(
            _same_group(image, image_hash, other, other_hash) for other, other_hash in reference
        ):
            dropped += 1
            continue
        kept.append(image)
    return kept, dropped
