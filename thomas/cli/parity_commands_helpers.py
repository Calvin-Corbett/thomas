"""Helper functions for parity_commands module."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from thomas.cli.parity_support import read_json as _read_json
from thomas.cli.parity_support import state_dir as _state_dir
from thomas.cli.parity_support import utc_iso as _utc_iso
from thomas.cli.parity_support import write_json as _write_json
from thomas.core.config import AppConfig


def devices_file(config: AppConfig) -> Path:
    """Get devices storage file path."""
    return _state_dir(config) / "devices.json"


def load_devices(config: AppConfig) -> list[dict[str, Any]]:
    """Load devices list from storage."""
    payload = _read_json(devices_file(config), {"devices": []})
    if not isinstance(payload, dict):
        return []
    rows = payload.get("devices")
    return rows if isinstance(rows, list) else []


def save_devices(config: AppConfig, devices_rows: list[dict[str, Any]]) -> None:
    """Save devices list to storage."""
    _write_json(devices_file(config), {"devices": devices_rows, "updated_at": _utc_iso()})


def token_hash(token: str) -> str:
    """Hash a device token."""
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def plugins_file(config: AppConfig) -> Path:
    """Get plugins storage file path."""
    return _state_dir(config) / "plugins.json"


def load_plugins(config: AppConfig) -> list[dict[str, Any]]:
    """Load plugins list from storage."""
    payload = _read_json(plugins_file(config), {"plugins": []})
    if not isinstance(payload, dict):
        return []
    rows = payload.get("plugins")
    return rows if isinstance(rows, list) else []


def save_plugins(config: AppConfig, rows: list[dict[str, Any]]) -> None:
    """Save plugins list to storage."""
    _write_json(plugins_file(config), {"plugins": rows, "updated_at": _utc_iso()})


def find_plugin(rows: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Find a plugin by name."""
    target = str(name).strip().lower()
    for row in rows:
        if str(row.get("name") or "").strip().lower() == target:
            return row
    return None


def sessions_count(config: AppConfig) -> int:
    """Count saved sessions."""
    root = config.memory.root_path / ".thomas" / "chats"
    if not root.exists():
        return 0
    return len(list(root.glob("*.json")))
