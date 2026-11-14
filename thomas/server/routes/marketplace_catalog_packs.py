"""Extension packs: normalizing catalog entries and reading them off disk.

Phase 3.5 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md).

The third layer of the four (see ``marketplace_catalog_fields``). A pack in
``extensions/catalog.json`` becomes a marketplace row here, and the pack's
directory is resolved, walked and zipped here.

**This is where the marketplace reads the catalog through the kernel.**
``_load_marketplace_catalog`` resolves the ``extension_catalog`` service and
calls ``load()`` on whatever provider is mounted, instead of importing
``load_extension_catalog`` and calling it. Mount a different provider and
``/api/marketplace/plugins`` answers from it on the next request, with no restart
and no edit here — which is the whole point of the service. The default provider
(``ExtensionCatalog`` in ``thomas/server/plugin_system_providers.py``) calls
exactly the function this module used to call, so nothing changes while it is the
one mounted.

The import of the kernel is deferred into the function for the same reason the
providers defer theirs: a module that only wants to normalize a row should not
drag the kernel in at import time. ``thomas/server/desktop_plugins.py`` defers
its resolve the same way.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from thomas.server.routes.marketplace_catalog_fields import (
    _DEFAULT_NAV_SECTIONS,
    _LEFT_NAV_BEHAVIORS,
    _LEGACY_MARKETPLACE_TYPE_ALIASES,
    _LEGACY_NAV_SECTION_ALIASES,
    _MARKETPLACE_TYPES,
    _TYPE_LABELS,
    _download_filename,
    _download_url,
    _is_retired_local_module_row,
    _safe_int,
    _safe_string,
    _slug_label,
    _slugify,
    _string_list,
)


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
    """The catalog, its root, and one normalized row per installable pack.

    The catalog comes from the mounted ``extension_catalog`` provider, so a
    provider swapped in while Thomas runs is answering this the next time a
    marketplace request arrives.
    """
    from thomas.server.plugin_systems_kernel import extension_catalog

    catalog = extension_catalog().load()
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
