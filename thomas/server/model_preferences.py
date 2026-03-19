from __future__ import annotations

from thomas.preferences import store as preferences_store


def read_user_model_preferences(*, user_id: str, db_path: str | None = None) -> tuple[str, str]:
    """Read persisted model preference fields for one user."""
    resolved_user_id = str(user_id or "").strip()
    if not resolved_user_id:
        return "", ""
    prefs = preferences_store.PreferencesStore(db_path or preferences_store.get_db_path()).get(user_id=resolved_user_id)
    model_prefs = getattr(getattr(prefs, "advanced", None), "model", None)
    preferred_profile = str(getattr(model_prefs, "active_profile", "") or "").strip()
    preferred_model_id = str(getattr(model_prefs, "model_id", "") or "").strip()
    return preferred_profile, preferred_model_id


def persist_user_model_preferences(
    *,
    user_id: str,
    profile: str,
    model_id: str | None,
    db_path: str | None = None,
) -> None:
    """Persist active profile/model preference fields for one user."""
    resolved_user_id = str(user_id or "").strip()
    resolved_profile = str(profile or "").strip()
    if not resolved_user_id or not resolved_profile:
        return
    resolved_model_id = str(model_id or "").strip()
    preferences_store.PreferencesStore(db_path or preferences_store.get_db_path()).patch(
        preferences_store.PreferencesPatch(
            advanced=preferences_store.AdvancedPatch(
                model=preferences_store.AdvancedModelPatch(
                    active_profile=resolved_profile,
                    model_id=resolved_model_id,
                ),
            ),
        ),
        user_id=resolved_user_id,
    )
