"""The ``/api/marketplace/*`` routes.

This module is the request layer only. What a field means, what a row looks like,
how a pack is read off disk and how a catalog is synced live in its three
siblings, imported below in that order:

- ``marketplace_catalog_fields`` — coercion, vocabulary, URL builders, retired
  local modules, store-URL candidates
- ``marketplace_catalog_rows`` — installed state overlaid on catalog rows, and
  the facet counts
- ``marketplace_catalog_packs`` — normalizing ``extensions/catalog.json`` entries
  and zipping a pack directory
- ``marketplace_catalog_sync`` — the hosted store, and the local fallback payload

They were split out of this file in phase 3.5: at 1,190 lines it was past the
800-line soft limit in ``docs/monolith_guard_baseline.json``, and because that
limit is enforced on every file a change touches, the module could not be edited
until it was smaller. The edit it was blocking is in ``_install_bundle_auto``
below — see that function.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
from aiohttp import web

from thomas.marketplace.surface_policy import classify_marketplace_row, row_is_visible
from thomas.server.agent_plugins_adapter import cleanup_agent_plugin_extras
from thomas.server.app_keys import APP_CONFIG
from thomas.server.desktop_plugins import (
    install_bundled_plugin,
    install_plugin_bundle_bytes,
    install_plugin_from_store,
    list_installed_plugins,
    parse_plugin_install_deep_link,
    resolve_installed_plugin_asset,
    set_installed_plugin_enabled,
    uninstall_plugin,
)
from thomas.server.desktop_plugins_runtime import get_installed_plugin
from thomas.server.marketplace_bundle_download import download_plugin_bundle
from thomas.server.plugin_shelf import forget_kept_copy, has_kept_copy, install_kept_copy, keep_copy, kept_copies
from thomas.server.plugin_systems_kernel import agent_plugin_installer
from thomas.server.routes.marketplace_catalog_fields import (
    _candidate_marketplace_store_urls,
    _default_marketplace_store_url,
    _is_retired_local_module_id,
    _is_retired_local_module_row,
    _plugin_id_from_row,
    _remove_retired_local_module_installs,
    _retired_plugin_response,
    _safe_string,
    _source_label_from_store_url,
)
from thomas.server.routes.marketplace_catalog_packs import (
    _build_pack_archive,
    _load_marketplace_catalog,
    _matches_query,
    _resolve_pack_dir,
)
from thomas.server.routes.marketplace_catalog_rows import (
    _add_kept_copy_rows,
    _add_stock_workspace_rows,
    _build_orphan_installed_row,
    _overlay_installed_state,
    _sort_marketplace_rows,
    _summarize_marketplace_facets,
)
from thomas.server.routes.marketplace_catalog_sync import (
    _augment_marketplace_rows,
    _build_local_sync_payload,
    _load_hosted_marketplace_catalog,
)
from thomas.server.stock_workspaces import removed_modes, set_removed, stock_mode, stock_records

log = logging.getLogger(__name__)


def _parse_int(value: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


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
            _add_kept_copy_rows(rows, kept_copies(app[APP_CONFIG]))
            _add_stock_workspace_rows(rows, stock_records(app[APP_CONFIG]))
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
        _add_kept_copy_rows(merged_rows, kept_copies(app[APP_CONFIG]))
        _add_stock_workspace_rows(merged_rows, stock_records(app[APP_CONFIG]))
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
        # The sidebar reads this list, so it carries which of Thomas's own workspaces you have uninstalled.
        removed = removed_modes(config)
        return web.json_response({"ok": True, "count": len(plugins), "plugins": plugins, "removed_workspaces": removed})

    def _install_from_anywhere(config: Any, plugin_id: str, store_url: str, channel: str) -> dict[str, Any]:
        """A store when one is named, then ``extensions/``, then the copy kept when you uninstalled it.

        The kept copy is what makes an uninstall of an imported plugin reversible: nothing else has it. A store or
        ``extensions/`` goes first because theirs may be newer.
        """
        plugin = None
        if store_url:
            try:
                plugin = install_plugin_from_store(config, plugin_id=plugin_id, store_url=store_url, channel=channel)
            except (FileNotFoundError, ValueError, httpx.HTTPError):  # type: ignore[name-defined]
                if not has_kept_copy(config, plugin_id):
                    raise
        if plugin is None:
            try:
                plugin = install_bundled_plugin(config, plugin_id)
            except FileNotFoundError:
                plugin = install_kept_copy(config, plugin_id)
        forget_kept_copy(config, plugin_id)
        return plugin

    async def api_marketplace_install(request: web.Request) -> web.Response:
        require_api_access(request)
        config = app[APP_CONFIG]
        plugin_id = _safe_string(request.match_info.get("plugin_id")).strip()
        if not plugin_id:
            return web.json_response({"ok": False, "error": "plugin_id is required"}, status=400)
        if _is_retired_local_module_id(plugin_id):
            return _retired_plugin_response(plugin_id)
        if stock_mode(plugin_id):
            set_removed(config, str(stock_mode(plugin_id)), False)
            return web.json_response(
                {"ok": True, "plugin": {"plugin_id": plugin_id, "installed": True, "enabled": True}}
            )
        body = await _read_optional_json(request)
        store_url = _safe_string(body.get("store") or body.get("store_url"))
        channel = _safe_string(body.get("channel")) or "stable"
        try:
            plugin = _install_from_anywhere(config, plugin_id, store_url, channel)
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
        if stock_mode(plugin_id):
            # One of Thomas's own workspaces: it leaves the sidebar and Marketplace offers it again. What it holds stays.
            set_removed(config, str(stock_mode(plugin_id)), True)
            return web.json_response({"ok": True, "plugin_id": plugin_id, "removed": True, "data_kept": True})
        existing = get_installed_plugin(config, plugin_id)
        if isinstance(existing, dict) and existing.get("agent_plugin"):
            # Remove what the Agent Plugin install added outside its own
            # directory (skills copies, disabled MCP rows) before the record
            # and tree go away.
            cleanup_agent_plugin_extras(config, existing)
        try:
            kept = keep_copy(config, plugin_id)  # first, so it can be installed again whatever it came from
            deleted = uninstall_plugin(config, plugin_id)
        except OSError as exc:
            # What you saved with it could not be moved to safety, so nothing was removed.
            error = f"Could not set aside what you saved with '{plugin_id}', so it was not uninstalled: {exc}"
            return web.json_response({"ok": False, "error": error}, status=409)
        if not deleted:
            return web.json_response({"ok": False, "error": f"Plugin '{plugin_id}' is not installed"}, status=404)
        return web.json_response(
            {"ok": True, "plugin_id": plugin_id, "removed": True, "data_kept": True, "kept_copy": kept}
        )

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
        through the signed path, unchanged.

        Both branches now go through a kernel service instead of an imported
        function. ``agent_plugin_installer()`` resolves the
        ``agent_plugin_installer`` provider and asks it both questions — does it
        claim this bundle, and install it — and ``install_plugin_bundle_bytes``
        is the facade in ``thomas/server/desktop_plugins.py`` that resolves the
        ``desktop_plugin_installer`` provider. Mount a replacement for either
        while Thomas runs and the next import request goes to it, with no
        restart and no edit here. Behaviour is unchanged while the default
        providers are the ones mounted: they call the same two functions this
        used to import.
        """
        config = app[APP_CONFIG]
        installer = agent_plugin_installer()
        if installer.accepts(bundle_bytes):
            return installer.install(config, bundle_bytes, source=source)
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
