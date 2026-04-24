"""thomas.plugins.p101_plugin_enable_and_disable_state_store

Persistent plugin enable/disable state for Thomas.

This module implements a small JSON-backed store that remembers whether a plugin
is enabled or disabled across runs.

Design goals:
- Thomas-native naming and contracts.
- Deterministic, machine-friendly errors.
- Minimal dependencies; safe for use from CLI and agent/gateway layers.

Storage format (schema_version=1):

    {
      "schema_version": 1,
      "updated_at": 1700000000.0,
      "plugins": {
        "some-plugin": {"enabled": true, "updated_at": 1700000000.0}
      }
    }

Behavior:
- If a plugin has no entry in the store, it is treated as enabled.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


PROMPT_ID = "p101"
TOOL_ID = "plugins.enablement_store"

STATE_SCHEMA_VERSION = 1

# Allow common plugin naming patterns, including namespaced keys like "owner/name".
_PLUGIN_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{0,255}$")


class PluginEnablementStoreError(RuntimeError):
    """Deterministic, machine-friendly failures for the enablement store."""

    def __init__(self, code: str, message: str, *, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: Dict[str, Any] = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": dict(self.details)}


@dataclass(frozen=True)
class PluginEnablementChange:
    """Result of a persisted enable/disable update."""

    plugin: str
    enabled: bool
    previous_enabled: bool
    changed: bool
    store_path: str
    updated_at: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plugin": self.plugin,
            "enabled": self.enabled,
            "previous_enabled": self.previous_enabled,
            "changed": self.changed,
            "store_path": self.store_path,
            "updated_at": self.updated_at,
        }


def resolve_enablement_store_path(explicit_path: Optional[Path]) -> Path:
    """Resolve enablement store path.

    Order:
    1) explicit_path
    2) THOMAS_PLUGIN_ENABLEMENT_STORE (file path)
    3) THOMAS_CONFIG_DIR (directory; file name: plugin_enablement.json)
    4) XDG_CONFIG_HOME/thomas/plugin_enablement.json
    5) ~/.config/thomas/plugin_enablement.json

    Raises STATE_STORE_NOT_CONFIGURED if no safe default can be determined.
    """

    if explicit_path is not None:
        return Path(explicit_path).expanduser()

    env_file = os.getenv("THOMAS_PLUGIN_ENABLEMENT_STORE")
    if env_file:
        return Path(env_file).expanduser()

    env_dir = os.getenv("THOMAS_CONFIG_DIR")
    if env_dir:
        return Path(env_dir).expanduser() / "plugin_enablement.json"

    xdg = os.getenv("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg).expanduser() / "thomas" / "plugin_enablement.json"

    try:
        home = Path.home()
    except Exception as e:  # pragma: no cover
        raise PluginEnablementStoreError(
            code="STATE_STORE_NOT_CONFIGURED",
            message="Could not determine where to persist plugin enablement state.",
            details={"reason": str(e)},
        ) from e

    return home / ".config" / "thomas" / "plugin_enablement.json"


def _validate_plugin_key(plugin: Any) -> str:
    if not isinstance(plugin, str) or not plugin.strip():
        raise PluginEnablementStoreError(
            code="INVALID_PLUGIN_KEY",
            message="Plugin key must be a non-empty string.",
            details={"plugin": plugin},
        )
    plugin = plugin.strip()
    if not _PLUGIN_KEY_RE.fullmatch(plugin):
        raise PluginEnablementStoreError(
            code="INVALID_PLUGIN_KEY",
            message="Plugin key contains unsupported characters.",
            details={"plugin": plugin},
        )
    return plugin


def _default_state() -> Dict[str, Any]:
    return {"schema_version": STATE_SCHEMA_VERSION, "updated_at": None, "plugins": {}}


class PluginEnablementStore:
    """JSON-backed store for plugin enablement."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def is_enabled(self, plugin: Any) -> bool:
        plugin_key = _validate_plugin_key(plugin)
        state = self._load_state()
        entry = state["plugins"].get(plugin_key)
        if entry is None:
            return True
        return bool(entry["enabled"])

    def set_enabled(self, plugin: Any, enabled: Any) -> PluginEnablementChange:
        plugin_key = _validate_plugin_key(plugin)
        if not isinstance(enabled, bool):
            raise PluginEnablementStoreError(
                code="INVALID_INPUT",
                message="Enabled flag must be boolean.",
                details={"enabled": enabled},
            )

        state = self._load_state()
        plugins = state["plugins"]

        previous_enabled = True if plugin_key not in plugins else bool(plugins[plugin_key]["enabled"])
        changed = previous_enabled != enabled
        now = time.time()

        plugins[plugin_key] = {"enabled": enabled, "updated_at": now}
        state["updated_at"] = now
        self._write_state(state)

        return PluginEnablementChange(
            plugin=plugin_key,
            enabled=enabled,
            previous_enabled=previous_enabled,
            changed=changed,
            store_path=str(self.path),
            updated_at=now,
        )

    def clear(self, plugin: Any) -> bool:
        """Remove a plugin entry (reverts to default-enabled).

        Returns True if an entry was removed, False if it did not exist.
        """

        plugin_key = _validate_plugin_key(plugin)
        state = self._load_state()
        plugins = state["plugins"]
        existed = plugin_key in plugins
        if existed:
            del plugins[plugin_key]
            state["updated_at"] = time.time()
            self._write_state(state)
        return existed

    def list_enabled_states(self) -> Dict[str, bool]:
        """Return stored states only (does not enumerate all installed plugins)."""

        state = self._load_state()
        return {k: bool(v["enabled"]) for k, v in state["plugins"].items()}

    def _load_state(self) -> Dict[str, Any]:
        if self.path.exists() and self.path.is_dir():
            raise PluginEnablementStoreError(
                code="STATE_STORE_PATH_INVALID",
                message="Enablement store path points to a directory, expected a file.",
                details={"path": str(self.path)},
            )

        if not self.path.exists():
            return _default_state()

        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as e:
            raise PluginEnablementStoreError(
                code="STATE_STORE_IO",
                message="Failed to read plugin enablement store.",
                details={"path": str(self.path), "errno": getattr(e, "errno", None)},
            ) from e

        # Treat empty/whitespace file as uninitialized store.
        if not raw.strip():
            return _default_state()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise PluginEnablementStoreError(
                code="STATE_STORE_CORRUPT",
                message="Plugin enablement store is not valid JSON.",
                details={"path": str(self.path), "pos": e.pos},
            ) from e

        return self._validate_state(data)

    def _validate_state(self, data: Any) -> Dict[str, Any]:
        if not isinstance(data, dict):
            raise PluginEnablementStoreError(
                code="STATE_STORE_CORRUPT",
                message="Plugin enablement store has an invalid format.",
                details={"path": str(self.path)},
            )

        schema_version = data.get("schema_version")
        if schema_version is None:
            raise PluginEnablementStoreError(
                code="STATE_STORE_CORRUPT",
                message="Plugin enablement store is missing schema_version.",
                details={"path": str(self.path)},
            )

        if schema_version != STATE_SCHEMA_VERSION:
            raise PluginEnablementStoreError(
                code="STATE_STORE_UNSUPPORTED_SCHEMA",
                message="Plugin enablement store schema version is unsupported.",
                details={"path": str(self.path), "schema_version": schema_version},
            )

        plugins_raw = data.get("plugins", {})
        if not isinstance(plugins_raw, dict):
            raise PluginEnablementStoreError(
                code="STATE_STORE_CORRUPT",
                message="Plugin enablement store has an invalid plugins map.",
                details={"path": str(self.path)},
            )

        normalized: Dict[str, Dict[str, Any]] = {}
        for key, entry in plugins_raw.items():
            if not isinstance(key, str) or not isinstance(entry, dict) or "enabled" not in entry:
                raise PluginEnablementStoreError(
                    code="STATE_STORE_CORRUPT",
                    message="Plugin enablement store contains an invalid entry.",
                    details={"path": str(self.path), "plugin": key},
                )
            enabled = entry.get("enabled")
            if not isinstance(enabled, bool):
                raise PluginEnablementStoreError(
                    code="STATE_STORE_CORRUPT",
                    message="Plugin enablement store contains a non-boolean enabled flag.",
                    details={"path": str(self.path), "plugin": key},
                )
            updated_at = entry.get("updated_at")
            if updated_at is not None and not isinstance(updated_at, (int, float)):
                raise PluginEnablementStoreError(
                    code="STATE_STORE_CORRUPT",
                    message="Plugin enablement store contains an invalid timestamp.",
                    details={"path": str(self.path), "plugin": key},
                )
            normalized[key] = {"enabled": enabled, "updated_at": updated_at}

        updated_at_top = data.get("updated_at")
        if updated_at_top is not None and not isinstance(updated_at_top, (int, float)):
            raise PluginEnablementStoreError(
                code="STATE_STORE_CORRUPT",
                message="Plugin enablement store contains an invalid updated_at timestamp.",
                details={"path": str(self.path)},
            )

        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "updated_at": updated_at_top,
            "plugins": normalized,
        }

    def _write_state(self, state: Dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise PluginEnablementStoreError(
                code="STATE_STORE_IO",
                message="Failed to create directory for plugin enablement store.",
                details={"path": str(self.path), "errno": getattr(e, "errno", None)},
            ) from e

        tmp_path = self.path.with_name(self.path.name + ".tmp")
        payload = json.dumps(state, sort_keys=True, indent=2)

        try:
            tmp_path.write_text(payload + "\n", encoding="utf-8")
            os.replace(tmp_path, self.path)
        except OSError as e:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            raise PluginEnablementStoreError(
                code="STATE_STORE_IO",
                message="Failed to write plugin enablement store.",
                details={"path": str(self.path), "errno": getattr(e, "errno", None)},
            ) from e


# ---- Convenience functions for callers that don't want to manage a store object ----


def is_plugin_enabled(plugin: Any, *, store_path: Optional[Path] = None) -> bool:
    """Check whether a plugin is enabled (default True if absent)."""

    path = resolve_enablement_store_path(store_path)
    return PluginEnablementStore(path).is_enabled(plugin)


def set_plugin_enabled(plugin: Any, enabled: Any, *, store_path: Optional[Path] = None) -> PluginEnablementChange:
    """Persist a plugin's enabled state."""

    path = resolve_enablement_store_path(store_path)
    return PluginEnablementStore(path).set_enabled(plugin, enabled)


def clear_plugin_enabled(plugin: Any, *, store_path: Optional[Path] = None) -> bool:
    """Remove a plugin from the enablement store (reverts to default-enabled)."""

    path = resolve_enablement_store_path(store_path)
    return PluginEnablementStore(path).clear(plugin)


# ---- Gateway-friendly IO contract (dict-in/dict-out) ----


def handle_enablement_change(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Dict-in/dict-out wrapper suitable for a gateway layer.

    Expected input:
        {"plugin": "<key>", "enabled": true|false, "store_path": "<optional path>"}

    Output on success:
        {"ok": true, "result": {...PluginEnablementChange...}}

    Output on failure:
        {"ok": false, "error": {"code": "...", "message": "...", "details": {...}}}
    """

    try:
        plugin = payload.get("plugin")
        enabled = payload.get("enabled")
        store_path_raw = payload.get("store_path")

        path: Optional[Path] = None
        if store_path_raw is not None:
            if not isinstance(store_path_raw, str) or not store_path_raw.strip():
                raise PluginEnablementStoreError(
                    code="INVALID_INPUT",
                    message="store_path must be a non-empty string when provided.",
                    details={"store_path": store_path_raw},
                )
            path = Path(store_path_raw)

        # Validate enabled is boolean here to avoid accidental truthiness coercion.
        if not isinstance(enabled, bool):
            raise PluginEnablementStoreError(
                code="INVALID_INPUT",
                message="enabled must be boolean.",
                details={"enabled": enabled},
            )

        change = set_plugin_enabled(plugin, enabled, store_path=path)
        return {"ok": True, "result": change.to_dict()}
    except PluginEnablementStoreError as e:
        return {"ok": False, "error": e.to_dict()}
    except Exception as e:
        err = PluginEnablementStoreError(
            code="UNEXPECTED_ERROR",
            message="Unexpected error while updating plugin enablement state.",
            details={"type": type(e).__name__},
        )
        return {"ok": False, "error": err.to_dict()}
