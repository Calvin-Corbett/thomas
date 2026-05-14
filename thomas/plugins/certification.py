"""Extension certification and plugin update planning helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from collections.abc import Iterable, Mapping

from thomas.plugins.extension_catalog_runtime import load_extension_catalog, validate_extension_catalog
from thomas.plugins.p104_plugin_update_planner import plan_plugin_updates

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REQUIRED_CAPABILITIES = ("healthcheck",)


def _normalize_required_capabilities(raw: Iterable[str] | None) -> list[str]:
    items = list(raw or [])
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        cap = str(item or "").strip()
        if not cap or cap in seen:
            continue
        seen.add(cap)
        out.append(cap)
    return out


def _catalog_map_by_id(catalog: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    rows = catalog.get("packs")
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        pack_id = str(row.get("id") or "").strip()
        if not pack_id:
            continue
        out[pack_id] = dict(row)
    return out


def _infer_version_from_plugin_path(plugin_path: str) -> str:
    text = str(plugin_path or "").strip()
    if not text:
        return ""
    path = Path(text).expanduser()
    manifest_path = path / "manifest.json" if path.is_dir() else path
    if not manifest_path.exists() or manifest_path.is_dir():
        return ""
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("version") or "").strip()


def _build_available_versions(catalog: Mapping[str, Any]) -> dict[str, dict[str, list[str]]]:
    rows = catalog.get("packs")
    out: dict[str, dict[str, list[str]]] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        pack_id = str(row.get("id") or "").strip()
        version = str(row.get("version") or "").strip()
        if not pack_id or not version:
            continue
        bucket = out.setdefault(pack_id, {"versions": []})
        versions = bucket["versions"]
        if version not in versions:
            versions.append(version)
    return out


def certify_extension_catalog(
    root: Path | None = None,
    *,
    required_capabilities: Iterable[str] | None = None,
    min_pass_rate: float = 0.95,
) -> dict[str, Any]:
    required = _normalize_required_capabilities(required_capabilities)
    if not required:
        required = list(DEFAULT_REQUIRED_CAPABILITIES)

    threshold = float(min_pass_rate)
    if threshold < 0.0:
        threshold = 0.0
    if threshold > 1.0:
        threshold = 1.0

    loaded = load_extension_catalog(root=root)
    validated = validate_extension_catalog(root=root)
    meta_by_id = _catalog_map_by_id(loaded)

    evaluated = []
    uncertified = []
    categories: set[str] = set()
    targets: set[str] = set()
    modes: set[str] = set()
    certified_count = 0

    for row in validated.get("packs") if isinstance(validated.get("packs"), list) else []:
        if not isinstance(row, dict):
            continue
        pack_id = str(row.get("id") or "").strip()
        caps_raw = row.get("capabilities")
        capabilities = [str(x) for x in caps_raw if isinstance(x, str)] if isinstance(caps_raw, list) else []
        meta = meta_by_id.get(pack_id, {})
        category = str(meta.get("category") or "").strip()
        target = str(meta.get("target") or "").strip()
        mode = str(meta.get("mode") or "").strip()
        if category:
            categories.add(category)
        if target:
            targets.add(target)
        if mode:
            modes.add(mode)

        missing_capabilities = [cap for cap in required if cap not in capabilities]
        valid = bool(row.get("valid", False))
        errors = list(row.get("errors") or [])
        certified = bool(valid and not missing_capabilities)
        reasons: list[str] = []
        reasons.extend(str(item) for item in errors if str(item).strip())
        for cap in missing_capabilities:
            reasons.append(f"missing required capability: {cap}")

        evaluated_row = {
            "id": pack_id,
            "version": str(meta.get("version") or ""),
            "category": category,
            "target": target,
            "mode": mode,
            "certified": certified,
            "valid": valid,
            "missing_capabilities": missing_capabilities,
            "reasons": reasons,
        }
        evaluated.append(evaluated_row)
        if certified:
            certified_count += 1
        else:
            uncertified.append(evaluated_row)

    total = len(evaluated)
    pass_rate = (float(certified_count) / float(total)) if total else 1.0
    ok = bool(pass_rate >= threshold and int(validated.get("invalid") or 0) == 0)

    return {
        "ok": ok,
        "root": str(loaded.get("root") or ""),
        "catalog_path": str(loaded.get("catalog_path") or ""),
        "required_capabilities": required,
        "min_pass_rate": threshold,
        "summary": {
            "total": total,
            "certified": certified_count,
            "uncertified": max(0, total - certified_count),
            "catalog_invalid": int(validated.get("invalid") or 0),
            "pass_rate": round(pass_rate, 6),
        },
        "coverage": {
            "categories": sorted(categories),
            "targets": sorted(targets),
            "modes": sorted(modes),
        },
        "uncertified": uncertified,
        "certified_sample": evaluated[:25],
    }


def build_plugin_update_plan_from_state(
    installed_plugins: Iterable[Mapping[str, Any]],
    *,
    catalog_root: Path | None = None,
    include_prereleases: bool = False,
) -> dict[str, Any]:
    loaded = load_extension_catalog(root=catalog_root)
    available = _build_available_versions(loaded)

    installed: list[dict[str, Any]] = []
    for row in installed_plugins:
        name = str(row.get("name") or row.get("id") or "").strip()
        if not name:
            continue
        version = str(row.get("version") or "").strip()
        if not version:
            version = _infer_version_from_plugin_path(str(row.get("path") or ""))
        if not version:
            version = "0.0.0"
        installed.append(
            {
                "id": name,
                "version": version,
                "pinned": bool(row.get("pinned", False)),
                "source": str(row.get("path") or "").strip() or None,
            }
        )

    if not installed:
        return {
            "ok": True,
            "summary": {"total": 0, "update": 0, "up_to_date": 0, "unknown": 0},
            "actions": [],
            "catalog_root": str(loaded.get("root") or ""),
            "note": "No installed plugin manifests were found in local state.",
        }

    result = plan_plugin_updates(
        {
            "installed": installed,
            "available": available,
            "include_prereleases": bool(include_prereleases),
        }
    )
    payload = dict(result)
    payload["catalog_root"] = str(loaded.get("root") or "")
    return payload
