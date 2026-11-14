"""A landed candidate's local refs gain a second name under ``refs/archive/ratchet/``. Nothing is deleted.

You asked that the ratchet never delete a branch. The plan had it *move* each ref
(Deviation 17), and that is what this module used to do: write the archive ref,
then ``git update-ref -d`` the original. Measured 2026-09-25: all seven heads of
the first candidate (fcb5f06a) are checked out in worktrees today, and deleting a
ref a worktree has checked out succeeds and leaves that worktree on "No commits
yet". Checking ``git worktree list`` first would narrow that; keeping the ref
removes it. So the archive ref is a second name for the same commit, written only
if absent, and the branch stays exactly where it was.

Nothing is lost by keeping it: the ledger line is the record that a candidate
landed, and ``Ledger.should_prove`` never proves a landed candidate again, so
discovery finding the ref next run costs nothing.

Not the custodian's ``consolidate``, which archives only SUPERSEDED branches (a
landed candidate stays UNIQUE_WORK, because the promoter lands a new commit),
deletes with ``git branch -D`` (which cannot touch refs/salvage), and writes
docs/ops/graveyard.json, a protected file in the running copy. Remote refs are
never touched and nothing is pushed; dev is never touched.
"""

from __future__ import annotations

from collections.abc import Sequence

from thomas.server.ratchet.gitrepo import Repo

ARCHIVE_PREFIX = "refs/archive/ratchet/"
_LOCAL = ("refs/heads/", "refs/salvage/")


def archive_refs(repo: Repo, refs: Sequence[str], sha: str) -> dict[str, str]:
    """Copy each local ref still at *sha* to its archive name; return what happened to each, in words."""
    notes: dict[str, str] = {}
    for ref in refs:
        if not ref.startswith(_LOCAL):
            notes[ref] = "kept: not a local ref"
            continue
        if ref == "refs/heads/dev":
            notes[ref] = "kept: it is dev"
            continue
        current = repo.run("rev-parse", "--verify", "--quiet", ref, ok=(0, 1)).stdout.strip()
        if current != sha:
            notes[ref] = f"kept: it no longer points at {sha[:12]}"
            continue
        target = ARCHIVE_PREFIX + ref.removeprefix("refs/")
        made = repo.run("update-ref", target, sha, "", ok=(0, 1, 128))
        if made.returncode != 0:
            notes[ref] = f"kept: {target} could not be written ({made.stderr.strip()[:160]})"
            continue
        notes[ref] = f"copied to {target}"
    return notes


__all__ = ["ARCHIVE_PREFIX", "archive_refs"]
