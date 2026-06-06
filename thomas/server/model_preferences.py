from __future__ import annotations

from thomas.preferences import store as preferences_store


def _normalize_model_role(role: str | None) -> str:
    return str(role or "").strip().lower().replace("-", "_").replace(" ", "_")


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


def read_user_model_role_preferences(*, user_id: str, role: str, db_path: str | None = None) -> tuple[str, str]:
    """Read persisted role-specific model preference fields for one user."""
    resolved_user_id = str(user_id or "").strip()
    resolved_role = _normalize_model_role(role)
    if not resolved_user_id or not resolved_role:
        return "", ""
    prefs = preferences_store.PreferencesStore(db_path or preferences_store.get_db_path()).get(user_id=resolved_user_id)
    model_prefs = getattr(getattr(prefs, "advanced", None), "model", None)
    role_profiles = getattr(model_prefs, "role_profiles", {}) or {}
    role_model_ids = getattr(model_prefs, "role_model_ids", {}) or {}
    preferred_profile = str(role_profiles.get(resolved_role, "") or "").strip()
    preferred_model_id = str(role_model_ids.get(resolved_role, "") or "").strip()
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


def persist_user_model_role_preference(
    *,
    user_id: str,
    role: str,
    profile: str | None,
    model_id: str | None,
    db_path: str | None = None,
) -> None:
    """Persist or clear one role-specific profile/model override for one user."""
    resolved_user_id = str(user_id or "").strip()
    resolved_role = _normalize_model_role(role)
    if not resolved_user_id or not resolved_role:
        return
    resolved_profile = str(profile or "").strip()
    resolved_model_id = str(model_id or "").strip()
    preferences_store.PreferencesStore(db_path or preferences_store.get_db_path()).patch(
        preferences_store.PreferencesPatch(
            advanced=preferences_store.AdvancedPatch(
                model=preferences_store.AdvancedModelPatch(
                    role_profiles={resolved_role: resolved_profile or None},
                    role_model_ids={resolved_role: resolved_model_id or None},
                ),
            ),
        ),
        user_id=resolved_user_id,
    )
