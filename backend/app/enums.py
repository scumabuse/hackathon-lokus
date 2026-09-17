"""Shared enumerations (SPEC Section 5)."""

from __future__ import annotations

from enum import Enum


class Category(str, Enum):
    campus = "campus"
    dormitory = "dormitory"
    classroom = "classroom"
    library = "library"
    lab = "lab"
    sport = "sport"
    student_life = "student_life"
    city = "city"
    other = "other"


class SourceType(str, Enum):
    wikidata_p18 = "wikidata_p18"
    official_site = "official_site"
    commons_category = "commons_category"
    flickr_geo = "flickr_geo"
    commons_search = "commons_search"
    web_search = "web_search"
    city_commons = "city_commons"


# Source priority (highest first) -- used for dedup representative choice and candidate caps.
SOURCE_PRIORITY: list[SourceType] = [
    SourceType.wikidata_p18,
    SourceType.official_site,
    SourceType.commons_category,
    SourceType.flickr_geo,
    SourceType.commons_search,
    SourceType.web_search,
    SourceType.city_commons,
]

SOURCE_RANK: dict[SourceType, int] = {s: i for i, s in enumerate(SOURCE_PRIORITY)}


def source_rank(source_type: SourceType) -> int:
    """Lower is better. Unknown sources sort last."""
    return SOURCE_RANK.get(source_type, len(SOURCE_PRIORITY))


class Verification(str, Enum):
    verified = "verified"
    likely = "likely"
    unverified = "unverified"


class ReasonCode(str, Enum):
    wikidata_main_image = "wikidata_main_image"
    official_site_source = "official_site_source"
    commons_category_source = "commons_category_source"
    commons_search_source = "commons_search_source"
    flickr_geo_source = "flickr_geo_source"
    web_search_source = "web_search_source"
    city_category_source = "city_category_source"
    # name/alias found in title, description, filename, alt or page title
    name_in_metadata = "name_in_metadata"
    # vision model read the name on a sign/banner in the image
    name_on_sign = "name_on_sign"
    geo_within_300m = "geo_within_300m"
    geo_within_1km = "geo_within_1km"
    # is_photo, plausibly related, category != other
    vision_consistent = "vision_consistent"
    # model failed / no key
    vision_unavailable = "vision_unavailable"
    # skipped by deadline monitor
    vision_timeout = "vision_timeout"
    # category from filename/caption keywords
    category_heuristic = "category_heuristic"
    cached_result = "cached_result"


class WarningCode(str, Enum):
    low_data = "low_data"
    no_coordinates = "no_coordinates"
    no_commons_category = "no_commons_category"
    no_official_site = "no_official_site"
    source_unavailable = "source_unavailable"  # detail = source name
    vision_unavailable = "vision_unavailable"
    time_budget_exceeded = "time_budget_exceeded"
    served_from_cache = "served_from_cache"
    ambiguous_name = "ambiguous_name"
    missing_category = "missing_category"  # detail = category name
    queued = "queued"
