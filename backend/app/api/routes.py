"""HTTP API (SPEC Section 12)."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from app.models import Profile, SearchResponse
from app.pipeline import PipelineDeps, ProfileNotFound, build_profile, run_pipeline
from app.resolver.search import search_universities
from app.resolver.wikidata import ResolverUnavailableError
from app.version import app_version

log = logging.getLogger("app.api")

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


# ----------------------------------------------------------------------------- profile + thumbs

QID_RE = re.compile(r"^Q\d+$")
PHOTO_ID_RE = re.compile(r"^[0-9a-f]{16}$")
THUMB_CACHE_CONTROL = "public, max-age=86400"


def pipeline_deps(request: Request) -> PipelineDeps:
    state = request.app.state
    return PipelineDeps(settings=state.settings, http=state.http, ai=state.ai, cache=state.cache)


def validate_qid(qid: str) -> str:
    if not QID_RE.match(qid):
        raise HTTPException(
            status_code=422,
            detail={"code": "validation_error", "message": "qid must look like Q12345"},
        )
    return qid


@router.get("/profile/{qid}", response_model=Profile)
async def profile(
    request: Request, qid: str, refresh: Annotated[int, Query(ge=0, le=1)] = 0
) -> Profile:
    """Section 12: the whole profile in one blocking response (the SSE variant streams it)."""
    validate_qid(qid)
    try:
        return await build_profile(pipeline_deps(request), qid, refresh=bool(refresh))
    except ProfileNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "unknown qid or not a university"},
        ) from exc
    except ResolverUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "resolver_unavailable",
                "message": f"could not resolve the university right now: {exc}",
            },
        ) from exc


@router.get("/profile/{qid}/stream")
async def profile_stream(
    request: Request,
    qid: str,
    refresh: Annotated[int, Query(ge=0, le=1)] = 0,
) -> EventSourceResponse:
    """Section 12 SSE endpoint: streams header → warnings → photos batches → description → stats → done.

    Headers: Cache-Control: no-cache, X-Accel-Buffering: no (Section 12).
    A ping comment every 5 s is handled by sse-starlette's ping parameter.
    """
    validate_qid(qid)
    deps = pipeline_deps(request)

    async def _event_generator() -> AsyncGenerator[dict[str, Any], None]:
        try:
            async for event in run_pipeline(deps, qid, refresh=bool(refresh)):
                yield {
                    "event": event.name,
                    "data": json.dumps(event.data, ensure_ascii=False, default=str),
                }
        except ProfileNotFound:
            yield {
                "event": "error",
                "data": json.dumps(
                    {"code": "not_found", "message": "unknown qid or not a university"}
                ),
            }
        except ResolverUnavailableError as exc:
            yield {
                "event": "error",
                "data": json.dumps({"code": "resolver_unavailable", "message": str(exc)}),
            }
        except Exception as exc:
            # never silent: the stream ends with an error event AND the traceback is logged
            log.warning("profile stream for %s crashed: %s", qid, exc, exc_info=True)
            yield {
                "event": "error",
                "data": json.dumps({"code": "internal_error", "message": str(exc)}),
            }

    return EventSourceResponse(
        _event_generator(),
        ping=5,
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/thumb/{photo_id}.jpg", response_class=FileResponse)
async def thumb(request: Request, photo_id: str) -> Response:
    """Thumbnails are always served by our backend (never hotlinked), 24 h cacheable."""
    not_found = HTTPException(
        status_code=404, detail={"code": "not_found", "message": "thumbnail not found"}
    )
    if not PHOTO_ID_RE.match(photo_id):
        raise not_found
    path = request.app.state.settings.thumbs_dir / f"{photo_id}.jpg"
    if not path.is_file():
        raise not_found
    return FileResponse(
        path, media_type="image/jpeg", headers={"Cache-Control": THUMB_CACHE_CONTROL}
    )
