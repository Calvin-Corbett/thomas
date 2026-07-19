"""Shared validation helpers for the durable Work store."""

from __future__ import annotations

from typing import Any

from .validation import WorkValidationError, clean_json_object

_JOB_STATUSES = {"active", "paused", "archived"}
_SKILL_STATUSES = {"draft", "active", "disabled"}
_JOB_SETTING_KEYS = {
    "autonomy",
    "file_access",
    "guardrails",
    "model_id",
    "memory",
    "profile",
    "reasoning",
    "reasoning_effort",
    "thinking",
    "tokenEconomy",
    "token_economy",
}


def _clean_object_list(value: Any, *, field: str, limit: int = 100) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise WorkValidationError(f"{field} must be an array")
    if len(value) > limit:
        raise WorkValidationError(f"{field} may contain at most {limit} items")
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise WorkValidationError(f"{field} entries must be objects")
        rows.append(dict(item))
    return rows


def _clean_settings(value: Any) -> dict[str, Any]:
    settings = clean_json_object(value, field="settings")
    unknown = sorted(set(settings) - _JOB_SETTING_KEYS)
    if unknown:
        raise WorkValidationError(f"unsupported settings: {', '.join(unknown)}")
    return settings


def _clean_bool(value: Any, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise WorkValidationError(f"{field} must be true or false")
    return value
