from __future__ import annotations

import hashlib
import io
import json
import logging
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from thomas.core.config import AppConfig
from thomas.plugins.extension_catalog_runtime import EXTENSIONS_ROOT

log = logging.getLogger(__name__)

_REGISTRY_VERSION = 1
_INSTALLED_REGISTRY_RELATIVE_PATH = Path(".thomas") / "installed_marketplace_plugins.json"
_INSTALLED_PLUGINS_RELATIVE_DIR = Path(".thomas") / "plugins"
_PLUGIN_STORE_IDENTITY_RELATIVE_PATH = Path(".thomas") / "plugin_store_identity.json"
# NOT a secret: a well-known placeholder credential for the *local* dev plugin
# store only. It is shipped in source (and asserted verbatim in the test suite),
# carries no access to any real resource. Production plugin-store access refuses
# to enable unless THOMAS_PLUGIN_STORE_API_KEY is present. The
# clear-text-storage finding on the identity file is therefore a false positive
# for this constant. Real keys come from the environment and are never written here.
_DEFAULT_PLUGIN_STORE_API_KEY = "local-dev-install-key"  # noqa: S105 - non-secret local-dev placeholder
_MARKETPLACE_TYPES = {"app", "plugin", "dependency", "integration"}
# "command_center" was renamed to "app" (2026-06-11). Old manifests and
# installed registries keep working: legacy values normalize on read.
_LEGACY_MARKETPLACE_TYPE_ALIASES = {"command_center": "app"}
_LEFT_NAV_BEHAVIORS = {"none", "workspace"}
_DEFAULT_NAV_SECTIONS = {"apps", "installed"}
_LEGACY_NAV_SECTION_ALIASES = {"command_centers": "apps"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


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
        text = _safe_text(item)
        if text and text not in out:
            out.append(text)
    return out


def _safe_rel_path(path_raw: str) -> str:
    normalized = str(PurePosixPath(_safe_text(path_raw).replace("\\", "/")))
    if not normalized or normalized in {".", "/"}:
        raise ValueError("relative path is required")
    if normalized.startswith("/") or ".." in PurePosixPath(normalized).parts:
        raise ValueError("unsafe relative path")
    return normalized


def _normalize_categories(data: dict[str, Any]) -> list[str]:
    categories = _string_list(data.get("categories"))
    legacy = _safe_text(data.get("category")).lower().replace(" ", "_").replace("-", "_")
    if legacy and legacy not in categories:
        categories.insert(0, legacy)
    return categories


def _infer_marketplace_type(
    data: dict[str, Any],
    *,
    kind: str,
    mode_id: str,
    surface_entry_html: str,
) -> str:
    explicit = _safe_text(data.get("marketplace_type")).lower()
    explicit = _LEGACY_MARKETPLACE_TYPE_ALIASES.get(explicit, explicit)
    if explicit in _MARKETPLACE_TYPES:
        return explicit
    if kind == "desktop_plugin" and mode_id and surface_entry_html:
        return "app"
    return "plugin"


def _infer_left_nav_behavior(data: dict[str, Any], marketplace_type: str) -> str:
    explicit = _safe_text(data.get("left_nav_behavior")).lower()
    if explicit in _LEFT_NAV_BEHAVIORS:
        return explicit
    return "workspace" if marketplace_type == "app" else "none"


def _infer_default_nav_section(data: dict[str, Any], marketplace_type: str, left_nav_behavior: str) -> str:
    explicit = _safe_text(data.get("default_nav_section")).lower()
    explicit = _LEGACY_NAV_SECTION_ALIASES.get(explicit, explicit)
    if explicit in _DEFAULT_NAV_SECTIONS:
        return explicit
    if marketplace_type == "app" or left_nav_behavior == "workspace":
        return "apps"
    return "installed"


def _normalize_tags(
    data: dict[str, Any], *, categories: list[str], marketplace_type: str, left_nav_behavior: str
) -> list[str]:
    tags = _string_list(data.get("tags"))
    for value in categories + [marketplace_type, left_nav_behavior]:
        text = _safe_text(value)
        if text and text not in tags:
            tags.append(text)
    return tags


def _installed_registry_path(config: AppConfig) -> Path:
    return Path(config.memory.root_path) / _INSTALLED_REGISTRY_RELATIVE_PATH


def _installed_plugins_root(config: AppConfig) -> Path:
    return Path(config.memory.root_path) / _INSTALLED_PLUGINS_RELATIVE_DIR


def _plugin_store_identity_path(config: AppConfig) -> Path:
    return Path(config.memory.root_path) / _PLUGIN_STORE_IDENTITY_RELATIVE_PATH


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def _write_json_file(path: Path, payload: Any) -> None:
    _ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _iter_plugin_files(plugin_dir: Path) -> list[tuple[Path, Path]]:
    rows: list[tuple[Path, Path]] = []
    for file_path in sorted(plugin_dir.rglob("*")):
        if not file_path.is_file():
            continue
        rel_path = file_path.relative_to(plugin_dir)
        if "__pycache__" in rel_path.parts:
            continue
        if any(part.startswith(".") for part in rel_path.parts):
            continue
        if file_path.suffix.lower() in {".pyc", ".pyo"}:
            continue
        rows.append((file_path, rel_path))
    return rows


def build_plugin_bundle_bytes(plugin_dir: Path, plugin_id: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source_path, rel_path in _iter_plugin_files(plugin_dir):
            archive.write(source_path, arcname=str(PurePosixPath(plugin_id, *rel_path.parts)))
    return buffer.getvalue()


def compute_plugin_bundle_sha256(plugin_dir: Path, plugin_id: str) -> str:
    return hashlib.sha256(build_plugin_bundle_bytes(plugin_dir, plugin_id)).hexdigest()


@dataclass(frozen=True)
class DesktopPluginManifest:
    plugin_id: str
    display_name: str
    version: str
    publisher_id: str
    publisher_name: str
    kind: str
    marketplace_type: str
    description: str
    subtitle: str
    mode_id: str
    icon: str
    api_namespace: str
    capabilities: list[str]
    categories: list[str]
    tags: list[str]
    requires: list[str]
    left_nav_behavior: str
    default_nav_section: str
    default_nav_order: int
    surface_entry_html: str
    surface_title: str
    surface_mode: str
    sha256: str
    signature: str
    entrypoint: str
    raw: dict[str, Any]


def maybe_load_desktop_plugin_manifest(
    plugin_dir: Path,
    *,
    require_signature: bool = False,
) -> DesktopPluginManifest | None:
    manifest_path = plugin_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if _safe_text(data.get("kind")).lower() != "desktop_plugin":
        return None
    try:
        return load_desktop_plugin_manifest_from_data(data, plugin_dir=plugin_dir, require_signature=require_signature)
    except ValueError:
        return None


def load_desktop_plugin_manifest_from_data(
    data: dict[str, Any],
    *,
    plugin_dir: Path | None = None,
    require_signature: bool = False,
) -> DesktopPluginManifest:
    surface = data.get("surface") if isinstance(data.get("surface"), dict) else {}
    plugin_id = _safe_text(data.get("plugin_id") or data.get("id"))
    display_name = _safe_text(data.get("display_name") or data.get("name"))
    version = _safe_text(data.get("version")) or "0.0.0"
    publisher_id = _safe_text(data.get("publisher_id")) or "unknown-publisher"
    publisher_name = _safe_text(data.get("publisher_name")) or publisher_id or "Unknown Publisher"
    kind = _safe_text(data.get("kind")).lower()
    description = _safe_text(data.get("description"))
    subtitle = _safe_text(data.get("subtitle")) or description
    mode_id = _safe_text(data.get("mode_id") or data.get("mode"))
    icon = _safe_text(data.get("icon")) or "ph-puzzle-piece"
    api_namespace = _safe_text(data.get("api_namespace") or plugin_id)
    capabilities = _string_list(data.get("capabilities"))
    categories = _normalize_categories(data)
    surface_entry_html = _safe_text(surface.get("entry_html"))
    marketplace_type = _infer_marketplace_type(data, kind=kind, mode_id=mode_id, surface_entry_html=surface_entry_html)
    left_nav_behavior = _infer_left_nav_behavior(data, marketplace_type)
    default_nav_section = _infer_default_nav_section(data, marketplace_type, left_nav_behavior)
    default_nav_order = _safe_int(data.get("default_nav_order"), 400 if marketplace_type == "app" else 900)
    tags = _normalize_tags(
        data, categories=categories, marketplace_type=marketplace_type, left_nav_behavior=left_nav_behavior
    )
    requires = _string_list(data.get("requires"))
    surface_title = _safe_text(surface.get("title")) or display_name or plugin_id
    surface_mode = _safe_text(surface.get("surface_mode")) or "immersive"
    sha256 = _safe_text(data.get("sha256"))
    signature = _safe_text(data.get("signature"))
    entrypoint = _safe_text(data.get("entrypoint")) or "hooks.py"

    errors: list[str] = []
    if not plugin_id:
        errors.append("plugin_id is required")
    if not display_name:
        errors.append("display_name is required")
    if kind != "desktop_plugin":
        errors.append("kind must be desktop_plugin")
    if not description:
        errors.append("description is required")
    if not mode_id:
        errors.append("mode_id is required")
    if not capabilities:
        errors.append("capabilities must be a non-empty list")
    if not surface_entry_html:
        errors.append("surface.entry_html is required")
    if not surface_title:
        errors.append("surface.title is required")
    if not api_namespace:
        errors.append("api_namespace is required")
    if require_signature and not signature:
        errors.append("signature is required")

    if errors:
        raise ValueError("; ".join(errors))

    if plugin_dir is not None:
        _safe_rel_path(surface_entry_html)
        candidate = (plugin_dir / PurePosixPath(surface_entry_html)).resolve()
        try:
            candidate.relative_to(plugin_dir.resolve())
        except ValueError as exc:
            raise ValueError("surface.entry_html escapes plugin directory") from exc
        if not candidate.exists() or not candidate.is_file():
            raise ValueError("surface.entry_html does not exist")

    return DesktopPluginManifest(
        plugin_id=plugin_id,
        display_name=display_name,
        version=version,
        publisher_id=publisher_id,
        publisher_name=publisher_name,
        kind=kind,
        marketplace_type=marketplace_type,
        description=description,
        subtitle=subtitle,
        mode_id=mode_id,
        icon=icon,
        api_namespace=api_namespace,
        capabilities=capabilities,
        categories=categories,
        tags=tags,
        requires=requires,
        left_nav_behavior=left_nav_behavior,
        default_nav_section=default_nav_section,
        default_nav_order=default_nav_order,
        surface_entry_html=surface_entry_html,
        surface_title=surface_title,
        surface_mode=surface_mode,
        sha256=sha256,
        signature=signature,
        entrypoint=entrypoint,
        raw=dict(data),
    )


def resolve_bundled_plugin_dir(plugin_id: str, *, extensions_root: Path | None = None) -> Path | None:
    root = (extensions_root or EXTENSIONS_ROOT).resolve()
    candidate = (root / plugin_id).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_dir() else None


def load_bundled_desktop_plugin_manifest(
    plugin_id: str,
    *,
    extensions_root: Path | None = None,
) -> tuple[Path, DesktopPluginManifest]:
    plugin_dir = resolve_bundled_plugin_dir(plugin_id, extensions_root=extensions_root)
    if plugin_dir is None:
        raise FileNotFoundError(f"Plugin '{plugin_id}' was not found in extensions/")
    manifest = maybe_load_desktop_plugin_manifest(plugin_dir)
    if manifest is None:
        raise ValueError(f"Plugin '{plugin_id}' is not installable as a desktop plugin")
    return plugin_dir, manifest
