"""Name normalization and matching for the ``name_in_metadata`` bonus (SPEC Section 10).

This is the single implementation: ``app.scoring`` re-exports ``normalize`` as ``normalize_text``
and delegates ``match_names_in`` here; ``app.selection`` normalizes its keyword rules with it.

Normalization, as Section 10 orders it: NFKD -> drop combining marks -> casefold -> replace
``[^\\w\\s]`` with a space -> collapse whitespace -> strip.  One deliberate addition: ``_`` is a
separator too (Python's ``\\w`` would keep it), because Commons, Flickr and official-site file
names spell spaces as underscores -- ``Nazarbayev_University.jpg`` must normalize to
``nazarbayev university jpg``.

Matching is substring-based on normalized text but token-boundary aware: a name must start at a
whitespace boundary and each of its words must match a whole word of the text, so ``tech`` never
matches ``technology``.  The last word of a multi-word name may carry an inflectional ending
(``Назарбаев Университета``, ``Назарбаев Университеті``): the leading words anchor the match,
and a prefix test on the final word keeps Russian/Kazakh case forms without opening the door to
single-word false positives.  Names shorter than four characters (after normalization) are never
used -- ``MIT`` alone would match far too much.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

MIN_NAME_LEN = 4

# ``\w`` includes ``_``; file names use ``_`` for spaces, so it is a separator here too
_NON_WORD_RE = re.compile(r"[^\w\s]|_")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize(text: str | None) -> str:
    """Section 10 normalization (``_`` counted as punctuation); ``None`` / empty give ``""``."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    folded = without_marks.casefold()
    spaced = _NON_WORD_RE.sub(" ", folded)
    return _WHITESPACE_RE.sub(" ", spaced).strip()


def _usable_names(names: Iterable[str | None]) -> list[str]:
    """Normalized, deduplicated names of length >= MIN_NAME_LEN, first occurrence order."""
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        normalized = normalize(name)
        if len(normalized) < MIN_NAME_LEN or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def name_terms(
    header_name: str | None,
    local_name: str | None,
    aliases: Iterable[str | None] = (),
) -> list[str]:
    """The normalized names to look for: header name, local name, aliases (deduped, >= 4 chars)."""
    return _usable_names([header_name, local_name, *aliases])


def contains_name(normalized_text: str, normalized_name: str) -> bool:
    """True when ``normalized_name`` occurs in ``normalized_text`` on token boundaries.

    Both arguments must already be normalized (single spaces, no leading/trailing whitespace),
    so padding both with one space turns "token boundary" into a plain substring test.  A
    multi-word name also matches when only its last word is a prefix of the text's word
    (inflected endings); a single-word name always needs the whole word.
    """
    if not normalized_text or not normalized_name:
        return False
    padded_text = f" {normalized_text} "
    if f" {normalized_name} " in padded_text:
        return True
    return " " in normalized_name and f" {normalized_name}" in padded_text


def match_names(names: Iterable[str | None], texts: Iterable[str | None]) -> bool:
    """True when any usable name occurs (token-boundary aware) in any of the texts."""
    usable = _usable_names(names)
    if not usable:
        return False
    for text in texts:
        normalized_text = normalize(text)
        if not normalized_text:
            continue
        if any(contains_name(normalized_text, name) for name in usable):
            return True
    return False
