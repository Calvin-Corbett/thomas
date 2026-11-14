"""The tip the scoped commit tool built its temporary index on, for the gates that ask what is staged.

A neighbour's landing moves HEAD but not the temporary index, so `git diff --cached` against HEAD lists the neighbour's files
as staged by the agent that is committing. Measured with ten simulated agents: workboard_agent_claim refused 32 of 113 landing
attempts and workboard_changed_files 59 of 125 for exactly that. The commit tool exports the tip it built the index on as
THOMAS_COMMIT_BASE; a gate that diffs the index passes ``args(ROOT)`` after ``--name-only`` and compares against it.

The value is used only when ALL of these hold, otherwise the gate diffs against HEAD as it always did:

* GIT_INDEX_FILE names a file inside a ``thomas-agent-commit-*`` directory, the temporary directory the commit tool builds
  its index in. A value left in an agent's shell, or set while the real index is staged (the pre-commit hook path), is
  ignored. Without this an exported value could point the diff at an older tree and hide a staged revert of a recent change
  from both gates (measured by the review, 2026-10-07).
* it is a full object name, and
* it is an ancestor of HEAD, so an invented value cannot point at a tree that hides what is staged.

This is not a security control: someone who can set both variables can also edit the gate. It closes the accident, and
the deliberate use of one stray variable.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_HEX = frozenset("0123456789abcdef")
# The prefix commit.py gives the temporary directory (tempfile.TemporaryDirectory(prefix=...) in _prepare_temp_index).
# tests/test_commit_base_gates.py reads commit.py and fails if the two ever differ.
INDEX_DIR_PREFIX = "thomas-agent-commit-"
ZERO_SHA = "0" * 40


def _git(root: Path, *cmd: str) -> subprocess.CompletedProcess | None:
    """The one place this module starts git. None when git cannot be run at all."""
    try:
        return subprocess.run(["git", *cmd], cwd=str(root), capture_output=True, text=True, check=False)
    except (OSError, subprocess.SubprocessError):
        return None


def _built_by_the_commit_tool() -> bool:
    index = os.environ.get("GIT_INDEX_FILE", "").strip()
    return bool(index) and Path(index).parent.name.startswith(INDEX_DIR_PREFIX)


def args(root: Path) -> list[str]:
    """[base] when THOMAS_COMMIT_BASE is trustworthy (see the module docstring), else []."""
    base = os.environ.get("THOMAS_COMMIT_BASE", "").strip().lower()
    if len(base) not in (40, 64) or not set(base) <= _HEX or not _built_by_the_commit_tool():
        return []
    proc = _git(root, "merge-base", "--is-ancestor", base, "HEAD")
    return [base] if proc is not None and proc.returncode == 0 else []


def staged_names(root: Path) -> list[str] | None:
    """The names of the staged files, or None when git cannot say (a gate then refuses: it never reads None as nothing)."""
    proc = _git(root, "diff", "--cached", "--name-only", *args(root))
    return proc.stdout.splitlines() if proc is not None and proc.returncode == 0 else None


def pre_push_range(root: Path, forced: bool = False) -> tuple[str, str] | None:
    """(from, to) of a real pre-push run, else None; a gate that gets None runs its ordinary commit-time check.

    A run is a pre-push run when pre-commit says so: PRE_COMMIT_HOOK_STAGE is "pre-push", or it exported both the remote's
    name and url (it does that for a push and for nothing else), or ``forced`` (the hook config's own --push). It also
    needs both refs, neither the all-zero sha (a new branch has no from-ref), and a range git can read that holds a commit.
    Like the rest of this module it is not a security control against someone who can set the environment and run the
    hook; it keeps a stray variable at commit time from reading as a push. The commit tool strips all of them.
    """
    env = os.environ
    stage = env.get("PRE_COMMIT_HOOK_STAGE") == "pre-push" or (
        bool(env.get("PRE_COMMIT_REMOTE_NAME")) and bool(env.get("PRE_COMMIT_REMOTE_URL"))
    )
    base, head = env.get("PRE_COMMIT_FROM_REF", "").strip(), env.get("PRE_COMMIT_TO_REF", "").strip()
    if not (stage or forced) or not base or not head or ZERO_SHA in (base, head):
        return None
    listing = _git(root, "rev-list", "--max-count=1", f"{base}..{head}")
    if listing is None or listing.returncode != 0 or not listing.stdout.strip():
        return None
    return base, head
