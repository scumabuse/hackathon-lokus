"""Evaluation runner (SPEC Section 15.2): search -> first candidate -> profile -> markdown table.

Usage (from the repo root or backend/):
    python scripts/eval.py [--base-url http://localhost:8000] [--file scripts/universities.txt]
                           [--no-vision] [--no-refresh] [--no-check-thumbs] [--out EVAL.md]

--no-vision runs the app IN-PROCESS with GEMINI_API_KEY cleared (no server, no AI): every photo is
scored without vision and can be at most "likely". Without --no-vision the script talks to a
running server at --base-url (start it with: cd backend && uvicorn app.main:app).
The profile is requested with refresh=1 unless --no-refresh is given (Section 15.2 says refresh=1).
Every photo's thumb_url is fetched (--no-check-thumbs disables it) so "a thumb that loads" is
verified, not assumed. One failing university never stops the run: it becomes a row with the error.
Writes EVAL.md (Section 14, Phase 7) and prints the same table.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


@dataclass
class Row:
    university: str
    qid: str = "-"
    label: str = "-"
    total_ms: int = 0
    found: int = 0
    shown: int = 0
    verified: int = 0
    likely: int = 0
    hidden: int = 0
    dupes: int = 0
    irrelevant: int = 0
    warnings: list[str] = field(default_factory=list)
    per_source: dict[str, int] = field(default_factory=dict)
    thumb_failures: int = 0
    thumb_checked: int = 0
    missing_source_links: int = 0
    error: str | None = None

    def markdown(self) -> str:
        warn = ", ".join(self.warnings) if self.warnings else "-"
        if self.error:
            warn = f"ERROR: {self.error}"
        return (
            f"| {self.university} | {self.qid} | {self.total_ms} | {self.found} | {self.shown} | "
            f"{self.verified} | {self.likely} | {self.hidden} | {self.dupes} | {warn} |"
        )


HEADER = (
    "| university | qid | total_ms | found | shown | verified | likely | hidden | dupes | warnings |\n"
    "|---|---|---:|---:|---:|---:|---:|---:|---:|---|"
)


@contextlib.asynccontextmanager
async def make_client(base_url: str, in_process: bool) -> AsyncIterator[httpx.AsyncClient]:
    if not in_process:
        async with httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(90.0)) as client:
            yield client
        return
    os.environ["GEMINI_API_KEY"] = ""  # --no-vision: no AI at all
    sys.path.insert(0, str(BACKEND))
    os.chdir(BACKEND)
    from app.config import reset_settings_cache
    from app.main import create_app

    reset_settings_cache()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://eval", timeout=httpx.Timeout(90.0)
        ) as client:
            yield client


async def evaluate(
    client: httpx.AsyncClient, name: str, *, refresh: bool, check_thumbs: bool
) -> Row:
    row = Row(university=name)
    started = time.monotonic()
    try:
        search = await client.get("/api/search", params={"q": name})
        search.raise_for_status()
        candidates = search.json().get("candidates", [])
        if not candidates:
            row.error = "no candidates"
            return row
        row.qid = candidates[0]["qid"]
        row.label = candidates[0]["label"]
        response = await client.get(
            f"/api/profile/{row.qid}", params={"refresh": 1 if refresh else 0}
        )
        if response.status_code != 200:
            row.error = f"profile {response.status_code}: {response.text[:120]}"
            return row
        profile: dict[str, Any] = response.json()
    except httpx.HTTPError as exc:
        row.error = f"{type(exc).__name__}: {exc}"
        return row
    stats = profile["stats"]
    photos = profile["photos"]
    row.total_ms = int(stats["total_ms"])
    row.found = int(stats["found"])
    row.shown = int(stats["shown"])
    row.hidden = int(stats["hidden_unverified"])
    row.dupes = int(stats["duplicates_removed"])
    row.irrelevant = int(stats["irrelevant_removed"])
    row.per_source = dict(stats.get("per_source", {}))
    row.verified = sum(1 for p in photos if p["verification"] == "verified")
    row.likely = sum(1 for p in photos if p["verification"] == "likely")
    row.warnings = [
        w["code"] + (f":{w['detail']}" if w.get("detail") else "") for w in profile["warnings"]
    ]
    row.missing_source_links = sum(1 for p in photos if not p.get("source_page_url"))
    if check_thumbs:
        for photo in photos:
            row.thumb_checked += 1
            try:
                thumb = await client.get(photo["thumb_url"])
                if thumb.status_code != 200 or not thumb.headers.get("content-type", "").startswith(
                    "image/"
                ):
                    row.thumb_failures += 1
            except httpx.HTTPError:
                row.thumb_failures += 1
    row.total_ms = row.total_ms or int((time.monotonic() - started) * 1000)
    return row


def render(rows: list[Row], *, mode: str) -> str:
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# EVAL.md",
        "",
        f"Generated by scripts/eval.py on {generated} ({mode}).",
        "",
        HEADER,
        *(row.markdown() for row in rows),
        "",
        "## Details per university",
        "",
        (
            "| university | label | per_source | irrelevant | thumbs checked | thumb failures | "
            "photos without source link |"
        ),
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        sources = ", ".join(f"{k}={v}" for k, v in row.per_source.items()) or "-"
        lines.append(
            f"| {row.university} | {row.label} | {sources} | {row.irrelevant} | "
            f"{row.thumb_checked} | {row.thumb_failures} | {row.missing_source_links} |"
        )
    return "\n".join(lines) + "\n"


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--file", default=str(ROOT / "scripts" / "universities.txt"))
    parser.add_argument("--no-vision", action="store_true", help="in-process run without any AI")
    parser.add_argument("--no-refresh", action="store_true", help="do not pass refresh=1")
    parser.add_argument("--no-check-thumbs", action="store_true")
    parser.add_argument("--out", default=str(ROOT / "EVAL.md"))
    args = parser.parse_args()

    names = [
        line.strip()
        for line in Path(args.file).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    mode = "no vision, in-process" if args.no_vision else f"server {args.base_url}"
    rows: list[Row] = []
    async with make_client(args.base_url, args.no_vision) as client:
        for name in names:
            row = await evaluate(
                client, name, refresh=not args.no_refresh, check_thumbs=not args.no_check_thumbs
            )
            rows.append(row)
            print(row.markdown(), flush=True)
    report = render(rows, mode=mode)
    Path(args.out).write_text(report, encoding="utf-8")
    print(f"\nwrote {args.out}")
    failures = [r for r in rows if r.error or r.thumb_failures or r.missing_source_links]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
