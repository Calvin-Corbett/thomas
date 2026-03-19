from __future__ import annotations

from pathlib import Path

from thomas.preferences.store import (
    AdvancedInterfacePatch,
    AdvancedInterfacePrefs,
    AdvancedPatch,
    PreferencesPatch,
    PreferencesStore,
)


def test_advanced_interface_workflow_mode_normalizes_expert_bypass() -> None:
    prefs = AdvancedInterfacePrefs(workflow_mode="expert bypass")
    assert prefs.workflow_mode == "expert"


def test_preferences_store_persists_workflow_mode(tmp_path: Path) -> None:
    store = PreferencesStore(db_path=str(tmp_path / "prefs.sqlite"))
    patched = store.patch(
        patch=PreferencesPatch(advanced=AdvancedPatch(interface=AdvancedInterfacePatch(workflow_mode="expert"))),
        user_id="default",
    )

    assert patched.advanced.interface.workflow_mode == "expert"
    loaded = store.get(user_id="default")
    assert loaded.advanced.interface.workflow_mode == "expert"
