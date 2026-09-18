"""Settings from environment variables (SPEC Section 16.2)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_VISION_MODEL = "gemini-3.5-flash-lite"

_OPTIONAL_STR_FIELDS = (
    "gemini_api_key",
    "text_model",
    "flickr_api_key",
    "google_cse_key",
    "google_cse_cx",
)


class Settings(BaseSettings):
    """Every variable from Section 16.2 with the documented default."""

    model_config = SettingsConfigDict(
        # later files override earlier ones; real environment variables always win
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    gemini_api_key: str | None = None
    vision_model: str = DEFAULT_VISION_MODEL
    text_model: str | None = None  # None -> same as vision_model
    flickr_api_key: str | None = None
    google_cse_key: str | None = None
    google_cse_cx: str | None = None
    contact_email: str = "team@example.com"
    cache_dir: Path = Path("./data")
    profile_ttl_hours: int = 24
    hard_deadline_s: float = 27.0
    vision_batch_size: int = 8
    vision_concurrency: int = 4
    download_concurrency: int = 16
    max_candidates: int = 120
    disable_sources: str = ""
    allowed_origins: str = "http://localhost:5173"
    log_level: str = "INFO"
    port: int = 8000

    @field_validator(*_OPTIONAL_STR_FIELDS, mode="before")
    @classmethod
    def _empty_string_is_none(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_validator("vision_model", "contact_email", "log_level", mode="before")
    @classmethod
    def _empty_string_is_default(cls, value: object, info: ValidationInfo) -> object:
        if isinstance(value, str) and value.strip() == "":
            return cls.model_fields[str(info.field_name)].default
        return value

    @property
    def effective_text_model(self) -> str:
        return self.text_model or self.vision_model

    @property
    def disabled_sources(self) -> frozenset[str]:
        return frozenset(s.strip().lower() for s in self.disable_sources.split(",") if s.strip())

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def thumbs_dir(self) -> Path:
        return self.cache_dir / "thumbs"

    @property
    def cache_db_path(self) -> Path:
        return self.cache_dir / "cache.sqlite"

    @property
    def vision_enabled(self) -> bool:
        return bool(self.gemini_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """For tests that change environment variables."""
    get_settings.cache_clear()
