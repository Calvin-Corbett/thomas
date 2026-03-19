"""Runtime loader + validator for extension pack catalogs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXTENSIONS_ROOT = ROOT / "extensions"
CATALOG_PATH = EXTENSIONS_ROOT / "catalog.json"


@dataclass(frozen=True)
class ExtensionPackStatus:
    pack_id: str
    directory: str
    valid: bool
    errors: list[str]
    capabilities: list[str]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _validate_manifest(manifest: dict[str, Any], expected_id: str) -> list[str]:
    errors: list[str] = []
    for key in ("id", "name", "version", "entrypoint", "capabilities"):
        if key not in manifest:
            errors.append(f"missing manifest key: {key}")
    if str(manifest.get("id") or "").strip() != expected_id:
        errors.append("manifest id mismatch")
    caps = manifest.get("capabilities")
    if not isinstance(caps, list) or not caps:
        errors.append("capabilities must be a non-empty list")
    return errors


def load_extension_catalog(root: Path | None = None) -> dict[str, Any]:
    extensions_root = (root if root is not None else EXTENSIONS_ROOT).resolve()
    catalog_path = extensions_root / "catalog.json"
    if not catalog_path.exists():
        raise FileNotFoundError(f"missing extension catalog: {catalog_path}")
    catalog = _read_json(catalog_path)
    packs = catalog.get("packs")
    if not isinstance(packs, list):
        raise ValueError("catalog.packs must be a list")
    return {
        "root": str(extensions_root),
        "catalog_path": str(catalog_path),
        "packs": packs,
    }


def validate_extension_catalog(root: Path | None = None) -> dict[str, Any]:
    loaded = load_extension_catalog(root=root)
    extensions_root = Path(str(loaded["root"]))
    rows: list[ExtensionPackStatus] = []
    seen: set[str] = set()

    for item in loaded["packs"]:
        if not isinstance(item, dict):
            continue
        pack_id = str(item.get("id") or "").strip()
        if not pack_id:
            continue
        if pack_id in seen:
            rows.append(
                ExtensionPackStatus(
                    pack_id=pack_id,
                    directory="",
                    valid=False,
                    errors=["duplicate pack id in catalog"],
                    capabilities=[],
                )
            )
            continue
        seen.add(pack_id)

        pack_dir = extensions_root / pack_id
        manifest_path = pack_dir / "manifest.json"
        hooks_path = pack_dir / "hooks.py"
        readme_path = pack_dir / "README.md"
        errors: list[str] = []

        if not pack_dir.exists() or not pack_dir.is_dir():
            errors.append("pack directory missing")
        if not manifest_path.exists():
            errors.append("manifest.json missing")
            manifest: dict[str, Any] = {}
        else:
            manifest = _read_json(manifest_path)
            errors.extend(_validate_manifest(manifest, expected_id=pack_id))
        if not hooks_path.exists():
            errors.append("hooks.py missing")
        if not readme_path.exists():
            errors.append("README.md missing")

        caps = manifest.get("capabilities")
        capabilities = [str(x) for x in caps if isinstance(x, str)] if isinstance(caps, list) else []
        rows.append(
            ExtensionPackStatus(
                pack_id=pack_id,
                directory=str(pack_dir),
                valid=len(errors) == 0,
                errors=errors,
                capabilities=capabilities,
            )
        )

    total = len(rows)
    valid = sum(1 for row in rows if row.valid)
    invalid = max(0, total - valid)
    return {
        "root": str(extensions_root),
        "total": total,
        "valid": valid,
        "invalid": invalid,
        "packs": [
            {
                "id": row.pack_id,
                "directory": row.directory,
                "valid": row.valid,
                "errors": row.errors,
                "capabilities": row.capabilities,
            }
            for row in rows
        ],
    }
