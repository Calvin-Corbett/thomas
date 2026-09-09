#!/usr/bin/env python3
"""Install Thomas commit hooks that make no-verify a breakglass path."""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PRE_COMMIT_HOOK = """#!/bin/sh
# thomas-commit-breakglass-guard

run_python() {
    if command -v python >/dev/null 2>&1; then
        python "$@"
    elif command -v py >/dev/null 2>&1; then
        py "$@"
    elif command -v python3 >/dev/null 2>&1; then
        python3 "$@"
    else
        echo "python not found; Thomas commit guard cannot run" 1>&2
        return 1
    fi
}

run_pre_commit() {
    HERE="$(cd "$(dirname "$0")" && pwd)"
    if command -v pre-commit >/dev/null 2>&1; then
        pre-commit hook-impl --config=.pre-commit-config.yaml --hook-type=pre-commit --hook-dir "$HERE" -- "$@"
    elif command -v python >/dev/null 2>&1; then
        python -mpre_commit hook-impl --config=.pre-commit-config.yaml --hook-type=pre-commit --hook-dir "$HERE" -- "$@"
    elif command -v py >/dev/null 2>&1; then
        py -mpre_commit hook-impl --config=.pre-commit-config.yaml --hook-type=pre-commit --hook-dir "$HERE" -- "$@"
    elif command -v python3 >/dev/null 2>&1; then
        python3 -mpre_commit hook-impl --config=.pre-commit-config.yaml --hook-type=pre-commit --hook-dir "$HERE" -- "$@"
    else
        echo "pre-commit not found and no Python launcher is available." 1>&2
        return 1
    fi
}

run_python scripts/commit_breakglass_guard.py pre-commit-start || exit $?
run_pre_commit "$@"
rc=$?
if [ "$rc" -eq 0 ]; then
    run_python scripts/commit_breakglass_guard.py pre-commit-success || exit $?
fi
exit "$rc"
"""

PREPARE_COMMIT_MSG_HOOK = """#!/bin/sh
# thomas-commit-breakglass-guard

if command -v python >/dev/null 2>&1; then
    exec python scripts/commit_breakglass_guard.py prepare-commit-msg "$@"
elif command -v py >/dev/null 2>&1; then
    exec py scripts/commit_breakglass_guard.py prepare-commit-msg "$@"
elif command -v python3 >/dev/null 2>&1; then
    exec python3 scripts/commit_breakglass_guard.py prepare-commit-msg "$@"
else
    echo "python not found; Thomas commit guard cannot run" 1>&2
    exit 1
fi
"""


def _git_path(name: str) -> Path:
    proc = subprocess.run(
        ["git", "rev-parse", "--git-path", name],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git rev-parse --git-path {name} failed")
    path = Path(str(proc.stdout or "").strip())
    if not path.is_absolute():
        path = ROOT / path
    return path


def _write_hook(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def main() -> int:
    pre_commit = _git_path("hooks/pre-commit")
    prepare_commit_msg = _git_path("hooks/prepare-commit-msg")
    _write_hook(pre_commit, PRE_COMMIT_HOOK)
    _write_hook(prepare_commit_msg, PREPARE_COMMIT_MSG_HOOK)
    print(f"Installed Thomas pre-commit guard hook: {pre_commit}")
    print(f"Installed Thomas prepare-commit-msg breakglass hook: {prepare_commit_msg}")
    print("A no-verify commit now requires native-auth breakglass unless pre-commit already passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
