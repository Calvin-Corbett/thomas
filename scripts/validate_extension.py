"""Validate marketplace extensions against docs/EXTENSION_STANDARD.md.

Every marketplace item has a type, every type has a ruleset. This tool
checks them mechanically:

    python scripts/validate_extension.py --all            # whole catalog
    python scripts/validate_extension.py inkwell          # one pack
    python scripts/validate_extension.py inkwell --strict # official-grade

Default mode: structural problems are errors, standard-polish gaps are
warnings (existing inventory is grandfathered). ``--strict`` promotes
warnings to errors — required for new/official modules.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTENSIONS_ROOT = REPO_ROOT / "extensions"
MARKETPLACE_TYPES = {"app", "plugin", "dependency", "integration"}
LEGACY_TYPE_ALIASES = {"command_center": "app"}  # renamed 2026-06-11
COMMON_FIELDS = ("id", "name", "version", "description", "entrypoint")
# Newer manifest fields the legacy generated inventory predates: warn by
# default (grandfathered), error under --strict.
SOFT_FIELDS = ("kind",)


class Report:
    def __init__(self, pack_id: str) -> None:
        self.pack_id = pack_id
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def _load_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _infer_type(manifest: dict) -> str:
    declared = str(manifest.get("marketplace_type") or "").strip()
    declared = LEGACY_TYPE_ALIASES.get(declared, declared)
    if declared:
        return declared
    surface = manifest.get("surface") if isinstance(manifest.get("surface"), dict) else {}
    if str(surface.get("entry_html") or "").strip():
        return "app"
    return "plugin"


def _check_common(report: Report, pack_dir: Path, manifest: dict) -> None:
    for field in COMMON_FIELDS:
        if not str(manifest.get(field) or "").strip():
            report.error(f"manifest missing required field '{field}'")
    for field in SOFT_FIELDS:
        if not str(manifest.get(field) or "").strip():
            report.warn(f"manifest missing field '{field}'")
    declared_type = str(manifest.get("marketplace_type") or "").strip()
    if declared_type in LEGACY_TYPE_ALIASES:
        report.warn(
            f"marketplace_type '{declared_type}' is the legacy name — use '{LEGACY_TYPE_ALIASES[declared_type]}'"
        )
    mp_type = _infer_type(manifest)
    if mp_type not in MARKETPLACE_TYPES:
        report.error(f"unknown marketplace_type '{mp_type}' (must be one of {sorted(MARKETPLACE_TYPES)})")
    declared_id = str(manifest.get("id") or "").strip()
    if declared_id and declared_id != pack_dir.name:
        report.error(f"manifest id '{declared_id}' does not match directory name '{pack_dir.name}'")
    entrypoint = str(manifest.get("entrypoint") or "").strip()
    if entrypoint and not (pack_dir / entrypoint).exists():
        report.error(f"entrypoint '{entrypoint}' does not exist in the pack")
    if not manifest.get("categories") and not str(manifest.get("category") or "").strip():
        report.warn("no categories declared")
    if not manifest.get("tags"):
        report.warn("no tags declared")


def _check_app(report: Report, pack_dir: Path, manifest: dict) -> None:
    surface = manifest.get("surface") if isinstance(manifest.get("surface"), dict) else {}
    entry = str(surface.get("entry_html") or "").strip()
    if not entry:
        report.error("app modules must declare surface.entry_html")
    else:
        if ".." in entry or entry.startswith(("/", "\\")):
            report.error(f"surface.entry_html '{entry}' escapes the pack directory")
        elif not (pack_dir / entry).exists():
            report.error(f"surface.entry_html '{entry}' does not exist")
    if not str(surface.get("title") or "").strip():
        report.warn("surface.title missing")
    if str(manifest.get("left_nav_behavior") or "").strip() != "workspace":
        report.warn("app modules should use left_nav_behavior 'workspace'")
    if not str(manifest.get("default_nav_section") or "").strip():
        report.warn("default_nav_section missing")
    standalone = manifest.get("standalone")
    if not (isinstance(standalone, dict) and standalone.get("enabled")):
        report.warn(
            "standalone block missing — app modules must be openable as their own window (EXTENSION_STANDARD.md)"
        )


def _check_plugin(report: Report, pack_dir: Path, manifest: dict) -> None:
    entrypoint = str(manifest.get("entrypoint") or "").strip()
    hooks_path = pack_dir / entrypoint if entrypoint else None
    if hooks_path is not None and hooks_path.exists():
        source = hooks_path.read_text(encoding="utf-8", errors="replace")
        if "def before_tool" not in source and "def after_tool" not in source:
            report.warn("entrypoint defines neither before_tool nor after_tool — hook contract unclear")


def _check_dependency(report: Report, pack_dir: Path, manifest: dict) -> None:
    surface = manifest.get("surface") if isinstance(manifest.get("surface"), dict) else {}
    if str(surface.get("entry_html") or "").strip():
        report.warn("dependency packs should not declare a UI surface")
    if manifest.get("requires"):
        report.warn("dependency packs should not require other packs")


def _check_catalog(report: Report, manifest: dict, catalog_index: dict[str, dict]) -> None:
    pack_id = str(manifest.get("id") or "").strip()
    row = catalog_index.get(pack_id)
    if row is None:
        report.warn("no row in extensions/catalog.json")
        return
    for field in ("version", "mode"):
        manifest_value = str(manifest.get(field) or "").strip()
        catalog_value = str(row.get(field) or "").strip()
        if manifest_value and catalog_value and manifest_value != catalog_value:
            report.warn(f"catalog {field} '{catalog_value}' != manifest {field} '{manifest_value}'")


_TYPE_CHECKS = {
    "app": _check_app,
    "plugin": _check_plugin,
    "dependency": _check_dependency,
    "integration": _check_plugin,  # integrations carry the same hook contract today
}


def validate_pack(pack_dir: Path, catalog_index: dict[str, dict]) -> Report:
    report = Report(pack_dir.name)
    manifest = _load_json(pack_dir / "manifest.json")
    if manifest is None:
        report.error("manifest.json missing or not valid JSON")
        return report
    _check_common(report, pack_dir, manifest)
    checker = _TYPE_CHECKS.get(_infer_type(manifest))
    if checker is not None:
        checker(report, pack_dir, manifest)
    _check_catalog(report, manifest, catalog_index)
    return report


def _catalog_index() -> dict[str, dict]:
    catalog = _load_json(EXTENSIONS_ROOT / "catalog.json") or {}
    packs = catalog.get("packs")
    if not isinstance(packs, list):
        return {}
    return {str(row.get("id") or ""): row for row in packs if isinstance(row, dict)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate extensions against the Thomas Extension Standard")
    parser.add_argument("plugin_id", nargs="?", default="", help="Pack id to validate (omit with --all)")
    parser.add_argument("--all", action="store_true", help="Validate every pack in extensions/")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as errors (official-grade)")
    args = parser.parse_args(argv)

    if not args.all and not args.plugin_id:
        parser.error("pass a plugin id or --all")

    if args.all:
        pack_dirs = sorted(p for p in EXTENSIONS_ROOT.iterdir() if p.is_dir() and (p / "manifest.json").exists())
    else:
        pack_dir = EXTENSIONS_ROOT / args.plugin_id
        if not pack_dir.is_dir():
            print(f"FAIL: no pack at extensions/{args.plugin_id}")
            return 2
        pack_dirs = [pack_dir]

    catalog_index = _catalog_index()
    failed = 0
    warned = 0
    for pack_dir in pack_dirs:
        report = validate_pack(pack_dir, catalog_index)
        problems = report.errors + (report.warnings if args.strict else [])
        if problems:
            failed += 1
            print(f"FAIL {report.pack_id}")
            for message in report.errors:
                print(f"  error: {message}")
            for message in report.warnings:
                level = "error" if args.strict else "warn"
                print(f"  {level}: {message}")
        elif report.warnings:
            warned += 1
            print(f"WARN {report.pack_id}")
            for message in report.warnings:
                print(f"  warn: {message}")

    total = len(pack_dirs)
    print(f"\nValidated {total} pack(s): {failed} failed, {warned} with warnings, {total - failed - warned} clean")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
