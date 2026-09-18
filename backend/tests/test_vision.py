"""Section 9 vision batches: request shape, JSON recovery, retry, failure modes, post-processing."""

from __future__ import annotations

import base64
import json
from io import BytesIO
from typing import Any

import pytest
from google.genai import errors, types
from PIL import Image

from app.ai import vision
from app.ai.client import AIUnavailableError
from app.ai.prompts import VISION_SYSTEM
from app.enums import Category, SourceType
from app.models import Place, ProcessedImage, RawCandidate, UniversityHeader
from app.scoring import VisionInfo

HEADER = UniversityHeader(
    qid="Q1",
    name="Testville Institute of Technology",
    aliases=["TIT", "Testville Tech"],
    country="Testland",
)


def _jpeg_b64() -> str:
    out = BytesIO()
    Image.new("RGB", (32, 24), (10, 120, 200)).save(out, format="JPEG")
    return base64.b64encode(out.getvalue()).decode("ascii")


def image(i: int, source_type: SourceType = SourceType.commons_category) -> ProcessedImage:
    candidate = RawCandidate(
        source_type=source_type,
        image_url=f"https://img.example.org/{i}.jpg",
        source_page_url=f"https://commons.wikimedia.org/wiki/File:{i}.jpg",
        source_label="Wikimedia Commons",
        filename=f"{i}.jpg",
    )
    return ProcessedImage(
        candidate=candidate,
        photo_id=candidate.photo_id,
        sha1="0" * 40,
        phash="0" * 16,
        thumb_path=f"/tmp/{i}.jpg",
        thumb_b64=_jpeg_b64(),
        width=640,
        height=480,
    )


def item(i: int, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "index": i,
        "is_photo": True,
        "category": "campus",
        "category_confidence": 0.9,
        "plausibly_university_related": True,
        "name_on_sign": False,
        "visible_text": None,
        "people_prominent": False,
        "quality_ok": True,
        "reason": "academic buildings",
    }
    base.update(overrides)
    return base


def response_with(text: str) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=[types.Part(text=text)]),
                finish_reason=types.FinishReason.STOP,
            )
        ]
    )


class FakeAI:
    vision_model = "gemini-x"

    def __init__(self, outputs: list[Any], *, available: bool = True) -> None:
        self.outputs = list(outputs)
        self.available = available
        self.unavailable_reason = None if available else "GEMINI_API_KEY is not set"
        self.calls: list[dict[str, Any]] = []

    async def generate(self, **kwargs: Any) -> types.GenerateContentResponse:
        if not self.available:
            raise AIUnavailableError("off")
        self.calls.append(kwargs)
        output = self.outputs.pop(0)
        if isinstance(output, BaseException):
            raise output
        return response_with(output)


def text_of(part: types.Part) -> str:
    return part.text or ""


async def test_first_attempt_parses_and_request_matches_section_9() -> None:
    images = [image(1), image(2)]
    ai = FakeAI([json.dumps([item(1), item(2, category="library", name_on_sign=True)])])
    outcome = await vision.classify_batch(ai, images, HEADER)  # type: ignore[arg-type]
    assert outcome.parsed_first_attempt is True and outcome.error is None
    assert [i.category for i in outcome.infos] == [Category.campus, Category.library]
    assert outcome.infos[1].name_on_sign is True
    assert all(i.usable for i in outcome.infos)
    call = ai.calls[0]
    assert call["model"] == "gemini-x"
    assert call["system"] == VISION_SYSTEM
    assert call["json_mode"] is True
    assert call["max_output_tokens"] == 900 + 130 * 2
    parts = call["contents"].parts
    assert len(parts) == 1 + 2 * 2 + 1
    assert "Testville Institute of Technology" in text_of(parts[0])
    assert "TIT; Testville Tech" in text_of(parts[0])
    assert "N=2" in text_of(parts[0])
    assert text_of(parts[1]) == "IMAGE 1"
    assert parts[2].inline_data is not None
    assert parts[2].inline_data.mime_type == "image/jpeg"
    assert parts[2].inline_data.data == base64.b64decode(images[0].thumb_b64)
    assert text_of(parts[3]) == "IMAGE 2"
    assert "Return ONLY a JSON array" in text_of(parts[-1])


async def test_fenced_json_and_string_booleans_are_accepted() -> None:
    fenced = "```json\n" + json.dumps([item(1, is_photo="true", category="Student Life")]) + "\n```"
    outcome = await vision.classify_batch(FakeAI([fenced]), [image(1)], HEADER)  # type: ignore[arg-type]
    assert outcome.parsed_first_attempt is True
    assert outcome.infos[0].is_photo is True
    assert outcome.infos[0].category is Category.student_life


async def test_unknown_category_becomes_other_instead_of_failing_the_batch() -> None:
    ai = FakeAI([json.dumps([item(1, category="parking lot")])])
    outcome = await vision.classify_batch(ai, [image(1)], HEADER)  # type: ignore[arg-type]
    assert outcome.parsed_first_attempt is True
    assert outcome.infos[0].category is Category.other


async def test_wrong_length_triggers_one_retry_with_the_suffix() -> None:
    ai = FakeAI([json.dumps([item(1)]), json.dumps([item(1), item(2)])])
    outcome = await vision.classify_batch(ai, [image(1), image(2)], HEADER)  # type: ignore[arg-type]
    assert outcome.parsed_first_attempt is False
    assert outcome.error is None
    assert len(ai.calls) == 2
    last_part = ai.calls[1]["contents"].parts[-1]
    assert "was not a valid JSON array" in text_of(last_part)


async def test_two_parse_failures_keep_images_as_unavailable() -> None:
    ai = FakeAI(["nonsense", "[]"])
    outcome = await vision.classify_batch(ai, [image(1), image(2)], HEADER)  # type: ignore[arg-type]
    assert len(outcome.infos) == 2
    assert all(not i.available for i in outcome.infos)
    assert outcome.error is not None


async def test_deadline_cancellation_is_marked_timed_out() -> None:
    ai = FakeAI([TimeoutError()])
    outcome = await vision.classify_batch(ai, [image(1)], HEADER)  # type: ignore[arg-type]
    assert outcome.error == "timeout"
    assert outcome.infos[0].timed_out is True and outcome.infos[0].available is True
    assert outcome.infos[0].usable is False


async def test_api_error_marks_unavailable_with_reason() -> None:
    error = errors.ServerError(503, {"error": {"code": 503, "message": "overloaded"}})
    outcome = await vision.classify_batch(FakeAI([error]), [image(1)], HEADER)  # type: ignore[arg-type]
    assert outcome.infos[0].available is False
    assert "vision unavailable" in (outcome.infos[0].reason or "")
    assert outcome.parsed_first_attempt is False


async def test_ai_off_means_no_call() -> None:
    ai = FakeAI([], available=False)
    outcome = await vision.classify_batch(ai, [image(1), image(2)], HEADER)  # type: ignore[arg-type]
    assert ai.calls == []
    assert all(not i.available for i in outcome.infos)


async def test_city_target_header_mentions_the_city() -> None:
    header = HEADER.model_copy(update={"city": Place(name="Testville")})
    ai = FakeAI([json.dumps([item(1, category="city")])])
    await vision.classify_batch(ai, [image(1)], header, target="city")  # type: ignore[arg-type]
    assert "Testville" in text_of(ai.calls[0]["contents"].parts[0])


@pytest.mark.parametrize(
    ("info", "source_type", "keep", "category"),
    [
        (
            VisionInfo(is_photo=False, category=Category.campus),
            SourceType.commons_search,
            False,
            None,
        ),
        (
            VisionInfo(people_prominent=True, category=Category.campus),
            SourceType.commons_search,
            False,
            None,
        ),
        (
            VisionInfo(quality_ok=False, category=Category.campus),
            SourceType.commons_search,
            False,
            None,
        ),
        (
            VisionInfo(plausibly_university_related=False, category=Category.campus),
            SourceType.commons_search,
            False,
            None,
        ),
        (
            VisionInfo(plausibly_university_related=False, category=Category.city),
            SourceType.commons_search,
            True,
            Category.city,
        ),
        (VisionInfo(category=Category.other), SourceType.commons_search, False, None),
        (
            VisionInfo(category=Category.library),
            SourceType.commons_category,
            True,
            Category.library,
        ),
        (
            VisionInfo(plausibly_university_related=False, category=Category.campus),
            SourceType.city_commons,
            True,
            Category.city,
        ),
        (VisionInfo(is_photo=False, category=Category.city), SourceType.city_commons, False, None),
        (VisionInfo(available=False), SourceType.commons_search, True, None),
        (VisionInfo(timed_out=True), SourceType.commons_search, True, None),
    ],
)
def test_post_processing_rules(
    info: VisionInfo, source_type: SourceType, keep: bool, category: Category | None
) -> None:
    adjusted, kept = vision.apply_post_processing(image(1, source_type), info)
    assert kept is keep
    if category is not None:
        assert adjusted.category is category
