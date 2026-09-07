#!/usr/bin/env python3
"""Seed the graveyard from git history -- so the armed merge trap is covered
before any merge can fire.

WHY THIS EXISTS: ``scripts/forge/graveyard.py`` (Task 1) gives the repo a
place to record deliberate deaths, but it starts empty. Every path deleted
on dev's first-parent history since the public-main squash point, and every
branch already archived under ``refs/archive/``, died BEFORE the graveyard
existed to record it -- and the merge-resurrection gate that Task 3 will
build only protects paths it can find a record for. This script backfills
those records once, from history and from the two archive-ref namespaces,
so the standing hazard (origin/main's June-9 merge-base still holds every
one of those paths and branch names) is covered from the moment the gate
goes live.

TWO DEATH SOURCES:
  * FILE deaths -- every path that ``git log --first-parent --diff-filter=D
    --name-only <merge-base>..HEAD --no-renames`` shows as deleted, AND is
    still absent from the HEAD tree (a path deleted and later re-added is
    not dead -- it is just absent from this one commit). ``--no-renames`` is
    deliberate: without it, a rename would not show as a deletion of its old
    path, and re-adding that old path later would slip past the gate this
    seed exists to arm.
  * BRANCH deaths -- every name under ``refs/archive/`` (the custodian's
    archive-and-delete namespace) and ``refs/archive/worktree/`` (the
    worktree-salvage namespace). A name can appear in both; the collision is
    resolved by giving the worktree-salvage source priority and noting the
    custodian archive in that one record's reason -- never two records for
    one name.

IDEMPOTENT BY CONSTRUCTION: before recording anything, this script loads
the graveyard and skips any path or name that already has a record --
seeded by a prior run of this script, or recorded by anything else (the
custodian, a manual CLI call). A second run of ``seed()`` therefore adds
zero records; ``main()`` prints the counts either way so that "zero added"
is a visible, positive statement and not silence.

CLI: ``python scripts/forge/graveyard_seed.py [--repo-root PATH]
[--merge-base SHA] [--by NAME]``.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.forge import graveyard  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]

_BY = "graveyard-seed"
_DEFAULT_MERGE_BASE = "8ee07acb"
_FILE_REASON = "seeded: deleted on dev after the public-main squash point"
_BRANCH_REASON_WORKTREE = "seeded: archived by custodian/salvage (worktree-salvage source)"
_BRANCH_REASON_CUSTODIAN = "seeded: archived by custodian/salvage (custodian-archive source)"
_COLLISION_NOTE = "; also present as a custodian archive ref for the same name -- worktree-salvage source used"

_SHA_MARKER = "SEED-SHA:"


def _git(repo_root: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo_root), *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"graveyard_seed: `git {' '.join(args)}` failed: {proc.stderr.strip()}")
    return proc.stdout


def _head_tree_paths(repo_root: Path) -> set[str]:
    """Every path present in the HEAD tree right now."""
    out = _git(repo_root, "ls-tree", "-r", "--name-only", "HEAD")
    return {line for line in out.splitlines() if line}


def _deleted_paths_since(repo_root: Path, merge_base: str) -> dict[str, str]:
    """path -> the SHA of the commit closest to HEAD that deleted it.

    Uses a distinctive ``SEED-SHA:`` marker (rather than assuming a blank
    line separates each commit's SHA from its path list) because git does
    NOT emit a blank line between one commit's last deleted path and the
    next commit's SHA -- only between the SHA and its own path list. A plain
    "blank line means new commit" parser silently swallows the second and
    later commits' SHAs as if they were paths.

    ``--first-parent`` walks only the mainline of merges (this dev branch's
    own history, not everything a merge pulled in). ``--no-renames`` is
    load-bearing: a rename must count as its OLD path dying, not as a
    same-content move invisible to the gate.
    """
    out = _git(
        repo_root,
        "log",
        "--first-parent",
        "--diff-filter=D",
        "--name-only",
        f"--format={_SHA_MARKER}%H",
        f"{merge_base}..HEAD",
        "--no-renames",
    )
    newest_deleting_sha: dict[str, str] = {}
    current_sha: str | None = None
    for line in out.splitlines():
        if line.startswith(_SHA_MARKER):
            current_sha = line[len(_SHA_MARKER) :]
            continue
        if not line or current_sha is None:
            continue
        if line not in newest_deleting_sha:
            newest_deleting_sha[line] = current_sha
    return newest_deleting_sha


def _archive_refs(repo_root: Path) -> tuple[dict[str, str], dict[str, str]]:
    """(worktree_refs, custodian_refs), each short-name -> object sha.

    ``refs/archive/worktree/<name>`` -> worktree_refs[name]; every other
    ``refs/archive/<name>`` -> custodian_refs[name]. A ref that resolves to
    something git cannot give a plain commit sha for (rare, e.g. a
    dangling/annotated edge case) is skipped rather than recorded with a
    guessed sha.
    """
    out = _git(repo_root, "for-each-ref", "--format=%(refname) %(objectname)", "refs/archive")
    worktree: dict[str, str] = {}
    custodian: dict[str, str] = {}
    for line in out.splitlines():
        if not line.strip():
            continue
        refname, _, sha = line.rpartition(" ")
        if not refname or not sha:
            continue
        if refname.startswith("refs/archive/worktree/"):
            name = refname[len("refs/archive/worktree/") :]
            if name:
                worktree[name] = sha
        elif refname.startswith("refs/archive/"):
            name = refname[len("refs/archive/") :]
            if name:
                custodian[name] = sha
    return worktree, custodian


def seed(repo_root: Path, *, merge_base: str = _DEFAULT_MERGE_BASE, by: str = _BY) -> dict[str, int]:
    """Record every not-yet-recorded file and branch death. Returns counts.

    Safe to call repeatedly: a name/path that already has ANY record (from
    this script or anything else) is counted as skipped, never re-recorded.
    """
    gy = graveyard.load(repo_root)
    already_dead_files = set(gy.dead_file_paths())
    already_dead_branches = set(gy.dead_ref_names())

    head_paths = _head_tree_paths(repo_root)
    deleted = _deleted_paths_since(repo_root, merge_base)

    files_added = 0
    files_skipped = 0
    for path in sorted(deleted):
        if path in head_paths:
            continue  # deleted, then re-added -- not actually dead
        if path in already_dead_files:
            files_skipped += 1
            continue
        graveyard.record_death(repo_root, "file", path, deleted[path], _FILE_REASON, by)
        already_dead_files.add(path)
        files_added += 1

    worktree_refs, custodian_refs = _archive_refs(repo_root)
    branches_added = 0
    branches_skipped = 0
    seen_this_run: set[str] = set()

    for name in sorted(worktree_refs):
        if name in already_dead_branches or name in seen_this_run:
            branches_skipped += 1
            continue
        reason = _BRANCH_REASON_WORKTREE + (_COLLISION_NOTE if name in custodian_refs else "")
        graveyard.record_death(repo_root, "branch", name, worktree_refs[name], reason, by)
        seen_this_run.add(name)
        branches_added += 1

    for name in sorted(custodian_refs):
        if name in already_dead_branches or name in seen_this_run:
            branches_skipped += 1
            continue
        graveyard.record_death(repo_root, "branch", name, custodian_refs[name], _BRANCH_REASON_CUSTODIAN, by)
        seen_this_run.add(name)
        branches_added += 1

    return {
        "files_added": files_added,
        "files_skipped": files_skipped,
        "branches_added": branches_added,
        "branches_skipped": branches_skipped,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(_REPO_ROOT), help="Repository root path.")
    parser.add_argument(
        "--merge-base", default=_DEFAULT_MERGE_BASE, help="Seed file deaths since this SHA (exclusive)."
    )
    parser.add_argument("--by", default=_BY, help="`by` field recorded on every seeded record.")
    args = parser.parse_args(argv)

    counts = seed(Path(args.repo_root), merge_base=args.merge_base, by=args.by)
    print(
        "graveyard-seed: "
        f"files added={counts['files_added']} skipped={counts['files_skipped']}; "
        f"branches added={counts['branches_added']} skipped={counts['branches_skipped']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
