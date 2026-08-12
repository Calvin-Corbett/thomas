from __future__ import annotations

from pathlib import Path

from thomas.preferences.model_prefs import (
    persist_user_model_preferences,
    persist_user_model_role_preference,
    read_user_model_preferences,
    read_user_model_role_preferences,
)


def _test_db_path(tmp_path: Path) -> str:
    return str((tmp_path / "thomas.db").resolve())


def test_persist_user_model_preferences_round_trip(tmp_path: Path) -> None:
    db_path = _test_db_path(tmp_path)

    persist_user_model_preferences(
        user_id="default",
        profile="codex",
        model_id="gpt-5",
        db_path=db_path,
    )

    assert read_user_model_preferences(user_id="default", db_path=db_path) == ("codex", "gpt-5")


def test_persist_user_model_preferences_clears_model_id_with_none(tmp_path: Path) -> None:
    db_path = _test_db_path(tmp_path)
    persist_user_model_preferences(
        user_id="default",
        profile="codex",
        model_id="gpt-5",
        db_path=db_path,
    )

    persist_user_model_preferences(
        user_id="default",
        profile="local",
        model_id=None,
        db_path=db_path,
    )

    assert read_user_model_preferences(user_id="default", db_path=db_path) == ("local", "")


def test_persist_user_model_role_preference_round_trip_and_clear(tmp_path: Path) -> None:
    db_path = _test_db_path(tmp_path)

    persist_user_model_role_preference(
        user_id="default",
        role="Research",
        profile="cloud",
        model_id="gpt-5",
        db_path=db_path,
    )

    assert read_user_model_role_preferences(user_id="default", role="research", db_path=db_path) == ("cloud", "gpt-5")

    persist_user_model_role_preference(
        user_id="default",
        role="research",
        profile=None,
        model_id=None,
        db_path=db_path,
    )

    assert read_user_model_role_preferences(user_id="default", role="research", db_path=db_path) == ("", "")
