"""Vision classification (SPEC Section 9, Stage F).

``classify_batch`` sends one Gemini request for up to VISION_BATCH_SIZE images and returns
a ``BatchOutcome`` with a ``VisionInfo`` per image.  ``apply_post_processing`` applies the
Section 9 post-processing rules (remove non-photos, prominent-people, low-quality, unrelated,
other).

City images are sent separately with a different header (``target="city"``).
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass

from pydantic import BaseModel, Field, ValidationError

from app.ai.client import (
    AIClient,
    AIUnavailableError,
    image_part,
    message_text,
    parse_json_text,
    text_part,
    user_content,
)
from app.ai.prompts import (
    VISION_FOOTER,
    VISION_HEADER,
    VISION_HEADER_CITY,
    VISION_RETRY_SUFFIX,
    VISION_SYSTEM,
)
from app.enums import Category, SourceType
from app.models import ProcessedImage, UniversityHeader
from app.scoring import VisionInfo

log = logging.getLogger("app.vision")


# ---------------------------------------------------------------------------
# Pydantic model for one item in the model's JSON array (Section 9 parsing)
# ---------------------------------------------------------------------------


class VisionItem(BaseModel):
    index: int
    is_photo: bool
    category: Category
    category_confidence: float = Field(ge=0.0, le=1.0)
    plausibly_university_related: bool
    name_on_sign: bool
    visible_text: str | None = None
    people_prominent: bool
    quality_ok: bool
    reason: str | None = None


# ---------------------------------------------------------------------------
# Batch outcome
# ---------------------------------------------------------------------------


@dataclass
class BatchOutcome:
    infos: list[VisionInfo]
    parsed_first_attempt: bool | None = None  # None when AI unavailable
    error: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _vision_info_from_item(item: VisionItem) -> VisionInfo:
    return VisionInfo(
        available=True,
        timed_out=False,
        is_photo=item.is_photo,
        plausibly_university_related=item.plausibly_university_related,
        category=item.category,
        category_confidence=item.category_confidence,
        name_on_sign=item.name_on_sign,
        visible_text=item.visible_text,
        people_prominent=item.people_prominent,
        quality_ok=item.quality_ok,
        reason=item.reason,
    )


def _unavailable_infos(n: int) -> list[VisionInfo]:
    return [VisionInfo(available=False) for _ in range(n)]


def _build_content_parts(
    images: list[ProcessedImage],
    header: UniversityHeader,
    *,
    target: str,
) -> list:
    """Build the list of content Parts for the vision request."""
    n = len(images)
    aliases = "; ".join(header.aliases[:6]) if header.aliases else header.name
    city = header.city.name if header.city else "unknown"
    country = header.country or "unknown"

    if target == "city":
        header_text = VISION_HEADER_CITY.format(
            name=header.name, city=city, country=country, n=n
        )
    else:
        header_text = VISION_HEADER.format(
            name=header.name, aliases=aliases, city=city, country=country, n=n
        )

    parts = [text_part(header_text)]
    for i, image in enumerate(images, start=1):
        parts.append(text_part(f"IMAGE {i}"))
        img_bytes = base64.b64decode(image.thumb_b64)
        parts.append(image_part(img_bytes, mime_type="image/jpeg"))
    parts.append(text_part(VISION_FOOTER))
    return parts


def _parse_response(text: str, n: int) -> list[VisionItem] | None:
    """Parse model output; return None when the output is structurally invalid."""
    try:
        raw = parse_json_text(text)
    except ValueError:
        return None
    if not isinstance(raw, list) or len(raw) != n:
        return None
    items: list[VisionItem] = []
    expected_indexes = set(range(1, n + 1))
    for obj in raw:
        try:
            item = VisionItem.model_validate(obj)
        except ValidationError:
            return None
        items.append(item)
    found_indexes = {item.index for item in items}
    if found_indexes != expected_indexes:
        return None
    items.sort(key=lambda x: x.index)
    return items


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def classify_batch(
    ai: AIClient,
    images: list[ProcessedImage],
    header: UniversityHeader,
    *,
    target: str = "university",
    timeout: float = 20.0,
) -> BatchOutcome:
    """Classify one batch (Section 9).

    Returns a ``BatchOutcome`` with one ``VisionInfo`` per image.
    On AI unavailability or parse failure after retry, every image gets ``available=False``.
    """
    n = len(images)
    if n == 0:
        return BatchOutcome(infos=[], parsed_first_attempt=None)

    try:
        parts = _build_content_parts(images, header, target=target)
        contents = user_content(parts)
    except Exception as exc:
        log.warning("vision batch content build failed: %s", exc)
        return BatchOutcome(
            infos=_unavailable_infos(n), parsed_first_attempt=False, error=str(exc)
        )

    max_tokens = 900 + 130 * n

    # First attempt
    try:
        response = await ai.generate(
            contents=contents,
            model=ai.vision_model,
            system=VISION_SYSTEM,
            max_output_tokens=max_tokens,
            json_mode=True,
            timeout=timeout,
        )
    except AIUnavailableError as exc:
        return BatchOutcome(infos=_unavailable_infos(n), parsed_first_attempt=None, error=str(exc))
    except Exception as exc:
        log.warning("vision batch API error: %s", exc)
        return BatchOutcome(
            infos=_unavailable_infos(n), parsed_first_attempt=False, error=str(exc)
        )

    text = message_text(response)
    items = _parse_response(text, n)
    if items is not None:
        return BatchOutcome(
            infos=[_vision_info_from_item(it) for it in items],
            parsed_first_attempt=True,
        )

    # Parse failed on first attempt → retry with correction suffix (Section 9)
    log.info("vision batch parse failed on first attempt (n=%d); retrying", n)
    retry_parts = list(parts) + [text_part(f"{VISION_RETRY_SUFFIX} N={n}")]
    retry_contents = user_content(retry_parts)
    try:
        response2 = await ai.generate(
            contents=retry_contents,
            model=ai.vision_model,
            system=VISION_SYSTEM,
            max_output_tokens=max_tokens,
            json_mode=True,
            timeout=timeout,
        )
        text2 = message_text(response2)
        items2 = _parse_response(text2, n)
        if items2 is not None:
            return BatchOutcome(
                infos=[_vision_info_from_item(it) for it in items2],
                parsed_first_attempt=False,
            )
    except Exception as exc2:
        log.warning("vision batch retry failed: %s", exc2)
        return BatchOutcome(
            infos=_unavailable_infos(n),
            parsed_first_attempt=False,
            error=f"retry error: {exc2}",
        )

    log.warning("vision batch parse failed after retry (n=%d)", n)
    return BatchOutcome(
        infos=_unavailable_infos(n),
        parsed_first_attempt=False,
        error="parse failed after retry",
    )


def apply_post_processing(
    image: ProcessedImage,
    info: VisionInfo,
) -> tuple[VisionInfo, bool]:
    """Section 9 post-processing: apply removal rules and return (info, keep).

    Removals (in order):
    - is_photo == false  → remove
    - people_prominent   → remove
    - quality_ok == false → remove
    - city_commons: force category=city then keep (only is_photo removal applies)
    - plausibly_university_related == false AND category != city → remove
    - category == other → remove
    """
    if not info.usable:
        # unavailable / timed out → keep (heuristic category assigned by caller)
        return info, True

    is_city_commons = image.candidate.source_type is SourceType.city_commons

    if not info.is_photo:
        return info, False
    if info.people_prominent:
        return info, False
    if not info.quality_ok:
        return info, False

    if is_city_commons:
        # Force category to city (Section 9: "for source_type == city_commons: force category=city")
        forced = VisionInfo(
            available=info.available,
            timed_out=info.timed_out,
            is_photo=info.is_photo,
            plausibly_university_related=info.plausibly_university_related,
            category=Category.city,
            category_confidence=info.category_confidence,
            name_on_sign=info.name_on_sign,
            visible_text=info.visible_text,
            people_prominent=info.people_prominent,
            quality_ok=info.quality_ok,
            reason=info.reason,
        )
        return forced, True

    if not info.plausibly_university_related and info.category is not Category.city:
        return info, False
    if info.category is Category.other:
        return info, False

    return info, True
