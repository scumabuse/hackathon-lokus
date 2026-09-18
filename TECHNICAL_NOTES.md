# Technical Notes

This document provides internal technical context on the implementation of Visual Campus.

## Statement of Implementation
**All code in this repository was written during the hackathon window with the assistance of AI coding assistants.** 

## External Services & APIs
1. **Wikidata API:** Used to resolve user queries into an internal QID, map university categories, logos, aliases, coordinates, and city information.
2. **Wikipedia REST API:** Used to pull down plain-text summaries (ru/en) to be synthesized by the LLM.
3. **Wikimedia Commons API:** Main image provider (category lookup, geo search, file querying).
4. **Official Sites (Direct HTTP):** Websites extracted via Wikidata P856 are scraped asynchronously with `BeautifulSoup4`. Image URLs are validated and downloaded.
5. **Gemini API:** Used for `vision` and `text` processing. 
    - Replaced the previously specified Anthropic Claude in accordance with `Amendment A`.
    - Handles classification (vision) and description generation (text).

## Architecture & Data Flow
The architecture is defined around a strict **27-second hard deadline**.
- **`pipeline.py`** coordinates the stages asynchronously using `asyncio` events and semaphores.
- **Stage A (Resolution):** `resolver/` module queries Wikidata/Wikipedia.
- **Stage B (Collection):** `sources/` module fans out to collect candidates. Handled by a polymorphic `BaseSource` class. 
- **Stage C & D & E (Processing):** Deduplication runs on both URL exact matches and Perceptual Hashing (pHash) on the actual bytes to merge near-duplicates.
- **Stage F & G (Vision & Scoring):** Vision processing batches up to 8 images per Gemini request to maximize throughput within the rate limits. Scoring computes deterministically. 

## Verification Methods
Vision models hallucinate. Therefore, we do not allow the AI to *decide* if an image is verified. 
We use an additive scoring algorithm based on factual metadata (GPS distance, URL provenance, name metadata). The AI acts as a **bonus** multiplier (`+0.15` for scene consistency, `+0.15` for OCR'ing the name on a sign). 
If the API fails, the image gets zero AI bonus and simply maxes out at "Likely" based purely on metadata.

## Evaluation Results
See `EVAL.md` for the auto-generated evaluation run over the 10 core universities.
