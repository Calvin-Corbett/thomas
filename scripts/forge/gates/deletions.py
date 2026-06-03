#!/usr/bin/env python3
"""Enforce deletion/rename records for protected repo paths."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DELETION_RECORD_DIR = ROOT / "docs" / "deletions"
PROTECTED_PREFIXES = ("thomas/", "tests/")


def _runtime_protection_disabled() -> bool:
    """B9 (praxis-unbypassable-2026-05-29): only a validly SIGNED disable flag
    counts. Presence alone is not enough — an unsigned planted flag must not
    disable this gate. Mirrors thomas.tools.filesystem signed-flag validation."""
    try:
        from scripts.forge.gates._runtime_guard import runtime_protection_disabled
    except ImportError:  # pragma: no cover - import path varies by run context
        try:
            from forge.gates._runtime_guard import runtime_protection_disabled
        except ImportError:
            from _runtime_guard import runtime_protection_disabled
    return runtime_protection_disabled(ROOT)


def _normalize(path: str) -> str:
    return str(path or "").strip().replace("\\", "/")


def _git_diff_name_status(repo_root: Path, *, base: str, head: str) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-status", f"{base}...{head}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git diff --name-status failed")
    return [line.rstrip("\n") for line in proc.stdout.splitlines() if line.strip()]


def _git_staged_name_status(repo_root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-status"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git diff --cached --name-status failed")
    return [line.rstrip("\n") for line in proc.stdout.splitlines() if line.strip()]


def _deleted_or_renamed_paths(name_status_lines: list[str]) -> list[str]:
    out: list[str] = []
    for raw in name_status_lines:
        parts = raw.split("\t")
        if not parts:
            continue
        status = parts[0].strip().upper()
        if status.startswith("D"):
            if len(parts) >= 2:
                out.append(_normalize(parts[1]))
            continue
        if status.startswith("R") and len(parts) >= 2:
            # Rename records are still a protected action requiring explicit record.
            out.append(_normalize(parts[1]))
    return sorted(set(p for p in out if p))


def _load_deletion_records(record_dir: Path) -> tuple[set[str], list[str]]:
    approved_paths: set[str] = set()
    errors: list[str] = []

    if not record_dir.exists():
        return approved_paths, errors

    for path in sorted(record_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - defensive parse handling
            errors.append(f"{path.as_posix()}: invalid json ({exc})")
            continue

        if not isinstance(payload, dict):
            errors.append(f"{path.as_posix()}: record must be a JSON object")
            continue

        approved = bool(payload.get("approved_by_human", False))
        if not approved:
            continue

        reason = str(payload.get("reason", "")).strip()
        if not reason:
            errors.append(f"{path.as_posix()}: approved record missing non-empty `reason`")
            continue

        verification = payload.get("verification")
        if not isinstance(verification, list) or not [str(v).strip() for v in verification if str(v).strip()]:
            errors.append(f"{path.as_posix()}: approved record must include non-empty `verification` list")
            continue

        files = payload.get("files")
        if not isinstance(files, list):
            errors.append(f"{path.as_posix()}: `files` must be a list")
            continue

        for item in files:
            normalized = _normalize(str(item or ""))
            if normalized:
                approved_paths.add(normalized)

    return approved_paths, errors


def run(argv: list[str] | None = None) -> int:
    if _runtime_protection_disabled():
        print("Deletion guard: PASS (runtime protection disabled by human)")
        return 0

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(ROOT), help="Repository root path.")
    parser.add_argument("--base", default="", help="Git base ref for range diff.")
    parser.add_argument("--head", default="HEAD", help="Git head ref for range diff.")
    parser.add_argument(
        "--staged-only",
        action="store_true",
        help="Use staged changes instead of a git base/head range.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    try:
        if args.staged_only:
            lines = _git_staged_name_status(repo_root)
        else:
            base = str(args.base or "").strip()
            if not base:
                raise ValueError("`--base` is required unless --staged-only is used.")
            lines = _git_diff_name_status(repo_root, base=base, head=str(args.head or "HEAD").strip() or "HEAD")
    except Exception as exc:
        payload = {"ok": False, "error": str(exc)}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"Deletion guard: FAIL ({exc})")
        return 1

    affected = _deleted_or_renamed_paths(lines)
    protected = [p for p in affected if any(p.startswith(prefix) for prefix in PROTECTED_PREFIXES)]
    approved_paths, record_errors = _load_deletion_records(repo_root / "docs" / "deletions")

    violations = [p for p in protected if p not in approved_paths]
    ok = not violations and not record_errors

    payload: dict[str, Any] = {
        "ok": ok,
        "deleted_or_renamed_paths": affected,
        "protected_paths": protected,
        "approved_paths_count": len(approved_paths),
        "violations": violations,
        "record_errors": record_errors,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if ok:
            print("Deletion guard: PASS")
            print(f"- protected deletions/renames requiring records: {len(protected)}")
        else:
            print("Deletion guard: FAIL")
            for err in record_errors:
                print(f"- record error: {err}")
            for path in violations:
                print(f"- missing deletion record for protected path: {path}")
            print("- required: docs/deletions/*.json with `approved_by_human: true` and `files` entries")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
