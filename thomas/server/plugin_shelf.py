"""The copy kept when a marketplace plugin is uninstalled, so it can be installed again.

Uninstalling deleted the plugin's folder and its line in the installed list. For a plugin that ships in
``extensions/`` that was reversible, because Marketplace could copy it in again. For one imported from a file, or one
whose folder has since left ``extensions/``, the installed copy was the only copy: uninstalling it was permanent, and
Marketplace stopped listing it at all.

So uninstall puts the plugin's files and its installed-list line on a shelf first:

    <memory root>/.thomas/plugin-shelf/<id>/      the files, as they were installed
    <memory root>/.thomas/plugin-shelf/<id>.json  its line from the installed list

Marketplace lists what is on the shelf as something you can install, and installing takes it from the shelf when
neither a store nor ``extensions/`` has it. What you made with the plugin is not on the shelf: that is in
``.thomas/plugin-data/<id>/`` (``thomas/core/plugin_data.py``) and is never removed.

An Agent Plugin is not shelved. Installing one also copies skills and registers servers outside its folder, and only
its own installer knows how to put those back.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from thomas.core.config import AppConfig
from thomas.core.plugin_data import data_dir_beside, keep_plugin_data
from thomas.server.desktop_plugins_manifest import _read_json_file, _safe_text, _utc_now_iso, _write_json_file
from thomas.server.desktop_plugins_runtime import (
    _copy_plugin_tree,
    _installed_plugin_dir,
    _load_installed_registry,
    _normalize_installed_record,
    _replace_installed_record,
    get_installed_plugin,
    install_bundled_plugin,
)


def _shelf_dir(config: AppConfig, plugin_id: str) -> Path:
    # Through the installed-folder helper, which refuses an id that is not one safe path segment.
    installed_dir = _installed_plugin_dir(config, plugin_id)
    return installed_dir.parent.parent / "plugin-shelf" / installed_dir.name


def _record_path(config: AppConfig, plugin_id: str) -> Path:
    shelf_dir = _shelf_dir(config, plugin_id)
    return shelf_dir.parent / f"{shelf_dir.name}.json"


def _installed_line(config: AppConfig, plugin_id: str) -> dict[str, Any] | None:
    for row in _load_installed_registry(config).get("plugins") or []:
        if isinstance(row, dict) and _safe_text(row.get("plugin_id")) == plugin_id:
            return row
    return None


def keep_copy(config: AppConfig, plugin_id: str) -> bool:
    """Shelve an installed plugin. Call before uninstalling it. False when there is nothing this can shelve.

    Raises ``OSError`` when the copy cannot be made, so the caller stops before deleting the only one.
    """
    installed_dir = _installed_plugin_dir(config, plugin_id)
    line = _installed_line(config, plugin_id)
    if line is None or not installed_dir.is_dir() or line.get("agent_plugin"):
        return False
    # Saved files leave first, so the shelf holds the plugin and nothing you made.
    keep_plugin_data(installed_dir, data_dir_beside(installed_dir))
    shutil.rmtree(_shelf_dir(config, plugin_id), ignore_errors=True)  # an older shelved copy is replaced
    _copy_plugin_tree(installed_dir, _shelf_dir(config, plugin_id))
    _write_json_file(_record_path(config, plugin_id), line)
    return True


def _kept_line(config: AppConfig, plugin_id: str) -> dict[str, Any] | None:
    try:
        shelf_dir = _shelf_dir(config, plugin_id)
    except ValueError:
        return None
    line = _read_json_file(_record_path(config, plugin_id), None)
    if not isinstance(line, dict) or not shelf_dir.is_dir() or _safe_text(line.get("plugin_id")) != plugin_id:
        return None
    return line


def has_kept_copy(config: AppConfig, plugin_id: str) -> bool:
    return _kept_line(config, plugin_id) is not None


def kept_copies(config: AppConfig) -> list[dict[str, Any]]:
    """Every shelved plugin that is not installed now, in the shape the installed list uses, marked not installed."""
    root = Path(config.memory.root_path) / ".thomas" / "plugin-shelf"
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for record_file in sorted(root.glob("*.json")):
        line = _kept_line(config, record_file.stem)
        if line is None or get_installed_plugin(config, record_file.stem) is not None:
            continue
        row = _normalize_installed_record(line)
        row.update({"installed": False, "enabled": False, "surface_url": ""})
        out.append(row)
    return out


def install_kept_copy(config: AppConfig, plugin_id: str) -> dict[str, Any]:
    """Install a plugin from the shelf, turned on. Raises ``FileNotFoundError`` when the shelf does not have it."""
    line = _kept_line(config, plugin_id)
    if line is None:
        raise FileNotFoundError(f"Plugin '{plugin_id}' is not in Marketplace and no copy of it was kept")
    for required in line.get("requires") or []:
        required_id = _safe_text(required)
        if required_id and get_installed_plugin(config, required_id) is None:
            # Uninstalling removed what only this plugin needed. Those come from extensions/, or from the shelf.
            try:
                install_bundled_plugin(config, required_id)
            except FileNotFoundError:
                install_kept_copy(config, required_id)
    _copy_plugin_tree(_shelf_dir(config, plugin_id), _installed_plugin_dir(config, plugin_id))
    record = dict(line)
    record.update({"installed": True, "enabled": True, "updated_at": _utc_now_iso()})
    _replace_installed_record(config, record)
    return _normalize_installed_record(record)


def forget_kept_copy(config: AppConfig, plugin_id: str) -> None:
    """Clear the shelf once the plugin is installed again, from anywhere: the installed copy is the newer one."""
    try:
        shelf_dir = _shelf_dir(config, plugin_id)
    except ValueError:
        return
    shutil.rmtree(shelf_dir, ignore_errors=True)
    _record_path(config, plugin_id).unlink(missing_ok=True)
