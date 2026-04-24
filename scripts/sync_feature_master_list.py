"""Generate docs/FEATURE_MASTER_LIST.md from docs/feature_master_manifest.json."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATUS_DONE = "DONE"
STATUS_PACK_FOUND = "PACK_FOUND"
STATUS_MISSING = "MISSING"

STATUS_LABELS: dict[str, str] = {
    STATUS_DONE: "DONE",
    STATUS_PACK_FOUND: "PACK FOUND",
    STATUS_MISSING: "MISSING",
}

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = "docs/feature_master_manifest.json"
DEFAULT_MASTER = "docs/FEATURE_MASTER_LIST.md"


def _normalize(rel_path: str) -> str:
    return str(rel_path).replace("\\", "/").strip()


def _dedupe_keep_order(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen = set()
    for raw in values:
        val = _normalize(raw)
        if not val or val in seen:
            continue
        seen.add(val)
        out.append(val)
    return out


def _existing_code_paths(repo_root: Path, item: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for raw in item.get("code_paths", []) or []:
        rel = _normalize(str(raw))
        if not rel:
            continue
        if (repo_root / rel).exists():
            out.append(rel)
    return _dedupe_keep_order(out)


def _existing_source_pack_matches(repo_root: Path, item: dict[str, Any]) -> list[str]:
    out: list[str] = []
    globs = list(item.get("source_pack_globs", []) or [])
    globs.extend(item.get("inbox_globs", []) or [])
    for raw in globs:
        pattern = str(raw).strip()
        if not pattern:
            continue
        try:
            matches = repo_root.glob(pattern)
        except Exception:
            continue
        for path in matches:
            if path.is_file():
                out.append(path.relative_to(repo_root).as_posix())
    return _dedupe_keep_order(out)


def evaluate_item(repo_root: Path, item: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    code_hits = _existing_code_paths(repo_root, item)
    if code_hits:
        return STATUS_DONE, code_hits, []
    source_pack_hits = _existing_source_pack_matches(repo_root, item)
    if source_pack_hits:
        return STATUS_PACK_FOUND, [], source_pack_hits
    return STATUS_MISSING, [], []


def _table_row(cols: Sequence[str]) -> str:
    return "| " + " | ".join(cols) + " |"


def _done_note(item: dict[str, Any], code_hits: list[str]) -> str:
    location = _normalize(str(item.get("location") or "")) or (code_hits[0] if code_hits else "")
    if location:
        return f"Implemented at `{location}`"
    return "Implemented in codebase."


def _missing_note(item: dict[str, Any]) -> str:
    explicit = str(item.get("missing_note") or "").strip()
    if explicit:
        return explicit
    location = _normalize(str(item.get("location") or ""))
    if location:
        return f"Needs `{location}`"
    return "Needs implementation."


def _source_pack_note(source_pack_hits: list[str]) -> str:
    if source_pack_hits:
        return f"Source pack found: `{Path(source_pack_hits[0]).name}`"
    return "Source pack detected."


def _render_foundation(repo_root: Path, items: list[dict[str, Any]]) -> tuple[list[str], dict[str, int]]:
    lines: list[str] = []
    counts = {STATUS_DONE: 0, STATUS_PACK_FOUND: 0, STATUS_MISSING: 0}
    for item in items:
        status, _, source_pack_hits = evaluate_item(repo_root, item)
        counts[status] += 1
        feature = str(item.get("name") or "").strip() or "Unknown"
        location = _normalize(str(item.get("location") or ""))
        notes = str(item.get("notes") or "").strip()
        if status == STATUS_PACK_FOUND and not notes:
            notes = _source_pack_note(source_pack_hits)
        if status == STATUS_MISSING and not notes:
            notes = _missing_note(item)
        lines.append(
            _table_row(
                [
                    f"**{feature}**",
                    STATUS_LABELS[status],
                    f"`{location}`" if location else "-",
                    notes or "-",
                ]
            )
        )
    return lines, counts


def _render_features(repo_root: Path, items: list[dict[str, Any]]) -> tuple[list[str], dict[str, int]]:
    lines: list[str] = []
    counts = {STATUS_DONE: 0, STATUS_PACK_FOUND: 0, STATUS_MISSING: 0}
    for item in sorted(items, key=lambda row: int(row.get("id", 0) or 0)):
        status, code_hits, source_pack_hits = evaluate_item(repo_root, item)
        counts[status] += 1
        num = int(item.get("id", 0) or 0)
        feature = str(item.get("name") or "").strip() or "Unknown"
        if status == STATUS_DONE:
            note = _done_note(item, code_hits)
        elif status == STATUS_PACK_FOUND:
            note = _source_pack_note(source_pack_hits)
        else:
            note = _missing_note(item)
        lines.append(_table_row([str(num), f"**{feature}**", STATUS_LABELS[status], note]))
    return lines, counts


def _render_source_packs(repo_root: Path, items: list[dict[str, Any]]) -> tuple[list[str], dict[str, int]]:
    lines: list[str] = []
    counts = {STATUS_DONE: 0, STATUS_PACK_FOUND: 0, STATUS_MISSING: 0}
    for item in items:
        status, code_hits, source_pack_hits = evaluate_item(repo_root, item)
        counts[status] += 1
        feature = str(item.get("name") or "").strip() or "Unknown"
        if status == STATUS_DONE:
            source = _done_note(item, code_hits)
        elif status == STATUS_PACK_FOUND:
            source = str(item.get("source_zip") or "").strip() or _source_pack_note(source_pack_hits)
        else:
            source = str(item.get("missing_note") or "").strip() or "No source pack and no implementation found."
        lines.append(_table_row([f"**{feature}**", STATUS_LABELS[status], source]))
    return lines, counts


def _sum_counts(parts: Iterable[dict[str, int]]) -> dict[str, int]:
    total = {STATUS_DONE: 0, STATUS_PACK_FOUND: 0, STATUS_MISSING: 0}
    for row in parts:
        for key in total:
            total[key] += int(row.get(key, 0) or 0)
    return total


def build_document(
    repo_root: Path, manifest: dict[str, Any], date_stamp: str | None = None
) -> tuple[str, dict[str, int]]:
    foundation = manifest.get("foundation")
    features = manifest.get("features")
    source_packs = manifest.get("source_packs", manifest.get("inbox_packs"))
    if not isinstance(foundation, list) or not isinstance(features, list) or not isinstance(source_packs, list):
        raise ValueError("Manifest must include list fields: foundation, features, source_packs.")

    core_lines, core_counts = _render_foundation(repo_root, foundation)
    feature_lines, feature_counts = _render_features(repo_root, features)
    source_pack_lines, source_pack_counts = _render_source_packs(repo_root, source_packs)
    totals = _sum_counts([core_counts, feature_counts, source_pack_counts])

    stamp = date_stamp or datetime.now(timezone.utc).date().isoformat()
    lines: list[str] = [
        "# Thomas Feature Master List",
        "",
        "**Status Legend:**",
        "",
        "- **DONE**: Implemented in the current codebase.",
        "- **PACK FOUND**: Source package found locally; not a public shipping claim.",
        "- **MISSING**: No implementation found in the current codebase.",
        "",
        "## Core Modules (Foundation)",
        "",
        "| Feature | Status | Location | Notes |",
        "| :--- | :--- | :--- | :--- |",
    ]
    lines.extend(core_lines)
    lines.extend(
        [
            "",
            '## The "20 Features" List',
            "",
            "| # | Feature | Status | Source / Notes |",
            "| :--- | :--- | :--- | :--- |",
        ]
    )
    lines.extend(feature_lines)
    lines.extend(
        [
            "",
            "## Candidate Feature Packs",
            "",
            "| Feature | Status | Source / Notes |",
            "| :--- | :--- | :--- |",
        ]
    )
    lines.extend(source_pack_lines)
    lines.extend(
        [
            "",
            "---",
            f"**Last Updated:** {stamp}",
            "**Source of Truth:** Generated from `docs/feature_master_manifest.json` via `python scripts/sync_feature_master_list.py`.",
            f"**Summary:** {totals[STATUS_DONE]} done, {totals[STATUS_PACK_FOUND]} source packs, {totals[STATUS_MISSING]} missing.",
            "",
        ]
    )
    return "\n".join(lines), totals


def _resolve_path(repo_root: Path, raw_path: str) -> Path:
    path = Path(str(raw_path).strip())
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync docs/FEATURE_MASTER_LIST.md with detected code and source-pack status.")
    parser.add_argument("--repo-root", default=None, help="Repository root (default: inferred from script location).")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST, help=f"Manifest path (default: {DEFAULT_MANIFEST}).")
    parser.add_argument("--master", default=DEFAULT_MASTER, help=f"Master list path (default: {DEFAULT_MASTER}).")
    parser.add_argument("--check", action="store_true", help="Check-only mode; do not write files.")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve() if args.repo_root else ROOT
    manifest_path = _resolve_path(repo_root, args.manifest)
    master_path = _resolve_path(repo_root, args.master)
    gate_name = "feature_master_sync"

    if not manifest_path.exists():
        message = f"Feature master sync failed: missing manifest {manifest_path}"
        if args.json:
            print(json.dumps({"ok": False, "gate": gate_name, "error": message}, ensure_ascii=False))
        else:
            print(message)
        return 1

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        message = f"Feature master sync failed: could not parse manifest: {exc}"
        if args.json:
            print(json.dumps({"ok": False, "gate": gate_name, "error": message}, ensure_ascii=False))
        else:
            print(message)
        return 1

    try:
        doc, totals = build_document(repo_root, manifest)
    except Exception as exc:
        message = f"Feature master sync failed: could not build document: {exc}"
        if args.json:
            print(json.dumps({"ok": False, "gate": gate_name, "error": message}, ensure_ascii=False))
        else:
            print(message)
        return 1

    current = master_path.read_text(encoding="utf-8") if master_path.exists() else ""
    changed = current != doc

    if args.check:
        if changed:
            if args.json:
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "gate": gate_name,
                            "stale": True,
                            "totals": totals,
                            "master_path": str(master_path),
                            "manifest_path": str(manifest_path),
                            "error": "docs/FEATURE_MASTER_LIST.md is stale",
                            "hint": "Run: python scripts/sync_feature_master_list.py",
                        },
                        ensure_ascii=False,
                    )
                )
            else:
                print("Feature master sync gate FAILED: docs/FEATURE_MASTER_LIST.md is stale.")
                print("Run: python scripts/sync_feature_master_list.py")
            return 1
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "gate": gate_name,
                        "stale": False,
                        "totals": totals,
                        "master_path": str(master_path),
                        "manifest_path": str(manifest_path),
                    },
                    ensure_ascii=False,
                )
            )
        else:
            print(
                "Feature master sync gate: OK "
                f"({totals[STATUS_DONE]} done, {totals[STATUS_PACK_FOUND]} source packs, {totals[STATUS_MISSING]} missing)"
            )
        return 0

    if changed:
        master_path.write_text(doc, encoding="utf-8")
        action = "updated"
    else:
        action = "already up to date"

    if args.json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "gate": gate_name,
                    "action": action,
                    "totals": totals,
                    "master_path": str(master_path),
                    "manifest_path": str(manifest_path),
                },
                ensure_ascii=False,
            )
        )
    else:
        print(
            f"Feature master list {action}: {master_path} "
            f"({totals[STATUS_DONE]} done, {totals[STATUS_PACK_FOUND]} source packs, {totals[STATUS_MISSING]} missing)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
