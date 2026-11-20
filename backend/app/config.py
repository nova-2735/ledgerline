"""Application settings, read from environment variables only."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
THINKING_LEVELS = ("off", "low", "medium", "high")


class AppEnv(StrEnum):
    development = "development"
    test = "test"
    production = "production"


class LLMProvider(StrEnum):
    gemini = "gemini"
    fake = "fake"
    openai_compat = "openai_compat"


class OCRMode(StrEnum):
    auto = "auto"
    off = "0"
    on = "1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        env_ignore_empty=True,
    )

    app_env: AppEnv = AppEnv.development
    app_today: date | None = None
    data_dir: Path = REPO_ROOT / "data"
    database_url: str | None = None

    llm_provider: LLMProvider = LLMProvider.gemini
    llm_model: str = "gemini-3.5-flash-lite"
    llm_model_light: str = "gemini-3.5-flash-lite"
    gemini_api_key: SecretStr | None = None
    openai_compat_base_url: str | None = None
    openai_compat_api_key: SecretStr | None = None
    llm_timeout_s: float = 60
    llm_thinking: str = "low"
    llm_cache: bool = True
    llm_explain: bool = True
    llm_price_in_per_m: float | None = None
    llm_price_out_per_m: float | None = None
    max_live_llm_calls_per_hour: int = 120
    allow_fake_llm: bool = False

    ocr_enabled: OCRMode = OCRMode.auto
    policy_path: Path = BACKEND_DIR / "policy" / "default_policy.yaml"
    max_upload_mb: int = Field(default=10, gt=0)
    max_pages: int = Field(default=10, gt=0)
    workers: int = Field(default=2, gt=0)
    cors_origins: str = "http://localhost:5173"
    demo_access_code: SecretStr | None = None
    invoice_font_path: Path | None = None

    imap_host: str | None = None
    imap_user: str | None = None
    imap_password: SecretStr | None = None
    imap_folder: str | None = None
    imap_poll_seconds: int | None = None
    imap_allowed_senders: str | None = None

    port: int = 8000

    @field_validator("llm_thinking", mode="before")
    @classmethod
    def _check_thinking(cls, value: object) -> str:
        text = str(value).strip().lower()
        if text in THINKING_LEVELS:
            return text
        try:
            budget = int(text)
        except ValueError:
            budget = -2
        if budget < 0:
            raise ValueError(
                "LLM_THINKING must be off, low, medium, high or a token budget (integer >= 0)"
            )
        return str(budget)

    @model_validator(mode="after")
    def _apply_env_rules(self) -> Self:
        if self.app_env is AppEnv.test:
            self.llm_provider = LLMProvider.fake
            self.ocr_enabled = OCRMode.off
        if (
            self.app_env is AppEnv.production
            and self.llm_provider is LLMProvider.fake
            and not self.allow_fake_llm
        ):
            raise ValueError(
                "LLM_PROVIDER=fake is not allowed in production unless ALLOW_FAKE_LLM=1"
            )
        if not self.data_dir.is_absolute():
            self.data_dir = (REPO_ROOT / self.data_dir).resolve()
        if not self.policy_path.is_absolute():
            self.policy_path = (REPO_ROOT / self.policy_path).resolve()
        return self

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'ledgerline.db').as_posix()}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
