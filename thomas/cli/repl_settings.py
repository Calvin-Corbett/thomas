"""Persistent REPL runtime settings (non-conversation state)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_VALID_TOOLS_POLICIES: set[str] = {"auto", "always", "never"}
_VALID_ACTIVITY_VERBOSITY: set[str] = {"minimal", "normal", "debug"}


@dataclass(frozen=True)
class ReplRuntimeSettings:
    autonomy_level: int = 3
    tools_policy: str = "auto"
    show_system_logs: bool = False
    activity_verbosity: str = "normal"


def _normalize_autonomy_level(value: object) -> int:
    try:
        level = int(value)
    except (TypeError, ValueError):
        return 3
    return max(1, min(4, level))


def _normalize_tools_policy(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw == "on":
        raw = "always"
    elif raw == "off":
        raw = "never"
    if raw in _VALID_TOOLS_POLICIES:
        return raw
    return "auto"


def _normalize_activity_verbosity(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw in _VALID_ACTIVITY_VERBOSITY:
        return raw
    return "normal"


def load_repl_runtime_settings(path: Path) -> ReplRuntimeSettings:
    """Load persisted REPL runtime settings from *path*."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return ReplRuntimeSettings()

    if not isinstance(raw, dict):
        return ReplRuntimeSettings()

    return ReplRuntimeSettings(
        autonomy_level=_normalize_autonomy_level(raw.get("autonomy_level")),
        tools_policy=_normalize_tools_policy(raw.get("tools_policy")),
        show_system_logs=bool(raw.get("show_system_logs", False)),
        activity_verbosity=_normalize_activity_verbosity(raw.get("activity_verbosity")),
    )


def save_repl_runtime_settings(path: Path, settings: ReplRuntimeSettings) -> None:
    """Persist REPL runtime settings to *path* (atomic file replace)."""
    payload = {
        "autonomy_level": _normalize_autonomy_level(settings.autonomy_level),
        "tools_policy": _normalize_tools_policy(settings.tools_policy),
        "show_system_logs": bool(settings.show_system_logs),
        "activity_verbosity": _normalize_activity_verbosity(settings.activity_verbosity),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
