"""Diagnose one profile build stage by stage (FIX_AND_RESTYLE Part A).

Runs the real pipeline IN-PROCESS for a university name (or a QID) at DEBUG level, bypassing
the profile cache, and prints a markdown stage table:

    candidates per source -> after normalize -> downloads ok/failed (with failure reasons)
    -> dedup groups -> vision batches sent/parsed/failed -> removals per post-processing rule
    -> label distribution (verified/likely/unverified) -> shown/hidden

Every exception that any stage caught (log records carrying exc_info) is printed with its
traceback at the end, so a silently swallowed failure cannot hide.

How to run (uses the repo-root .env, i.e. the real GEMINI_API_KEY when present):
    cd backend && python ../scripts/diagnose.py "Al-Farabi Kazakh National University"
    cd backend && python ../scripts/diagnose.py Q49108 --no-vision
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import logging
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

_REJECT_RE = re.compile(r"^image skipped (?P<url>\S+) \((?P<source>[^)]+)\): (?P<reason>.*)$")


class Capture(logging.Handler):
    """Keeps every record; counts download rejections by reason; collects tracebacks."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []
        self.rejections: collections.Counter[str] = collections.Counter()
        self.exceptions: list[tuple[logging.LogRecord, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
        message = record.getMessage()
        match = _REJECT_RE.match(message)
        if match:
            reason = match.group("reason")
            reason = re.sub(r"\d+x\d+", "WxH", reason)
            reason = re.sub(r"\d+(\.\d+)?", "N", reason)
            self.rejections[reason] += 1
        if record.exc_info and record.exc_info[0] is not None:
            self.exceptions.append((record, "".join(traceback.format_exception(*record.exc_info))))


@dataclass
class Report:
    query: str
    qid: str | None = None
    name: str | None = None
    coords: str = "-"
    per_source: dict[str, int] = field(default_factory=dict)
    source_errors: dict[str, str] = field(default_factory=dict)
    found: int = 0
    downloads_ok: int = 0
    downloads_failed: int = 0
    downloads_timed_out: int = 0
    dedup_in: int = 0
    dedup_kept: int = 0
    dedup_removed: int = 0
    logo_removed: int = 0
    batches: list[dict[str, Any]] = field(default_factory=list)
    removals: collections.Counter[str] = field(default_factory=collections.Counter)
    labels: collections.Counter[str] = field(default_factory=collections.Counter)
    emitted: int = 0
    header_ms: int | None = None
    first_photos_ms: int | None = None
    stats: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    wall_ms: int = 0


def removal_rule(image: Any, info: Any) -> str | None:
    """Mirror of Section 9 post-processing, used only to attribute removals to a rule."""
    if not info.usable:
        return None
    if not info.is_photo:
        return "is_photo=false"
    if info.people_prominent:
        return "people_prominent"
    if not info.quality_ok:
        return "quality_ok=false"
    if str(image.candidate.source_type.value) == "city_commons":
        return None
    if not info.plausibly_university_related and str(info.category) != "Category.city":
        return "not plausibly related"
    if info.category is not None and info.category.value == "other":
        return "category=other"
    return None


def install_probes(report: Report) -> None:
    """Wrap the stage functions the pipeline calls so their inputs/outputs are recorded."""
    from app import pipeline
    from app.ai import vision

    real_download = pipeline.download_candidates
    real_dedupe = pipeline.dedupe
    real_classify = vision.classify_batch
    real_post = vision.apply_post_processing

    async def download_probe(*args: Any, **kwargs: Any) -> Any:
        result = await real_download(*args, **kwargs)
        report.downloads_ok += len(result.images)  # summed over the download waves
        report.downloads_failed += result.failed
        report.downloads_timed_out += result.timed_out
        return result

    def dedupe_probe(images: Any, **kwargs: Any) -> Any:
        result = real_dedupe(images, **kwargs)
        report.dedup_in = len(images)
        report.dedup_kept = len(result.kept)
        report.dedup_removed = result.removed
        report.logo_removed = result.logo_removed
        return result

    async def classify_probe(ai: Any, images: Any, header: Any, **kwargs: Any) -> Any:
        started = time.monotonic()
        outcome = await real_classify(ai, images, header, **kwargs)
        usable = sum(1 for i in outcome.infos if i.available and not i.timed_out)
        report.batches.append(
            {
                "n": len(images),
                "target": kwargs.get("target", "university"),
                "parsed_first_attempt": outcome.parsed_first_attempt,
                "usable": usable,
                "error": outcome.error,
                "ms": int((time.monotonic() - started) * 1000),
            }
        )
        return outcome

    def post_probe(image: Any, info: Any) -> Any:
        result_info, keep = real_post(image, info)
        if not keep:
            report.removals[removal_rule(image, info) or "unknown rule"] += 1
        return result_info, keep

    pipeline.download_candidates = download_probe  # type: ignore[assignment]
    pipeline.dedupe = dedupe_probe  # type: ignore[assignment]
    vision.classify_batch = classify_probe  # type: ignore[assignment]
    vision.apply_post_processing = post_probe  # type: ignore[assignment]


async def run(query: str, *, no_vision: bool) -> Report:
    if no_vision:
        os.environ["GEMINI_API_KEY"] = ""
    from app.config import reset_settings_cache

    reset_settings_cache()
    from app.ai.client import AIClient
    from app.cache import Cache
    from app.config import get_settings
    from app.http import create_client
    from app.pipeline import PipelineDeps, run_pipeline
    from app.resolver.search import search_universities

    settings = get_settings()
    settings.thumbs_dir.mkdir(parents=True, exist_ok=True)
    report = Report(query=query)
    install_probes(report)
    http = create_client(settings)
    ai = AIClient(settings)
    cache = Cache(settings.cache_db_path)
    await cache.init()
    if settings.gemini_api_key:
        await ai.startup_check()
    try:
        if re.fullmatch(r"Q\d+", query):
            qid = query
        else:
            search = await search_universities(http, query, ai=ai, cache=cache)
            if not search.candidates:
                report.error = "no candidates"
                return report
            qid = search.candidates[0].qid
        report.qid = qid
        deps = PipelineDeps(settings=settings, http=http, ai=ai, cache=cache)
        started = time.monotonic()
        async for event in run_pipeline(deps, qid, refresh=True):
            if event.name == "header":
                report.header_ms = int((time.monotonic() - started) * 1000)
                report.name = event.data.get("name")
                coords = event.data.get("coords")
                report.coords = (
                    f"{coords['lat']:.4f}, {coords['lon']:.4f}" if coords else "none (no P625)"
                )
            elif event.name == "photos":
                if report.first_photos_ms is None:
                    report.first_photos_ms = int((time.monotonic() - started) * 1000)
                for photo in event.data["photos"]:
                    report.labels[photo["verification"]] += 1
                    report.emitted += 1
            elif event.name == "warning":
                detail = event.data.get("detail")
                report.warnings.append(event.data["code"] + (f": {detail}" if detail else ""))
            elif event.name == "stats":
                report.stats = event.data
                report.per_source = dict(event.data.get("per_source", {}))
                report.found = int(event.data.get("found", 0))
        report.wall_ms = int((time.monotonic() - started) * 1000)
    except Exception as exc:  # noqa: BLE001 - the whole point of this script is to show it
        report.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    finally:
        await cache.close()
        await ai.aclose()
        await http.aclose()
    return report


def render(report: Report, capture: Capture) -> str:
    stats = report.stats
    rows = [
        ("query", report.query),
        ("qid / name", f"{report.qid} / {report.name}"),
        ("campus coords", report.coords),
        (
            "candidates per source",
            ", ".join(f"{k}={v}" for k, v in report.per_source.items()) or "-",
        ),
        ("after normalize (found)", str(report.found)),
        (
            "downloads ok / failed / timed out",
            f"{report.downloads_ok} / {report.downloads_failed} / {report.downloads_timed_out}",
        ),
        (
            "download failure reasons",
            "; ".join(f"{k} x{v}" for k, v in capture.rejections.most_common()) or "-",
        ),
        (
            "dedup in -> kept (duplicates removed, logo matches)",
            f"{report.dedup_in} -> {report.dedup_kept} ({report.dedup_removed}, {report.logo_removed})",
        ),
        (
            "vision batches sent / parsed 1st / usable images / failed",
            (
                f"{len(report.batches)} / "
                f"{sum(1 for b in report.batches if b['parsed_first_attempt'])} / "
                f"{sum(b['usable'] for b in report.batches)} / "
                f"{sum(1 for b in report.batches if b['error'])}"
            ),
        ),
        (
            "vision batch errors",
            "; ".join(sorted({str(b["error"])[:80] for b in report.batches if b["error"]})) or "-",
        ),
        (
            "removals per post-processing rule",
            "; ".join(f"{k} x{v}" for k, v in report.removals.most_common()) or "-",
        ),
        (
            "labels emitted (verified / likely / unverified)",
            f"{report.labels['verified']} / {report.labels['likely']} / {report.labels['unverified']}",
        ),
        (
            "stats: found / duplicates / irrelevant / shown / hidden",
            (
                f"{stats.get('found', '-')} / {stats.get('duplicates_removed', '-')} / "
                f"{stats.get('irrelevant_removed', '-')} / {stats.get('shown', '-')} / "
                f"{stats.get('hidden_unverified', '-')}"
            ),
        ),
        ("timings ms", ", ".join(f"{k}={v}" for k, v in stats.get("timings_ms", {}).items())),
        ("warnings", "; ".join(report.warnings) or "-"),
        (
            "header / first photos / done (ms after start)",
            f"{report.header_ms} / {report.first_photos_ms} / {report.wall_ms}",
        ),
    ]
    lines = ["| stage | value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rows]
    if report.error:
        lines.append(f"| pipeline error | {report.error.splitlines()[0]} |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("query", help="university name or QID")
    parser.add_argument("--no-vision", action="store_true", help="run without any AI")
    args = parser.parse_args()

    capture = Capture()
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(capture)
    from app.logging_setup import setup_logging

    setup_logging("DEBUG")
    root.setLevel(logging.DEBUG)
    for noisy in ("httpx", "httpcore", "google_genai", "google.genai", "urllib3", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    report = asyncio.run(run(args.query, no_vision=args.no_vision))
    print("\n" + render(report, capture))
    warnings_logged = [r for r in capture.records if r.levelno >= logging.WARNING]
    print(f"\nWARNING+ log records: {len(warnings_logged)}")
    for record in warnings_logged:
        print(f"  [{record.levelname}] {record.name}: {record.getMessage()[:200]}")
    print(f"\nCaught exceptions with traceback: {len(capture.exceptions)}")
    for record, tb in capture.exceptions:
        print(f"--- {record.name}: {record.getMessage()[:120]}\n{tb}")
    if report.error:
        print("\nPIPELINE ERROR:\n" + report.error)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
