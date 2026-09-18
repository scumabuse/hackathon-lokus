"""Which sources run, in SOURCE_PRIORITY order (SPEC Sections 6.1, 7, 16.2 ``DISABLE_SOURCES``)."""

from __future__ import annotations

import logging

from app.config import Settings
from app.enums import source_rank
from app.sources.base import Source
from app.sources.commons import (
    CityCommonsSource,
    CommonsCategorySource,
    CommonsGeoSource,
    CommonsSearchSource,
    WikidataP18Source,
)
from app.sources.flickr import FlickrSource
from app.sources.official_site import OfficialSiteSource

log = logging.getLogger("app.sources.registry")

SOURCE_NAMES: tuple[str, ...] = (
    "wikidata_p18",
    "official_site",
    "commons_category",
    "commons_geo",
    "flickr",
    "commons_search",
    "city_commons",
)


def all_sources() -> list[Source]:
    """Fresh instances of every implemented source, in SOURCE_PRIORITY order."""
    sources: list[Source] = [
        WikidataP18Source(),
        OfficialSiteSource(),
        CommonsCategorySource(),
        CommonsGeoSource(),
        FlickrSource(),
        CommonsSearchSource(),
        CityCommonsSource(),
    ]
    sources.sort(key=lambda s: source_rank(s.source_type))
    return sources


def build_sources(settings: Settings) -> list[Source]:
    """Enabled sources: everything minus ``DISABLE_SOURCES`` and, silently, Flickr without a key."""
    disabled = settings.disabled_sources
    enabled: list[Source] = []
    dropped: list[str] = []
    for source in all_sources():
        if source.name in disabled:
            dropped.append(source.name)
            continue
        if source.name == "flickr" and not settings.flickr_api_key:
            log.debug("flickr source omitted: no FLICKR_API_KEY")
            continue
        enabled.append(source)
    if dropped:
        log.info("sources disabled by DISABLE_SOURCES: %s", ", ".join(dropped))
    unknown = sorted(disabled - set(SOURCE_NAMES))
    if unknown:
        log.info("DISABLE_SOURCES names without a registered source: %s", ", ".join(unknown))
    return enabled
