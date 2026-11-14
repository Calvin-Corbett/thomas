"""Field-level helpers for the marketplace catalog routes.

Phase 3.5 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md).

The bottom layer of the four the catalog routes were split into, and the only
one that imports nothing from its siblings: value coercion, the vocabulary of
marketplace types and nav sections, the per-plugin URL builders, the retired
local modules, and the store-URL candidates. ``marketplace_catalog_rows``,
``marketplace_catalog_packs`` and ``marketplace_catalog_sync`` build on this one,
in that order, and ``marketplace_catalog_aiohttp`` imports from all four.

The split happened because the routes module had grown to 1,190 lines, which put
it past the 800-line soft limit in ``docs/monolith_guard_baseline.json`` — and
the guard enforces that limit on every file a change touches, so the module could
not be edited at all until it was smaller. Names keep their leading underscore:
they are internal to this package of four, not a surface anything else should
import.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import quote, urlparse

from aiohttp import web

from thomas.server.desktop_plugins import uninstall_plugin

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
