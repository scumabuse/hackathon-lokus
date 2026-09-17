"""LLM spelling normalization fallback (SPEC Section 7.8.b): never raises, max 3 clean names."""

from __future__ import annotations

from typing import Any

import pytest

from app.ai.prompts import SPELLING_PROMPT
from app.resolver.spelling import suggest_official_names


class FakeAI:
    """Duck-typed stand-in for AIClient: canned reply or a raised error."""

    def __init__(
        self, *, available: bool = True, reply: str = "", error: Exception | None = None
    ) -> None:
        self.available = available
        self.reply = reply
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def complete_text(self, prompt: str, **kwargs: Any) -> str:
        self.calls.append({"prompt": prompt, **kwargs})
        if self.error is not None:
            raise self.error
        return self.reply


async def test_returns_names_and_passes_spec_parameters() -> None:
    ai = FakeAI(reply='["Nazarbayev University", "Nazarbaev University"]')
    names = await suggest_official_names(ai, "nazarbaev univ")  # type: ignore[arg-type]
    assert names == ["Nazarbayev University", "Nazarbaev University"]
    assert len(ai.calls) == 1
    call = ai.calls[0]
    assert call["prompt"] == SPELLING_PROMPT.format(q="nazarbaev univ")
    assert '"nazarbaev univ"' in call["prompt"]
    assert call["max_tokens"] == 200
    assert call["temperature"] == 0
    assert call["timeout"] == 6.0


async def test_fenced_reply_is_parsed() -> None:
    ai = FakeAI(reply='```json\n["Example University"]\n```')
    assert await suggest_official_names(ai, "exampl univ") == ["Example University"]  # type: ignore[arg-type]


async def test_strips_dedupes_drops_junk_and_caps_at_three() -> None:
    reply = (
        '["  Example University ", "example university", "", 42, null, '
        '"Sample   College", "Third Name", "Fourth Name"]'
    )
    ai = FakeAI(reply=reply)
    names = await suggest_official_names(ai, "q")  # type: ignore[arg-type]
    assert names == ["Example University", "Sample College", "Third Name"]


@pytest.mark.parametrize(
    "reply",
    ["I do not know that university.", '{"names": ["Example University"]}', "[]", "", "```\n```"],
)
async def test_garbage_or_non_array_reply_gives_empty_list(reply: str) -> None:
    ai = FakeAI(reply=reply)
    assert await suggest_official_names(ai, "q") == []  # type: ignore[arg-type]


async def test_call_error_gives_empty_list() -> None:
    ai = FakeAI(error=RuntimeError("boom"))
    assert await suggest_official_names(ai, "q") == []  # type: ignore[arg-type]
    assert len(ai.calls) == 1


async def test_unavailable_client_is_not_called() -> None:
    ai = FakeAI(available=False, reply='["Example University"]')
    assert await suggest_official_names(ai, "q") == []  # type: ignore[arg-type]
    assert ai.calls == []
