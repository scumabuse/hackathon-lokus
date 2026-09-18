"""Gemini client wrapper: startup check, retry policy, text / vision calls, JSON recovery.

SPEC Sections 7.7, 7.8 and 9 ("Parsing"), as amended by the customer: the only AI provider is
Gemini (``GEMINI_API_KEY``, Google AI Studio) through the official ``google-genai`` SDK. One
``genai.Client`` per process, created only when the key is set. Every request goes through one
tenacity policy: 2 retries with exponential backoff (1 -> 4 s) on 429, connection errors /
timeouts and 5xx; never on other 4xx. The SDK's built-in retries are disabled so that this policy
is the only one.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

import httpx
from google import genai
from google.genai import errors, types
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import Settings

log = logging.getLogger("app.ai")

MAX_ATTEMPTS = 3  # 1 call + 2 retries (SPEC Section 9)
RETRY_WAIT = wait_exponential(multiplier=1.0, min=1.0, max=4.0)  # 1 s, then 2 s (capped at 4 s)
DEFAULT_TIMEOUT_S = 30.0  # no call may outlive the 30 s budget
STARTUP_CHECK_TIMEOUT_S = 10.0
STARTUP_CHECK_PROMPT = "Reply with the single word OK."
RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
JSON_MIME = "application/json"

_FENCE_OPEN = re.compile(r"^```[A-Za-z0-9_-]*[ \t]*\r?\n?")
_FENCE_CLOSE = re.compile(r"\r?\n?[ \t]*```\s*$")

ContentsType = str | list[types.Content] | types.Content


class AIUnavailableError(RuntimeError):
    """No API key is configured or the startup check failed; AI features are switched off."""


def is_retryable(exc: BaseException) -> bool:
    """Retry on 429 / 5xx / timeouts / connection errors; never on any other 4xx."""
    if isinstance(exc, errors.APIError):
        code = exc.code or 0
        return code in RETRYABLE_STATUS or code >= 500
    return isinstance(exc, (httpx.TransportError, TimeoutError))


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
    return f"({exc.code})" if isinstance(exc, errors.APIError) else ""


def message_text(response: types.GenerateContentResponse) -> str:
    """Section 9 parsing: the concatenated text parts of the first candidate ("" when none)."""
    try:
        text = response.text
    except (ValueError, AttributeError):
        text = None
    return text or ""


def finish_reason(response: types.GenerateContentResponse) -> str | None:
    """The first candidate's finish reason as a plain string (``"STOP"``, ``"MAX_TOKENS"``...)."""
    candidates = response.candidates or []
    if not candidates or candidates[0].finish_reason is None:
        return None
    reason = candidates[0].finish_reason
    return reason.value if isinstance(reason, types.FinishReason) else str(reason)


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


def thinking_config(model: str) -> types.ThinkingConfig:
    """Minimal reasoning: classification and short descriptions need speed, not deliberation.

    Gemini 2.5 models take a token budget (0 = off); Gemini 3.x models take a level.
    """
    if "2.5" in model:
        return types.ThinkingConfig(thinking_budget=0)
    return types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL)


def text_part(text: str) -> types.Part:
    return types.Part.from_text(text=text)


def image_part(data: bytes, mime_type: str = "image/jpeg") -> types.Part:
    """Inline image block (Section 7.7: JPEG, long side <= 512 px)."""
    return types.Part.from_bytes(data=data, mime_type=mime_type)


def user_content(parts: list[types.Part]) -> types.Content:
    return types.Content(role="user", parts=parts)


class AIClient:
    """Thin wrapper over ``genai.Client`` with the shared retry policy and an availability flag."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: genai.Client | None = None
        self._no_thinking_models: set[str] = set()
        self.available: bool = False
        self.unavailable_reason: str | None = "GEMINI_API_KEY is not set"
        if settings.gemini_api_key:
            # retry_options.attempts=1: the SDK's own retries would stack on the tenacity policy
            self._client = genai.Client(
                api_key=settings.gemini_api_key,
                http_options=types.HttpOptions(
                    timeout=int(DEFAULT_TIMEOUT_S * 1000),
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
            self.available = True
            self.unavailable_reason = None

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
        """One tiny text call (max 5 output tokens). Failure disables AI features, never raises."""
        if self._client is None:
            log.info("GEMINI_API_KEY not set: vision classification and AI description are off")
            self.available = False
            return False
        self.available = True
        self.unavailable_reason = None
        try:
            response = await self.generate(
                contents=STARTUP_CHECK_PROMPT,
                model=self.text_model,
                max_output_tokens=5,
                timeout=STARTUP_CHECK_TIMEOUT_S,
                minimal_thinking=False,
            )
        except Exception as exc:
            self.available = False
            self.unavailable_reason = f"startup check failed: {type(exc).__name__}"
            log.warning(
                "!!! GEMINI STARTUP CHECK FAILED (model=%s): vision classification and AI "
                "description are DISABLED; the app keeps serving without them !!!",
                self.text_model,
                exc_info=True,
            )
            return False
        log.info(
            "gemini startup check ok: model=%s reply=%r",
            self.text_model,
            message_text(response)[:40],
        )
        return True

    def _config(
        self,
        *,
        model: str,
        system: str | None,
        temperature: float,
        max_output_tokens: int,
        json_mode: bool,
        timeout: float,
        minimal_thinking: bool,
    ) -> types.GenerateContentConfig:
        thinking = (
            thinking_config(model)
            if minimal_thinking and model not in self._no_thinking_models
            else None
        )
        return types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            response_mime_type=JSON_MIME if json_mode else None,
            thinking_config=thinking,
            http_options=types.HttpOptions(timeout=int(timeout * 1000)),
        )

    async def generate(
        self,
        *,
        contents: ContentsType,
        model: str | None = None,
        system: str | None = None,
        temperature: float = 0.0,
        max_output_tokens: int,
        json_mode: bool = False,
        timeout: float | None = None,
        minimal_thinking: bool = True,
    ) -> types.GenerateContentResponse:
        """``generate_content`` with the retry policy (vision batches and text tasks use this).

        Raises AIUnavailableError when the client is off, otherwise the SDK / transport
        exception once the retries are exhausted.
        """
        if self._client is None or not self.available:
            raise AIUnavailableError(f"Gemini API unavailable: {self.unavailable_reason}")
        model_name = model or self.text_model
        request_timeout = DEFAULT_TIMEOUT_S if timeout is None else timeout
        client = self._client
        async for attempt in _retrying():
            with attempt:
                config = self._config(
                    model=model_name,
                    system=system,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    json_mode=json_mode,
                    timeout=request_timeout,
                    minimal_thinking=minimal_thinking,
                )
                started = time.monotonic()
                try:
                    response = await asyncio.wait_for(
                        client.aio.models.generate_content(
                            model=model_name, contents=contents, config=config
                        ),
                        timeout=request_timeout + 1.0,
                    )
                except errors.ClientError as exc:
                    if self._thinking_rejected(exc, model_name, config):
                        # the model does not accept this thinking config: retry once without it
                        self._no_thinking_models.add(model_name)
                        raise errors.ServerError(503, {"error": {"message": str(exc)}}) from exc
                    log.info(
                        "gemini generate model=%s -> %s%s %dms",
                        model_name,
                        type(exc).__name__,
                        _status_suffix(exc),
                        _elapsed_ms(started),
                    )
                    raise
                except (errors.APIError, httpx.HTTPError, TimeoutError) as exc:
                    log.info(
                        "gemini generate model=%s -> %s%s %dms",
                        model_name,
                        type(exc).__name__,
                        _status_suffix(exc),
                        _elapsed_ms(started),
                    )
                    raise
                log.info("gemini generate model=%s -> ok %dms", model_name, _elapsed_ms(started))
                return response
        raise RuntimeError("unreachable")  # pragma: no cover

    @staticmethod
    def _thinking_rejected(
        exc: errors.ClientError, model: str, config: types.GenerateContentConfig
    ) -> bool:
        return (
            exc.code == 400
            and config.thinking_config is not None
            and "thinking" in str(exc).lower()
        )

    async def complete_text(
        self,
        prompt: str,
        *,
        max_tokens: int,
        temperature: float = 0.0,
        model: str | None = None,
        system: str | None = None,
        timeout: float | None = None,
        json_mode: bool = False,
    ) -> str:
        """Single-turn text completion; returns the joined text parts."""
        response = await self.generate(
            contents=prompt,
            model=model or self.text_model,
            system=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
            json_mode=json_mode,
            timeout=timeout,
        )
        return message_text(response)

    async def aclose(self) -> None:
        """Release the SDK's HTTP clients (lifespan shutdown)."""
        if self._client is None:
            return
        closer = getattr(self._client.aio, "aclose", None)
        if closer is None:
            return
        try:
            await closer()
        except Exception:  # pragma: no cover - shutdown must never fail
            log.debug("gemini client close failed", exc_info=True)
