"""Shared httpx.AsyncClient factory, User-Agent and retrying GET (SPEC Section 7, shared rules)."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import Settings
from app.logging_setup import log_external_call

log = logging.getLogger("app.http")

RETRY_STATUSES = frozenset({429, 502, 503, 504})
MAX_ATTEMPTS = 3  # 1 call + 2 retries
SENSITIVE_PARAMS = ("key", "api_key")
DEFAULT_TIMEOUT = httpx.Timeout(8.0, connect=4.0)


def user_agent(settings: Settings) -> str:
    return (
        "VisualCampus/1.0 (https://github.com/visual-campus/visual-campus; "
        f"{settings.contact_email})"
    )


def bot_user_agent(settings: Settings) -> str:
    """User-Agent for scraping official sites (Section 7.5)."""
    return f"Mozilla/5.0 (compatible; VisualCampusBot/1.0; +mailto:{settings.contact_email})"


def create_client(settings: Settings) -> httpx.AsyncClient:
    """The one shared client: redirects on, HTTP/2 off, explicit timeouts, bounded pool."""
    return httpx.AsyncClient(
        follow_redirects=True,
        http2=False,
        timeout=DEFAULT_TIMEOUT,
        limits=httpx.Limits(max_connections=40, max_keepalive_connections=20),
        headers={"User-Agent": user_agent(settings), "Accept": "application/json"},
    )


class RetryableStatus(Exception):
    """Raised internally to make tenacity retry a 429/502/503/504 response."""

    def __init__(self, response: httpx.Response) -> None:
        super().__init__(f"retryable status {response.status_code}")
        self.response = response


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(
        exc,
        (RetryableStatus, httpx.NetworkError, httpx.ConnectTimeout, httpx.RemoteProtocolError),
    )


def redact_url(url: str | httpx.URL, params: dict[str, Any] | None = None) -> str:
    """URL for logs: merged query params with api keys removed."""
    try:
        merged = httpx.URL(str(url))
        if params:
            merged = merged.copy_merge_params({k: str(v) for k, v in params.items()})
        for name in SENSITIVE_PARAMS:
            if name in merged.params:
                merged = merged.copy_remove_param(name)
        text = str(merged)
    except (ValueError, TypeError, httpx.InvalidURL):  # logging must never fail
        text = str(url)
    return text if len(text) <= 300 else text[:297] + "..."


async def get(
    client: httpx.AsyncClient,
    url: str,
    *,
    service: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | httpx.Timeout | None = None,
) -> httpx.Response:
    """GET with the Section 7 retry policy. Returns the final response (caller checks status).

    Retries (max 2) on connection errors and 429/502/503/504 with exponential backoff 0.5 -> 2 s.
    Other 4xx are returned immediately. Every call is logged without secrets.
    """
    request_timeout = timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT
    logged_url = redact_url(url, params)
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(MAX_ATTEMPTS),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=2.0),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    ):
        with attempt:
            started = time.monotonic()
            try:
                response = await client.get(
                    url, params=params, headers=headers, timeout=request_timeout
                )
            except httpx.HTTPError as exc:
                elapsed = int((time.monotonic() - started) * 1000)
                log_external_call(log, service, logged_url, type(exc).__name__, elapsed)
                raise
            elapsed = int((time.monotonic() - started) * 1000)
            log_external_call(log, service, logged_url, response.status_code, elapsed)
            if (
                response.status_code in RETRY_STATUSES
                and attempt.retry_state.attempt_number < MAX_ATTEMPTS
            ):
                raise RetryableStatus(response)
            return response
    raise RuntimeError("unreachable")  # pragma: no cover


async def get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    service: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | httpx.Timeout | None = None,
) -> Any:
    """GET + raise_for_status + JSON decode."""
    response = await get(
        client, url, service=service, params=params, headers=headers, timeout=timeout
    )
    response.raise_for_status()
    return response.json()
