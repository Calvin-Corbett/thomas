#!/usr/bin/env python3
"""Prevent accidental edits to shared Thomas overhead files."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Iterable, Sequence
from pathlib import Path

import sys
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = ROOT / "docs" / "core_overhead_manifest.json"
UNLOCK_ENV = "THOMAS_CORE_OVERHEAD_UNLOCK"
AGENT_ROLE_ENV = "THOMAS_AGENT_ROLE"
ORCHESTRATOR_ROLES = {"orchestrator", "thomas_orchestrator", "swarm_orchestrator"}


def _normalize(path: str) -> str:
    p = str(path or "").strip().replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    return p


def _truthy(value: str | None) -> bool:
    v = str(value or "").strip().lower()
    return v in {"1", "true", "yes", "on"}


def _is_orchestrator_role() -> bool:
    role = _normalize(os.environ.get(AGENT_ROLE_ENV, "")).lower()
    return role in ORCHESTRATOR_ROLES


def _load_manifest(path: Path) -> dict:
    if not path.exists():
        raise RuntimeError(f"manifest not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise RuntimeError(f"invalid manifest JSON: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"manifest must be a JSON object: {path}")
    return data


def _manifest_files(manifest: dict) -> set[str]:
    files = manifest.get("protected_files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("manifest must define non-empty protected_files[]")
    out: set[str] = set()
    for item in files:
        rel = _normalize(item)
        if not rel:
            continue
        out.add(rel)
    if not out:
        raise RuntimeError("manifest protected_files[] resolved to empty")
    return out


def _git_changed(base: str, head: str) -> list[str]:
    cmd = ["git", "diff", "--name-only", base, head]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git diff failed: {' '.join(cmd)}\n{proc.stderr.strip()}")
    return sorted({_normalize(line) for line in proc.stdout.splitlines() if _normalize(line)})


def _is_git_repo() -> bool:
    cmd = ["git", "rev-parse", "--is-inside-work-tree"]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return proc.returncode == 0 and proc.stdout.strip().lower() == "true"


def _git_staged_changed() -> list[str]:
    candidates = [
        ["git", "diff", "--cached", "--name-only"],
        ["git", "diff", "--staged", "--name-only"],
    ]
    errors: list[str] = []
    for cmd in candidates:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if proc.returncode == 0:
            return sorted({_normalize(line) for line in proc.stdout.splitlines() if _normalize(line)})
        errors.append(f"{' '.join(cmd)} :: {proc.stderr.strip() or proc.stdout.strip()}")
    raise RuntimeError("git diff failed:\n" + "\n".join(errors))


def _resolve_changed_files(
    *,
    explicit_files: Iterable[str],
    base: str | None,
    head: str | None,
) -> list[str]:
    normalized_explicit = sorted({_normalize(p) for p in explicit_files if _normalize(p)})
    if normalized_explicit:
        return normalized_explicit
    if base and head:
        return _git_changed(base, head)
    if base or head:
        raise RuntimeError("both --base and --head are required together")
    if not _is_git_repo():
        return []
    return _git_staged_changed()


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Block accidental edits to shared Thomas overhead files.")
    parser.add_argument("--base", default=None, help="base git SHA for diff mode")
    parser.add_argument("--head", default=None, help="head git SHA for diff mode")
    parser.add_argument(
        "--manifest",
        default=str(MANIFEST_PATH),
        help="path to core overhead manifest JSON",
    )
    parser.add_argument("files", nargs="*", help="optional explicit file list")
    args = parser.parse_args(argv)

    if _is_orchestrator_role():
        print("Core overhead guard: SKIP (orchestrator role exempt via THOMAS_AGENT_ROLE)")
        return 0

    try:
        manifest = _load_manifest(Path(args.manifest))
        protected = _manifest_files(manifest)
        changed = _resolve_changed_files(
            explicit_files=args.files,
            base=args.base,
            head=args.head,
        )
    except Exception as exc:
        print("Core overhead guard: FAIL")
        print(f"- {exc}")
        return 1

    touched = sorted(rel for rel in changed if rel in protected)
    if not touched:
        print("Core overhead guard: PASS")
        print("- no protected overhead files changed")
        return 0

    if _truthy(os.environ.get(UNLOCK_ENV)):
        print("Core overhead guard: PASS (unlocked)")
        for rel in touched:
            print(f"- intentional protected edit: {rel}")
        return 0

    print("Core overhead guard: FAIL")
    print("- protected Thomas overhead files were modified:")
    for rel in touched:
        print(f"- {rel}")
    print(f"- to edit intentionally, set {UNLOCK_ENV}=1")
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
