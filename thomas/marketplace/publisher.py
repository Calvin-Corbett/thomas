from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from thomas.plugins.extension_catalog_runtime import load_extension_catalog, validate_extension_catalog
from thomas.server.desktop_plugins_manifest import build_plugin_bundle_bytes, maybe_load_desktop_plugin_manifest
from thomas.server.desktop_plugins_runtime import create_official_hosted_manifest

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXTENSIONS_ROOT = ROOT / "extensions"
DEFAULT_HOSTED_STORE_ROOT = ROOT / "thomas" / "server" / "plugins_registry" / "plugins"


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_family_tokens(value: Any) -> list[str]:
    if isinstance(value, list):
        tokens = value
    elif value is None:
        tokens = []
    else:
        tokens = [value]
    out: list[str] = []
    for item in tokens:
        text = _safe_text(item).lower()
        if text and text not in out:
            out.append(text)
    return out


def _catalog_by_id(extensions_root: Path) -> dict[str, dict[str, Any]]:
    loaded = load_extension_catalog(root=extensions_root)
    out: dict[str, dict[str, Any]] = {}
    for row in loaded.get("packs") or []:
        if not isinstance(row, dict):
            continue
        plugin_id = _safe_text(row.get("id"))
        if plugin_id:
            out[plugin_id] = dict(row)
    return out


def _validation_by_id(extensions_root: Path) -> dict[str, dict[str, Any]]:
    payload = validate_extension_catalog(root=extensions_root)
    out: dict[str, dict[str, Any]] = {}
    for row in payload.get("packs") or []:
        if not isinstance(row, dict):
            continue
        plugin_id = _safe_text(row.get("id"))
        if plugin_id:
            out[plugin_id] = dict(row)
    return out


def _family_matches(row: dict[str, Any], family: str) -> bool:
    token = _safe_text(family).lower()
    if not token:
        return False
    tokens = {
        _safe_text(row.get("id")).lower(),
        _safe_text(row.get("category")).lower(),
        _safe_text(row.get("target")).lower(),
        _safe_text(row.get("mode")).lower(),
        _safe_text(row.get("marketplace_type")).lower(),
    }
    tokens.update(_normalize_family_tokens(row.get("categories")))
    tokens.update(_normalize_family_tokens(row.get("tags")))
    return token in {item for item in tokens if item}


def select_extension_pack_ids(
    *,
    extensions_root: Path = DEFAULT_EXTENSIONS_ROOT,
    plugin_ids: list[str] | None = None,
    families: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    catalog = _catalog_by_id(extensions_root)
    selected: list[str] = []
    skipped: list[str] = []
    for plugin_id in plugin_ids or []:
        normalized = _safe_text(plugin_id)
        if not normalized:
            continue
        if normalized in catalog and normalized not in selected:
            selected.append(normalized)
        elif normalized not in skipped:
            skipped.append(normalized)
    for family in families or []:
        normalized_family = _safe_text(family)
        if not normalized_family:
            continue
        matched = False
        for plugin_id, row in catalog.items():
            if _family_matches(row, normalized_family) and plugin_id not in selected:
                selected.append(plugin_id)
                matched = True
        if not matched and normalized_family not in skipped:
            skipped.append(normalized_family)
    return selected, skipped


def publish_marketplace_wave(
    *,
    extensions_root: Path = DEFAULT_EXTENSIONS_ROOT,
    hosted_store_root: Path = DEFAULT_HOSTED_STORE_ROOT,
    plugin_ids: list[str] | None = None,
    families: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    selected_ids, unmatched_selectors = select_extension_pack_ids(
        extensions_root=extensions_root,
        plugin_ids=plugin_ids,
        families=families,
    )
    catalog = _catalog_by_id(extensions_root)
    validation = _validation_by_id(extensions_root)
    report: dict[str, Any] = {
        "ok": True,
        "dry_run": bool(dry_run),
        "extensions_root": str(extensions_root),
        "hosted_store_root": str(hosted_store_root),
        "published": [],
        "skipped": [],
        "errors": [],
    }

    for selector in unmatched_selectors:
        report["errors"].append(
            {
                "selector": selector,
                "reason": "selection_not_found",
            }
        )

    for plugin_id in selected_ids:
        catalog_row = catalog.get(plugin_id) or {}
        validation_row = validation.get(plugin_id) or {}
        plugin_dir = (extensions_root / plugin_id).resolve()
        output_dir = hosted_store_root / plugin_id
        entry: dict[str, Any] = {
            "plugin_id": plugin_id,
            "version": _safe_text(catalog_row.get("version")) or "0.0.0",
            "output_dir": str(output_dir),
        }
        if not bool(validation_row.get("valid")):
            report["skipped"].append(
                {
                    **entry,
                    "reason": "certification_failed",
                    "details": list(validation_row.get("errors") or []),
                }
            )
            continue
        manifest = maybe_load_desktop_plugin_manifest(plugin_dir, require_signature=False)
        if manifest is None:
            report["skipped"].append(
                {
                    **entry,
                    "reason": "desktop_plugin_manifest_required",
                    "details": [
                        "Pack is valid inventory but does not expose a desktop_plugin manifest with a real surface.",
                    ],
                }
            )
            continue

        bundle_bytes = build_plugin_bundle_bytes(plugin_dir, plugin_id)
        hosted_manifest = create_official_hosted_manifest(
            plugin_dir=plugin_dir,
            plugin_id=manifest.plugin_id,
            display_name=manifest.display_name,
            description=manifest.description,
            version=manifest.version,
            mode_id=manifest.mode_id,
            icon=manifest.icon,
            api_namespace=manifest.api_namespace,
            surface_entry_html=manifest.surface_entry_html,
            surface_title=manifest.surface_title,
            surface_mode=manifest.surface_mode,
            subtitle=manifest.subtitle,
            capabilities=list(manifest.capabilities),
            marketplace_type=manifest.marketplace_type,
            categories=list(manifest.categories),
            tags=list(manifest.tags),
            requires=list(manifest.requires),
            left_nav_behavior=manifest.left_nav_behavior,
            default_nav_section=manifest.default_nav_section,
            default_nav_order=manifest.default_nav_order,
        )
        published_row = {
            **entry,
            "sha256": _safe_text(hosted_manifest.get("sha256")),
            "marketplace_type": _safe_text(hosted_manifest.get("marketplace_type")),
            "requires": list(hosted_manifest.get("requires") or []),
            "bundle_size_bytes": len(bundle_bytes),
            "dry_run": bool(dry_run),
        }
        if not dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "bundle.zip").write_bytes(bundle_bytes)
            (output_dir / "manifest.json").write_text(
                json.dumps(hosted_manifest, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        report["published"].append(published_row)

    report["ok"] = not bool(report["errors"])
    return report
