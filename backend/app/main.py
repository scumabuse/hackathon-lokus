"""FastAPI app factory: /api/* routes, static SPA mount with fallback (SPEC Sections 12, 16)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

from app.ai.client import AIClient
from app.api.routes import router as api_router
from app.cache import Cache
from app.config import Settings, get_settings
from app.http import create_client
from app.logging_setup import setup_logging
from app.version import app_version

log = logging.getLogger("app.main")

STATIC_DIR = Path(__file__).resolve().parent / "static"

_STATUS_CODES = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    422: "unprocessable",
    429: "too_many_requests",
    500: "internal_error",
    503: "service_unavailable",
}


def error_body(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


def validation_message(exc: RequestValidationError) -> str:
    """Human-readable text for the Section 12 error envelope, e.g. "q: string too short"."""
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()) if p not in ("query", "path", "body"))
        msg = str(err.get("msg", "invalid value"))
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts) or "invalid request"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    try:
        settings.thumbs_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # the app still serves: the cache degrades to a no-op and thumbs become unavailable
        log.warning(
            "cannot create %s (%s); thumbnails will be unavailable", settings.thumbs_dir, exc
        )
    app.state.http = create_client(settings)
    app.state.ai = AIClient(settings)
    app.state.cache = Cache(settings.cache_db_path)
    await app.state.cache.init()
    if settings.gemini_api_key:
        # never fails startup: on error the client marks itself unavailable and logs loudly
        await app.state.ai.startup_check()
    log.info(
        "visual-campus %s starting; cache_dir=%s ai=%s",
        app_version(),
        settings.cache_dir,
        "on" if app.state.ai.available else "off",
    )
    try:
        yield
    finally:
        await app.state.cache.close()
        await app.state.ai.aclose()
        await app.state.http.aclose()


def create_app(settings: Settings | None = None, static_dir: Path | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)
    app = FastAPI(title="Visual Campus", version=app_version(), lifespan=lifespan)
    app.state.settings = settings

    if settings.allowed_origins_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.allowed_origins_list,
            allow_methods=["GET"],
            allow_headers=["*"],
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            body = error_body(str(detail["code"]), str(detail.get("message", "")))
        else:
            body = error_body(_STATUS_CODES.get(exc.status_code, "http_error"), str(detail))
        return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422, content=error_body("validation_error", validation_message(exc))
        )

    app.include_router(api_router, prefix="/api")
    _mount_spa(app, static_dir or STATIC_DIR)
    return app


def _mount_spa(app: FastAPI, static_dir: Path) -> None:
    """Serve the built frontend; any non-API GET that is not a file returns index.html."""
    static_dir = static_dir.resolve()
    index_file = static_dir / "index.html"
    if not index_file.is_file():
        log.warning("frontend build not found at %s; only /api is served", static_dir)
        return
    assets_dir = static_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
    async def spa(full_path: str) -> Response:
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse(
                status_code=404, content=error_body("not_found", "unknown API path")
            )
        candidate = (static_dir / full_path).resolve()
        if full_path and candidate.is_file() and static_dir in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index_file)


app = create_app()
