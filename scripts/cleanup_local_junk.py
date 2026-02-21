"""Remove known local artifact files from the Thomas repo.

By default this script scans both untracked and ignored paths so local junk can
still be cleaned after patterns are added to ``.gitignore``.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, List


ROOT = Path(__file__).resolve().parent.parent

JUNK_PATTERNS = [
    ".coverage",
    ".coverage.*",
    "server_output.txt",
    "thomas_state.json",
    "thomas_tool_registry.json",
    "thomas_webhooks.json.lock",
    "thomas_test_results.jsonl",
    "thomas_test_report_*.md",
    "ux_event_probe.txt",
    "ux_visible_test_*.txt",
    "vel4_test.txt",
    "test_autonomous_task*.txt",
    "tmp_switch_test.py",
]

WINDOWS_DEVICE_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}


def _git_ls_files(repo_root: Path, args: List[str]) -> List[str]:
    proc = subprocess.run(
        ["git", "ls-files", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        joined = " ".join(args)
        raise RuntimeError(proc.stderr.strip() or f"git ls-files {joined} failed")
    out = []
    for raw in proc.stdout.splitlines():
        rel = str(raw or "").strip().replace("\\", "/")
        if rel:
            out.append(rel)
    return sorted(set(out))


def _git_untracked(repo_root: Path, include_ignored: bool) -> List[str]:
    paths = set(_git_ls_files(repo_root, ["--others", "--exclude-standard"]))
    if include_ignored:
        paths.update(_git_ls_files(repo_root, ["--others", "--ignored", "--exclude-standard"]))
    return sorted(paths)


def _matches_any(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def _is_windows_device_name(path: Path) -> bool:
    stem = path.name.split(".", 1)[0].strip().upper()
    return stem in WINDOWS_DEVICE_NAMES


def _remove_path(path: Path) -> tuple[bool, str]:
    if _is_windows_device_name(path):
        return False, "reserved Windows device name; skipped"
    if not path.exists():
        return True, ""
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


def run(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean known local junk artifacts.")
    parser.add_argument("--apply", action="store_true", help="Delete matched files/directories.")
    parser.add_argument(
        "--ignored",
        dest="ignored",
        action="store_true",
        default=True,
        help="Include ignored paths in scan (default: true).",
    )
    parser.add_argument(
        "--no-ignored",
        dest="ignored",
        action="store_false",
        help="Only scan non-ignored untracked paths.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)

    untracked = _git_untracked(ROOT, include_ignored=args.ignored)
    candidates = [p for p in untracked if _matches_any(p, JUNK_PATTERNS)]

    removed: List[str] = []
    failed: List[dict[str, str]] = []
    if args.apply:
        for rel in candidates:
            abs_path = (ROOT / rel).resolve()
            ok, reason = _remove_path(abs_path)
            if ok:
                removed.append(rel)
            else:
                failed.append({"path": rel, "error": reason})

    payload = {
        "repo_root": str(ROOT),
        "include_ignored": bool(args.ignored),
        "patterns": JUNK_PATTERNS,
        "candidates": candidates,
        "removed": removed,
        "failed": failed,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"cleanup_local_junk: candidates={len(candidates)} removed={len(removed)}")
        if candidates:
            print("candidates:")
            for rel in candidates:
                print(f"  - {rel}")
        if failed:
            print("failed:")
            for row in failed:
                print(f"  - {row['path']}: {row['error']}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
