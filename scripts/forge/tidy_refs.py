#!/usr/bin/env python3
"""Anti-sprawl janitor: reap landed/recoverable branches and stale worktrees.

WHY THIS EXISTS
---------------
Thomas's per-task workflow spins up a topic branch *and* a separate worktree for
almost every agent session (the sanctioned way to dodge the shared-checkout commit
jam, where the active-folder-guard rewrites WORKBOARD.md on every commit). Nothing
tears them down afterward:

  * PRs squash-merge into the base, so the source branch's commits are never
    ancestors of the base -> git forever reports them "unmerged" even though the
    work landed, and ``git branch -d`` will not reap them.
  * ``dev_land --delete-branch`` only deletes the *remote* branch; the local branch
    and the worktree linger.

Over weeks that compounds into dozens of branches and worktrees. Every guardrail in
the repo is commit-time (it stops bad commits); none manage ref *lifecycle*. This is
that missing janitor.

SAFETY CONTRACT
---------------
Reaps ONLY what is provably safe to lose:

  * worktrees with no uncommitted work (the branch ref survives; the worktree can be
    recreated with ``git worktree add``),
  * branches that are ancestors of the base (truly merged),
  * branches fully contained in their upstream -- every commit is already on the
    remote, so ``git fetch`` restores them.

NEVER touches: a branch with local-only commits, a branch with no upstream that is
not merged, or a worktree with uncommitted work. Those are reported, never reaped.

USAGE
-----
  python scripts/forge/tidy_refs.py             # dry-run: show what WOULD be reaped
  python scripts/forge/tidy_refs.py --apply     # reap the provably-safe set
  python scripts/forge/tidy_refs.py --base dev  # base to measure "merged" against
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def _git(args: list[str]) -> str:
    proc = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return proc.stdout if proc.returncode == 0 else ""


def _current_branch() -> str:
    return _git(["rev-parse", "--abbrev-ref", "HEAD"]).strip()


def _worktrees() -> list[dict[str, str]]:
    """Parsed ``git worktree list --porcelain`` entries (path, branch, is_dirty)."""
    out: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    for line in _git(["worktree", "list", "--porcelain"]).splitlines():
        if line.startswith("worktree "):
            if cur:
                out.append(cur)
            cur = {"path": line[len("worktree ") :].strip(), "branch": ""}
        elif line.startswith("branch "):
            cur["branch"] = line[len("branch ") :].strip().replace("refs/heads/", "")
    if cur:
        out.append(cur)
    for wt in out:
        status = subprocess.run(
            ["git", "-C", wt["path"], "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        wt["dirty"] = "yes" if status.stdout.strip() else "no"
    return out


def _branch_checked_out(branch: str, worktrees: list[dict[str, str]]) -> bool:
    return any(wt.get("branch") == branch for wt in worktrees)


def reap_worktrees(*, apply: bool) -> tuple[list[str], list[str]]:
    """Remove worktrees with no uncommitted work. Returns (removed, kept_dirty)."""
    main = str(ROOT).replace("\\", "/").rstrip("/")
    removed: list[str] = []
    kept: list[str] = []
    for wt in _worktrees():
        path = wt["path"].replace("\\", "/").rstrip("/")
        if path == main:
            continue  # never the primary checkout
        if wt.get("dirty") == "yes":
            kept.append(wt["path"])
            continue
        if apply:
            proc = subprocess.run(["git", "worktree", "remove", wt["path"]], cwd=ROOT, capture_output=True, text=True)
            if proc.returncode != 0:
                kept.append(wt["path"])
                continue
        removed.append(wt["path"])
    return removed, kept


def classify_branches(base: str) -> dict[str, list[tuple[str, str]]]:
    """Bucket every local branch (except base/current/checked-out) into reapable vs kept,
    each with a human reason."""
    worktrees = _worktrees()
    current = _current_branch()
    reapable: list[tuple[str, str]] = []
    kept: list[tuple[str, str]] = []

    fmt = "%(refname:short)|%(upstream:short)"
    for row in _git(["for-each-ref", "--format", fmt, "refs/heads/"]).splitlines():
        name, _, upstream = row.partition("|")
        name = name.strip()
        upstream = upstream.strip()
        if not name or name in {base, current}:
            continue
        if _branch_checked_out(name, worktrees):
            kept.append((name, "checked out in a worktree (holds WIP)"))
            continue
        # Ancestor of base -> truly merged.
        if subprocess.run(["git", "merge-base", "--is-ancestor", name, base], cwd=ROOT).returncode == 0:
            reapable.append((name, f"merged into {base}"))
            continue
        # Fully on its upstream -> every commit is on the remote (recoverable via fetch).
        if upstream and _git(["rev-parse", "--verify", upstream]):
            ahead = _git(["rev-list", "--count", f"{upstream}..{name}"]).strip()
            if ahead == "0":
                reapable.append((name, f"fully on remote {upstream}"))
                continue
            kept.append((name, f"ahead of {upstream} by {ahead} local commit(s)"))
            continue
        kept.append((name, "local-only, unmerged, no remote"))
    return {"reapable": reapable, "kept": kept}


def reap_branches(base: str, *, apply: bool) -> dict[str, list[tuple[str, str]]]:
    buckets = classify_branches(base)
    if apply:
        for name, reason in buckets["reapable"]:
            flag = "-d" if reason.startswith("merged") else "-D"  # -D only for remote-backed (recoverable)
            subprocess.run(["git", "branch", flag, name], cwd=ROOT, capture_output=True, text=True)
    return buckets


def main() -> int:
    ap = argparse.ArgumentParser(description="Reap landed/recoverable branches and stale worktrees.")
    ap.add_argument("--apply", action="store_true", help="actually reap (default is dry-run)")
    ap.add_argument("--base", default="dev", help="base branch to measure 'merged' against (default: dev)")
    args = ap.parse_args()

    mode = "APPLYING" if args.apply else "DRY-RUN (use --apply to reap)"
    print(f"=== Thomas ref janitor — {mode} | base={args.base} ===\n")

    wt_removed, wt_kept = reap_worktrees(apply=args.apply)
    verb = "Removed" if args.apply else "Would remove"
    print(f"WORKTREES: {verb} {len(wt_removed)} clean, kept {len(wt_kept)} dirty.")
    for p in wt_removed:
        print(f"  - {verb.lower()}: {p}")
    for p in wt_kept:
        print(f"  - kept (uncommitted work): {p}")

    buckets = reap_branches(args.base, apply=args.apply)
    verb = "Deleted" if args.apply else "Would delete"
    print(f"\nBRANCHES: {verb} {len(buckets['reapable'])} reapable, kept {len(buckets['kept'])}.")
    for name, reason in buckets["reapable"]:
        print(f"  - {verb.lower()}: {name}  ({reason})")
    print("\n  KEPT (never reaped — may hold unique work):")
    for name, reason in buckets["kept"]:
        print(f"  - keep: {name}  ({reason})")

    if not args.apply and (wt_removed or buckets["reapable"]):
        print("\nRun with --apply to reap the safe set above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
