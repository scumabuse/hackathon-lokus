"""Gemini client wrapper: JSON recovery, availability, retry policy (SPEC 7.7, 7.8, 9)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from google.genai import errors, types
from tenacity import wait_none

from app.ai import client as client_module
from app.ai.client import (
    AIClient,
    AIUnavailableError,
    finish_reason,
    is_retryable,
    message_text,
    parse_json_text,
    strip_code_fences,
    thinking_config,
)
from app.config import Settings

FakeGenerate = Callable[..., Awaitable[types.GenerateContentResponse]]


def fake_response(text: str, reason: types.FinishReason = types.FinishReason.STOP) -> Any:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=[types.Part(text=text)]),
                finish_reason=reason,
            )
        ]
    )


def api_error(code: int, message: str = "boom") -> errors.APIError:
    body = {"error": {"code": code, "message": message, "status": "ERR"}}
    if code >= 500:
        return errors.ServerError(code, body)
    return errors.ClientError(code, body)


@pytest.fixture
def keyed_ai(monkeypatch: pytest.MonkeyPatch) -> AIClient:
    monkeypatch.setattr(client_module, "RETRY_WAIT", wait_none())
    return AIClient(
        Settings(
            gemini_api_key="test-not-a-real-key",
            vision_model="gemini-x",
            vision_fallback_model=None,
        )
    )


@pytest.fixture
def fallback_ai(monkeypatch: pytest.MonkeyPatch) -> AIClient:
    monkeypatch.setattr(client_module, "RETRY_WAIT", wait_none())
    return AIClient(
        Settings(
            gemini_api_key="test-not-a-real-key",
            vision_model="gemini-x",
            vision_fallback_model="gemini-fb",
        )
    )


def install(monkeypatch: pytest.MonkeyPatch, ai: AIClient, fake: FakeGenerate) -> None:
    assert ai._client is not None
    monkeypatch.setattr(ai._client.aio.models, "generate_content", fake)


# ----------------------------------------------------------------------------- JSON recovery


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('```json\n[{"a": 1}]\n```', '[{"a": 1}]'),
        ("```\n{}\n```", "{}"),
        ("  [1, 2]  ", "[1, 2]"),
        ("```JSON\r\n[]\r\n```", "[]"),
    ],
)
def test_strip_code_fences(raw: str, expected: str) -> None:
    assert strip_code_fences(raw) == expected


def test_parse_json_text_fenced_plain_and_prose() -> None:
    assert parse_json_text('```json\n[{"index": 1}]\n```') == [{"index": 1}]
    assert parse_json_text('{"text_ru": "а", "text_en": "b"}') == {"text_ru": "а", "text_en": "b"}
    assert parse_json_text('Sure! Here it is: ["MIT", "ETH Zurich"] hope it helps') == [
        "MIT",
        "ETH Zurich",
    ]
    assert parse_json_text('Result: {"items": [1, 2]}') == {"items": [1, 2]}


@pytest.mark.parametrize("raw", ["", "no json here", "[1, 2", "```json\n```"])
def test_parse_json_text_invalid_raises(raw: str) -> None:
    with pytest.raises(ValueError, match="no valid JSON"):
        parse_json_text(raw)


def test_message_text_and_finish_reason() -> None:
    response = fake_response("hello", types.FinishReason.MAX_TOKENS)
    assert message_text(response) == "hello"
    assert finish_reason(response) == "MAX_TOKENS"
    empty = types.GenerateContentResponse(candidates=[])
    assert message_text(empty) == ""
    assert finish_reason(empty) is None


def test_thinking_config_per_model_family() -> None:
    assert thinking_config("gemini-2.5-flash-lite").thinking_budget == 0
    assert thinking_config("gemini-3.5-flash-lite").thinking_level == types.ThinkingLevel.MINIMAL


# ----------------------------------------------------------------------------- availability


async def test_without_key_is_unavailable() -> None:
    ai = AIClient(Settings(gemini_api_key=None))
    assert ai.available is False
    assert ai.configured is False
    assert ai.unavailable_reason
    assert await ai.startup_check() is False
    with pytest.raises(AIUnavailableError):
        await ai.complete_text("hi", max_tokens=5)
    await ai.aclose()


def test_model_properties() -> None:
    same = AIClient(Settings(gemini_api_key=None, vision_model="vision-x", text_model=None))
    assert same.vision_model == "vision-x"
    assert same.text_model == "vision-x"
    split = AIClient(Settings(gemini_api_key=None, vision_model="vision-x", text_model="t"))
    assert split.text_model == "t"


def test_keyed_client_is_available_before_check(keyed_ai: AIClient) -> None:
    assert keyed_ai.configured is True
    assert keyed_ai.available is True


async def test_startup_check_success(keyed_ai: AIClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    async def fake(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return fake_response("OK")

    install(monkeypatch, keyed_ai, fake)
    assert await keyed_ai.startup_check() is True
    assert keyed_ai.available is True
    assert calls[0]["model"] == "gemini-x"
    assert calls[0]["config"].max_output_tokens == 5


async def test_startup_check_failure_disables_client(
    keyed_ai: AIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(**kwargs: Any) -> Any:
        raise api_error(401, "bad key")

    install(monkeypatch, keyed_ai, fake)
    assert await keyed_ai.startup_check() is False
    assert keyed_ai.available is False
    assert "startup check failed" in (keyed_ai.unavailable_reason or "")
    with pytest.raises(AIUnavailableError):
        await keyed_ai.complete_text("hi", max_tokens=5)


# ----------------------------------------------------------------------------- retry policy


def test_is_retryable_matrix() -> None:
    assert is_retryable(api_error(429)) is True
    assert is_retryable(api_error(503)) is True
    assert is_retryable(api_error(500)) is True
    assert is_retryable(api_error(400)) is False
    assert is_retryable(api_error(401)) is False
    assert is_retryable(api_error(404)) is False
    request = httpx.Request("POST", "https://example.invalid")
    assert is_retryable(httpx.ConnectError("down", request=request)) is True
    assert is_retryable(httpx.ReadTimeout("slow", request=request)) is True
    assert is_retryable(TimeoutError()) is False  # our own budget is final
    assert is_retryable(ValueError("x")) is False


async def test_rate_limit_retried_twice_then_succeeds(
    keyed_ai: AIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = 0

    async def fake(**kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise api_error(429, "quota")
        return fake_response("done")

    install(monkeypatch, keyed_ai, fake)
    assert await keyed_ai.complete_text("hi", max_tokens=10) == "done"
    assert attempts == 3


async def test_bad_request_is_not_retried(
    keyed_ai: AIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = 0

    async def fake(**kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        raise api_error(400, "invalid argument")

    install(monkeypatch, keyed_ai, fake)
    with pytest.raises(errors.ClientError):
        await keyed_ai.complete_text("hi", max_tokens=10)
    assert attempts == 1


async def test_server_error_gives_up_after_two_retries(
    keyed_ai: AIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = 0

    async def fake(**kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        raise api_error(503, "overloaded")

    install(monkeypatch, keyed_ai, fake)
    with pytest.raises(errors.ServerError):
        await keyed_ai.complete_text("hi", max_tokens=10)
    assert attempts == 3


async def test_timeout_is_retried(keyed_ai: AIClient, monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    async def fake(**kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("slow", request=httpx.Request("POST", "https://x"))
        return fake_response("late")

    install(monkeypatch, keyed_ai, fake)
    assert await keyed_ai.complete_text("hi", max_tokens=10) == "late"
    assert attempts == 2


async def test_thinking_config_rejected_is_retried_without_it(
    keyed_ai: AIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    configs: list[types.GenerateContentConfig] = []

    async def fake(**kwargs: Any) -> Any:
        configs.append(kwargs["config"])
        if kwargs["config"].thinking_config is not None:
            raise api_error(400, "Thinking level is not supported for this model")
        return fake_response("ok")

    install(monkeypatch, keyed_ai, fake)
    assert await keyed_ai.complete_text("hi", max_tokens=10) == "ok"
    assert configs[0].thinking_config is not None
    assert configs[-1].thinking_config is None
    # the model is remembered: the next call skips the thinking config right away
    configs.clear()
    assert await keyed_ai.complete_text("hi", max_tokens=10) == "ok"
    assert len(configs) == 1 and configs[0].thinking_config is None


async def test_complete_text_passes_system_json_mode_and_timeout(
    keyed_ai: AIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict[str, Any]] = []

    async def fake(**kwargs: Any) -> Any:
        seen.append(kwargs)
        return fake_response('{"ok": true}')

    install(monkeypatch, keyed_ai, fake)
    text = await keyed_ai.complete_text(
        "prompt", max_tokens=77, system="sys", timeout=6.0, json_mode=True, temperature=0.0
    )
    assert text == '{"ok": true}'
    config = seen[0]["config"]
    assert seen[0]["model"] == "gemini-x"
    assert seen[0]["contents"] == "prompt"
    assert config.system_instruction == "sys"
    assert config.max_output_tokens == 77
    assert config.temperature == 0.0
    assert config.response_mime_type == "application/json"
    # a 6 s budget is enforced by asyncio.wait_for; the HTTP deadline is clamped to Gemini's 10 s
    assert config.http_options is not None and config.http_options.timeout == 10000
    assert config.thinking_config is not None


async def test_generate_default_timeout(
    keyed_ai: AIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict[str, Any]] = []

    async def fake(**kwargs: Any) -> Any:
        seen.append(kwargs)
        return fake_response("x")

    install(monkeypatch, keyed_ai, fake)
    await keyed_ai.generate(contents="p", max_output_tokens=5, json_mode=False)
    assert seen[0]["config"].http_options.timeout == int(client_module.DEFAULT_TIMEOUT_S * 1000)
    assert seen[0]["config"].response_mime_type is None


# ----------------------------------------------------------------------------- quota fallback


def test_retry_delay_seconds_parses_the_api_hint() -> None:
    exc = api_error(429, "Quota exceeded ... Please retry in 11.639420936s.")
    assert abs(client_module.retry_delay_seconds(exc) - 11.64) < 0.01
    assert client_module.retry_delay_seconds(api_error(429, "no hint")) == 20.0
    assert client_module.retry_delay_seconds(api_error(429, "retry in 500s")) == 60.0


async def test_429_switches_to_the_fallback_model_immediately(
    fallback_ai: AIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def fake(**kwargs: Any) -> Any:
        calls.append(kwargs["model"])
        if kwargs["model"] == "gemini-x":
            raise api_error(429, "Quota exceeded. Please retry in 30s.")
        return fake_response("from fallback")

    install(monkeypatch, fallback_ai, fake)
    assert await fallback_ai.complete_text("hi", max_tokens=10, model="gemini-x") == "from fallback"
    assert calls == ["gemini-x", "gemini-fb"]  # no retries burned on the exhausted model
    # the primary is remembered as cooling down: the next call goes straight to the fallback
    calls.clear()
    assert await fallback_ai.complete_text("hi", max_tokens=10, model="gemini-x") == "from fallback"
    assert calls == ["gemini-fb"]


async def test_429_on_both_models_is_retried_on_the_last_one_then_raised(
    fallback_ai: AIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def fake(**kwargs: Any) -> Any:
        calls.append(kwargs["model"])
        raise api_error(429, "quota")

    install(monkeypatch, fallback_ai, fake)
    with pytest.raises(errors.ClientError):
        await fallback_ai.complete_text("hi", max_tokens=10, model="gemini-x")
    assert calls == ["gemini-x", "gemini-fb", "gemini-fb", "gemini-fb"]


async def test_fallback_is_not_used_for_other_errors(
    fallback_ai: AIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def fake(**kwargs: Any) -> Any:
        calls.append(kwargs["model"])
        raise api_error(400, "bad request")

    install(monkeypatch, fallback_ai, fake)
    with pytest.raises(errors.ClientError):
        await fallback_ai.complete_text("hi", max_tokens=10, model="gemini-x")
    assert calls == ["gemini-x"]


def test_fallback_model_settings() -> None:
    assert AIClient(Settings(gemini_api_key=None))._model_chain("gemini-3.5-flash-lite") == [
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
    ]
    same = AIClient(Settings(gemini_api_key=None, vision_fallback_model="gemini-x"))
    assert same._model_chain("gemini-x") == ["gemini-x"]
    assert AIClient(Settings(gemini_api_key=None, vision_fallback_model=""))._model_chain("a") == [
        "a"
    ]
