"""Which build is this, exactly.

The version alone cannot answer "am I looking at the right Thomas". This
repository routinely has a dozen worktrees checked out at once, several of them
on the same version string, and the launcher only prints the version to a
console that is closed by the time anyone is looking at the browser. So the
honest answer needs the commit as well -- and whether the tree has uncommitted
edits on top of it, because a build made from a dirty tree is not the commit it
claims to be.

Resolved once and cached: this is boot-time identity, it cannot change while the
process runs, and no health check should be paying for a subprocess.
"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

from thomas import __version__

# Git should answer instantly on a warm repo. If it does not -- a stale index
# lock, a network filesystem, an enormous worktree -- identity is a nicety and
# must never be the reason the server is slow to say it is alive.
_GIT_TIMEOUT_S = 2.0

_SOURCE_ROOT = Path(__file__).resolve().parent.parent.parent


def _git(*args: str) -> str:
    """One git query against the source tree, or "" if git cannot answer."""
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(_SOURCE_ROOT),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""  # git absent, or an installed copy with no repository
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


@lru_cache(maxsize=1)
def build_info() -> dict[str, object]:
    """Identity of the running build, for display.

    Every field is best-effort. An installed copy with no repository still
    reports its version; it simply cannot name a commit.
    """
    commit = _git("rev-parse", "--short=8", "HEAD")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    # Untracked files are ignored deliberately. Screenshots and scratch files
    # accumulate constantly here and do not change what the server runs, so
    # counting them would leave the badge permanently marked dirty and the
    # signal would stop meaning anything.
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    return {
        "version": str(__version__),
        "commit": commit,
        "branch": "" if branch == "HEAD" else branch,
        "dirty": dirty,
        "root": str(_SOURCE_ROOT),
    }


def build_label() -> str:
    """One line a human can compare against another instance at a glance."""
    info = build_info()
    label = f"v{info['version']}"
    if info["branch"]:
        label += f" {info['branch']}"
    if info["commit"]:
        label += f"@{info['commit']}"
    if info["dirty"]:
        label += "+dirty"
    return label


__all__ = ["build_info", "build_label"]
