"""Gate major-module changes behind audit-log + changelog updates."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Sequence, Set

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from thomas.observability.module_audit import (
    MAJOR_MODULES,
    load_registry,
    normalize_path,
    sha256_file,
    touched_modules,
)


ROOT = Path(__file__).resolve().parent.parent
ROOT_DIRNAME = ROOT.name
REQUIRED_CHANGED = {"CHANGELOG.md", "docs/ops/module_audit_log.json"}
READY_STATUSES = {"pass", "warn", "fail"}


def _normalize_path(path: str) -> str:
    p = normalize_path(path)
    prefix = ROOT_DIRNAME + "/"
    if p.startswith(prefix):
        p = p[len(prefix):]
    return p


def _git_changed_files(base: str | None, head: str | None) -> List[str]:
    if head is None:
        head = "HEAD"
    if base and base.strip("0"):
        range_expr = f"{base}...{head}"
    else:
        range_expr = f"{head}~1...{head}"

    def _run(cmd: List[str]) -> List[str]:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if proc.returncode != 0:
            return []
        out = []
        for line in proc.stdout.splitlines():
            p = _normalize_path(line)
            if p:
                out.append(p)
        return out

    changed: Set[str] = set(_run(["git", "diff", "--name-only", range_expr]))
    if not changed:
        changed.update(_run(["git", "diff", "--name-only", head]))

    # Local + staged for developer runs.
    changed.update(_run(["git", "diff", "--name-only"]))
    changed.update(_run(["git", "diff", "--name-only", "--cached"]))
    changed.update(_run(["git", "ls-files", "--others", "--exclude-standard"]))
    return sorted(changed)


def _parse_iso_utc(raw: str) -> datetime | None:
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _age_days(raw_iso: str) -> float | None:
    dt = _parse_iso_utc(raw_iso)
    if dt is None:
        return None
    now = datetime.now(timezone.utc)
    return max(0.0, (now - dt).total_seconds() / 86400.0)


def _module_files(changed: Iterable[str], module: str) -> List[str]:
    prefix = f"thomas/{module}/"
    out = [
        _normalize_path(path)
        for path in changed
        if _normalize_path(path).startswith(prefix)
    ]
    return sorted(set(out), key=str.lower)


def _file_hash_for_gate(path: str) -> str:
    abs_path = (ROOT / path).resolve()
    if abs_path.is_file():
        return sha256_file(abs_path)
    return "deleted"


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enforce module-audit registry + changelog updates.")
    parser.add_argument("--base", default=None, help="Diff base ref/sha (optional)")
    parser.add_argument("--head", default=None, help="Diff head ref/sha (default: HEAD)")
    parser.add_argument("--max-age-days", type=float, default=30.0, help="Max allowed age for latest module audit.")
    parser.add_argument(
        "--changed-file",
        action="append",
        default=[],
        help="Explicit changed file path (repeatable). If provided, git diff is skipped.",
    )
    args = parser.parse_args(argv)

    if args.changed_file:
        changed = sorted({_normalize_path(x) for x in args.changed_file if str(x).strip()})
    else:
        changed = _git_changed_files(args.base, args.head)

    if not changed:
        print("Module audit gate: no changed files; skipping.")
        return 0

    touched = touched_modules(changed)
    touched = {m for m in touched if m in MAJOR_MODULES}
    if not touched:
        print("Module audit gate: no major-module changes detected; skipping.")
        return 0

    print("Module audit gate: major-module changes detected:")
    for m in sorted(touched):
        print(f"  - thomas/{m}/")

    changed_set = set(changed)
    missing = sorted(REQUIRED_CHANGED - changed_set)
    failed = False
    if missing:
        failed = True
        print("\nMissing required changed files:")
        for p in missing:
            print(f"  - {p}")

    registry_path = ROOT / "docs" / "ops" / "module_audit_log.json"
    registry = load_registry(registry_path)
    latest = registry.get("latest_by_module") or {}

    for module in sorted(touched):
        row = latest.get(module) if isinstance(latest, dict) else None
        if not isinstance(row, dict):
            failed = True
            print(f"\nMissing latest audit entry for module: {module}")
            continue

        auditor = str(row.get("auditor") or "").strip()
        status = str(row.get("status") or "").strip().lower()
        audited_at = str(row.get("audited_at") or "").strip()
        signature = str(row.get("signature") or "").strip()
        files_touched = {
            _normalize_path(item)
            for item in (row.get("files_touched") or [])
            if _normalize_path(item)
        }
        file_hashes = {
            _normalize_path(key): str(value or "").strip().lower()
            for key, value in dict(row.get("file_hashes") or {}).items()
            if _normalize_path(key)
        }

        if not auditor:
            failed = True
            print(f"\nInvalid audit entry for module={module}: missing auditor")
        if status not in READY_STATUSES:
            failed = True
            print(
                f"\nInvalid audit entry for module={module}: "
                f"status='{status}' is not one of {sorted(READY_STATUSES)}"
            )
        if not signature:
            failed = True
            print(f"\nInvalid audit entry for module={module}: missing signature")
        age = _age_days(audited_at)
        if age is None:
            failed = True
            print(f"\nInvalid audit entry for module={module}: bad audited_at='{audited_at}'")
        elif age > float(args.max_age_days):
            failed = True
            print(
                f"\nStale audit entry for module={module}: "
                f"age_days={age:.1f} > max_age_days={float(args.max_age_days):.1f}"
            )

        changed_module_files = _module_files(changed_set, module)
        missing_coverage = [path for path in changed_module_files if path not in files_touched]
        if missing_coverage:
            failed = True
            print(f"\nAudit entry for module={module} does not cover changed file(s):")
            for path in missing_coverage:
                print(f"  - {path}")

        for path in changed_module_files:
            expected_hash = str(file_hashes.get(path) or "").strip().lower()
            if not expected_hash:
                failed = True
                print(
                    f"\nAudit entry for module={module} missing file hash for changed file: {path}"
                )
                continue
            actual_hash = _file_hash_for_gate(path)
            if expected_hash != actual_hash:
                failed = True
                print(
                    f"\nAudit entry for module={module} has stale hash for {path}: "
                    f"expected {expected_hash}, actual {actual_hash}"
                )

    if failed:
        return 1
    print("Module audit gate: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

