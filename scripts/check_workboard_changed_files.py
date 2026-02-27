#!/usr/bin/env python3
"""Require changed files to stay within active WORKBOARD claim scopes."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

try:
    from scripts import check_workboard_claims as claims_gate
except Exception:  # pragma: no cover
    import check_workboard_claims as claims_gate  # type: ignore


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"
DEFAULT_IGNORE_PATTERNS = ("plans/thomas/WORKBOARD.md",)
DEFAULT_MAX_CHANGED_FILES = 200
DEFAULT_BULK_ALLOW_ENV = "THOMAS_ALLOW_BULK_CHANGED_FILES"


def _normalize_path(value: str) -> str:
    path = str(value or "").strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    while "//" in path:
        path = path.replace("//", "/")
    return path.strip("/")


def _scope_matches_path(scope: str, rel_path: str) -> bool:
    scope_norm = _normalize_path(scope).lower()
    path_norm = _normalize_path(rel_path).lower()
    if not scope_norm or not path_norm:
        return False
    if scope_norm in {".", "*", "**"}:
        return True
    if any(ch in scope_norm for ch in "*?["):
        if fnmatch.fnmatchcase(path_norm, scope_norm):
            return True
        if scope_norm.endswith("/**"):
            base = scope_norm[:-3].rstrip("/")
            return bool(base) and (path_norm == base or path_norm.startswith(base + "/"))
        return False
    return path_norm == scope_norm or path_norm.startswith(scope_norm + "/")


def _run_git(args: Sequence[str]) -> list[str] | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    rows: list[str] = []
    for raw in str(proc.stdout or "").splitlines():
        token = _normalize_path(raw)
        if token:
            rows.append(token)
    return sorted(set(rows))


def _git_changed_files(*, base: str | None, head: str, staged: bool) -> list[str]:
    if staged:
        rows = _run_git(["diff", "--cached", "--name-only"])
        return rows or []

    base_ref = str(base or "").strip()
    head_ref = str(head or "HEAD").strip() or "HEAD"
    if base_ref and base_ref.strip("0"):
        rows = _run_git(["diff", "--name-only", f"{base_ref}...{head_ref}"])
        if rows is not None:
            return rows

    rows = _run_git(["diff", "--name-only", f"{head_ref}~1...{head_ref}"])
    if rows is not None:
        return rows

    fallback = _run_git(["diff", "--name-only", head_ref])
    return fallback or []


def _split_patterns(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        for token in str(raw or "").split(","):
            normalized = _normalize_path(token)
            if normalized:
                out.append(normalized)
    return sorted(set(out), key=str.lower)


def _matches_ignore(path: str, patterns: Sequence[str]) -> bool:
    candidate = _normalize_path(path)
    if not candidate:
        return False
    for pattern in patterns:
        pat = _normalize_path(pattern)
        if not pat:
            continue
        if any(ch in pat for ch in "*?["):
            if fnmatch.fnmatchcase(candidate.lower(), pat.lower()):
                return True
            continue
        if candidate.lower() == pat.lower():
            return True
    return False


def _is_truthy(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "yes", "y", "on"}


def evaluate_changed_files(
    *,
    workboard_path: Path,
    changed_files: Sequence[str],
    ignore_patterns: Sequence[str],
    require_identity_metadata: bool = False,
) -> tuple[bool, dict[str, object]]:
    board_violations, claims, _tasks, _grab, _issues = claims_gate.evaluate_board(
        workboard_path,
        require_identity_metadata=require_identity_metadata,
    )
    if board_violations:
        payload = {
            "gate": "workboard_changed_files",
            "ok": False,
            "error": "workboard claims invalid",
            "violations": list(board_violations),
            "workboard": str(workboard_path),
            "require_identity_metadata": bool(require_identity_metadata),
        }
        return False, payload

    seen_files: list[str] = []
    ignored_files: list[str] = []
    owner_by_file: dict[str, str] = {}
    unclaimed_files: list[str] = []
    ambiguous_files: list[dict[str, object]] = []

    for raw in changed_files:
        path = _normalize_path(raw)
        if not path or path in seen_files:
            continue
        seen_files.append(path)
        if _matches_ignore(path, ignore_patterns):
            ignored_files.append(path)
            continue

        owners: list[str] = []
        for claim in claims:
            if any(_scope_matches_path(scope, path) for scope in claim.scopes):
                owners.append(str(claim.agent).strip())

        unique_owners = sorted({owner for owner in owners if owner}, key=str.lower)
        if not unique_owners:
            unclaimed_files.append(path)
            continue
        if len(unique_owners) > 1:
            ambiguous_files.append({"path": path, "owners": unique_owners})
            continue
        owner_by_file[path] = unique_owners[0]

    ok = not unclaimed_files and not ambiguous_files
    payload = {
        "gate": "workboard_changed_files",
        "ok": bool(ok),
        "workboard": str(workboard_path),
        "require_identity_metadata": bool(require_identity_metadata),
        "changed_file_count": len(seen_files),
        "ignored_file_count": len(ignored_files),
        "checked_file_count": len(owner_by_file) + len(unclaimed_files) + len(ambiguous_files),
        "ignored_files": ignored_files,
        "owner_by_file": owner_by_file,
        "unclaimed_file_count": len(unclaimed_files),
        "unclaimed_files": unclaimed_files,
        "ambiguous_file_count": len(ambiguous_files),
        "ambiguous_files": ambiguous_files,
    }
    if not ok:
        payload["error"] = "changed files must map to exactly one active claim scope"
    return ok, payload


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=("Validate that changed files are owned by exactly one active WORKBOARD claim scope.")
    )
    parser.add_argument(
        "--workboard",
        default=str(DEFAULT_WORKBOARD),
        help="Path to workboard markdown file (default: plans/thomas/WORKBOARD.md)",
    )
    parser.add_argument(
        "--base",
        default="",
        help="Optional git base ref/SHA (used with --head for changed-file evaluation).",
    )
    parser.add_argument(
        "--head",
        default="HEAD",
        help="Optional git head ref/SHA for changed-file evaluation (default: HEAD).",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Use staged files from `git diff --cached --name-only`.",
    )
    parser.add_argument(
        "--file",
        action="append",
        default=[],
        help=(
            "Explicit changed file path(s) (repeatable, comma-separated tokens allowed). "
            "When provided, git diff is not used."
        ),
    )
    parser.add_argument(
        "--ignore",
        action="append",
        default=[],
        help=("Ignore path pattern(s), repeatable or comma-separated. Defaults to plans/thomas/WORKBOARD.md."),
    )
    parser.add_argument(
        "--require-identity-metadata",
        action="store_true",
        help="Require name/role/parent metadata fields while parsing claims.",
    )
    parser.add_argument(
        "--max-changed-files",
        type=int,
        default=DEFAULT_MAX_CHANGED_FILES,
        help="Maximum changed files allowed before requiring bulk override (default: 200).",
    )
    parser.add_argument(
        "--bulk-allow-env",
        default=DEFAULT_BULK_ALLOW_ENV,
        help=f"Env var name allowing bulk changed-file checks (default: {DEFAULT_BULK_ALLOW_ENV}).",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    args = parser.parse_args(argv)

    workboard_path = Path(args.workboard).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (ROOT / workboard_path).resolve()

    explicit_files = _split_patterns(args.file)
    ignore_patterns = list(DEFAULT_IGNORE_PATTERNS)
    ignore_patterns.extend(_split_patterns(args.ignore))

    changed_files = explicit_files
    if not changed_files:
        changed_files = _git_changed_files(
            base=str(args.base or "").strip() or None,
            head=str(args.head or "HEAD").strip() or "HEAD",
            staged=bool(args.staged),
        )

    max_changed_files = max(1, int(args.max_changed_files))
    bulk_allow_env = str(args.bulk_allow_env or "").strip() or DEFAULT_BULK_ALLOW_ENV
    bulk_override = _is_truthy(os.getenv(bulk_allow_env, ""))
    if len(changed_files) > max_changed_files and not bulk_override:
        sample = changed_files[:20]
        payload = {
            "gate": "workboard_changed_files",
            "ok": False,
            "error": (
                f"changed file count {len(changed_files)} exceeds max {max_changed_files}; "
                f"set {bulk_allow_env}=1 for audited bulk override"
            ),
            "workboard": str(workboard_path),
            "require_identity_metadata": bool(args.require_identity_metadata),
            "changed_file_count": len(changed_files),
            "max_changed_files": max_changed_files,
            "bulk_allow_env": bulk_allow_env,
            "bulk_override": bulk_override,
            "sample_changed_files": sample,
            "base": str(args.base or "").strip(),
            "head": str(args.head or "HEAD").strip() or "HEAD",
            "staged": bool(args.staged),
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard changed-files gate: FAIL")
            print(f"- {payload['error']}")
            print("- sample changed files:")
            for path in sample:
                print(f"  - {path}")
        return 1

    ok, payload = evaluate_changed_files(
        workboard_path=workboard_path,
        changed_files=changed_files,
        ignore_patterns=ignore_patterns,
        require_identity_metadata=bool(args.require_identity_metadata),
    )

    payload["base"] = str(args.base or "").strip()
    payload["head"] = str(args.head or "HEAD").strip() or "HEAD"
    payload["staged"] = bool(args.staged)
    payload["max_changed_files"] = max_changed_files
    payload["bulk_allow_env"] = bulk_allow_env
    payload["bulk_override"] = bulk_override

    if args.json:
        print(json.dumps(payload, sort_keys=True))
        return 0 if ok else 1

    if not ok:
        print("Workboard changed-files gate: FAIL")
        if payload.get("error"):
            print(f"- {payload['error']}")
        for item in payload.get("violations") or []:
            print(f"- {item}")
        unclaimed_files = payload.get("unclaimed_files") or []
        if unclaimed_files:
            print("- unclaimed changed files:")
            for path in unclaimed_files:
                print(f"  - {path}")
        ambiguous_files = payload.get("ambiguous_files") or []
        if ambiguous_files:
            print("- ambiguously claimed changed files:")
            for row in ambiguous_files:
                path = str((row or {}).get("path") or "")
                owners = ", ".join((row or {}).get("owners") or [])
                print(f"  - {path}: {owners}")
        return 1

    print("Workboard changed-files gate: PASS")
    print(
        "- checked files="
        f"{int(payload.get('checked_file_count', 0))}, ignored files="
        f"{int(payload.get('ignored_file_count', 0))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
