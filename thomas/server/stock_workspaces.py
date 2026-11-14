"""System, Virtual Office, Library, Channels and Token Economy as plugins you can uninstall and install again.

You said: "Those should be plugins. There should be no build-ins ... everything should be a plugin. This is an
open-source build-your-own agent ... Shouldn't have forced to be doing anything." Before this the sidebar could only
hide these five, in one browser, and told you they were built in.

Each one has a Marketplace id (``thomas-<mode>``) and is listed in Marketplace with Install or Uninstall like any other
plugin. Uninstalling that id through the ordinary Marketplace route writes the mode into
``<memory root>/.thomas/removed_workspaces.json``; installing it takes the mode out. The sidebar reads that list with
the installed plugins and leaves those rows out, in every window. Nothing a workspace holds is touched either way.

What this is not yet: these five are not separate downloads. Their pages still ship inside Thomas, so an uninstalled
one's address still answers if something opens it directly. Moving each into its own folder under ``extensions/`` is
the work that finishes this. Marketplace is not on the list, because it is where the others are installed again.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from thomas import __version__
from thomas.core.config import AppConfig
from thomas.server.desktop_plugins_manifest import _read_json_file, _write_json_file

_PREFIX = "thomas-"
# mode -> (name, what Marketplace says about it)
STOCK_WORKSPACES: dict[str, tuple[str, str]] = {
    "system": ("System", "What Thomas is doing and how he is: tasks, load, plugins, spend and builds."),
    "office": ("Virtual Office", "The office view of who Thomas is following and what they are doing."),
    "my_stuff": ("Library", "What you and Thomas have made and installed, in one place."),
    "channels": ("Channels", "The channels Thomas listens and answers on."),
    "token_economy": ("Token Economy", "What Thomas has spent, by model and by day."),
}


def stock_mode(plugin_id: str) -> str | None:
    """The workspace a Marketplace id names, or None when the id is some other plugin's."""
    mode = plugin_id[len(_PREFIX) :] if plugin_id.startswith(_PREFIX) else ""
    return mode if mode in STOCK_WORKSPACES else None


def _path(config: AppConfig) -> Path:
    return Path(config.memory.root_path) / ".thomas" / "removed_workspaces.json"


def removed_modes(config: AppConfig) -> list[str]:
    saved = _read_json_file(_path(config), {})
    listed = saved.get("removed") if isinstance(saved, dict) else None
    return [mode for mode in STOCK_WORKSPACES if isinstance(listed, list) and mode in listed]


def set_removed(config: AppConfig, mode: str, removed: bool) -> list[str]:
    """Uninstall (True) or install (False) one of the five. Returns the list as saved."""
    now = [one for one in removed_modes(config) if one != mode]
    if removed:
        now.append(mode)
    _write_json_file(_path(config), {"removed": now})
    return removed_modes(config)


def stock_records(config: AppConfig) -> list[dict[str, Any]]:
    """One record per workspace, in the shape the installed list uses, for Marketplace to turn into rows."""
    gone = set(removed_modes(config))
    return [
        {
            "plugin_id": f"{_PREFIX}{mode}",
            "display_name": name,
            "subtitle": "Comes with Thomas",
            "description": about,
            "version": __version__,
            "mode_id": mode,
            "publisher_name": "Thomas",
            "marketplace_type": "app",
            "categories": ["workspace"],
            # Not "workspace": the sidebar draws these itself, and must not also list them as installed plugins.
            "left_nav_behavior": "none",
            "enabled": mode not in gone,
            "installed": mode not in gone,
        }
        for mode, (name, about) in STOCK_WORKSPACES.items()
    ]
