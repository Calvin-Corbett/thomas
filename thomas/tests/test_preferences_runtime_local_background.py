from __future__ import annotations

from thomas.preferences.store import (
    AdvancedPatch,
    AdvancedRuntimePatch,
    PreferencesPatch,
    PreferencesStore,
)


def test_runtime_local_background_settings_roundtrip(tmp_path) -> None:
    store = PreferencesStore(db_path=str(tmp_path / "prefs.db"))

    patched = store.patch(
        PreferencesPatch(
            advanced=AdvancedPatch(
                runtime=AdvancedRuntimePatch(
                    local_background_agents_enabled=True,
                    local_background_min_gpu_headroom_pct=42,
                )
            )
        ),
        user_id="tester",
    )

    assert patched.advanced.runtime.local_background_agents_enabled is True
    assert patched.advanced.runtime.local_background_min_gpu_headroom_pct == 42

    loaded = store.get(user_id="tester")
    assert loaded.advanced.runtime.local_background_agents_enabled is True
    assert loaded.advanced.runtime.local_background_min_gpu_headroom_pct == 42
