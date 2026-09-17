"""All prompt texts sent to the Anthropic API live in this module (SPEC Sections 7.8, 9).

Phase 1 ships only the spelling-normalization prompt (Section 7.8.b). Phase 3 adds the vision
system prompt, the per-batch header/footer texts and the description prompt (Sections 7.8.a, 9)
as constants in this same file, so the README can link to one place for every prompt.
"""

from __future__ import annotations

# Section 7.8.b -- resolver fallback only. Filled with str.format(q=<the user query>).
SPELLING_PROMPT = (
    'The user typed a university name that was not found: "{q}". Return ONLY a JSON array of '
    "up to 3 strings with the most probable official English names of the university they "
    "meant, as used on Wikipedia and Wikidata. No explanations, no markdown, no text outside "
    "the array."
)
