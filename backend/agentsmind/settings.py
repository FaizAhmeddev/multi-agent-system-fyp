"""Typed application settings, loaded from environment variables and `.env`.

Secrets are never given defaults. Missing required values fail at startup with a
message that says which variable to set.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "AgentsMind"
    app_env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    log_json: bool = True

    database_url: str = Field(default=f"sqlite:///{(REPO_ROOT / 'data' / 'agentsmind.db').as_posix()}")

    jwt_secret: SecretStr = Field(..., min_length=32)
    jwt_issuer: str = "agentsmind"
    access_token_minutes: int = Field(default=15, ge=1, le=120)
    refresh_token_days: int = Field(default=7, ge=1, le=60)

    lockout_max_attempts: int = Field(default=5, ge=3, le=20)
    lockout_minutes: int = Field(default=15, ge=1, le=1440)
    password_min_length: int = Field(default=12, ge=8, le=128)
    password_reset_minutes: int = Field(default=30, ge=5, le=240)

    # First-run admin. Only read when the users table is empty.
    agentsmind_admin_email: str | None = None
    agentsmind_admin_password: SecretStr | None = None

    timezone: str = "Asia/Karachi"

    queue_backend: Literal["db", "memory"] = "db"
    queue_lease_seconds: int = Field(default=60, ge=2, le=3600)
    queue_backoff_seconds: float = Field(default=2.0, ge=0.0, le=300.0)
    queue_max_attempts: int = Field(default=3, ge=1, le=20)

    # MCP servers (Phase 2). The core reaches external systems only through these.
    finance_mcp_url: str = "http://127.0.0.1:8101/mcp"
    finance_mcp_token: SecretStr | None = None
    it_mcp_url: str = "http://127.0.0.1:8102/mcp"
    it_mcp_token: SecretStr | None = None
    mcp_timeout_seconds: float = Field(default=15.0, ge=1, le=120)
    mcp_read_retries: int = Field(default=2, ge=0, le=5)
    it_portal_public_url: str = "http://127.0.0.1:8202"
    finance_portal_public_url: str = "http://127.0.0.1:8201"

    # LLM. Empty key = sandbox mode: agents return output labeled "Simulated".
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @field_validator("timezone")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"TIMEZONE '{v}' is not a valid IANA time zone") from exc
        return v

    @field_validator("database_url")
    @classmethod
    def _normalise_db_url(cls, v: str) -> str:
        if v.startswith("postgres://"):
            v = "postgresql+psycopg://" + v[len("postgres://"):]
        return v

    @property
    def llm_configured(self) -> bool:
        return bool(self.openai_api_key and self.openai_api_key.get_secret_value().strip())

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    # AGENTSMIND_ENV_FILE="" disables .env loading (used by the test suite).
    env_file = os.environ.get("AGENTSMIND_ENV_FILE", str(REPO_ROOT / ".env"))
    return Settings(_env_file=env_file or None)  # type: ignore[call-arg]


def reset_settings_cache() -> None:
    get_settings.cache_clear()
