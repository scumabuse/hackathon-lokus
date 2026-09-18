"""Probe the real Gemini API with the configured key (no data is stored).

What it checks:
  1. which models the key can list (first 40 ids);
  2. one tiny text call on VISION_MODEL (latency, usage);
  3. one image-classification call with two real Commons thumbnails from
     backend/tests/fixtures/images and JSON output (response_mime_type=application/json);
  4. a burst of N concurrent tiny text calls to observe free-tier rate limiting (429s).

How to run:  cd backend && python ../scripts/probe_gemini.py [burst_size]
Reads GEMINI_API_KEY / VISION_MODEL from the environment or the repo-root .env file.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from google import genai
from google.genai import errors, types

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    env_file = ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    values.update({k: v for k, v in os.environ.items() if k in ("GEMINI_API_KEY", "VISION_MODEL")})
    return values


async def main() -> None:
    env = load_env()
    key = env.get("GEMINI_API_KEY", "")
    model = env.get("VISION_MODEL") or "gemini-3.5-flash-lite"
    if not model.startswith("gemini"):
        model = "gemini-3.5-flash-lite"
    print(f"key present: {bool(key)} (len {len(key)}); model: {model}")
    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=30_000))

    print("\n=== 1. models.list ===")
    try:
        names = []
        async for m in await client.aio.models.list():
            names.append(m.name)
        print(len(names), "models;", [n for n in names if "flash" in n][:40])
    except errors.APIError as exc:
        print("list failed:", exc.code, exc.status, exc.message)

    print("\n=== 2. text call ===")
    t = time.monotonic()
    try:
        resp = await client.aio.models.generate_content(
            model=model,
            contents="Reply with the single word OK.",
            config=types.GenerateContentConfig(temperature=0, max_output_tokens=20),
        )
        print(f"{int((time.monotonic() - t) * 1000)} ms ->", repr(resp.text), resp.usage_metadata)
    except errors.APIError as exc:
        print("text failed:", exc.code, exc.status, exc.message)

    print("\n=== 3. image classification (JSON) ===")
    images = sorted((ROOT / "backend/tests/fixtures/images").glob("*.jpg"))[:2]
    parts: list[types.Part] = [
        types.Part.from_text(
            text="Classify each image. Return ONLY a JSON array of objects {index, category, is_photo, reason} ordered by index 1..N."
        )
    ]
    for i, path in enumerate(images, 1):
        parts.append(types.Part.from_text(text=f"IMAGE {i}"))
        parts.append(types.Part.from_bytes(data=path.read_bytes(), mime_type="image/jpeg"))
    parts.append(types.Part.from_text(text="Return ONLY the JSON array."))
    t = time.monotonic()
    try:
        resp = await client.aio.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(
                system_instruction="You are an image-classification component. Categories: campus, lab, other.",
                temperature=0,
                max_output_tokens=600,
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
            ),
        )
        ms = int((time.monotonic() - t) * 1000)
        print(
            f"{ms} ms; finish={resp.candidates[0].finish_reason if resp.candidates else None}; usage={resp.usage_metadata}"
        )
        print("text:", (resp.text or "")[:500])
        json.loads(resp.text or "")
        print("JSON parse: ok")
    except errors.APIError as exc:
        print("image call failed:", exc.code, exc.status, exc.message)
    except (ValueError, TypeError) as exc:
        print("image call parse problem:", exc)

    burst = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    print(f"\n=== 4. burst of {burst} concurrent tiny calls ===")

    async def one(i: int) -> str:
        t0 = time.monotonic()
        try:
            r = await client.aio.models.generate_content(
                model=model,
                contents=f"Reply with the number {i}.",
                config=types.GenerateContentConfig(temperature=0, max_output_tokens=10),
            )
            return (
                f"#{i} ok {int((time.monotonic() - t0) * 1000)}ms {(r.text or '').strip()[:10]!r}"
            )
        except errors.APIError as exc:
            return f"#{i} ERR {exc.code} {exc.status} {int((time.monotonic() - t0) * 1000)}ms {str(exc.message)[:160]}"

    results = await asyncio.gather(*(one(i) for i in range(burst)))
    for line in results:
        print("  ", line)


if __name__ == "__main__":
    asyncio.run(main())
