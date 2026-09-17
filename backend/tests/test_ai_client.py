"""AI client wrapper: JSON recovery, availability, retry policy (SPEC Sections 7.7, 9)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from tenacity import wait_none

from app.ai import client as client_module
from app.ai.client import (
    DEFAULT_TIMEOUT_S,
    AIClient,
    AIUnavailableError,
    is_retryable,
    message_text,
    parse_json_text,
    strip_code_fences,
)
from app.config import Settings

API_URL = "https://api.anthropic.com/v1/messages"


def _request() -> httpx2.Request:
    return httpx2.Request("POST", API_URL)


def _response(status: int) -> httpx2.Response:
    return httpx2.Response(status, request=_request())


def _status_error(
    status: int, cls: type[anthropic.APIStatusError] = anthropic.APIStatusError
) -> Any:
    return cls(f"status {status}", response=_response(status), body=None)


def _message(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text=text),
            SimpleNamespace(type="tool_use", text="ignored"),
        ]
    )


@pytest.fixture
async def keyed_ai(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AIClient]:
    """A client with a (fake) key and no retry sleeps; the SDK call is always monkeypatched."""
    monkeypatch.setattr(client_module, "RETRY_WAIT", wait_none())
    ai = AIClient(Settings(anthropic_api_key="sk-ant-test-not-a-real-key"))
    yield ai
    await ai.aclose()


def _patch_create(
    monkeypatch: pytest.MonkeyPatch, ai: AIClient, outcomes: list[Any]
) -> list[dict[str, Any]]:
    """Replace the SDK call: each outcome is an exception to raise or a message to return."""
    calls: list[dict[str, Any]] = []
    queue = list(outcomes)

    async def fake_create(**kwargs: Any) -> Any:
        calls.append(kwargs)
        outcome = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    assert ai._client is not None
    monkeypatch.setattr(ai._client.messages, "create", fake_create)
    return calls


# --- JSON recovery (Section 9 "Parsing") -----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("```json\n[1, 2]\n```", "[1, 2]"),
        ("```\n[1, 2]\n```", "[1, 2]"),
        ('  ```JSON\r\n{"a": 1}\r\n```  ', '{"a": 1}'),
        ("```json\n[1]", "[1]"),
        ("[1, 2]", "[1, 2]"),
        ("plain text", "plain text"),
    ],
)
def test_strip_code_fences(raw: str, expected: str) -> None:
    assert strip_code_fences(raw) == expected


def test_parse_json_text_fenced() -> None:
    assert parse_json_text('```json\n["Example University", "Sample College"]\n```') == [
        "Example University",
        "Sample College",
    ]


def test_parse_json_text_plain() -> None:
    assert parse_json_text('{"text_en": "x", "n": 2}') == {"text_en": "x", "n": 2}


def test_parse_json_text_prose_wrapped_array() -> None:
    raw = 'Sure! Here are the names:\n["Example University"]\nHope this helps.'
    assert parse_json_text(raw) == ["Example University"]


def test_parse_json_text_prose_wrapped_object_with_inner_array() -> None:
    raw = 'Result: {"items": [1, 2]} -- done'
    assert parse_json_text(raw) == {"items": [1, 2]}


@pytest.mark.parametrize("raw", ["no json here", "[1, 2", "", "``` ```", "{oops: [}"])
def test_parse_json_text_invalid_raises(raw: str) -> None:
    with pytest.raises(ValueError, match="no valid JSON"):
        parse_json_text(raw)


def test_message_text_joins_only_text_blocks() -> None:
    message = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="a"),
            SimpleNamespace(type="tool_use", text="ignored"),
            SimpleNamespace(type="text", text="b"),
        ]
    )
    assert message_text(message) == "ab"  # type: ignore[arg-type]


# --- availability ----------------------------------------------------------------------------


async def test_without_key_is_unavailable() -> None:
    ai = AIClient(Settings(anthropic_api_key=None))
    assert ai.available is False
    assert ai.configured is False
    assert await ai.startup_check() is False
    with pytest.raises(AIUnavailableError):
        await ai.complete_text("hello", max_tokens=5)
    with pytest.raises(AIUnavailableError):
        await ai.create_message(model="m", max_tokens=5, messages=[])
    await ai.aclose()


def test_model_properties() -> None:
    same = AIClient(Settings(anthropic_api_key=None, vision_model="vision-x", text_model=None))
    assert same.vision_model == "vision-x"
    assert same.text_model == "vision-x"
    split = AIClient(Settings(anthropic_api_key=None, vision_model="vision-x", text_model="t"))
    assert split.text_model == "t"


def test_keyed_client_is_available_before_check(keyed_ai: AIClient) -> None:
    assert keyed_ai.available is True
    assert keyed_ai.configured is True


async def test_startup_check_success(keyed_ai: AIClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_create(monkeypatch, keyed_ai, [_message("OK")])
    assert await keyed_ai.startup_check() is True
    assert keyed_ai.available is True
    assert len(calls) == 1
    assert calls[0]["max_tokens"] == 5
    assert calls[0]["model"] == keyed_ai.text_model


async def test_startup_check_failure_disables_client(
    keyed_ai: AIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _patch_create(
        monkeypatch, keyed_ai, [_status_error(401, anthropic.AuthenticationError)]
    )
    assert await keyed_ai.startup_check() is False  # never raises
    assert keyed_ai.available is False
    assert len(calls) == 1  # 401 is not retried
    with pytest.raises(AIUnavailableError):
        await keyed_ai.complete_text("x", max_tokens=5)


# --- retry policy ----------------------------------------------------------------------------


def test_is_retryable_matrix() -> None:
    assert is_retryable(_status_error(429, anthropic.RateLimitError)) is True
    assert is_retryable(_status_error(500, anthropic.InternalServerError)) is True
    assert is_retryable(_status_error(503)) is True
    assert is_retryable(_status_error(529)) is True
    assert is_retryable(anthropic.APIConnectionError(request=_request())) is True
    assert is_retryable(anthropic.APITimeoutError(request=_request())) is True
    assert is_retryable(_status_error(400)) is False
    assert is_retryable(_status_error(401)) is False
    assert is_retryable(_status_error(404)) is False
    assert is_retryable(_status_error(422)) is False
    assert is_retryable(ValueError("x")) is False


async def test_rate_limit_retried_twice_then_succeeds(
    keyed_ai: AIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _patch_create(
        monkeypatch,
        keyed_ai,
        [
            _status_error(429, anthropic.RateLimitError),
            _status_error(429, anthropic.RateLimitError),
            _message("hello"),
        ],
    )
    result = await keyed_ai.complete_text("prompt text", max_tokens=10, timeout=3.0)
    assert result == "hello"
    assert len(calls) == 3
    sent = calls[-1]
    assert sent["model"] == keyed_ai.text_model
    assert sent["max_tokens"] == 10
    assert sent["temperature"] == 0.0
    assert sent["timeout"] == 3.0
    assert sent["messages"] == [{"role": "user", "content": "prompt text"}]
    assert "system" not in sent


async def test_bad_request_is_not_retried(
    keyed_ai: AIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _patch_create(monkeypatch, keyed_ai, [_status_error(400)])
    with pytest.raises(anthropic.APIStatusError):
        await keyed_ai.complete_text("prompt", max_tokens=10)
    assert len(calls) == 1
    assert keyed_ai.available is True  # a per-call failure does not disable the client


async def test_server_error_gives_up_after_two_retries(
    keyed_ai: AIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _patch_create(
        monkeypatch, keyed_ai, [_status_error(500, anthropic.InternalServerError)]
    )
    with pytest.raises(anthropic.InternalServerError):
        await keyed_ai.create_message(model="m", max_tokens=5, messages=[])
    assert len(calls) == 3


async def test_timeout_error_retried(keyed_ai: AIClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_create(
        monkeypatch, keyed_ai, [anthropic.APITimeoutError(request=_request()), _message("ok")]
    )
    assert await keyed_ai.complete_text("prompt", max_tokens=10) == "ok"
    assert len(calls) == 2


async def test_complete_text_defaults_and_system(
    keyed_ai: AIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _patch_create(monkeypatch, keyed_ai, [_message("done")])
    await keyed_ai.complete_text("p", max_tokens=7, system="be terse", model="other-model")
    sent = calls[0]
    assert sent["timeout"] == DEFAULT_TIMEOUT_S
    assert sent["system"] == "be terse"
    assert sent["model"] == "other-model"


async def test_create_message_passthrough_sets_default_timeout(
    keyed_ai: AIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _patch_create(monkeypatch, keyed_ai, [_message("x")])
    message = await keyed_ai.create_message(model="m", max_tokens=5, messages=[], system="s")
    assert message_text(message) == "x"
    assert calls[0]["timeout"] == DEFAULT_TIMEOUT_S
    assert calls[0]["system"] == "s"
