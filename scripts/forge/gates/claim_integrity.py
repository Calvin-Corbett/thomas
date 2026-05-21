#!/usr/bin/env python3
"""Fail when release claims point at untracked or placeholder-backed files."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from typing import Any

from thomas.core.placeholder_policy import placeholder_policy_report

ROOT = Path(__file__).resolve().parents[3]
CHANGELOG_PATH = ROOT / "CHANGELOG.md"
PATH_REF_RE = re.compile(r"`((?:thomas|apps|scripts|tests|docs|plans|server|cli|extensions)/[^`\s]+)`")


def _normalize_rel_path(raw: str) -> str:
    return str(raw or "").strip().replace("\\", "/")


def _tracked_files(repo_root: Path) -> set[str]:
    proc = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git ls-files failed")
    return {_normalize_rel_path(line) for line in proc.stdout.splitlines() if _normalize_rel_path(line)}


def _latest_changelog_section(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    headings = list(re.finditer(r"^## \[[^\]]+\].*$", text, flags=re.MULTILINE))
    if not headings:
        return ""
    start = headings[0].start()
    end = headings[1].start() if len(headings) > 1 else len(text)
    return text[start:end]


def _extract_path_refs(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for match in PATH_REF_RE.finditer(text):
        ref = _normalize_rel_path(match.group(1))
        if ref and ref not in seen:
            out.append(ref)
            seen.add(ref)
    return out


def _is_placeholder_backed(path: Path) -> bool:
    report = placeholder_policy_report(path)
    return bool(report.get("is_placeholder", False))


def _evaluate_claim_paths(*, refs: Sequence[str], repo_root: Path, tracked: set[str]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for ref in refs:
        full_path = repo_root / ref
        if not full_path.exists():
            issues.append({"path": ref, "issue": "missing"})
            continue
        # Directory refs (paths ending in '/') are tracked as long as at least one
        # file under them is tracked. `git ls-files` returns files, not directories.
        if ref.endswith("/") or full_path.is_dir():
            prefix = ref if ref.endswith("/") else ref + "/"
            if any(path.startswith(prefix) for path in tracked):
                if _is_placeholder_backed(full_path):
                    issues.append({"path": ref, "issue": "placeholder_backed"})
                continue
            issues.append({"path": ref, "issue": "untracked"})
            continue
        if ref not in tracked:
            issues.append({"path": ref, "issue": "untracked"})
            continue
        if _is_placeholder_backed(full_path):
            issues.append({"path": ref, "issue": "placeholder_backed"})
    return issues


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check that latest release claims only reference tracked, source-backed files."
    )
    parser.add_argument("--repo-root", default=".", help="Repository root (default: current repo).")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    try:
        tracked = _tracked_files(repo_root)
    except Exception as exc:
        payload = {"ok": False, "errors": [f"failed to enumerate tracked files: {exc}"]}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("claim integrity: FAIL")
            print(f"- failed to enumerate tracked files: {exc}")
        return 1

    section = _latest_changelog_section(repo_root / "CHANGELOG.md")
    refs = _extract_path_refs(section)
    issues = _evaluate_claim_paths(refs=refs, repo_root=repo_root, tracked=tracked)
    ok = not issues
    payload: dict[str, Any] = {
        "ok": ok,
        "surface": "CHANGELOG.md latest release section",
        "path_ref_count": len(refs),
        "issues": issues,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if ok:
            print("claim integrity: PASS")
            print(f"- checked refs: {len(refs)}")
        else:
            print("claim integrity: FAIL")
            for item in issues:
                print(f"- {item['path']}: {item['issue']}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
