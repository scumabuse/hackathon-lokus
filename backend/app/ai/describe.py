"""Campus description generation (SPEC Section 7.8.a, Stage H).

``describe_campus`` calls the Gemini text model and returns a ``Description``.
``fallback_description`` assembles a description from plain Wikipedia extracts when the
model is unavailable or the call fails.
"""

from __future__ import annotations

import logging

from app.ai.client import AIClient, parse_json_text
from app.ai.prompts import DESCRIPTION_PROMPT
from app.models import Description, SourceLink
from app.resolver.wikipedia import WikiSummary

log = logging.getLogger("app.describe")

DESCRIPTION_MAX_TOKENS = 700
DESCRIPTION_TIMEOUT_S = 20.0
EXTRACT_MAX_CHARS = 1500


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


class DescriptionInputs:
    """Everything the description step needs from the pipeline."""

    def __init__(
        self,
        *,
        name: str,
        local_name: str | None,
        city: str | None,
        country: str | None,
        summaries: list[WikiSummary],
        site_title: str | None = None,
        site_description: str | None = None,
    ) -> None:
        self.name = name
        self.local_name = local_name
        self.city = city or "unknown"
        self.country = country or "unknown"
        self.summaries = summaries
        self.site_title = site_title
        self.site_description = site_description


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first_sentences(text: str, n: int) -> str:
    """Return approximately the first ``n`` sentences of plain text."""
    parts: list[str] = []
    count = 0
    for segment in text.replace("! ", ". ").replace("? ", ". ").split(". "):
        segment = segment.strip()
        if not segment:
            continue
        parts.append(segment)
        count += 1
        if count >= n:
            break
    return ". ".join(parts) + ("." if parts else "")


def _extract_for_lang(summaries: list[WikiSummary], lang: str) -> tuple[str | None, str | None]:
    """Return (extract[:1500], page_url) for the requested language, or (None, None)."""
    for s in summaries:
        if s.lang == lang and s.extract:
            return s.extract[:EXTRACT_MAX_CHARS], s.page_url
    return None, None


def _basis(has_en: bool, has_ru: bool, has_site: bool) -> str:
    if (has_en or has_ru) and has_site:
        return "wikipedia_and_site"
    if has_en or has_ru:
        return "wikipedia_only"
    if has_site:
        return "site_only"
    return "insufficient"


def _build_prompt(inputs: DescriptionInputs) -> tuple[str, list[SourceLink]]:
    """Build the filled DESCRIPTION_PROMPT and collect source links."""
    sources: list[SourceLink] = []

    en_extract, en_url = _extract_for_lang(inputs.summaries, "en")
    ru_extract, ru_url = _extract_for_lang(inputs.summaries, "ru")

    for lang, url in (("en", en_url), ("ru", ru_url)):
        if url:
            sources.append(SourceLink(title=f"Wikipedia ({lang})", url=url))

    local_name_part = f" ({inputs.local_name})" if inputs.local_name else ""
    en_extract_part = f"English Wikipedia extract:\n{en_extract}\n\n" if en_extract else ""
    ru_extract_part = f"Russian Wikipedia extract:\n{ru_extract}\n\n" if ru_extract else ""

    site_meta_part = ""
    if inputs.site_title or inputs.site_description:
        meta_parts: list[str] = []
        if inputs.site_title:
            meta_parts.append(f"title: {inputs.site_title}")
        if inputs.site_description:
            meta_parts.append(f"description: {inputs.site_description}")
        site_meta_part = f"Official website meta ({', '.join(meta_parts)}).\n\n"

    source_urls = ", ".join(s.url for s in sources) or "none"

    prompt = DESCRIPTION_PROMPT.format(
        name=inputs.name,
        local_name_part=local_name_part,
        city=inputs.city,
        country=inputs.country,
        en_extract_part=en_extract_part,
        ru_extract_part=ru_extract_part,
        site_meta_part=site_meta_part,
        source_urls=source_urls,
    )
    return prompt, sources


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def describe_campus(ai: AIClient, inputs: DescriptionInputs) -> Description:
    """Generate a campus description via Gemini (Section 7.8.a).

    Falls back to ``fallback_description`` on any error.
    """
    prompt, sources = _build_prompt(inputs)
    basis = _basis(
        has_en=any(s.lang == "en" and s.extract for s in inputs.summaries),
        has_ru=any(s.lang == "ru" and s.extract for s in inputs.summaries),
        has_site=bool(inputs.site_title or inputs.site_description),
    )

    try:
        response_text = await ai.complete_text(
            prompt,
            max_tokens=DESCRIPTION_MAX_TOKENS,
            timeout=DESCRIPTION_TIMEOUT_S,
            json_mode=True,
        )
        raw = parse_json_text(response_text)
        if not isinstance(raw, dict):
            raise TypeError("model did not return a JSON object")
        text_ru = str(raw.get("text_ru") or "").strip()
        text_en = str(raw.get("text_en") or "").strip()
        raw_basis = str(raw.get("basis") or basis)
        # validate basis
        valid_bases = {"wikipedia_and_site", "wikipedia_only", "site_only", "insufficient"}
        if raw_basis not in valid_bases:
            raw_basis = basis
        if not text_ru or not text_en:
            raise ValueError("empty description from model")
        return Description(text_ru=text_ru, text_en=text_en, sources=sources, basis=raw_basis)  # type: ignore[arg-type]
    except Exception as exc:
        log.warning(
            "describe_campus failed (%s: %s); using the Wikipedia fallback text",
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return fallback_description(inputs)


def fallback_description(inputs: DescriptionInputs) -> Description:
    """Build a description from raw Wikipedia extracts (no AI required)."""
    en_extract, en_url = _extract_for_lang(inputs.summaries, "en")
    ru_extract, ru_url = _extract_for_lang(inputs.summaries, "ru")

    sources: list[SourceLink] = []
    if en_url:
        sources.append(SourceLink(title="Wikipedia (en)", url=en_url))
    if ru_url:
        sources.append(SourceLink(title="Wikipedia (ru)", url=ru_url))

    has_en = bool(en_extract)
    has_ru = bool(ru_extract)
    has_site = bool(inputs.site_title or inputs.site_description)
    basis: str = _basis(has_en, has_ru, has_site)  # type: ignore[assignment]

    if en_extract:
        text_en = _first_sentences(en_extract, 3)
    else:
        text_en = "Not enough open-source data to describe the campus."

    if ru_extract:
        text_ru = _first_sentences(ru_extract, 3)
    elif en_extract:
        text_ru = text_en  # fall back to English text in the RU field
    else:
        text_ru = "Недостаточно данных для описания кампуса из открытых источников."

    return Description(text_ru=text_ru, text_en=text_en, sources=sources, basis=basis)  # type: ignore[arg-type]
