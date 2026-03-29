from __future__ import annotations

import hashlib
import io
import os
import secrets
import shutil
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, quote, urljoin, urlparse

import httpx

from thomas.core.config import AppConfig
from thomas.server.desktop_plugins_manifest import (
    _DEFAULT_PLUGIN_STORE_API_KEY,
    _LEFT_NAV_BEHAVIORS,
    _REGISTRY_VERSION,
    DesktopPluginManifest,
    _installed_plugins_root,
    _installed_registry_path,
    _plugin_store_identity_path,
    _read_json_file,
    _safe_int,
    _safe_rel_path,
    _safe_text,
    _string_list,
    _utc_now_iso,
    _write_json_file,
    build_plugin_bundle_bytes,
    compute_plugin_bundle_sha256,
    load_bundled_desktop_plugin_manifest,
    load_desktop_plugin_manifest_from_data,
)


def _load_installed_registry(config: AppConfig) -> dict[str, Any]:
    payload = _read_json_file(_installed_registry_path(config), {"version": _REGISTRY_VERSION, "plugins": []})
    if not isinstance(payload, dict):
        return {"version": _REGISTRY_VERSION, "plugins": []}
    plugins = payload.get("plugins")
    if not isinstance(plugins, list):
        payload["plugins"] = []
    return payload


def _save_installed_registry(config: AppConfig, rows: list[dict[str, Any]]) -> None:
    payload = {
        "version": _REGISTRY_VERSION,
        "updated_at": _utc_now_iso(),
        "plugins": sorted(
            rows,
            key=lambda row: (_safe_text(row.get("display_name")), _safe_text(row.get("plugin_id"))),
        ),
    }
    _write_json_file(_installed_registry_path(config), payload)


def _replace_installed_record(config: AppConfig, record: dict[str, Any]) -> None:
    payload = _load_installed_registry(config)
    rows = [
        row
        for row in (payload.get("plugins") or [])
        if _safe_text(row.get("plugin_id")) != _safe_text(record.get("plugin_id"))
    ]
    rows.append(record)
    _save_installed_registry(config, rows)


def _remove_installed_record(config: AppConfig, plugin_id: str) -> None:
    payload = _load_installed_registry(config)
    rows = [row for row in (payload.get("plugins") or []) if _safe_text(row.get("plugin_id")) != plugin_id]
    _save_installed_registry(config, rows)


def _installed_plugin_dir(config: AppConfig, plugin_id: str) -> Path:
    return _installed_plugins_root(config) / plugin_id


def _delete_installed_plugin_payload(config: AppConfig, plugin_id: str) -> bool:
    destination_dir = _installed_plugin_dir(config, plugin_id)
    existed = destination_dir.exists()
    if destination_dir.exists():
        shutil.rmtree(destination_dir, ignore_errors=True)
    _remove_installed_record(config, plugin_id)
    return existed


def _prune_orphan_dependency_plugins(config: AppConfig) -> list[str]:
    removed: list[str] = []
    while True:
        installed = list_installed_plugins(config, include_disabled=True)
        if not installed:
            break
        required_ids = {
            _safe_text(required)
            for row in installed
            for required in (row.get("requires") or [])
            if _safe_text(required)
        }
        orphan = next(
            (
                row
                for row in installed
                if _safe_text(row.get("marketplace_type")).lower() == "dependency"
                and _safe_text(row.get("plugin_id"))
                and _safe_text(row.get("plugin_id")) not in required_ids
            ),
            None,
        )
        if orphan is None:
            break
        plugin_id = _safe_text(orphan.get("plugin_id"))
        if not plugin_id:
            break
        _delete_installed_plugin_payload(config, plugin_id)
        removed.append(plugin_id)
    return removed


def _build_surface_url(plugin_id: str, entry_html: str) -> str:
    return f"/plugins/{quote(plugin_id, safe='')}/{quote(_safe_rel_path(entry_html), safe='/')}"


def _normalize_installed_record(record: dict[str, Any]) -> dict[str, Any]:
    plugin_id = _safe_text(record.get("plugin_id"))
    surface = record.get("surface") if isinstance(record.get("surface"), dict) else {}
    entry_html = _safe_text(surface.get("entry_html"))
    left_nav_behavior = _safe_text(record.get("left_nav_behavior")).lower() or "none"
    mode_id = _safe_text(record.get("mode_id"))
    return {
        "plugin_id": plugin_id,
        "kind": _safe_text(record.get("kind")) or "desktop_plugin",
        "marketplace_type": _safe_text(record.get("marketplace_type")) or "plugin",
        "mode_id": mode_id,
        "workspace_id": mode_id if left_nav_behavior == "workspace" else "",
        "display_name": _safe_text(record.get("display_name")) or plugin_id,
        "subtitle": _safe_text(record.get("subtitle")) or _safe_text(record.get("description")),
        "description": _safe_text(record.get("description")),
        "icon": _safe_text(record.get("icon")) or "ph-puzzle-piece",
        "categories": _string_list(record.get("categories")),
        "tags": _string_list(record.get("tags")),
        "requires": _string_list(record.get("requires")),
        "left_nav_behavior": left_nav_behavior if left_nav_behavior in _LEFT_NAV_BEHAVIORS else "none",
        "default_nav_section": _safe_text(record.get("default_nav_section")).lower() or "installed",
        "default_nav_order": _safe_int(record.get("default_nav_order"), 900),
        "surface_title": _safe_text(surface.get("title")) or _safe_text(record.get("display_name")) or plugin_id,
        "surface_mode": _safe_text(surface.get("surface_mode")) or "immersive",
        "surface_url": _build_surface_url(plugin_id, entry_html) if plugin_id and entry_html else "",
        "installed": True,
        "enabled": bool(record.get("enabled", True)),
        "version": _safe_text(record.get("version")) or "0.0.0",
        "publisher_id": _safe_text(record.get("publisher_id")),
        "publisher_name": _safe_text(record.get("publisher_name")),
        "api_namespace": _safe_text(record.get("api_namespace")),
        "capabilities": _string_list(record.get("capabilities")),
        "installed_at": _safe_text(record.get("installed_at")),
        "updated_at": _safe_text(record.get("updated_at")),
        "source": record.get("source") if isinstance(record.get("source"), dict) else {},
    }


def list_installed_plugins(config: AppConfig, *, include_disabled: bool = True) -> list[dict[str, Any]]:
    payload = _load_installed_registry(config)
    out: list[dict[str, Any]] = []
    for raw in payload.get("plugins") or []:
        if not isinstance(raw, dict):
            continue
        row = _normalize_installed_record(raw)
        if not row["plugin_id"]:
            continue
        if not include_disabled and not row["enabled"]:
            continue
        if not _installed_plugin_dir(config, row["plugin_id"]).exists():
            continue
        out.append(row)
    return out


def get_installed_plugin(config: AppConfig, plugin_id: str) -> dict[str, Any] | None:
    for row in list_installed_plugins(config, include_disabled=True):
        if row["plugin_id"] == plugin_id:
            return row
    return None


def is_plugin_enabled(config: AppConfig, plugin_id: str) -> bool:
    row = get_installed_plugin(config, plugin_id)
    return bool(row and row.get("enabled"))


def _copy_plugin_tree(source_dir: Path, destination_dir: Path) -> None:
    if destination_dir.exists():
        shutil.rmtree(destination_dir)
    destination_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, destination_dir)


def _manifest_with_runtime_hash(manifest: DesktopPluginManifest, actual_sha256: str) -> dict[str, Any]:
    payload = dict(manifest.raw)
    payload["plugin_id"] = manifest.plugin_id
    payload["display_name"] = manifest.display_name
    payload["marketplace_type"] = manifest.marketplace_type
    payload["categories"] = list(manifest.categories)
    payload["tags"] = list(manifest.tags)
    payload["requires"] = list(manifest.requires)
    payload["left_nav_behavior"] = manifest.left_nav_behavior
    payload["default_nav_section"] = manifest.default_nav_section
    payload["default_nav_order"] = manifest.default_nav_order
    payload["sha256"] = actual_sha256
    if not payload.get("signature"):
        payload["signature"] = manifest.signature or "bundled"
    return payload


def _build_installed_record(
    manifest: DesktopPluginManifest,
    *,
    actual_sha256: str,
    source: dict[str, Any],
    enabled: bool = True,
    installed_at: str | None = None,
) -> dict[str, Any]:
    now = installed_at or _utc_now_iso()
    return {
        "plugin_id": manifest.plugin_id,
        "display_name": manifest.display_name,
        "description": manifest.description,
        "subtitle": manifest.subtitle,
        "version": manifest.version,
        "publisher_id": manifest.publisher_id,
        "publisher_name": manifest.publisher_name,
        "kind": manifest.kind,
        "marketplace_type": manifest.marketplace_type,
        "mode_id": manifest.mode_id,
        "icon": manifest.icon,
        "api_namespace": manifest.api_namespace,
        "capabilities": list(manifest.capabilities),
        "categories": list(manifest.categories),
        "tags": list(manifest.tags),
        "requires": list(manifest.requires),
        "left_nav_behavior": manifest.left_nav_behavior,
        "default_nav_section": manifest.default_nav_section,
        "default_nav_order": manifest.default_nav_order,
        "sha256": actual_sha256,
        "signature": manifest.signature or "bundled",
        "entrypoint": manifest.entrypoint,
        "surface": {
            "entry_html": manifest.surface_entry_html,
            "title": manifest.surface_title,
            "surface_mode": manifest.surface_mode,
        },
        "installed": True,
        "enabled": enabled,
        "installed_at": now,
        "updated_at": _utc_now_iso(),
        "source": source,
    }


def _install_manifest_requirements(
    config: AppConfig,
    manifest: DesktopPluginManifest,
    *,
    dependency_installer: Callable[[str, set[str]], dict[str, Any]] | None = None,
    extensions_root: Path | None = None,
    visited: set[str] | None = None,
) -> None:
    seen = visited if isinstance(visited, set) else set()
    for dependency_id_raw in manifest.requires:
        dependency_id = _safe_text(dependency_id_raw)
        if not dependency_id or dependency_id in seen:
            continue
        if dependency_installer is not None:
            dependency_installer(dependency_id, seen)
            continue
        install_bundled_plugin(config, dependency_id, extensions_root=extensions_root, _visited=seen)


def install_bundled_plugin(
    config: AppConfig,
    plugin_id: str,
    *,
    extensions_root: Path | None = None,
    _visited: set[str] | None = None,
) -> dict[str, Any]:
    visited = set(_visited or set())
    if plugin_id in visited:
        existing = get_installed_plugin(config, plugin_id)
        if existing is not None:
            return existing
    visited.add(plugin_id)
    source_dir, manifest = load_bundled_desktop_plugin_manifest(plugin_id, extensions_root=extensions_root)
    _install_manifest_requirements(config, manifest, extensions_root=extensions_root, visited=visited)
    actual_sha256 = compute_plugin_bundle_sha256(source_dir, manifest.plugin_id)
    if manifest.sha256 and manifest.sha256 != actual_sha256:
        raise ValueError(f"Bundled plugin '{plugin_id}' failed checksum verification")
    destination_dir = _installed_plugin_dir(config, manifest.plugin_id)
    _copy_plugin_tree(source_dir, destination_dir)
    manifest_payload = _manifest_with_runtime_hash(manifest, actual_sha256)
    _write_json_file(destination_dir / "manifest.json", manifest_payload)
    record = _build_installed_record(
        manifest,
        actual_sha256=actual_sha256,
        source={"type": "bundled", "directory": str(source_dir)},
    )
    _replace_installed_record(config, record)
    return _normalize_installed_record(record)


def _detect_extracted_plugin_root(extract_root: Path) -> Path:
    manifest_here = extract_root / "manifest.json"
    if manifest_here.exists():
        return extract_root
    children = [child for child in extract_root.iterdir() if child.is_dir()]
    if len(children) == 1 and (children[0] / "manifest.json").exists():
        return children[0]
    raise ValueError("Bundle does not contain a plugin manifest")


def install_plugin_bundle_bytes(
    config: AppConfig,
    bundle_bytes: bytes,
    *,
    source: dict[str, Any],
    require_signature: bool = True,
    dependency_installer: Callable[[str, set[str]], dict[str, Any]] | None = None,
    extensions_root: Path | None = None,
    _visited: set[str] | None = None,
) -> dict[str, Any]:
    actual_sha256 = hashlib.sha256(bundle_bytes).hexdigest()
    plugins_root = _installed_plugins_root(config)
    plugins_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=str(plugins_root.parent)) as tmp_dir_raw:
        tmp_dir = Path(tmp_dir_raw)
        try:
            with zipfile.ZipFile(io.BytesIO(bundle_bytes)) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    rel_path = _safe_rel_path(info.filename)
                    destination = (tmp_dir / PurePosixPath(rel_path)).resolve()
                    try:
                        destination.relative_to(tmp_dir.resolve())
                    except ValueError as exc:
                        raise ValueError("Bundle contains unsafe paths") from exc
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info, "r") as src, destination.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
        except zipfile.BadZipFile as exc:
            raise ValueError("Invalid plugin bundle") from exc

        plugin_root = _detect_extracted_plugin_root(tmp_dir)
        manifest_raw = _read_json_file(plugin_root / "manifest.json", {})
        if not isinstance(manifest_raw, dict):
            raise ValueError("Plugin manifest is invalid")
        manifest = load_desktop_plugin_manifest_from_data(
            manifest_raw,
            plugin_dir=plugin_root,
            require_signature=require_signature,
        )
        if manifest.sha256 and manifest.sha256 != actual_sha256:
            raise ValueError("Plugin bundle checksum mismatch")

        visited = set(_visited or set())
        if manifest.plugin_id in visited:
            existing = get_installed_plugin(config, manifest.plugin_id)
            if existing is not None:
                return existing
        visited.add(manifest.plugin_id)
        _install_manifest_requirements(
            config,
            manifest,
            dependency_installer=dependency_installer,
            extensions_root=extensions_root,
            visited=visited,
        )

        destination_dir = _installed_plugin_dir(config, manifest.plugin_id)
        _copy_plugin_tree(plugin_root, destination_dir)
        _write_json_file(destination_dir / "manifest.json", _manifest_with_runtime_hash(manifest, actual_sha256))
        record = _build_installed_record(manifest, actual_sha256=actual_sha256, source=source)
        _replace_installed_record(config, record)
        return _normalize_installed_record(record)


def install_plugin_bundle_file(
    config: AppConfig,
    bundle_path: Path,
    *,
    source: dict[str, Any] | None = None,
    require_signature: bool = True,
    dependency_installer: Callable[[str, set[str]], dict[str, Any]] | None = None,
    extensions_root: Path | None = None,
    _visited: set[str] | None = None,
) -> dict[str, Any]:
    if not bundle_path.exists() or not bundle_path.is_file():
        raise FileNotFoundError(f"Bundle file was not found: {bundle_path}")
    return install_plugin_bundle_bytes(
        config,
        bundle_path.read_bytes(),
        source=source or {"type": "file_import", "path": str(bundle_path)},
        require_signature=require_signature,
        dependency_installer=dependency_installer,
        extensions_root=extensions_root,
        _visited=_visited,
    )


def set_installed_plugin_enabled(config: AppConfig, plugin_id: str, enabled: bool) -> dict[str, Any]:
    payload = _load_installed_registry(config)
    rows = payload.get("plugins") or []
    updated: dict[str, Any] | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _safe_text(row.get("plugin_id")) != plugin_id:
            continue
        row["enabled"] = bool(enabled)
        row["updated_at"] = _utc_now_iso()
        updated = row
        break
    if updated is None:
        raise FileNotFoundError(f"Plugin '{plugin_id}' is not installed")
    _save_installed_registry(config, [row for row in rows if isinstance(row, dict)])
    return _normalize_installed_record(updated)


def uninstall_plugin(config: AppConfig, plugin_id: str) -> bool:
    existed = _delete_installed_plugin_payload(config, plugin_id)
    if existed:
        _prune_orphan_dependency_plugins(config)
    return existed


def resolve_installed_plugin_asset(config: AppConfig, plugin_id: str, asset_path_raw: str) -> Path:
    plugin = get_installed_plugin(config, plugin_id)
    if plugin is None:
        raise FileNotFoundError(f"Plugin '{plugin_id}' is not installed")
    if not plugin.get("enabled"):
        raise PermissionError(f"Plugin '{plugin_id}' is disabled")
    rel_path = _safe_rel_path(asset_path_raw)
    root = _installed_plugin_dir(config, plugin_id).resolve()
    candidate = (root / PurePosixPath(rel_path)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("Unsafe asset path") from exc
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(f"Asset '{rel_path}' was not found")
    return candidate


def get_or_create_plugin_store_api_key(config: AppConfig) -> str:
    env_key = _safe_text(os.environ.get("THOMAS_PLUGIN_STORE_API_KEY"))
    if env_key:
        return env_key
    path = _plugin_store_identity_path(config)
    payload = _read_json_file(path, {})
    if isinstance(payload, dict):
        api_key = _safe_text(payload.get("api_key"))
        if api_key:
            return api_key
    api_key = _DEFAULT_PLUGIN_STORE_API_KEY
    _write_json_file(path, {"api_key": api_key, "created_at": _utc_now_iso()})
    return api_key


def install_plugin_from_store(
    config: AppConfig,
    *,
    plugin_id: str,
    store_url: str,
    channel: str = "stable",
    _visited: set[str] | None = None,
) -> dict[str, Any]:
    base_url = _safe_text(store_url).rstrip("/")
    if not base_url:
        raise ValueError("store_url is required")

    visited = set(_visited or set())
    if plugin_id in visited:
        existing = get_installed_plugin(config, plugin_id)
        if existing is not None:
            return existing
    visited.add(plugin_id)

    api_key = get_or_create_plugin_store_api_key(config)
    token_url = urljoin(base_url + "/", "api/v1/plugins/download-token")
    verify_url = urljoin(base_url + "/", "api/v1/plugins/verify")
    with httpx.Client(timeout=25.0, follow_redirects=True) as client:
        token_response = client.post(
            token_url,
            headers={"X-Thomas-API-Key": api_key},
            json={"plugin_id": plugin_id, "channel": _safe_text(channel) or "stable"},
        )
        token_response.raise_for_status()
        token_payload = token_response.json()
        download_url = urljoin(base_url + "/", _safe_text(token_payload.get("download_url")).lstrip("/"))
        bundle_response = client.get(download_url)
        bundle_response.raise_for_status()
        bundle_bytes = bundle_response.content
        expected_sha256 = _safe_text(token_payload.get("sha256"))
        actual_sha256 = hashlib.sha256(bundle_bytes).hexdigest()
        if expected_sha256 and expected_sha256 != actual_sha256:
            raise ValueError("Hosted plugin download checksum mismatch")
        verify_response = client.post(verify_url, json={"plugin_id": plugin_id})
        verify_response.raise_for_status()
        verify_payload = verify_response.json()
        if not bool(verify_payload.get("valid")):
            raise ValueError(_safe_text(verify_payload.get("error")) or "Hosted plugin verification failed")
    return install_plugin_bundle_bytes(
        config,
        bundle_bytes,
        source={"type": "hosted", "store_url": base_url, "channel": _safe_text(channel) or "stable"},
        require_signature=True,
        dependency_installer=lambda dependency_id, dependency_visited: install_plugin_from_store(
            config,
            plugin_id=dependency_id,
            store_url=base_url,
            channel=channel,
            _visited=dependency_visited,
        ),
        _visited=visited,
    )


def parse_plugin_install_deep_link(url_raw: str) -> dict[str, str]:
    parsed = urlparse(_safe_text(url_raw))
    if parsed.scheme.lower() != "thomas":
        raise ValueError("Deep link must use the thomas:// scheme")
    action = _safe_text(parsed.netloc or parsed.path).lstrip("/")
    if action.lower() != "install-plugin":
        raise ValueError("Unsupported Thomas deep-link action")
    query = parse_qs(parsed.query, keep_blank_values=False)
    plugin_id = _safe_text((query.get("plugin_id") or [""])[0])
    store = _safe_text((query.get("store") or [""])[0])
    channel = _safe_text((query.get("channel") or ["stable"])[0]) or "stable"
    if not plugin_id:
        raise ValueError("plugin_id is required")
    if not store:
        raise ValueError("store is required")
    return {
        "plugin_id": plugin_id,
        "store": store,
        "channel": channel,
    }


def build_plugin_install_deep_link(plugin_id: str, store: str, *, channel: str = "stable") -> str:
    plugin = quote(_safe_text(plugin_id), safe="")
    store_value = quote(_safe_text(store), safe="")
    channel_value = quote(_safe_text(channel) or "stable", safe="")
    return f"thomas://install-plugin?plugin_id={plugin}&store={store_value}&channel={channel_value}"


def create_plugin_store_api_key_file(storage_dir: Path, api_key: str | None = None) -> None:
    key_value = _safe_text(api_key) or _DEFAULT_PLUGIN_STORE_API_KEY
    payload = _read_json_file(storage_dir / "api_keys.json", {"keys": {}})
    if not isinstance(payload, dict):
        payload = {"keys": {}}
    keys = payload.get("keys")
    if not isinstance(keys, dict):
        keys = {}
    keys[key_value] = {
        "label": "Local Desktop Install Identity",
        "active": True,
        "created_at": _utc_now_iso(),
    }
    payload["keys"] = keys
    _write_json_file(storage_dir / "api_keys.json", payload)


def create_official_hosted_manifest(
    *,
    plugin_dir: Path,
    plugin_id: str,
    display_name: str,
    description: str,
    version: str,
    mode_id: str,
    icon: str,
    api_namespace: str,
    surface_entry_html: str,
    surface_title: str,
    surface_mode: str = "immersive",
    subtitle: str = "",
    capabilities: list[str] | None = None,
    marketplace_type: str = "command_center",
    categories: list[str] | None = None,
    tags: list[str] | None = None,
    requires: list[str] | None = None,
    left_nav_behavior: str = "workspace",
    default_nav_section: str = "command_centers",
    default_nav_order: int = 400,
) -> dict[str, Any]:
    bundle_bytes = build_plugin_bundle_bytes(plugin_dir, plugin_id)
    bundle_sha256 = hashlib.sha256(bundle_bytes).hexdigest()
    category_list = [item for item in (categories or []) if _safe_text(item)]
    tag_list = [item for item in (tags or []) if _safe_text(item)]
    for tag in [marketplace_type, left_nav_behavior, "official", "desktop"] + category_list:
        if _safe_text(tag) and tag not in tag_list:
            tag_list.append(tag)
    return {
        "id": plugin_id,
        "plugin_id": plugin_id,
        "title": display_name,
        "name": display_name,
        "display_name": display_name,
        "description": description,
        "subtitle": subtitle or description,
        "version": version,
        "author": "Thomas",
        "source": "Thomas Official",
        "publisher_id": "thomas-official",
        "publisher_name": "Thomas",
        "kind": "desktop_plugin",
        "marketplace_type": marketplace_type,
        "category": category_list[0] if category_list else "",
        "categories": category_list,
        "tags": tag_list,
        "requires": [item for item in (requires or []) if _safe_text(item)],
        "left_nav_behavior": left_nav_behavior,
        "default_nav_section": default_nav_section,
        "default_nav_order": int(default_nav_order),
        "section": "apps",
        "mode_id": mode_id,
        "icon": icon,
        "api_namespace": api_namespace,
        "entrypoint": "hooks.py",
        "surface": {
            "entry_html": surface_entry_html,
            "title": surface_title,
            "surface_mode": surface_mode,
        },
        "capabilities": list(capabilities or []),
        "sha256": bundle_sha256,
        "signature": f"official-{secrets.token_hex(8)}",
        "size_bytes": len(bundle_bytes),
        "verified": True,
    }
