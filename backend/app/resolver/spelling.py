"""LLM spelling normalization -- resolver fallback only (SPEC Section 6 Stage A, Section 7.8.b)."""

from __future__ import annotations

import logging

from app.ai.client import AIClient, parse_json_text
from app.ai.prompts import SPELLING_PROMPT

log = logging.getLogger("app.resolver.spelling")

MAX_SUGGESTIONS = 3
SPELLING_MAX_TOKENS = 200
SPELLING_TIMEOUT_S = 6.0


async def suggest_official_names(ai: AIClient, q: str) -> list[str]:
    """Up to 3 probable official English names for a query that found nothing. Never raises."""
    if not ai.available:
        return []
    try:
        raw = await ai.complete_text(
            SPELLING_PROMPT.format(q=q),
            max_tokens=SPELLING_MAX_TOKENS,
            temperature=0.0,
            timeout=SPELLING_TIMEOUT_S,
        )
    except Exception:
        log.warning("spelling normalization call failed for %r", q, exc_info=True)
        return []
    try:
        data = parse_json_text(raw)
    except ValueError as exc:
        log.warning("spelling normalization returned no JSON for %r: %s", q, exc)
        return []
    if not isinstance(data, list):
        log.warning("spelling normalization returned a non-array for %r", q)
        return []
    names: list[str] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, str):
            continue
        name = " ".join(item.split())
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        names.append(name)
        if len(names) == MAX_SUGGESTIONS:
            break
    return names
