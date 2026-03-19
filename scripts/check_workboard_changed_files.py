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
except ImportError:  # pragma: no cover
    import check_workboard_claims as claims_gate  # type: ignore


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"
DEFAULT_IGNORE_PATTERNS = ("plans/thomas/WORKBOARD.md",)
DEFAULT_MAX_CHANGED_FILES = 200
DEFAULT_BULK_ALLOW_ENV = "THOMAS_ALLOW_BULK_CHANGED_FILES"
FALLBACK_SCOPE_ENV = "THOMAS_WORKBOARD_SCOPE_FALLBACK"
AGENT_ENV_KEYS: tuple[str, ...] = (
    "THOMAS_AGENT_ID",
    "AGENT_ID",
    "CODEX_AGENT_ID",
    "GEMINI_AGENT_ID",
    "CLAUDE_AGENT_ID",
)


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
    except (OSError, subprocess.SubprocessError):
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


def _fallback_scopes_from_env() -> tuple[str, ...]:
    return tuple(_split_patterns([os.getenv(FALLBACK_SCOPE_ENV, "")]))


def _fallback_agent_from_env() -> str | None:
    for key in AGENT_ENV_KEYS:
        value = str(os.getenv(key) or "").strip()
        if value:
            return value
    return None


def evaluate_changed_files(
    *,
    workboard_path: Path,
    changed_files: Sequence[str],
    ignore_patterns: Sequence[str],
    require_identity_metadata: bool = False,
    fallback_scopes: Sequence[str] = (),
    fallback_agent: str | None = None,
) -> tuple[bool, dict[str, object]]:
    board_violations, claims, _tasks, _grab, _issues = claims_gate.evaluate_board(
        workboard_path,
        require_identity_metadata=require_identity_metadata,
    )
    fallback_scope_list = sorted({_normalize_path(scope) for scope in fallback_scopes if _normalize_path(scope)})
    fallback_owner = str(fallback_agent or "").strip() or None
    if board_violations:
        payload = {
            "gate": "workboard_changed_files",
            "ok": False,
            "error": "workboard claims invalid",
            "violations": list(board_violations),
            "workboard": str(workboard_path),
            "require_identity_metadata": bool(require_identity_metadata),
            "fallback_scope_count": len(fallback_scope_list),
            "fallback_scopes": fallback_scope_list,
            "fallback_agent": fallback_owner or "",
        }
        return False, payload

    seen_files: list[str] = []
    ignored_files: list[str] = []
    owner_by_file: dict[str, str] = {}
    unclaimed_files: list[str] = []
    ambiguous_files: list[dict[str, object]] = []
    fallback_conflicts: list[dict[str, object]] = []

    fallback_owner_key = str(fallback_owner or "").strip().lower()
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
        fallback_matches = [scope for scope in fallback_scope_list if _scope_matches_path(scope, path)]
        if fallback_matches and unique_owners:
            unique_owner_keys = {owner.strip().lower() for owner in unique_owners}
            if fallback_owner_key and unique_owner_keys != {fallback_owner_key}:
                fallback_conflicts.append({"path": path, "owners": unique_owners, "fallback_scopes": fallback_matches})
                continue
        if not unique_owners and fallback_matches and fallback_owner:
            owner_by_file[path] = fallback_owner
            continue
        if not unique_owners:
            unclaimed_files.append(path)
            continue
        if len(unique_owners) > 1:
            ambiguous_files.append({"path": path, "owners": unique_owners})
            continue
        owner_by_file[path] = unique_owners[0]

    ok = not unclaimed_files and not ambiguous_files and not fallback_conflicts
    payload = {
        "gate": "workboard_changed_files",
        "ok": bool(ok),
        "workboard": str(workboard_path),
        "require_identity_metadata": bool(require_identity_metadata),
        "changed_file_count": len(seen_files),
        "ignored_file_count": len(ignored_files),
        "checked_file_count": len(owner_by_file) + len(unclaimed_files) + len(ambiguous_files) + len(fallback_conflicts),
        "ignored_files": ignored_files,
        "owner_by_file": owner_by_file,
        "unclaimed_file_count": len(unclaimed_files),
        "unclaimed_files": unclaimed_files,
        "ambiguous_file_count": len(ambiguous_files),
        "ambiguous_files": ambiguous_files,
        "fallback_scope_count": len(fallback_scope_list),
        "fallback_scopes": fallback_scope_list,
        "fallback_agent": fallback_owner or "",
        "fallback_conflict_count": len(fallback_conflicts),
        "fallback_conflicts": fallback_conflicts,
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
    changed_files = explicit_files or _git_changed_files(base=args.base, head=args.head, staged=bool(args.staged))

    max_changed_files = max(1, int(args.max_changed_files or DEFAULT_MAX_CHANGED_FILES))
    bulk_allow_env = str(args.bulk_allow_env or DEFAULT_BULK_ALLOW_ENV).strip() or DEFAULT_BULK_ALLOW_ENV
    bulk_override = _is_truthy(os.getenv(bulk_allow_env, ""))
    fallback_scopes = _fallback_scopes_from_env()
    fallback_agent = _fallback_agent_from_env()
    if len(changed_files) > max_changed_files and not bulk_override:
        payload = {
            "gate": "workboard_changed_files",
            "ok": False,
            "error": (
                f"changed file count {len(changed_files)} exceeds max {max_changed_files}; "
                f"set {bulk_allow_env}=1 to override"
            ),
            "changed_file_count": len(changed_files),
            "max_changed_files": max_changed_files,
            "bulk_override": False,
            "bulk_allow_env": bulk_allow_env,
            "workboard": str(workboard_path),
            "require_identity_metadata": bool(args.require_identity_metadata),
            "fallback_scope_count": len(fallback_scopes),
            "fallback_scopes": list(fallback_scopes),
            "fallback_agent": fallback_agent or "",
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard changed-files gate: FAIL")
            print(f"- {payload['error']}")
        return 1

    ok, payload = evaluate_changed_files(
        workboard_path=workboard_path,
        changed_files=changed_files,
        ignore_patterns=ignore_patterns,
        require_identity_metadata=bool(args.require_identity_metadata),
        fallback_scopes=fallback_scopes,
        fallback_agent=fallback_agent,
    )
    payload["bulk_override"] = bool(bulk_override)
    payload["bulk_allow_env"] = bulk_allow_env
    payload["max_changed_files"] = max_changed_files

    if args.json:
        print(json.dumps(payload, sort_keys=True))
        return 0 if ok else 1

    print("Workboard changed-files gate: PASS" if ok else "Workboard changed-files gate: FAIL")
    if fallback_scopes:
        print(f"- fallback scope count: {len(fallback_scopes)}")
    if ok:
        print(f"- checked files: {payload['checked_file_count']}")
        print(f"- ignored files: {payload['ignored_file_count']}")
        return 0

    print(f"- {payload.get('error', 'changed files must map to exactly one active claim scope')}")
    unclaimed_files = list(payload.get("unclaimed_files") or [])
    ambiguous_files = list(payload.get("ambiguous_files") or [])
    fallback_conflicts = list(payload.get("fallback_conflicts") or [])
    if unclaimed_files:
        print("- unclaimed files:")
        for path in unclaimed_files:
            print(f"  - {path}")
    if ambiguous_files:
        print("- ambiguous files:")
        for item in ambiguous_files:
            path = item.get("path") if isinstance(item, dict) else ""
            owners = item.get("owners") if isinstance(item, dict) else []
            print(f"  - {path}: {', '.join(str(owner) for owner in owners)}")
    if fallback_conflicts:
        print("- fallback conflicts:")
        for item in fallback_conflicts:
            path = item.get("path") if isinstance(item, dict) else ""
            owners = item.get("owners") if isinstance(item, dict) else []
            print(f"  - {path}: {', '.join(str(owner) for owner in owners)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
