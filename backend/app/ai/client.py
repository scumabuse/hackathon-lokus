"""Anthropic client wrapper: startup check, retry policy, text calls, JSON recovery.

SPEC Sections 7.7, 7.8 and 9 ("Parsing"). One ``AsyncAnthropic`` per process, created only when
``ANTHROPIC_API_KEY`` is set. Every request goes through one tenacity policy: 2 retries with
exponential backoff (1 -> 4 s) on 429, connection errors / timeouts and 5xx; never on other 4xx.
The SDK's built-in retries are disabled so that this policy is the only one.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import anthropic
from anthropic import AsyncAnthropic
from anthropic.types import Message
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import Settings

log = logging.getLogger("app.ai")

MAX_ATTEMPTS = 3  # 1 call + 2 retries (SPEC Section 9)
RETRY_WAIT = wait_exponential(multiplier=1.0, min=1.0, max=4.0)  # 1 s, then 2 s (capped at 4 s)
DEFAULT_TIMEOUT_S = 30.0  # the SDK default is 600 s; no call may outlive the 30 s budget
STARTUP_CHECK_TIMEOUT_S = 10.0
STARTUP_CHECK_PROMPT = "Reply with the single word OK."

_FENCE_OPEN = re.compile(r"^```[A-Za-z0-9_-]*[ \t]*\r?\n?")
_FENCE_CLOSE = re.compile(r"\r?\n?[ \t]*```\s*$")


class AIUnavailableError(RuntimeError):
    """No API key is configured or the startup check failed; AI features are switched off."""


def is_retryable(exc: BaseException) -> bool:
    """Retry on 429, connection errors / timeouts and 5xx; never on any other 4xx."""
    if isinstance(exc, (anthropic.RateLimitError, anthropic.APIConnectionError)):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code >= 500
    return False


def _retrying() -> AsyncRetrying:
    return AsyncRetrying(
        stop=stop_after_attempt(MAX_ATTEMPTS),
        wait=RETRY_WAIT,
        retry=retry_if_exception(is_retryable),
        reraise=True,
    )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _status_suffix(exc: BaseException) -> str:
    return f"({exc.status_code})" if isinstance(exc, anthropic.APIStatusError) else ""


def message_text(message: Message) -> str:
    """Section 9 parsing: the concatenated text blocks of a response."""
    return "".join(block.text for block in message.content if block.type == "text")


def strip_code_fences(text: str) -> str:
    """Drop a leading ```json / ``` fence line and a trailing ``` fence, if present."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = _FENCE_OPEN.sub("", stripped, count=1)
        stripped = _FENCE_CLOSE.sub("", stripped, count=1)
    return stripped.strip()


def parse_json_text(text: str) -> Any:
    """Strip fences and ``json.loads``; else try the outermost ``[...]`` / ``{...}`` substring.

    Raises ValueError when no valid JSON can be recovered.
    """
    cleaned = strip_code_fences(text)
    spans: list[tuple[int, int]] = []
    for opener, closer in (("[", "]"), ("{", "}")):
        start, end = cleaned.find(opener), cleaned.rfind(closer)
        if start != -1 and end > start:
            spans.append((start, end + 1))
    candidates = [cleaned, *(cleaned[start:end] for start, end in sorted(spans))]
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise ValueError("model output contains no valid JSON")


class AIClient:
    """Thin wrapper over ``AsyncAnthropic`` with the shared retry policy and an availability flag."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: AsyncAnthropic | None = None
        self.available: bool = False
        if settings.anthropic_api_key:
            # max_retries=0: the SDK's own retries would stack on top of the tenacity policy
            self._client = AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=0)
            self.available = True

    @property
    def configured(self) -> bool:
        """True when an API key is set (regardless of the startup check)."""
        return self._client is not None

    @property
    def vision_model(self) -> str:
        return self._settings.vision_model

    @property
    def text_model(self) -> str:
        return self._settings.effective_text_model

    async def startup_check(self) -> bool:
        """One tiny text call (max_tokens=5). Failure disables AI features but never raises."""
        if self._client is None:
            log.info("ANTHROPIC_API_KEY not set: vision classification and AI description are off")
            self.available = False
            return False
        self.available = True
        try:
            message = await self.create_message(
                model=self.text_model,
                max_tokens=5,
                temperature=0.0,
                messages=[{"role": "user", "content": STARTUP_CHECK_PROMPT}],
                timeout=STARTUP_CHECK_TIMEOUT_S,
            )
        except Exception:
            self.available = False
            log.warning(
                "!!! ANTHROPIC STARTUP CHECK FAILED (model=%s): vision classification and AI "
                "description are DISABLED; the app keeps serving without them !!!",
                self.text_model,
                exc_info=True,
            )
            return False
        log.info(
            "anthropic startup check ok: model=%s reply=%r",
            self.text_model,
            message_text(message)[:40],
        )
        return True

    async def create_message(self, **kwargs: Any) -> Message:
        """``messages.create`` with the retry policy (Phase 3 vision batches call this directly).

        A missing ``timeout`` defaults to DEFAULT_TIMEOUT_S. Raises AIUnavailableError when the
        client is off, otherwise the SDK exception once the retries are exhausted.
        """
        if self._client is None or not self.available:
            raise AIUnavailableError("Anthropic API unavailable: no key or startup check failed")
        kwargs.setdefault("timeout", DEFAULT_TIMEOUT_S)
        model = str(kwargs.get("model", "?"))
        client = self._client
        async for attempt in _retrying():
            with attempt:
                started = time.monotonic()
                try:
                    message = await client.messages.create(**kwargs)
                except anthropic.AnthropicError as exc:
                    log.info(
                        "anthropic messages.create model=%s -> %s%s %dms",
                        model,
                        type(exc).__name__,
                        _status_suffix(exc),
                        _elapsed_ms(started),
                    )
                    raise
                log.info(
                    "anthropic messages.create model=%s -> ok %dms", model, _elapsed_ms(started)
                )
                return message
        raise RuntimeError("unreachable")  # pragma: no cover

    async def complete_text(
        self,
        prompt: str,
        *,
        max_tokens: int,
        temperature: float = 0.0,
        model: str | None = None,
        system: str | None = None,
        timeout: float | None = None,
    ) -> str:
        """Single-turn text completion; returns the joined text blocks."""
        kwargs: dict[str, Any] = {
            "model": model or self.text_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
            "timeout": DEFAULT_TIMEOUT_S if timeout is None else timeout,
        }
        if system is not None:
            kwargs["system"] = system
        return message_text(await self.create_message(**kwargs))

    async def aclose(self) -> None:
        """Release the SDK's HTTP client (lifespan shutdown)."""
        if self._client is not None:
            await self._client.close()
