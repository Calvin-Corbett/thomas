from __future__ import annotations

import io
import logging
import os
import zipfile
from collections import Counter
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import httpx
from aiohttp import web

from thomas.marketplace.surface_policy import classify_marketplace_row, row_is_visible
from thomas.plugins.extension_catalog_runtime import load_extension_catalog
from thomas.server.agent_plugins_adapter import (
    cleanup_agent_plugin_extras,
    install_agent_plugin_bytes,
)
from thomas.server.agent_plugins_manifest import bundle_is_agent_plugin
from thomas.server.app_keys import APP_CONFIG
from thomas.server.desktop_plugins import (
    install_bundled_plugin,
    install_plugin_bundle_bytes,
    install_plugin_from_store,
    list_installed_plugins,
    maybe_load_desktop_plugin_manifest,
    parse_plugin_install_deep_link,
    resolve_installed_plugin_asset,
    set_installed_plugin_enabled,
    uninstall_plugin,
)
from thomas.server.desktop_plugins_runtime import get_installed_plugin
from thomas.server.marketplace_bundle_download import download_plugin_bundle
from thomas.server.net_safety import validate_public_url

log = logging.getLogger(__name__)

_MARKETPLACE_TYPES = {"app", "plugin", "dependency", "integration"}
# "command_center" renamed to "app" (2026-06-11); legacy values normalize on read.
_LEGACY_MARKETPLACE_TYPE_ALIASES = {"command_center": "app"}
_LEFT_NAV_BEHAVIORS = {"none", "workspace"}
_DEFAULT_NAV_SECTIONS = {"apps", "installed"}
_LEGACY_NAV_SECTION_ALIASES = {"command_centers": "apps"}
_TYPE_LABELS = {
    "app": "App",
    "command_center": "App",
    "plugin": "Plugin",
    "dependency": "Dependency",
    "integration": "Integration",
}
_RETIRED_LOCAL_MODULE_IDS = frozenset(
    {
        "life-manager",
        "life-manager-foundation",
        "brownies",
        "smart-home",
        "telegram-channel",
    }
)
_CANONICAL_MARKETPLACE_STORE_URL = "https://thomas-site.thomasdevhub.workers.dev"
_LEGACY_MARKETPLACE_STORE_URL = "https://thomas.dev"


def _safe_string(value: Any) -> str:
    return value if isinstance(value, str) else ("" if value is None else str(value))


def _plugin_id_from_row(row: dict[str, Any]) -> str:
    return _safe_string(row.get("plugin_id") or row.get("id")).strip()


def _is_retired_local_module_id(plugin_id: str) -> bool:
    return _safe_string(plugin_id).strip().lower() in _RETIRED_LOCAL_MODULE_IDS


def _is_retired_local_module_row(row: dict[str, Any]) -> bool:
    return _is_retired_local_module_id(_plugin_id_from_row(row))


def _retired_plugin_response(plugin_id: str, *, status: int = 404) -> web.Response:
    return web.json_response(
        {
            "ok": False,
            "error": f"Plugin '{plugin_id}' is retired from the local marketplace.",
            "retired": True,
        },
        status=status,
    )


def _remove_retired_local_module_installs(config: Any, plugin: dict[str, Any] | None = None) -> None:
    plugin_ids = set(_RETIRED_LOCAL_MODULE_IDS)
    if isinstance(plugin, dict):
        plugin_id = _plugin_id_from_row(plugin)
        if plugin_id:
            plugin_ids.add(plugin_id)
        for dependency_id in plugin.get("requires") or []:
            dependency = _safe_string(dependency_id).strip()
            if dependency:
                plugin_ids.add(dependency)
    for plugin_id in plugin_ids:
        if not _is_retired_local_module_id(plugin_id):
            continue
        try:
            uninstall_plugin(config, plugin_id)
        # Uninstall is a filesystem delete plus a JSON manifest rewrite: OSError
        # for the files, ValueError/TypeError/KeyError for a manifest that is not
        # shaped the way we expect. A retired plugin that will not budge is a
        # debug note, not a failed catalog request.
        except (OSError, ValueError, TypeError, KeyError):
            log.debug("Unable to remove retired marketplace plugin '%s'", plugin_id, exc_info=True)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = _safe_string(item).strip()
        if text and text not in out:
            out.append(text)
    return out


def _slugify(value: str) -> str:
    return _safe_string(value).strip().lower().replace(" ", "_").replace("-", "_")


def _slug_label(value: str) -> str:
    words = [part for part in _safe_string(value).replace("_", "-").split("-") if part]
    return " ".join(word[:1].upper() + word[1:] for word in words) or "Other"


def _download_url(plugin_id: str) -> str:
    return f"/api/marketplace/plugins/{quote(plugin_id, safe='')}/download"


def _install_url(plugin_id: str) -> str:
    return f"/api/marketplace/plugins/{quote(plugin_id, safe='')}/install"


def _uninstall_url(plugin_id: str) -> str:
    return f"/api/marketplace/plugins/{quote(plugin_id, safe='')}/uninstall"


def _enable_url(plugin_id: str) -> str:
    return f"/api/marketplace/plugins/{quote(plugin_id, safe='')}/enable"


def _disable_url(plugin_id: str) -> str:
    return f"/api/marketplace/plugins/{quote(plugin_id, safe='')}/disable"


def _download_filename(plugin_id: str, version: str) -> str:
    return f"{plugin_id}-{version}.zip".replace('"', "_")


def _default_marketplace_store_url() -> str:
    explicit = _safe_string(os.environ.get("THOMAS_MARKETPLACE_STORE_URL")).strip()
    if explicit:
        return explicit.rstrip("/")
    site_url = _safe_string(os.environ.get("SITE_URL")).strip()
    if site_url:
        return site_url.rstrip("/")
    return _CANONICAL_MARKETPLACE_STORE_URL


def _candidate_marketplace_store_urls(preferred_store_url: str = "") -> list[str]:
    candidates: list[str] = []
    for raw in (
        preferred_store_url,
        _safe_string(os.environ.get("THOMAS_MARKETPLACE_STORE_URL")).strip(),
        _safe_string(os.environ.get("SITE_URL")).strip(),
        _CANONICAL_MARKETPLACE_STORE_URL,
        _LEGACY_MARKETPLACE_STORE_URL,
    ):
        candidate = _safe_string(raw).strip().rstrip("/")
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _source_label_from_store_url(store_url: str) -> str:
    parsed = urlparse(_safe_string(store_url))
    host = _safe_string(parsed.netloc or parsed.path).strip().lower()
    if not host:
        return "marketplace store"
    return host


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


async def _load_hosted_marketplace_catalog(*, store_url: str, channel: str) -> dict[str, Any]:
    catalog_urls = [
        urljoin(store_url.rstrip("/") + "/", f"api/marketplace/catalog?channel={quote(channel, safe='')}"),
        urljoin(store_url.rstrip("/") + "/", f"api/v1/plugins/catalog?channel={quote(channel, safe='')}"),
    ]
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        for catalog_url in catalog_urls:
            try:
                response = await client.get(validate_public_url(catalog_url))
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


def _infer_marketplace_type(raw: dict[str, Any], *, target: str, mode: str) -> str:
    explicit = _safe_string(raw.get("marketplace_type")).strip().lower()
    explicit = _LEGACY_MARKETPLACE_TYPE_ALIASES.get(explicit, explicit)
    if explicit in _MARKETPLACE_TYPES:
        return explicit
    if target == "desktop" and mode:
        return "app"
    return "plugin"


def _infer_left_nav_behavior(raw: dict[str, Any], marketplace_type: str) -> str:
    explicit = _safe_string(raw.get("left_nav_behavior")).strip().lower()
    if explicit in _LEFT_NAV_BEHAVIORS:
        return explicit
    return "workspace" if marketplace_type == "app" else "none"


def _infer_default_nav_section(raw: dict[str, Any], *, marketplace_type: str, left_nav_behavior: str) -> str:
    explicit = _safe_string(raw.get("default_nav_section")).strip().lower()
    explicit = _LEGACY_NAV_SECTION_ALIASES.get(explicit, explicit)
    if explicit in _DEFAULT_NAV_SECTIONS:
        return explicit
    if marketplace_type == "app" or left_nav_behavior == "workspace":
        return "apps"
    return "installed"


def _normalize_pack(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    plugin_id = _safe_string(raw.get("id")).strip()
    if not plugin_id:
        return None
    capabilities = raw.get("capabilities")
    version = _safe_string(raw.get("version")).strip() or "0.0.0"
    category = _slugify(raw.get("category")) or "other"
    categories = _string_list(raw.get("categories"))
    if category not in categories:
        categories.insert(0, category)
    target = _safe_string(raw.get("target")).strip()
    mode = _safe_string(raw.get("mode")).strip()
    marketplace_type = _infer_marketplace_type(raw, target=target, mode=mode)
    left_nav_behavior = _infer_left_nav_behavior(raw, marketplace_type)
    default_nav_section = _infer_default_nav_section(
        raw, marketplace_type=marketplace_type, left_nav_behavior=left_nav_behavior
    )
    default_nav_order = _safe_int(raw.get("default_nav_order"), 400 if marketplace_type == "app" else 900)
    tags = _string_list(raw.get("tags"))
    for value in categories + [marketplace_type, target, mode, left_nav_behavior]:
        text = _safe_string(value).strip()
        if text and text not in tags:
            tags.append(text)
    return {
        "id": plugin_id,
        "plugin_id": plugin_id,
        "name": _safe_string(raw.get("name")).strip() or plugin_id,
        "display_name": _safe_string(raw.get("name")).strip() or plugin_id,
        "version": version,
        "category": category,
        "category_label": _slug_label(category),
        "categories": categories,
        "tags": tags,
        "requires": _string_list(raw.get("requires")),
        "target": target,
        "mode": mode,
        "mode_id": _safe_string(raw.get("mode_id") or raw.get("mode")).strip(),
        "marketplace_type": marketplace_type,
        "marketplace_type_label": _TYPE_LABELS.get(marketplace_type, "Plugin"),
        "left_nav_behavior": left_nav_behavior,
        "default_nav_section": default_nav_section,
        "default_nav_order": default_nav_order,
        "description": _safe_string(raw.get("description")).strip(),
        "entrypoint": _safe_string(raw.get("entrypoint")).strip(),
        "capabilities": [str(item).strip() for item in capabilities if isinstance(item, str) and str(item).strip()]
        if isinstance(capabilities, list)
        else [],
        "download_url": _download_url(plugin_id),
        "download_filename": _download_filename(plugin_id, version),
        "download_available": False,
        "installable": False,
        "installed": False,
        "enabled": False,
        "workspace_id": "",
        "kind": "extension_pack",
        "source": "extensions/catalog.json",
    }


def _matches_query(row: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    blob = " ".join(
        [
            _safe_string(row.get("id")),
            _safe_string(row.get("name")),
            _safe_string(row.get("display_name")),
            _safe_string(row.get("description")),
            _safe_string(row.get("category")),
            " ".join(row.get("categories") or []),
            " ".join(row.get("tags") or []),
            _safe_string(row.get("marketplace_type")),
            _safe_string(row.get("target")),
            _safe_string(row.get("mode")),
            _safe_string(row.get("mode_id")),
            _safe_string(row.get("publisher_name")),
            " ".join(row.get("capabilities") or []),
        ]
    ).lower()
    return query in blob


def _parse_int(value: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _safe_plugin_id_segment(plugin_id: str) -> str | None:
    """Return ``plugin_id`` if it is a single safe path segment, else ``None``.

    ``plugin_id`` is request-controlled (URL match_info / catalog rows), so
    reject anything that could escape ``extensions_root``: empty values, path
    separators, drive markers, and ``.``/``..`` segments.
    """
    candidate = _safe_string(plugin_id).strip()
    if not candidate or candidate in {".", ".."}:
        return None
    if "/" in candidate or "\\" in candidate:
        return None
    if PurePosixPath(candidate).is_absolute() or PurePosixPath(candidate).parts != (candidate,):
        return None
    return candidate


def _resolve_pack_dir(extensions_root: Path, plugin_id: str) -> Path | None:
    safe_id = _safe_plugin_id_segment(plugin_id)
    if safe_id is None:
        return None
    base = extensions_root.resolve()
    candidate = (base / safe_id).resolve()
    # Confine the resolved directory to the extensions root to block traversal.
    if not candidate.is_relative_to(base):
        return None
    return candidate if candidate.is_dir() else None


def _iter_pack_files(pack_dir: Path) -> list[tuple[Path, Path]]:
    rows: list[tuple[Path, Path]] = []
    for path in sorted(pack_dir.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(pack_dir)
        if "__pycache__" in rel_path.parts:
            continue
        if path.suffix.lower() in {".pyc", ".pyo"}:
            continue
        if any(part.startswith(".") for part in rel_path.parts):
            continue
        rows.append((path, rel_path))
    return rows


def _build_pack_archive(plugin_id: str, pack_dir: Path) -> bytes:
    files = _iter_pack_files(pack_dir)
    if not files:
        raise FileNotFoundError(f"Plugin '{plugin_id}' does not contain any downloadable files")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source_path, rel_path in files:
            archive.write(source_path, arcname=str(PurePosixPath(plugin_id, *rel_path.parts)))
    return buffer.getvalue()


def _load_marketplace_catalog() -> tuple[dict[str, Any], Path, list[dict[str, Any]]]:
    catalog = load_extension_catalog()
    extensions_root = Path(_safe_string(catalog.get("root")) or ".").resolve()
    packs_raw = catalog.get("packs")
    rows: list[dict[str, Any]] = []
    if isinstance(packs_raw, list):
        for item in packs_raw:
            row = _normalize_pack(item)
            if row is None:
                continue
            if _is_retired_local_module_row(row):
                continue
            row["download_available"] = _resolve_pack_dir(extensions_root, _safe_string(row.get("id"))) is not None
            rows.append(row)
    return catalog, extensions_root, rows


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


async def _read_optional_json(request: web.Request) -> dict[str, Any]:
    content_type = _safe_string(request.content_type).lower()
    if "json" not in content_type:
        return {}
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def register_marketplace_catalog_routes(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
) -> None:
    async def api_marketplace_plugins(request: web.Request) -> web.Response:
        require_api_access(request)

        query = _safe_string(request.query.get("q")).strip().lower()
        category = _safe_string(request.query.get("category")).strip().lower()
        marketplace_type = _safe_string(request.query.get("type")).strip().lower()
        offset = _parse_int(_safe_string(request.query.get("offset")), 0, minimum=0, maximum=100000)
        limit = _parse_int(_safe_string(request.query.get("limit")), 600, minimum=1, maximum=2000)

        try:
            catalog, extensions_root, rows = _load_marketplace_catalog()
            rows = _augment_marketplace_rows(app, extensions_root, rows)
        except Exception as exc:
            log.exception("Failed to load marketplace plugin catalog")
            return web.json_response(
                {"ok": False, "error": f"Unable to load marketplace plugin catalog: {exc}"},
                status=500,
            )

        rows = [row for row in rows if row_is_visible(row, include_catalog_only=True, include_scaffold=False)]
        _sort_marketplace_rows(rows)
        categories, types = _summarize_marketplace_facets(rows)
        filtered = [
            row
            for row in rows
            if (not category or category == "all" or _safe_string(row.get("category")).lower() == category)
            and (
                not marketplace_type
                or marketplace_type == "all"
                or _safe_string(row.get("marketplace_type")).lower() == marketplace_type
            )
            and _matches_query(row, query)
        ]

        paginated = filtered[offset : offset + limit]

        return web.json_response(
            {
                "ok": True,
                "generated_at": _safe_string(catalog.get("generated_at")),
                "catalog_source": "extensions/catalog.json",
                "count": len(filtered),
                "total": len(rows),
                "offset": offset,
                "limit": limit,
                "categories": categories,
                "types": types,
                "plugins": paginated,
            }
        )

    async def api_marketplace_sync(request: web.Request) -> web.Response:
        require_api_access(request)

        query = _safe_string(request.query.get("q")).strip().lower()
        category = _safe_string(request.query.get("category")).strip().lower()
        marketplace_type = _safe_string(request.query.get("type")).strip().lower()
        offset = _parse_int(_safe_string(request.query.get("offset")), 0, minimum=0, maximum=100000)
        limit = _parse_int(_safe_string(request.query.get("limit")), 600, minimum=1, maximum=2000)
        requested_store_url = _safe_string(request.query.get("store") or request.query.get("store_url")).strip()
        channel = _safe_string(request.query.get("channel")).strip() or "stable"

        attempted_store_urls: list[str] = []
        remote_payload: dict[str, Any] | None = None
        store_url = requested_store_url or _default_marketplace_store_url()
        last_error: Exception | None = None
        for candidate_store_url in _candidate_marketplace_store_urls(requested_store_url):
            attempted_store_urls.append(candidate_store_url)
            try:
                remote_payload = await _load_hosted_marketplace_catalog(store_url=candidate_store_url, channel=channel)
                store_url = candidate_store_url
                break
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                log.warning("Hosted marketplace sync failed for %s: %s", candidate_store_url, exc)

        if remote_payload is None:
            fallback_payload = _build_local_sync_payload(app, store_url=store_url, channel=channel)
            if last_error is not None:
                fallback_payload["sync_error"] = f"Unable to sync marketplace catalog from {store_url}: {last_error}"
            fallback_payload["attempted_store_urls"] = attempted_store_urls
            filtered = [
                row
                for row in fallback_payload["plugins"]
                if (not category or category == "all" or _safe_string(row.get("category")).lower() == category)
                and (
                    not marketplace_type
                    or marketplace_type == "all"
                    or _safe_string(row.get("marketplace_type")).lower() == marketplace_type
                )
                and _matches_query(row, query)
            ]
            fallback_payload["count"] = len(filtered)
            fallback_payload["total"] = len(fallback_payload["plugins"])
            fallback_payload["offset"] = offset
            fallback_payload["limit"] = limit
            fallback_payload["plugins"] = filtered[offset : offset + limit]
            return web.json_response(fallback_payload)

        raw_rows = remote_payload.get("plugins")
        rows = [dict(item) for item in raw_rows if isinstance(item, dict)] if isinstance(raw_rows, list) else []
        config = app[APP_CONFIG]
        installed = list_installed_plugins(config, include_disabled=True)
        installed_by_id = {row["plugin_id"]: row for row in installed if not _is_retired_local_module_row(row)}
        merged_rows: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for row in rows:
            plugin_id = _safe_string(row.get("id") or row.get("plugin_id")).strip()
            if not plugin_id:
                continue
            if _is_retired_local_module_id(plugin_id):
                continue
            row["id"] = plugin_id
            row["plugin_id"] = plugin_id
            merged_row = _overlay_installed_state(row, installed_by_id.get(plugin_id))
            merged_row.update(
                classify_marketplace_row(
                    merged_row,
                    installable_candidate=bool(merged_row.get("installable")),
                )
            )
            if _safe_string(merged_row.get("availability")).lower() != "installable":
                merged_row["installable"] = False
            merged_rows.append(merged_row)
            seen_ids.add(plugin_id)
        for plugin_id, installed_row in installed_by_id.items():
            if plugin_id in seen_ids:
                continue
            merged_rows.append(_build_orphan_installed_row(installed_row, store_url=store_url, channel=channel))
        merged_rows = [
            row for row in merged_rows if row_is_visible(row, include_catalog_only=True, include_scaffold=False)
        ]
        _sort_marketplace_rows(merged_rows)
        categories, types = _summarize_marketplace_facets(merged_rows)
        filtered = [
            row
            for row in merged_rows
            if (not category or category == "all" or _safe_string(row.get("category")).lower() == category)
            and (
                not marketplace_type
                or marketplace_type == "all"
                or _safe_string(row.get("marketplace_type")).lower() == marketplace_type
            )
            and _matches_query(row, query)
        ]
        paginated = filtered[offset : offset + limit]
        update_candidates = [
            _safe_string(row.get("plugin_id"))
            for row in merged_rows
            if bool(row.get("update_available")) and _safe_string(row.get("plugin_id")).strip()
        ]
        return web.json_response(
            {
                "ok": True,
                "sync_source": "hosted_catalog",
                "source_label": _source_label_from_store_url(store_url),
                "store_url": store_url,
                "attempted_store_urls": attempted_store_urls,
                "catalog_url": _safe_string(remote_payload.get("catalog_url")),
                "channel": channel,
                "generated_at": _safe_string(remote_payload.get("generated_at")),
                "synced_at": _safe_string(remote_payload.get("generated_at"))
                or _safe_string(remote_payload.get("synced_at")),
                "count": len(filtered),
                "total": len(merged_rows),
                "offset": offset,
                "limit": limit,
                "categories": categories,
                "types": types,
                "plugins": paginated,
                "installed": [dict(row) for row in merged_rows if bool(row.get("installed"))],
                "update_candidates": update_candidates,
            }
        )

    async def api_marketplace_plugin_download(request: web.Request) -> web.Response:
        require_api_access(request)

        plugin_id = _safe_string(request.match_info.get("plugin_id")).strip()
        if not plugin_id:
            return web.json_response({"ok": False, "error": "plugin_id is required"}, status=400)
        if _is_retired_local_module_id(plugin_id):
            return _retired_plugin_response(plugin_id)

        try:
            _catalog, extensions_root, rows = _load_marketplace_catalog()
        except Exception as exc:
            log.exception("Failed to load marketplace plugin catalog for download")
            return web.json_response(
                {"ok": False, "error": f"Unable to load marketplace plugin catalog: {exc}"},
                status=500,
            )

        plugin_row = next((row for row in rows if _safe_string(row.get("id")) == plugin_id), None)
        if plugin_row is None:
            return web.json_response({"ok": False, "error": f"Plugin '{plugin_id}' not found"}, status=404)

        pack_dir = _resolve_pack_dir(extensions_root, plugin_id)
        if pack_dir is None:
            return web.json_response(
                {"ok": False, "error": f"Plugin '{plugin_id}' is not available for download"},
                status=404,
            )

        try:
            archive_bytes = _build_pack_archive(plugin_id, pack_dir)
        except FileNotFoundError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=404)
        except Exception as exc:
            log.exception("Failed to package marketplace plugin '%s'", plugin_id)
            return web.json_response(
                {"ok": False, "error": f"Unable to package marketplace plugin '{plugin_id}': {exc}"},
                status=500,
            )

        response = web.Response(body=archive_bytes, content_type="application/zip")
        response.headers["Content-Disposition"] = (
            f'attachment; filename="{_safe_string(plugin_row.get("download_filename")) or f"{plugin_id}.zip"}"'
        )
        response.headers["Content-Length"] = str(len(archive_bytes))
        return response

    async def api_marketplace_installed(request: web.Request) -> web.Response:
        require_api_access(request)
        config = app[APP_CONFIG]
        plugins = [
            row
            for row in list_installed_plugins(config, include_disabled=True)
            if not _is_retired_local_module_row(row)
        ]
        return web.json_response({"ok": True, "count": len(plugins), "plugins": plugins})

    async def api_marketplace_install(request: web.Request) -> web.Response:
        require_api_access(request)
        config = app[APP_CONFIG]
        plugin_id = _safe_string(request.match_info.get("plugin_id")).strip()
        if not plugin_id:
            return web.json_response({"ok": False, "error": "plugin_id is required"}, status=400)
        if _is_retired_local_module_id(plugin_id):
            return _retired_plugin_response(plugin_id)
        body = await _read_optional_json(request)
        store_url = _safe_string(body.get("store") or body.get("store_url"))
        channel = _safe_string(body.get("channel")) or "stable"
        try:
            if store_url:
                plugin = install_plugin_from_store(config, plugin_id=plugin_id, store_url=store_url, channel=channel)
            else:
                plugin = install_bundled_plugin(config, plugin_id)
        except (FileNotFoundError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except httpx.HTTPError as exc:  # type: ignore[name-defined]
            return web.json_response({"ok": False, "error": str(exc)}, status=502)
        except Exception as exc:
            log.exception("Failed to install marketplace plugin '%s'", plugin_id)
            return web.json_response({"ok": False, "error": f"Unable to install plugin: {exc}"}, status=500)
        return web.json_response({"ok": True, "plugin": plugin})

    async def api_marketplace_install_from_deep_link(request: web.Request) -> web.Response:
        require_api_access(request)
        config = app[APP_CONFIG]
        body = await _read_optional_json(request)
        deep_link = _safe_string(body.get("url") or body.get("deep_link")).strip()
        if not deep_link:
            return web.json_response({"ok": False, "error": "deep_link is required"}, status=400)
        try:
            install_request = parse_plugin_install_deep_link(deep_link)
            plugin_id = _safe_string(install_request.get("plugin_id"))
            if _is_retired_local_module_id(plugin_id):
                return _retired_plugin_response(plugin_id)
            plugin = install_plugin_from_store(
                config,
                plugin_id=plugin_id,
                store_url=_safe_string(install_request.get("store")),
                channel=_safe_string(install_request.get("channel")) or "stable",
            )
        except (FileNotFoundError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except httpx.HTTPError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=502)
        except Exception as exc:
            log.exception("Failed to install marketplace plugin from deep link")
            return web.json_response(
                {"ok": False, "error": f"Unable to install plugin from deep link: {exc}"}, status=500
            )
        return web.json_response({"ok": True, "plugin": plugin, "request": install_request})

    async def api_marketplace_uninstall(request: web.Request) -> web.Response:
        require_api_access(request)
        config = app[APP_CONFIG]
        plugin_id = _safe_string(request.match_info.get("plugin_id")).strip()
        if not plugin_id:
            return web.json_response({"ok": False, "error": "plugin_id is required"}, status=400)
        if _is_retired_local_module_id(plugin_id):
            removed = uninstall_plugin(config, plugin_id)
            return web.json_response({"ok": True, "plugin_id": plugin_id, "removed": bool(removed), "retired": True})
        existing = get_installed_plugin(config, plugin_id)
        if isinstance(existing, dict) and existing.get("agent_plugin"):
            # Remove what the Agent Plugin install added outside its own
            # directory (skills copies, disabled MCP rows) before the record
            # and tree go away.
            cleanup_agent_plugin_extras(config, existing)
        deleted = uninstall_plugin(config, plugin_id)
        if not deleted:
            return web.json_response({"ok": False, "error": f"Plugin '{plugin_id}' is not installed"}, status=404)
        return web.json_response({"ok": True, "plugin_id": plugin_id, "removed": True})

    async def api_marketplace_enable(request: web.Request) -> web.Response:
        require_api_access(request)
        config = app[APP_CONFIG]
        plugin_id = _safe_string(request.match_info.get("plugin_id")).strip()
        if _is_retired_local_module_id(plugin_id):
            return _retired_plugin_response(plugin_id)
        try:
            plugin = set_installed_plugin_enabled(config, plugin_id, True)
        except FileNotFoundError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=404)
        return web.json_response({"ok": True, "plugin": plugin})

    async def api_marketplace_disable(request: web.Request) -> web.Response:
        require_api_access(request)
        config = app[APP_CONFIG]
        plugin_id = _safe_string(request.match_info.get("plugin_id")).strip()
        if _is_retired_local_module_id(plugin_id):
            return _retired_plugin_response(plugin_id)
        try:
            plugin = set_installed_plugin_enabled(config, plugin_id, False)
        except FileNotFoundError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=404)
        return web.json_response({"ok": True, "plugin": plugin})

    def _install_bundle_auto(bundle_bytes: bytes, source: dict[str, Any]) -> dict[str, Any]:
        """One dispatch for every import shape: an open-standard bundle
        (agent-plugins.org) installs as the UNVERIFIED community tier -
        skills copied, MCP servers registered off; anything else goes
        through the signed path, unchanged."""
        config = app[APP_CONFIG]
        if bundle_is_agent_plugin(bundle_bytes):
            return install_agent_plugin_bytes(config, bundle_bytes, source=source)
        return install_plugin_bundle_bytes(config, bundle_bytes, source=source, require_signature=True)

    async def api_marketplace_import(request: web.Request) -> web.Response:
        require_api_access(request)
        config = app[APP_CONFIG]
        content_type = _safe_string(request.content_type).lower()
        try:
            if "multipart/" in content_type:
                reader = await request.multipart()
                bundle_bytes = b""
                filename = ""
                async for part in reader:
                    if _safe_string(part.name) != "file":
                        continue
                    filename = _safe_string(part.filename) or "plugin-bundle.zip"
                    bundle_bytes = await part.read(decode=False)
                    break
                if not bundle_bytes:
                    return web.json_response({"ok": False, "error": "No plugin bundle file was uploaded"}, status=400)
                plugin = _install_bundle_auto(bundle_bytes, {"type": "file_upload", "filename": filename})
            else:
                body = await _read_optional_json(request)
                raw_url = _safe_string(body.get("url")).strip()
                raw_path = _safe_string(body.get("path")).strip()
                if raw_url:
                    bundle_bytes = await download_plugin_bundle(raw_url)
                    plugin = _install_bundle_auto(bundle_bytes, {"type": "url_import", "url": raw_url})
                elif raw_path:
                    # ``path`` is request-controlled. Reject traversal components and
                    # require the resolved target to be an existing regular bundle file
                    # before reading it, so a caller cannot point the importer at
                    # arbitrary system files via ``..`` segments.
                    if ".." in PurePosixPath(raw_path.replace("\\", "/")).parts:
                        raise ValueError("Unsafe bundle file path")
                    bundle_path = Path(raw_path).expanduser().resolve()
                    if not bundle_path.is_file():
                        raise FileNotFoundError(f"Bundle file was not found: {bundle_path}")
                    plugin = _install_bundle_auto(
                        bundle_path.read_bytes(), {"type": "file_import", "path": str(bundle_path)}
                    )
                else:
                    raise ValueError("A bundle file path or url is required")
        except (FileNotFoundError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            log.exception("Failed to import marketplace plugin bundle")
            return web.json_response({"ok": False, "error": f"Unable to import plugin bundle: {exc}"}, status=500)
        plugin_id = _plugin_id_from_row(plugin)
        if _is_retired_local_module_id(plugin_id):
            _remove_retired_local_module_installs(config, plugin)
            return _retired_plugin_response(plugin_id)
        return web.json_response({"ok": True, "plugin": plugin})

    async def plugin_asset(request: web.Request) -> web.StreamResponse:
        require_api_access(request)
        config = app[APP_CONFIG]
        plugin_id = _safe_string(request.match_info.get("plugin_id")).strip()
        asset_path = _safe_string(request.match_info.get("asset_path")).strip()
        if _is_retired_local_module_id(plugin_id):
            raise web.HTTPNotFound(text="plugin asset was not found")
        try:
            asset = resolve_installed_plugin_asset(config, plugin_id, asset_path)
        except PermissionError as exc:
            log.warning("Denied plugin asset request for '%s'", plugin_id)
            raise web.HTTPForbidden(text="plugin asset is not available") from exc
        except (FileNotFoundError, ValueError) as exc:
            log.info("Plugin asset request could not be resolved for '%s'", plugin_id)
            raise web.HTTPNotFound(text="plugin asset was not found") from exc
        return web.FileResponse(asset, headers={"Cache-Control": "no-store"})

    app.router.add_get("/api/marketplace/plugins", api_marketplace_plugins)
    app.router.add_get("/api/marketplace/sync", api_marketplace_sync)
    app.router.add_get("/api/marketplace/plugins/{plugin_id}/download", api_marketplace_plugin_download)
    app.router.add_get("/api/marketplace/installed", api_marketplace_installed)
    app.router.add_post("/api/marketplace/plugins/{plugin_id}/install", api_marketplace_install)
    app.router.add_post("/api/marketplace/install-from-deep-link", api_marketplace_install_from_deep_link)
    app.router.add_post("/api/marketplace/plugins/{plugin_id}/uninstall", api_marketplace_uninstall)
    app.router.add_post("/api/marketplace/plugins/{plugin_id}/enable", api_marketplace_enable)
    app.router.add_post("/api/marketplace/plugins/{plugin_id}/disable", api_marketplace_disable)
    app.router.add_post("/api/marketplace/import", api_marketplace_import)
    app.router.add_get("/plugins/{plugin_id}/{asset_path:.*}", plugin_asset)
