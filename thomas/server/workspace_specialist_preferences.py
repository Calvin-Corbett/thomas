"""Structured live PreferencesStore adapter for workspace residents."""

from __future__ import annotations

from typing import Any

from thomas.preferences.store import PreferencesPatch, PreferencesStore, get_db_path

PREFERENCE_PATHS: dict[str, tuple[str, ...]] = {
    "animation_fidelity": ("advanced", "interface", "animation_fidelity"),
    "code_theme": ("advanced", "interface", "code_theme"),
    "daily_token_budget": ("advanced", "cost", "daily_token_budget"),
    "default_autonomy_level": ("autonomy", "default_level"),
    "default_model": ("advanced", "model", "model_id"),
    "default_reasoning_effort": ("advanced", "model", "reasoning_effort"),
    "default_run_mode": ("advanced", "runtime", "default_mode"),
    "default_token_economy": ("advanced", "runtime", "default_token_economy"),
    "reasoning_token_budget": ("advanced", "model", "reasoning_token_budget"),
    "session_token_budget": ("advanced", "cost", "session_token_budget"),
    "show_token_meter": ("advanced", "interface", "show_token_meter"),
    "token_throttle_enabled": ("advanced", "cost", "throttle_on_budget"),
    "ui_density": ("advanced", "interface", "ui_density"),
}


def _nested_payload(path: tuple[str, ...], value: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {path[-1]: value}
    for part in reversed(path[:-1]):
        payload = {part: payload}
    return payload


def _value_at_path(payload: Any, path: tuple[str, ...]) -> Any:
    value = payload
    for part in path:
        if hasattr(value, part):
            value = getattr(value, part)
        elif isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def normalized_preference_value(key: str, value: Any) -> Any:
    """Validate and normalize using the same typed patch model as /api/preferences."""

    path = PREFERENCE_PATHS[key]
    patch = PreferencesPatch(**_nested_payload(path, value))
    return _value_at_path(patch, path)


class WorkspacePreferencesMixin:
    preferences_store: PreferencesStore | None
    user_id: str

    def _live_preferences_store(self) -> PreferencesStore:
        if self.preferences_store is None:
            self.preferences_store = PreferencesStore(db_path=get_db_path())
        return self.preferences_store

    def _read_structured_preference(self, key: str) -> dict[str, Any]:
        path = PREFERENCE_PATHS[key]
        preferences = self._live_preferences_store().get(user_id=self.user_id)
        return {"key": key, "path": ".".join(path), "value": _value_at_path(preferences, path)}

    def _list_structured_preferences(self, keys: frozenset[str]) -> dict[str, Any]:
        preferences = self._live_preferences_store().get(user_id=self.user_id)
        return {
            "preferences": {
                key: {
                    "path": ".".join(PREFERENCE_PATHS[key]),
                    "value": _value_at_path(preferences, PREFERENCE_PATHS[key]),
                }
                for key in sorted(keys)
            }
        }

    def _patch_structured_preference(self, key: str, value: Any) -> dict[str, Any]:
        path = PREFERENCE_PATHS[key]
        patch = PreferencesPatch(**_nested_payload(path, value))
        self._live_preferences_store().patch(patch=patch, user_id=self.user_id)
        return self._read_structured_preference(key)


__all__ = ["PREFERENCE_PATHS", "WorkspacePreferencesMixin", "normalized_preference_value"]
