"""Application settings (pydantic-settings). Reads env vars and the repo-root `.env`.

Fail-fast policy:
- Always required: DATABASE_URL, REDIS_URL, JWT_SECRET.
- In `prod`, secrets must be real (no dev placeholder JWT secret, API keys present).
- In `dev`/`test`, provider keys may be empty; code that needs one calls `require()` and
  gets a clear error naming the missing variable.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
DEV_JWT_PLACEHOLDER = "dev-only-change-me"


class MissingSettingError(RuntimeError):
    """A feature needs an env var that is not set."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    env: Literal["dev", "test", "prod"] = "dev"
    tz_default: str = "Asia/Karachi"

    database_url: str
    migrations_database_url: str | None = None
    redis_url: str
    jwt_secret: SecretStr

    # Auth (PLAN §4 Auth, §18)
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14
    invite_ttl_days: int = 7
    login_lockout_threshold: int = 10
    login_lockout_window_seconds: int = 900
    admin_base_url: str = "http://localhost:3000"
    seed_demo_password: SecretStr | None = None  # demo users (step 1.5); required to seed in prod

    anthropic_api_key: SecretStr | None = None
    voyage_api_key: SecretStr | None = None

    # Knowledge base (Phase 2, PLAN §5 KNOW)
    blob_backend: Literal["local", "s3"] = "local"
    blob_dir: Path = REPO_ROOT / "var" / "blobs"
    kb_max_upload_mb: int = 25
    # D-01: voyage (once confirmed) | bge_m3 (self-hosted TEI) | fake (tests/dev, no spend)
    embedding_provider: Literal["fake", "voyage", "bge_m3"] = "fake"
    embedding_model: str = "voyage-3.5"
    bge_m3_url: str | None = None
    kb_facts_llm: bool = False  # Opus facts extraction at ingestion (spends tokens)
    kb_vision_ocr: bool = False  # Opus vision transcription of flagged PDF pages
    stt_provider: str = "openai"
    stt_api_key: SecretStr | None = None

    meta_app_id: str | None = None
    meta_app_secret: SecretStr | None = None
    meta_verify_token: SecretStr | None = None
    meta_access_token: SecretStr | None = None
    meta_phone_number_id: str | None = None
    meta_waba_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _empty_strings_are_unset(cls, data: object) -> object:
        # `.env` lines like `ANTHROPIC_API_KEY=` mean "not set", not "empty secret".
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v != ""}
        return data

    @model_validator(mode="after")
    def _prod_requires_real_secrets(self) -> "Settings":
        if self.env != "prod":
            return self
        problems = []
        if self.jwt_secret.get_secret_value() == DEV_JWT_PLACEHOLDER:
            problems.append("JWT_SECRET is the dev placeholder")
        if len(self.jwt_secret.get_secret_value()) < 32:
            problems.append("JWT_SECRET must be at least 32 characters")
        for name in ("anthropic_api_key", "voyage_api_key"):
            if getattr(self, name) is None:
                problems.append(f"{name.upper()} is required in prod")
        if self.embedding_provider == "fake":
            problems.append("EMBEDDING_PROVIDER=fake is not allowed in prod")
        if problems:
            raise ValueError("Invalid production settings: " + "; ".join(problems))
        return self

    def require(self, name: str) -> str:
        """Return a secret/str setting's value or raise a clear error if it is unset."""
        value = getattr(self, name)
        if value is None:
            raise MissingSettingError(
                f"{name.upper()} is not set — add it to .env (see .env.example)"
            )
        return value.get_secret_value() if isinstance(value, SecretStr) else str(value)


class SettingsError(RuntimeError):
    """Startup configuration error. Message names fields only — never values (no secret leaks)."""


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()  # values come from env / .env
    except ValidationError as exc:
        problems = []
        for err in exc.errors(include_input=False, include_url=False):
            field = ".".join(str(p) for p in err["loc"]) or "settings"
            problems.append(f"{field.upper()}: {err['msg']}")
        raise SettingsError(
            "Invalid configuration (check .env / environment): " + "; ".join(problems)
        ) from None
