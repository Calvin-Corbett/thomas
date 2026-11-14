"""Marketplace rows: installed state overlaid on catalog rows, and the facets.

Phase 3.5 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md).

The second layer of the four (see ``marketplace_catalog_fields``). Everything
here takes rows and gives back rows: merging a catalog row with what is actually
installed, building a row for a plugin that is installed but absent from the
catalog, ordering them, and counting them into facets. No I/O, no request, no
kernel — which is why it can be read and tested on its own.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from thomas.marketplace.surface_policy import classify_marketplace_row
from thomas.server.routes.marketplace_catalog_fields import (
    _TYPE_LABELS,
    _install_url,
    _safe_int,
    _safe_string,
    _slug_label,
    _uninstall_url,
)


def _merge_nav_metadata(base: dict[str, Any], installed: dict[str, Any]) -> dict[str, Any]:
    row_marketplace_type = _safe_string(base.get("marketplace_type")) or "plugin"
    installed_marketplace_type = _safe_string(installed.get("marketplace_type"))
    marketplace_type = (
        row_marketplace_type
        if row_marketplace_type in {"app", "command_center"}
        else (installed_marketplace_type or row_marketplace_type)
    )

    row_left_nav_behavior = _safe_string(base.get("left_nav_behavior")) or "none"
    installed_left_nav_behavior = _safe_string(installed.get("left_nav_behavior"))
    left_nav_behavior = (
        row_left_nav_behavior
        if row_left_nav_behavior == "workspace"
        else (installed_left_nav_behavior or row_left_nav_behavior or "none")
    )

    row_default_nav_section = _safe_string(base.get("default_nav_section")) or (
        "apps" if left_nav_behavior == "workspace" else "installed"
    )
    installed_default_nav_section = _safe_string(installed.get("default_nav_section"))
    default_nav_section = (
        row_default_nav_section
        if row_left_nav_behavior == "workspace"
        else (installed_default_nav_section or row_default_nav_section)
    )

    row_default_nav_order = _safe_int(
        base.get("default_nav_order"),
        400 if left_nav_behavior == "workspace" else 900,
    )
    installed_default_nav_order = _safe_int(installed.get("default_nav_order"), row_default_nav_order)
    default_nav_order = row_default_nav_order if row_left_nav_behavior == "workspace" else installed_default_nav_order

    workspace_id = _safe_string(base.get("workspace_id"))
    if not workspace_id and left_nav_behavior == "workspace":
        workspace_id = _safe_string(base.get("mode_id")) or _safe_string(installed.get("mode_id"))
    if not workspace_id and left_nav_behavior != "workspace":
        workspace_id = _safe_string(installed.get("workspace_id"))

    return {
        "marketplace_type": marketplace_type,
        "marketplace_type_label": _TYPE_LABELS.get(marketplace_type, "Plugin"),
        "left_nav_behavior": left_nav_behavior,
        "default_nav_section": default_nav_section,
        "default_nav_order": default_nav_order,
        "workspace_id": workspace_id,
    }


def _overlay_installed_state(row: dict[str, Any], installed: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(row)
    if installed is None:
        out["installed"] = bool(out.get("installed"))
        out["enabled"] = bool(out.get("enabled"))
        out["update_available"] = False
        out["installed_version"] = _safe_string(out.get("installed_version"))
        return out
    installed_version = _safe_string(installed.get("version"))
    available_version = _safe_string(out.get("version"))
    nav_metadata = _merge_nav_metadata(out, installed)
    out.update(
        {
            "installed": True,
            "verified": installed.get("verified") is not False,
            "enabled": bool(installed.get("enabled")),
            "surface_url": _safe_string(installed.get("surface_url")),
            "surface_mode": _safe_string(installed.get("surface_mode")),
            "installed_version": installed_version,
            "installed_at": _safe_string(installed.get("installed_at")),
            "updated_at": _safe_string(installed.get("updated_at")),
            "marketplace_type": nav_metadata["marketplace_type"],
            "marketplace_type_label": nav_metadata["marketplace_type_label"],
            "categories": list(installed.get("categories") or out.get("categories") or []),
            "tags": list(installed.get("tags") or out.get("tags") or []),
            "requires": list(installed.get("requires") or out.get("requires") or []),
            "left_nav_behavior": nav_metadata["left_nav_behavior"],
            "default_nav_section": nav_metadata["default_nav_section"],
            "default_nav_order": nav_metadata["default_nav_order"],
            "workspace_id": nav_metadata["workspace_id"],
            "publisher_id": _safe_string(installed.get("publisher_id")) or out.get("publisher_id") or "",
            "publisher_name": _safe_string(installed.get("publisher_name")) or out.get("publisher_name") or "",
            "version_installed_only": bool(not available_version and installed_version),
            "update_available": bool(
                available_version and installed_version and available_version != installed_version
            ),
        }
    )
    return out


def _build_orphan_installed_row(installed: dict[str, Any], *, store_url: str, channel: str) -> dict[str, Any]:
    plugin_id = _safe_string(installed.get("plugin_id"))
    marketplace_type = _safe_string(installed.get("marketplace_type")) or "plugin"
    categories = list(installed.get("categories") or [])
    category = _safe_string(categories[0] if categories else "installed")
    source = installed.get("source") if isinstance(installed.get("source"), dict) else {}
    row = {
        "id": plugin_id,
        "plugin_id": plugin_id,
        "name": _safe_string(installed.get("display_name")) or plugin_id,
        "display_name": _safe_string(installed.get("display_name")) or plugin_id,
        "version": _safe_string(installed.get("version")),
        "installed_version": _safe_string(installed.get("version")),
        "subtitle": _safe_string(installed.get("subtitle")),
        "description": _safe_string(installed.get("description")),
        "category": category or "installed",
        "category_label": _slug_label(category or "installed"),
        "categories": categories,
        "tags": list(installed.get("tags") or []),
        "requires": list(installed.get("requires") or []),
        "target": "desktop",
        "mode": _safe_string(installed.get("mode_id")),
        "mode_id": _safe_string(installed.get("mode_id")),
        "marketplace_type": marketplace_type,
        "marketplace_type_label": _TYPE_LABELS.get(marketplace_type, "Plugin"),
        "left_nav_behavior": _safe_string(installed.get("left_nav_behavior")) or "none",
        "default_nav_section": _safe_string(installed.get("default_nav_section")) or "installed",
        "default_nav_order": _safe_int(installed.get("default_nav_order"), 900),
        "entrypoint": _safe_string(installed.get("entrypoint")),
        "capabilities": list(installed.get("capabilities") or []),
        "kind": _safe_string(installed.get("kind")) or "desktop_plugin",
        "source": _safe_string(source.get("type")) or "installed",
        "publisher_id": _safe_string(installed.get("publisher_id")),
        "publisher_name": _safe_string(installed.get("publisher_name")),
        "icon": _safe_string(installed.get("icon")),
        "api_namespace": _safe_string(installed.get("api_namespace")) or plugin_id,
        "download_available": False,
        "installable": False,
        "installed": True,
        "verified": installed.get("verified") is not False,
        "agent_plugin": installed.get("agent_plugin") if isinstance(installed.get("agent_plugin"), dict) else None,
        "enabled": bool(installed.get("enabled")),
        "workspace_id": _safe_string(installed.get("workspace_id")),
        "download_url": "",
        "manual_download_url": "",
        "store_url": store_url,
        "channel": channel,
        "surface": {
            "entry_html": "",
            "title": _safe_string(installed.get("surface_title"))
            or _safe_string(installed.get("display_name"))
            or plugin_id,
            "surface_mode": _safe_string(installed.get("surface_mode")) or "immersive",
        },
        "surface_url": _safe_string(installed.get("surface_url")),
        "surface_mode": _safe_string(installed.get("surface_mode")),
        "installed_at": _safe_string(installed.get("installed_at")),
        "updated_at": _safe_string(installed.get("updated_at")),
        "update_available": False,
        "catalog_status": "installed_only",
    }
    row.update(classify_marketplace_row(row, installable_candidate=False))
    return row


def _build_kept_copy_row(kept: dict[str, Any]) -> dict[str, Any]:
    """A plugin you uninstalled whose copy Thomas kept (``thomas/server/plugin_shelf.py``): listed so you can install
    it again. Without this it was in neither the catalog nor the installed list, so Marketplace did not show it."""
    row = _build_orphan_installed_row(kept, store_url="", channel="")
    row.update(
        {
            "installed": False,
            "enabled": False,
            "installed_version": "",
            "surface_url": "",
            "installable": True,
            "install_url": _install_url(_safe_string(kept.get("plugin_id"))),
            "catalog_status": "kept_copy",
            "kept_copy": True,
            "availability": "installable",
        }
    )
    row.update(classify_marketplace_row(row, installable_candidate=True, installable_reason="kept_copy_present"))
    return row


def _add_kept_copy_rows(rows: list[dict[str, Any]], kept: list[dict[str, Any]]) -> None:
    """Append a row for each kept copy the list does not already have (one in the catalog installs from there)."""
    listed = {_safe_string(row.get("plugin_id") or row.get("id")) for row in rows}
    rows.extend(_build_kept_copy_row(one) for one in kept if _safe_string(one.get("plugin_id")) not in listed)


def _add_stock_workspace_rows(rows: list[dict[str, Any]], records: list[dict[str, Any]]) -> None:
    """System, Virtual Office, Library, Channels and Token Economy, listed like any plugin, with Install when you
    have uninstalled one and Uninstall when you have not (``thomas/server/stock_workspaces.py``)."""
    for record in records:
        plugin_id = _safe_string(record.get("plugin_id"))
        installed = bool(record.get("installed"))
        row = _build_orphan_installed_row(record, store_url="", channel="")
        row.update(
            {
                "installed": installed,
                "enabled": installed,
                "installable": True,
                "install_url": _install_url(plugin_id),
                "uninstall_url": _uninstall_url(plugin_id),
                "catalog_status": "stock_workspace",
                "availability": "installable",
            }
        )
        row.update(classify_marketplace_row(row, installable_candidate=True, installable_reason="ships_with_thomas"))
        rows.append(row)


def _sort_marketplace_rows(rows: list[dict[str, Any]]) -> None:
    type_priority = {"app": 0, "command_center": 0, "plugin": 1, "integration": 2, "dependency": 3}
    rows.sort(
        key=lambda row: (
            0 if row.get("installable") else 1,
            0 if row.get("installed") else 1,
            type_priority.get(_safe_string(row.get("marketplace_type")), 9),
            _safe_string(row.get("category")).lower(),
            _safe_string(row.get("display_name") or row.get("name")).lower(),
        )
    )


def _summarize_marketplace_facets(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    type_priority = {"app": 0, "command_center": 0, "plugin": 1, "integration": 2, "dependency": 3}
    category_counts = Counter(
        _safe_string(row.get("category")).lower() for row in rows if _safe_string(row.get("category")).strip()
    )
    type_counts = Counter(
        _safe_string(row.get("marketplace_type")).lower()
        for row in rows
        if _safe_string(row.get("marketplace_type")).strip()
    )
    categories = [
        {"id": slug, "label": _slug_label(slug), "count": int(count)}
        for slug, count in sorted(category_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    types = [
        {"id": slug, "label": _TYPE_LABELS.get(slug, _slug_label(slug)), "count": int(count)}
        for slug, count in sorted(type_counts.items(), key=lambda item: (type_priority.get(item[0], 9), item[0]))
    ]
    return categories, types
