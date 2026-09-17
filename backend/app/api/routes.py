"""HTTP API (SPEC Section 12)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from app.models import SearchResponse
from app.resolver.search import search_universities
from app.version import app_version

router = APIRouter()

QUERY_MIN_LEN = 2
QUERY_MAX_LEN = 120


def clean_query(q: str) -> str:
    """Collapse whitespace, then enforce the Section 12 length rule (2-120 chars) -> 422."""
    query = " ".join(q.split())
    if not QUERY_MIN_LEN <= len(query) <= QUERY_MAX_LEN:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "validation_error",
                "message": f"q must be {QUERY_MIN_LEN}-{QUERY_MAX_LEN} characters",
            },
        )
    return query


@router.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "version": app_version(),
        "time": datetime.now(UTC).isoformat(),
    }


@router.get("/search", response_model=SearchResponse)
async def search(
    request: Request, q: Annotated[str, Query(min_length=QUERY_MIN_LEN, max_length=QUERY_MAX_LEN)]
) -> SearchResponse:
    """Section 7.1 resolver: Wikidata search with Wikipedia / spelling fallbacks, cached 6 h."""
    state = request.app.state
    return await search_universities(
        state.http,
        clean_query(q),
        ai=getattr(state, "ai", None),
        cache=getattr(state, "cache", None),
    )
