from __future__ import annotations

from pathlib import Path

import pytest

from tests.workspace_specialist_test_support import Dispatcher, GuardedRunner, operator
from thomas.preferences.store import PreferencesStore
from thomas.server.workspace_specialist_policy import WORKSPACE_ACTION_POLICIES


@pytest.mark.asyncio
async def test_token_economy_mutates_live_typed_cost_preferences(tmp_path: Path) -> None:
    store = PreferencesStore(db_path=str(tmp_path / "prefs.db"))
    receipt = await operator(
        "token_economy",
        Dispatcher(),
        guarded_runner=GuardedRunner(),
        preferences_store=store,
    ).execute(
        {"action": "preferences.set", "key": "daily_token_budget", "value": 4_000_000}
    )
    persisted = store.get(user_id="owner-test")
    assert receipt["ok"] is True
    assert receipt["evidence"]["after"] == {
        "key": "daily_token_budget",
        "path": "advanced.cost.daily_token_budget",
        "value": 4_000_000,
    }
    assert persisted.advanced.cost.daily_token_budget == 4_000_000
    assert persisted.thomads == {}


def test_settings_policy_does_not_claim_local_storage_shell_theme() -> None:
    keys = WORKSPACE_ACTION_POLICIES["settings"]["preferences.set"].preference_keys
    assert "theme" not in keys
    assert "ui_density" in keys
