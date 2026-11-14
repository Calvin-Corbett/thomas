"""Add folders to the cage account's git safe.directory, through the caged shell.

Git refuses a repository owned by another account ("dubious ownership"), and your
projects are owned by you while the caged Thomas works in them as the cage
account. enable_build_projects.ps1 passes the folders; this adds each one the cage
account's global git config does not already list. Prints how many were added.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO_ROOT = Path(__file__).resolve().parents[2]


def main(folders: list[str]) -> int:
    from thomas.tools.cage_shell import run_caged

    listed = run_caged("git config --global --get-all safe.directory", cwd=str(REPO_ROOT), timeout_s=60.0)
    have = {line.strip() for line in (listed.output or "").splitlines() if line.strip()}
    added = 0
    for folder in folders:
        if folder in have:
            continue
        done = run_caged(f'git config --global --add safe.directory "{folder}"', cwd=str(REPO_ROOT), timeout_s=60.0)
        if done.returncode != 0:
            print(f"could not trust {folder}: {done.output.strip()[-200:]}")
            return 1
        added += 1
    print(f"added {added}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
