"""Catalog sync: the hosted store, and the local catalog Thomas falls back to.

Phase 3.5 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md).

The top layer of the four (see ``marketplace_catalog_fields``): it uses fields,
rows and packs, and only the routes module uses it. Three things live here —
fetching the hosted catalog, augmenting local catalog rows with the installed
manifest and installed state, and assembling the whole local payload the sync
route returns when the hosted store cannot be reached.

``_load_hosted_marketplace_catalog`` is imported into
``marketplace_catalog_aiohttp`` by name, and ``tests/test_server_marketplace_routes.py``
patches it there (``...marketplace_catalog_aiohttp._load_hosted_marketplace_catalog``)
to simulate a store that is down. That patch still lands after the split, because
the route looks the name up as a module global at call time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import httpx
from aiohttp import web

from thomas.marketplace.surface_policy import classify_marketplace_row, row_is_visible
from thomas.server.app_keys import APP_CONFIG
from thomas.server.desktop_plugins import list_installed_plugins, maybe_load_desktop_plugin_manifest
from thomas.server.net_safety import request_validated_async
from thomas.server.plugin_shelf import kept_copies
from thomas.server.routes.marketplace_catalog_fields import (
    _TYPE_LABELS,
    _disable_url,
    _enable_url,
    _install_url,
    _is_retired_local_module_row,
    _plugin_id_from_row,
    _safe_string,
    _slug_label,
    _uninstall_url,
)
from thomas.server.routes.marketplace_catalog_packs import _load_marketplace_catalog, _resolve_pack_dir
from thomas.server.routes.marketplace_catalog_rows import (
    _add_kept_copy_rows,
    _add_stock_workspace_rows,
    _build_orphan_installed_row,
    _merge_nav_metadata,
    _sort_marketplace_rows,
    _summarize_marketplace_facets,
)
from thomas.server.stock_workspaces import stock_records


async def _load_hosted_marketplace_catalog(*, store_url: str, channel: str) -> dict[str, Any]:
    catalog_urls = [
        urljoin(store_url.rstrip("/") + "/", f"api/marketplace/catalog?channel={quote(channel, safe='')}"),
        urljoin(store_url.rstrip("/") + "/", f"api/v1/plugins/catalog?channel={quote(channel, safe='')}"),
    ]
    errors: list[str] = []
    # request_validated_async re-runs the SSRF guard on every redirect hop; a
    # client-level follow_redirects=True checked only the first URL.
    async with httpx.AsyncClient(timeout=25.0) as client:
        for catalog_url in catalog_urls:
            try:
                response = await request_validated_async(client, "GET", catalog_url)
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                errors.append(f"{catalog_url}: {exc}")
                continue
            if not isinstance(payload, dict) or payload.get("ok") is False:
                errors.append(f"{catalog_url}: invalid payload")
                continue
            payload["catalog_url"] = catalog_url
            return payload
    raise ValueError("Hosted marketplace catalog is invalid: " + "; ".join(errors))


def _augment_marketplace_rows(
    app: web.Application,
    extensions_root: Path,
    rows: list[dict[str, Any]],
    *,
    installed_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    config = app[APP_CONFIG]
    if installed_by_id is None:
        installed_by_id = {
            row["plugin_id"]: row
            for row in list_installed_plugins(config, include_disabled=True)
            if not _is_retired_local_module_row(row)
        }
    out: list[dict[str, Any]] = []
    for base in rows:
        row = dict(base)
        plugin_id = _safe_string(row.get("id"))
        pack_dir = _resolve_pack_dir(extensions_root, plugin_id)
        manifest = maybe_load_desktop_plugin_manifest(pack_dir) if pack_dir is not None else None
        installed = installed_by_id.get(plugin_id)
        if manifest is not None:
            row.update(
                {
                    "kind": manifest.kind,
                    "plugin_id": manifest.plugin_id,
                    "display_name": manifest.display_name,
                    "subtitle": manifest.subtitle,
                    "publisher_id": manifest.publisher_id,
                    "publisher_name": manifest.publisher_name,
                    "mode_id": manifest.mode_id,
                    "icon": manifest.icon,
                    "api_namespace": manifest.api_namespace,
                    "marketplace_type": manifest.marketplace_type,
                    "marketplace_type_label": _TYPE_LABELS.get(manifest.marketplace_type, "Plugin"),
                    "categories": list(manifest.categories),
                    "tags": list(manifest.tags),
                    "requires": list(manifest.requires),
                    "left_nav_behavior": manifest.left_nav_behavior,
                    "default_nav_section": manifest.default_nav_section,
                    "default_nav_order": manifest.default_nav_order,
                    "workspace_id": manifest.mode_id if manifest.left_nav_behavior == "workspace" else "",
                    "surface": {
                        "entry_html": manifest.surface_entry_html,
                        "title": manifest.surface_title,
                        "surface_mode": manifest.surface_mode,
                    },
                    "installable": True,
                    "install_url": _install_url(plugin_id),
                    "uninstall_url": _uninstall_url(plugin_id),
                    "enable_url": _enable_url(plugin_id),
                    "disable_url": _disable_url(plugin_id),
                }
            )
            primary_category = row["categories"][0] if row.get("categories") else row.get("category")
            row["category"] = primary_category or row.get("category") or "other"
            row["category_label"] = _slug_label(row["category"])
        if installed is not None:
            nav_metadata = _merge_nav_metadata(row, installed)
            row.update(
                {
                    "installed": True,
                    "enabled": bool(installed.get("enabled")),
                    "surface_url": _safe_string(installed.get("surface_url")),
                    "surface_mode": _safe_string(installed.get("surface_mode")),
                    "installed_version": _safe_string(installed.get("version")),
                    "installed_at": _safe_string(installed.get("installed_at")),
                    "updated_at": _safe_string(installed.get("updated_at")),
                    "marketplace_type": nav_metadata["marketplace_type"],
                    "marketplace_type_label": nav_metadata["marketplace_type_label"],
                    "categories": list(installed.get("categories") or row.get("categories") or []),
                    "tags": list(installed.get("tags") or row.get("tags") or []),
                    "requires": list(installed.get("requires") or row.get("requires") or []),
                    "left_nav_behavior": nav_metadata["left_nav_behavior"],
                    "default_nav_section": nav_metadata["default_nav_section"],
                    "default_nav_order": nav_metadata["default_nav_order"],
                    "workspace_id": nav_metadata["workspace_id"],
                }
            )
        row.update(
            classify_marketplace_row(
                row,
                installable_candidate=bool(manifest is not None),
                installable_reason="bundled_runtime_present",
            )
        )
        if _safe_string(row.get("availability")).lower() != "installable":
            row["installable"] = False
            row["install_url"] = ""
            row["uninstall_url"] = ""
            row["enable_url"] = ""
            row["disable_url"] = ""
        out.append(row)
    return out


def _build_local_sync_payload(
    app: web.Application,
    *,
    store_url: str,
    channel: str,
) -> dict[str, Any]:
    catalog, extensions_root, rows = _load_marketplace_catalog()
    installed_by_id = {
        row["plugin_id"]: row
        for row in list_installed_plugins(app[APP_CONFIG], include_disabled=True)
        if not _is_retired_local_module_row(row)
    }
    rows = _augment_marketplace_rows(app, extensions_root, rows, installed_by_id=installed_by_id)
    # Installed plugins missing from the catalog (community/URL installs) must
    # still surface, mirroring the hosted-sync orphan merge.
    catalog_ids = {_plugin_id_from_row(row) for row in rows}
    for plugin_id, installed_row in installed_by_id.items():
        if plugin_id not in catalog_ids:
            rows.append(_build_orphan_installed_row(installed_row, store_url=store_url, channel=channel))
    _add_kept_copy_rows(rows, kept_copies(app[APP_CONFIG]))  # uninstalled, with a copy kept to install again
    _add_stock_workspace_rows(rows, stock_records(app[APP_CONFIG]))
    rows = [row for row in rows if row_is_visible(row, include_catalog_only=True, include_scaffold=False)]
    _sort_marketplace_rows(rows)
    categories, types = _summarize_marketplace_facets(rows)
    installed = [dict(row) for row in rows if bool(row.get("installed"))]
    update_candidates = [
        _safe_string(row.get("plugin_id"))
        for row in rows
        if bool(row.get("update_available")) and _safe_string(row.get("plugin_id")).strip()
    ]
    return {
        "ok": True,
        "sync_source": "local_catalog_fallback",
        "source_label": "local marketplace catalog",
        "store_url": store_url,
        "catalog_url": "",
        "channel": channel,
        "generated_at": _safe_string(catalog.get("generated_at")),
        "synced_at": _safe_string(catalog.get("generated_at")),
        "count": len(rows),
        "total": len(rows),
        "offset": 0,
        "limit": len(rows),
        "categories": categories,
        "types": types,
        "plugins": rows,
        "installed": installed,
        "update_candidates": update_candidates,
        "degraded": True,
        "warning": f"Hosted marketplace sync failed for {store_url}; using local catalog fallback.",
    }
