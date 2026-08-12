from __future__ import annotations

from pathlib import Path

from thomas.core.config import AppConfig, ModelConfig
from thomas.core.model_resolution import resolve_effective_model, resolve_effective_model_for_role
from thomas.preferences.model_prefs import (
    persist_user_model_preferences,
    persist_user_model_role_preference,
)


def _test_db_path(tmp_path: Path) -> str:
    return str((tmp_path / "thomas.db").resolve())


def _config() -> AppConfig:
    return AppConfig(
        models={
            "local": ModelConfig(name="local", model="llama3", provider="ollama"),
            "cloud": ModelConfig(name="cloud", model="gpt-4", provider="openai", api_key="sk-test"),
            "gemini": ModelConfig(name="gemini", model="gemini-pro", provider="google", api_key="test"),
        },
        default_model="local",
    )


def test_resolve_effective_model_uses_base_user_preference(tmp_path: Path) -> None:
    db_path = _test_db_path(tmp_path)
    persist_user_model_preferences(user_id="default", profile="cloud", model_id="gpt-5", db_path=db_path)

    assert resolve_effective_model(_config(), db_path=db_path) == ("cloud", "gpt-5")


def test_resolve_effective_model_for_role_prefers_role_override(tmp_path: Path) -> None:
    db_path = _test_db_path(tmp_path)
    persist_user_model_preferences(user_id="default", profile="cloud", model_id="gpt-5", db_path=db_path)
    persist_user_model_role_preference(
        user_id="default",
        role="research",
        profile="gemini",
        model_id="gemini-2.5-pro",
        db_path=db_path,
    )

    assert resolve_effective_model_for_role(_config(), "research", db_path=db_path) == (
        "gemini",
        "gemini-2.5-pro",
    )


def test_resolve_effective_model_cli_profile_beats_role_override(tmp_path: Path) -> None:
    db_path = _test_db_path(tmp_path)
    persist_user_model_role_preference(
        user_id="default",
        role="research",
        profile="gemini",
        model_id="gemini-2.5-pro",
        db_path=db_path,
    )

    assert resolve_effective_model_for_role(_config(), "research", cli_profile="cloud", db_path=db_path) == (
        "cloud",
        "",
    )
