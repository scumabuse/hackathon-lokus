"""HTTP API (SPEC Section 12)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from app.version import app_version

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "version": app_version(),
        "time": datetime.now(UTC).isoformat(),
    }
