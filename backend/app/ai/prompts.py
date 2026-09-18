"""All prompt texts sent to the Gemini API live in this module (SPEC Sections 7.8, 9).

Phase 1: SPELLING_PROMPT (Section 7.8.b).
Phase 3: VISION_SYSTEM, VISION_HEADER, VISION_FOOTER (Section 9),
         DESCRIPTION_PROMPT (Section 7.8.a).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Section 7.8.b — resolver fallback only. Filled with str.format(q=<query>).
# ---------------------------------------------------------------------------

SPELLING_PROMPT = (
    'The user typed a university name that was not found: "{q}". Return ONLY a JSON array of '
    "up to 3 strings with the most probable official English names of the university they "
    "meant, as used on Wikipedia and Wikidata. No explanations, no markdown, no text outside "
    "the array."
)

# ---------------------------------------------------------------------------
# Section 9 — vision classification
# ---------------------------------------------------------------------------

VISION_SYSTEM = (
    "You are an image-classification component inside a pipeline that builds a verified visual "
    "profile of a university for prospective students. You receive N images from various web "
    "sources. Your job is to classify each image strictly according to the schema provided. "
    "Be conservative: when in doubt, prefer lower confidence and 'other'. Never invent details "
    "not visible in the image. Return only valid JSON."
)

# Filled per batch; placeholders: {name}, {aliases}, {city}, {country}, {n}
VISION_HEADER = (
    "University: {name} (aliases: {aliases}). City: {city}, {country}. "
    "Classify each of the N={n} images below. For each image return an object: "
    '{"index": <1..N>, '
    '"is_photo": <true|false>, '
    '// false for logos, emblems, maps, floor plans, diagrams, 3D renders/visualizations, '
    "screenshots, documents, slides, text-only graphics, coats of arms\n"
    '"category": "campus"|"dormitory"|"classroom"|"library"|"lab"|"sport"|"student_life"'
    '|"city"|"other", '
    '"category_confidence": <0.0-1.0>, '
    '"plausibly_university_related": <true|false>, '
    "// the scene could plausibly be a university campus/facility/student activity, "
    "or the named city; false for unrelated scenery\n"
    '"name_on_sign": <true|false>, '
    "// true ONLY if readable text in the image clearly contains the university name "
    "or an alias (any language or script)\n"
    '"visible_text": <string up to 80 chars, or null>, '
    '"people_prominent": <true|false>, '
    "// a person or face is the main subject\n"
    '"quality_ok": <true|false>, '
    "// false if blurry, tiny, heavily watermarked, or dominated by overlaid text/advertising\n"
    '"reason": <string, max 12 words>}'
)

VISION_HEADER_CITY = (
    "University: {name}. City: {city}, {country}. "
    "The following N={n} images are from a Wikimedia Commons category for the city, NOT the "
    "university. Classify each image. For each image return an object with the same schema as "
    "above; category should be 'city' unless the image clearly shows a university building/event."
)

VISION_FOOTER = (
    "Return ONLY a JSON array with exactly N objects, ordered by index 1..N. "
    "No markdown, no comments, no text outside the array."
)

VISION_RETRY_SUFFIX = (
    "\nYour previous output was not a valid JSON array of N objects. "
    "Output only the JSON array."
)

# ---------------------------------------------------------------------------
# Section 7.8.a — campus description.
# Placeholders: {name}, {local_name}, {city}, {country},
#               {en_extract}, {ru_extract}, {site_meta}, {source_urls}
# ---------------------------------------------------------------------------

DESCRIPTION_PROMPT = (
    "You write a short, factual campus description for prospective students, based ONLY on the "
    "provided source texts. Do not add facts that are not in the sources. "
    "Return ONLY a JSON object: "
    '{"text_ru": "<3-5 sentences in Russian>", '
    '"text_en": "<3-5 sentences in English>", '
    '"basis": "wikipedia_and_site" | "wikipedia_only" | "site_only" | "insufficient"}. '
    "Cover, when available: where the campus is (city, district), what the campus is like "
    "(buildings, size, notable facilities: libraries, dormitories, labs, sports), "
    "student life highlights.\n\n"
    "University: {name}{local_name_part}. City: {city}, {country}.\n"
    "{en_extract_part}"
    "{ru_extract_part}"
    "{site_meta_part}"
    "Source URLs used: {source_urls}"
)
