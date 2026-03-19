from __future__ import annotations

from pathlib import Path

from thomas.server.model_preferences import (
    persist_user_model_preferences,
    read_user_model_preferences,
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
