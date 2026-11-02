import pytest
from pydantic import ValidationError

from app.core.config import DEV_JWT_PLACEHOLDER, MissingSettingError, Settings

BASE = {
    "database_url": "postgresql+asyncpg://u:p@localhost:5432/db",
    "redis_url": "redis://localhost:6379/0",
}


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, "jwt_secret": "x" * 40, **overrides})  # type: ignore[arg-type]


def test_missing_database_url_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None, redis_url="redis://x", jwt_secret="s")  # noqa: S106


def test_dev_allows_missing_provider_keys_and_empty_strings_mean_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    s = make(env="dev", anthropic_api_key="", voyage_api_key=None)
    assert s.anthropic_api_key is None
    assert s.voyage_api_key is None


def test_require_gives_clear_error_naming_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s = make(env="dev", anthropic_api_key=None)
    with pytest.raises(MissingSettingError, match="ANTHROPIC_API_KEY is not set"):
        s.require("anthropic_api_key")


def test_require_returns_secret_value() -> None:
    assert make(anthropic_api_key="sk-test").require("anthropic_api_key") == "sk-test"


def test_prod_rejects_placeholder_secret_and_missing_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("ANTHROPIC_API_KEY", "VOYAGE_API_KEY"):
        monkeypatch.delenv(key, raising=False)  # hermetic: ignore keys in the shell env
    with pytest.raises(ValidationError) as exc:
        make(env="prod", jwt_secret=DEV_JWT_PLACEHOLDER)
    msg = str(exc.value)
    assert "dev placeholder" in msg
    assert "ANTHROPIC_API_KEY is required in prod" in msg
    assert "VOYAGE_API_KEY is required in prod" in msg


def test_prod_accepts_real_settings() -> None:
    s = make(
        env="prod", anthropic_api_key="sk-a", voyage_api_key="pa-v", embedding_provider="voyage"
    )
    assert s.env == "prod"


def test_prod_rejects_fake_embeddings() -> None:
    with pytest.raises(ValidationError, match="EMBEDDING_PROVIDER=fake"):
        make(env="prod", anthropic_api_key="sk-a", voyage_api_key="pa-v")


def test_secrets_are_not_leaked_in_repr() -> None:
    assert "sk-hidden" not in repr(make(anthropic_api_key="sk-hidden"))


def test_get_settings_error_names_fields_but_never_values(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import SettingsError, get_settings

    get_settings.cache_clear()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-never-appear")
    monkeypatch.setattr(Settings, "model_config", {**Settings.model_config, "env_file": None})
    try:
        with pytest.raises(SettingsError) as exc:
            get_settings()
    finally:
        get_settings.cache_clear()
    assert "DATABASE_URL: Field required" in str(exc.value)
    assert "sk-should-never-appear" not in str(exc.value)
