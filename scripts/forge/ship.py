#!/usr/bin/env python3
"""Ship: take a dirty tree all the way to GitHub ``dev`` and back to this machine.

``ship`` is Thomas's end-to-end wrap-up. One command closes the whole loop:

    dirty tree
      -> stage + commit (through the Forge gates)
      -> push the feature branch
      -> merge the PR into the protected ``dev`` branch (owner override)
      -> sync this machine (fast-forward local ``dev`` to the merged tip)

It is a *thin orchestrator* over already-proven tools, not a reimplementation:

  * commits run through the normal pre-commit gate stack. The code-quality and
    security spine (ruff, secret-scan, enforcement-integrity, protected-files,
    monolith, commit-growth) is ALWAYS enforced. The workflow/coordination/
    location gates relax only when QuickBuilder mode is active (a signed,
    human-authorized flag) -- ``ship`` checks for it and says how to enable it.
  * the dangerous step -- merging into protected ``dev`` -- delegates to
    ``scripts/dev_land.py``, whose ``try/finally`` ALWAYS restores branch
    protection even if the merge errors. ``ship`` never touches protection
    itself.

Because the merge (and optionally QuickBuilder activation) need a Windows
credential tap, ``ship`` is an owner tool: it cannot run fully headless. Run
``--dry-run`` first to see the exact plan with zero side effects.

Usage (from a Thomas worktree):
    python scripts/forge/ship.py -m "fix: thing"            # full loop
    python scripts/forge/ship.py -m "wip" --no-merge        # commit + push only
    python scripts/forge/ship.py --dry-run -m "preview"     # plan, no side effects
    python scripts/forge/ship.py -m "x" --pr 70             # reuse an existing PR

Phase flags (``--no-commit/--no-push/--no-merge/--no-sync``) let ``ship`` double
as a resumable recovery tool when a single phase fails midway.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.forge.ship_phases import (  # noqa: E402
    current_branch,
    git,
    has_uncommitted_changes,
    phase_commit,
    phase_merge,
    phase_push,
    phase_sync,
    resolve_agent,
)


def run_ship(
    *,
    message: str,
    base: str = "dev",
    repo: str = "Calvin-Corbett/thomas-dev",
    remote: str = "dev-origin",
    merge: str = "squash",
    pr: str | None = None,
    agent: str | None = None,
    do_commit: bool = True,
    do_push: bool = True,
    do_merge: bool = True,
    do_sync: bool = True,
    dry_run: bool = False,
) -> int:
    cwd = Path.cwd()
    try:
        cwd = Path(git(["rev-parse", "--show-toplevel"], cwd=cwd))
    except RuntimeError:
        print("ERROR: not inside a git repository.")
        return 1

    branch = current_branch(cwd)
    agent_id = resolve_agent(agent)
    mode = "DRY-RUN" if dry_run else "LIVE"
    print(f"\n  thomas ship [{mode}] -- branch '{branch}' -> {repo}:{base}\n")

    if branch in (base, "main", "master", "HEAD"):
        print(f"ERROR: refusing to ship from '{branch}'. Switch to a feature branch first.")
        return 1
    if do_commit and not message and has_uncommitted_changes(cwd):
        print("ERROR: uncommitted changes need a commit message (-m).")
        return 1

    try:
        if do_commit:
            phase_commit(cwd, branch, message, agent_id, dry_run)
        if do_push:
            phase_push(cwd, branch, remote, dry_run)
        landed_pr = phase_merge(cwd, repo, base, branch, pr, merge, dry_run) if do_merge else None
        if do_sync:
            phase_sync(cwd, remote, base, dry_run)
    except RuntimeError as exc:
        print(f"\n  SHIP HALTED: {exc}\n")
        return 1

    print("\n  [OK] ship complete" + (" (dry-run, no changes made)" if dry_run else ""))
    if not dry_run and do_merge and landed_pr:
        print(f"    PR #{landed_pr} is on {base}; this machine is synced.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-m", "--message", default="", help="Commit message (required if the tree is dirty).")
    parser.add_argument("--base", default="dev", help="Target branch to merge into (default: dev).")
    parser.add_argument("--repo", default="Calvin-Corbett/thomas-dev", help="GitHub OWNER/REPO for the merge.")
    parser.add_argument("--remote", default="dev-origin", help="Git remote to push to (default: dev-origin).")
    parser.add_argument("--merge", choices=["squash", "merge", "rebase"], default="squash")
    parser.add_argument("--pr", default=None, help="Existing PR number to land (skips PR lookup/creation).")
    parser.add_argument("--agent", default=None, help="Agent id for the commit trailer/claim.")
    parser.add_argument("--no-commit", action="store_true", help="Skip the commit phase.")
    parser.add_argument("--no-push", action="store_true", help="Skip the push phase.")
    parser.add_argument("--no-merge", action="store_true", help="Stop after push (no dev merge).")
    parser.add_argument("--no-sync", action="store_true", help="Skip syncing dev back to this machine.")
    parser.add_argument("--dry-run", action="store_true", help="Show the plan without making any changes.")
    args = parser.parse_args()

    return run_ship(
        message=args.message,
        base=args.base,
        repo=args.repo,
        remote=args.remote,
        merge=args.merge,
        pr=args.pr,
        agent=args.agent,
        do_commit=not args.no_commit,
        do_push=not args.no_push,
        do_merge=not args.no_merge,
        do_sync=not args.no_sync,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
