#!/usr/bin/env python3
"""Create a clean git snapshot of the current repo for publish preflight."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO_HYGIENE_BASELINE = ROOT / "docs" / "repo_hygiene_baseline.json"
PUBLIC_SNAPSHOT_EXCLUDED_PREFIXES = (
    "agent_memory/",
    "agent_vf/",
    "code_intake/",
    "library/entries/",
    "patches/",
    "plans/",
)
PUBLIC_SNAPSHOT_EXCLUDED_PATHS = {
    ".github/pull_request_template.md",
    "definitions/model-vs-os.md",
    "docs/evals/2026-02-21_webui_natural_behavior_eval.md",
    "docs/feature_13_dep_scanner.md",
    "tests/test_agent_memory_cli_workflow.py",
    "tests/test_agent_memory_workflow_evals.py",
}


def _run_git(repo_root: Path, args: Sequence[str]) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return str(proc.stdout or "")


def _normalize_path(raw: str) -> str:
    return str(raw or "").strip().replace("\\", "/")


def _any_suffix(path: str, suffixes: Sequence[str]) -> bool:
    lowered = _normalize_path(path).lower()
    for raw in suffixes:
        suffix = str(raw or "").strip().lower()
        if suffix and lowered.endswith(suffix):
            return True
    return False


def _any_prefix(path: str, prefixes: Sequence[str]) -> bool:
    lowered = _normalize_path(path).lower()
    for raw in prefixes:
        prefix = _normalize_path(str(raw or "")).lower()
        if prefix and lowered.startswith(prefix):
            return True
    return False


def _list_git_paths(repo_root: Path, *, include_untracked: bool) -> list[str]:
    tracked = {
        _normalize_path(line) for line in _run_git(repo_root, ["ls-files"]).splitlines() if _normalize_path(line)
    }
    if not include_untracked:
        return sorted(tracked)

    untracked = {
        _normalize_path(line)
        for line in _run_git(repo_root, ["ls-files", "--others", "--exclude-standard"]).splitlines()
        if _normalize_path(line)
    }
    return sorted(tracked | untracked)


def _load_repo_hygiene_baseline(repo_root: Path) -> dict[str, Any] | None:
    path = repo_root / DEFAULT_REPO_HYGIENE_BASELINE.relative_to(ROOT)
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else None


def _filter_publish_paths(
    repo_root: Path,
    rel_paths: Sequence[str],
    *,
    respect_repo_hygiene: bool,
) -> list[str]:
    base_filtered = []
    for raw in rel_paths:
        rel = _normalize_path(raw)
        if not rel:
            continue
        if rel in PUBLIC_SNAPSHOT_EXCLUDED_PATHS:
            continue
        if _any_prefix(rel, PUBLIC_SNAPSHOT_EXCLUDED_PREFIXES):
            continue
        base_filtered.append(rel)
    if not respect_repo_hygiene:
        return sorted(set(base_filtered))

    baseline = _load_repo_hygiene_baseline(repo_root)
    if not baseline:
        return sorted(set(base_filtered))

    allowed_root = {
        _normalize_path(item) for item in (baseline.get("allowed_tracked_root_files") or []) if _normalize_path(item)
    }
    forbidden_prefixes = [
        _normalize_path(item) for item in (baseline.get("forbidden_tracked_prefixes") or []) if _normalize_path(item)
    ]
    blocked_suffixes = [str(item) for item in (baseline.get("blocked_tracked_suffixes") or []) if str(item).strip()]

    filtered: list[str] = []
    for rel in base_filtered:
        if "/" not in rel and allowed_root and rel not in allowed_root:
            continue
        if _any_prefix(rel, forbidden_prefixes):
            continue
        if _any_suffix(rel, blocked_suffixes):
            continue
        filtered.append(rel)
    return sorted(set(filtered))


def _copy_snapshot_paths(repo_root: Path, snapshot_root: Path, rel_paths: Sequence[str]) -> list[str]:
    copied: list[str] = []
    for rel in rel_paths:
        src = repo_root / rel
        if not src.exists() or not src.is_file():
            continue
        dst = snapshot_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(rel)
    return copied


def _resolve_snapshot_root(output_root: str | None) -> Path:
    raw = str(output_root or "").strip()
    if raw:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (ROOT / path).resolve()
        return path
    return Path(tempfile.mkdtemp(prefix="thomas-github-publish-snapshot-"))


def _current_origin(repo_root: Path) -> str:
    try:
        return _run_git(repo_root, ["remote", "get-url", "origin"]).strip()
    except RuntimeError:
        return ""


def _init_snapshot_repo(snapshot_root: Path, *, origin_url: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=snapshot_root, check=True)
    subprocess.run(["git", "config", "user.name", "Thomas Snapshot"], cwd=snapshot_root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "snapshot@local.invalid"],
        cwd=snapshot_root,
        check=True,
    )
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=snapshot_root, check=True)
    if origin_url:
        subprocess.run(["git", "remote", "add", "origin", origin_url], cwd=snapshot_root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=snapshot_root, check=True)
    subprocess.run(["git", "commit", "-qm", "publish snapshot"], cwd=snapshot_root, check=True)
    subprocess.run(["git", "branch", "dev"], cwd=snapshot_root, check=True)
    subprocess.run(["git", "branch", "prod"], cwd=snapshot_root, check=True)


def _run_preflight(snapshot_root: Path, *, deep: bool) -> dict[str, Any]:
    cmd = [
        "python",
        "scripts/github_publish_preflight.py",
        "--json",
        "--strict",
    ]
    if deep:
        cmd.append("--deep")
    proc = subprocess.run(
        cmd,
        cwd=snapshot_root,
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        payload = {"ok": False, "errors": [proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"]}
    payload["exit_code"] = int(proc.returncode)
    return payload


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a clean publish snapshot without touching the active tree.")
    parser.add_argument("--repo-root", default=".", help="Source repository root.")
    parser.add_argument("--output-root", default="", help="Optional snapshot destination directory.")
    parser.add_argument(
        "--include-untracked",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include untracked files in the snapshot (default: true).",
    )
    parser.add_argument(
        "--respect-repo-hygiene",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Prune files rejected by docs/repo_hygiene_baseline.json when building the publish snapshot.",
    )
    parser.add_argument("--deep-preflight", action="store_true", help="Run deep publish preflight in snapshot.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    snapshot_root = _resolve_snapshot_root(args.output_root)
    if snapshot_root.exists() and any(snapshot_root.iterdir()):
        raise SystemExit(f"snapshot destination must be empty: {snapshot_root}")
    snapshot_root.mkdir(parents=True, exist_ok=True)

    rel_paths = _list_git_paths(repo_root, include_untracked=bool(args.include_untracked))
    rel_paths = _filter_publish_paths(
        repo_root,
        rel_paths,
        respect_repo_hygiene=bool(args.respect_repo_hygiene),
    )
    copied = _copy_snapshot_paths(repo_root, snapshot_root, rel_paths)

    _init_snapshot_repo(snapshot_root, origin_url=_current_origin(repo_root))
    preflight = _run_preflight(snapshot_root, deep=bool(args.deep_preflight))
    payload: dict[str, Any] = {
        "ok": bool(preflight.get("ok")),
        "snapshot_root": str(snapshot_root),
        "copied_file_count": len(copied),
        "include_untracked": bool(args.include_untracked),
        "respect_repo_hygiene": bool(args.respect_repo_hygiene),
        "preflight": preflight,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"snapshot root: {snapshot_root}")
        print(f"copied files: {len(copied)}")
        print(f"preflight ok: {bool(preflight.get('ok'))}")
    return 0 if bool(preflight.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(run())
