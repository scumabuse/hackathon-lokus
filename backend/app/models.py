"""All pydantic models (SPEC Section 5). Frontend types.ts mirrors the public ones exactly."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.enums import Category, ReasonCode, SourceType, Verification, WarningCode

DateKind = Literal["taken", "published", "uploaded", "unknown"]
CategorySource = Literal["vision", "heuristic", "source_hint"]
DescriptionBasis = Literal["wikipedia_and_site", "wikipedia_only", "site_only", "insufficient"]


class Coordinates(BaseModel):
    lat: float
    lon: float


class Candidate(BaseModel):
    qid: str
    label: str
    description: str | None = None
    country: str | None = None
    city: str | None = None


class SearchResponse(BaseModel):
    query: str
    candidates: list[Candidate]
    suggestions_used: bool = False
    corrected_query: str | None = None


class Place(BaseModel):
    qid: str | None = None
    name: str
    coords: Coordinates | None = None
    wikipedia_url: str | None = None
    commons_category: str | None = None


class UniversityHeader(BaseModel):
    qid: str
    name: str
    local_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    country: str | None = None
    city: Place | None = None
    coords: Coordinates | None = None
    official_website: str | None = None
    wikipedia_url: str | None = None
    commons_category: str | None = None
    logo_url: str | None = None
    distance_to_city_center_km: float | None = None
    cached: bool = False
    cached_at: datetime | None = None


class SourceLink(BaseModel):
    title: str
    url: str


class Description(BaseModel):
    text_ru: str
    text_en: str
    sources: list[SourceLink]
    basis: DescriptionBasis


class Photo(BaseModel):
    id: str  # first 16 hex chars of sha1(source_page_url + "|" + image_url)
    thumb_url: str  # "/api/thumb/{id}.jpg" -- always served by our backend
    image_url: str  # original image URL (for the lightbox link, not for <img>)
    source_page_url: str  # clickable source
    source_type: SourceType
    source_label: str  # "Wikimedia Commons" | "Flickr" | "<official site host>" | "<displayLink>"
    title: str | None = None
    author: str | None = None
    license: str | None = None
    date: str | None = None  # "YYYY-MM-DD" (time dropped) or None
    date_kind: DateKind = "unknown"
    category: Category
    category_source: CategorySource
    width: int | None = None
    height: int | None = None
    confidence: float  # 0.0-1.0, rounded to 2 decimals
    verification: Verification
    reasons: list[ReasonCode]
    geo: Coordinates | None = None
    distance_m: float | None = None
    visible_text: str | None = None
    vision_reason: str | None = None


class Stats(BaseModel):
    found: int
    duplicates_removed: int
    irrelevant_removed: int
    shown: int
    hidden_unverified: int
    per_source: dict[str, int]  # raw candidates per source
    timings_ms: dict[str, int]  # resolve, collect, download, dedup, vision, describe, total
    total_ms: int


class Warning(BaseModel):
    code: WarningCode
    detail: str | None = None


class Profile(BaseModel):
    header: UniversityHeader
    description: Description | None
    photos: list[Photo]  # shown photos (verified + likely) AND up to 15 unverified (hidden by UI)
    stats: Stats
    warnings: list[Warning]
    generated_at: datetime


# ----------------------------------------------------------------------------- internal models
# Not exposed through the API. Shared contracts between sources, processing, vision and scoring.


def photo_id_for(source_page_url: str, image_url: str) -> str:
    """Stable photo id: first 16 hex chars of sha1(source_page_url + "|" + image_url)."""
    digest = hashlib.sha1((source_page_url + "|" + image_url).encode("utf-8")).hexdigest()
    return digest[:16]


class RawCandidate(BaseModel):
    """One image found by a source, before download (SPEC Section 5, internal)."""

    source_type: SourceType
    image_url: str
    source_page_url: str
    source_label: str
    title: str | None = None
    description: str | None = None
    alt: str | None = None
    author: str | None = None
    license: str | None = None
    date: str | None = None
    date_kind: DateKind = "unknown"
    geo: Coordinates | None = None
    distance_m: float | None = None
    page_title: str | None = None
    filename: str | None = None
    width: int | None = None
    height: int | None = None
    source_hint_category: Category | None = None

    @property
    def photo_id(self) -> str:
        return photo_id_for(self.source_page_url, self.image_url)


class ProcessedImage(BaseModel):
    """RawCandidate after download + validation (SPEC Section 8)."""

    candidate: RawCandidate
    photo_id: str
    sha1: str
    phash: str  # imagehash hex string (hash_size=8)
    thumb_path: str
    thumb_b64: str  # base64 JPEG, long side <= 512 px, for the vision batch
    width: int  # decoded original width
    height: int  # decoded original height
