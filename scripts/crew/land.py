#!/usr/bin/env python3
"""land.py — the one sanctioned way for an agent to finish a unit.

Takes the current branch from "work committed locally" to "merged on dev with
zero human taps": rebase onto fresh dev, pre-flight the exact checks CI will
run (signatures first — unsigned commits were the #1 silent killer), push,
open a PR, arm auto-merge, watch the gate battery, and clean up after the
merge. Every failure prints a fix-it card with the concrete next command
instead of a dead end, because dead ends are how agents end up forking
branches-on-branches and stranding features.

Landing Lane component B (plans/thomas/PRODUCT_READY_PUSH_2026-07-15.md).
Check implementations live in land_checks.py.

Usage (from the worktree with the finished, committed unit):
    python scripts/crew/land.py --agent <id> --title "fix(x): ..." [--body-file PR_BODY.md]
    python scripts/crew/land.py --agent <id> --title "..." --no-watch   # fire and forget
    python scripts/crew/land.py --agent <id> --dry-run                  # preflight only

Never bypasses gates: protected-file diffs are detected up front and routed to
the commit_guarded / owner-tap flow instead of self-approval trailers.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Windows consoles default to cp1252; keep card output readable.
with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.crew.land_checks import (  # noqa: E402
    StepResult,
    card,
    check_growth,
    check_preconditions,
    detect_protected,
    gh,
    git,
    rebase_onto_base,
    rehearse_gates,
    verify_signatures,
)

DEFAULT_REMOTE = "dev-origin"
DEFAULT_BASE = "dev"
DEFAULT_REPO_SLUG = "Calvin-Corbett/thomas-dev"
WATCH_INTERVAL_SECONDS = 45
WATCH_TIMEOUT_SECONDS = 30 * 60


@dataclass
class LandReport:
    ok: bool
    steps: list[StepResult] = field(default_factory=list)
    branch: str = ""
    pr_url: str = ""
    merged: bool = False

    def to_json(self) -> str:
        return json.dumps(
            {
                "ok": self.ok,
                "branch": self.branch,
                "pr_url": self.pr_url,
                "merged": self.merged,
                "steps": [{"name": s.name, "ok": s.ok, "detail": s.detail, "fix": s.fix} for s in self.steps],
            },
            indent=2,
        )


def push_and_pr(repo: Path, *, remote: str, base: str, slug: str, title: str, body: str) -> tuple[StepResult, str]:
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    push = git(repo, "push", "--force-with-lease", "-u", remote, branch)
    if push.returncode != 0:
        return (
            StepResult(
                "push",
                False,
                push.stderr.strip()[:400],
                "if rejected by lease: someone updated the remote branch — fetch, inspect, rebase, re-run",
            ),
            "",
        )
    view = gh(repo, "pr", "view", branch, "--repo", slug, "--json", "url,state")
    pr_url = ""
    if view.returncode == 0:
        try:
            payload = json.loads(view.stdout)
            if payload.get("state") == "OPEN":
                pr_url = payload.get("url", "")
        except json.JSONDecodeError:
            pr_url = ""
    if not pr_url:
        create = gh(
            repo,
            "pr",
            "create",
            "--repo",
            slug,
            "--base",
            base,
            "--head",
            branch,
            "--title",
            title,
            "--body",
            body,
        )
        if create.returncode != 0:
            return (
                StepResult("pr.create", False, create.stderr.strip()[:400], "inspect gh error; re-run"),
                "",
            )
        pr_url = create.stdout.strip().splitlines()[-1]
    merge = gh(repo, "pr", "merge", pr_url, "--repo", slug, "--auto", "--squash")
    if merge.returncode != 0 and "already enabled" not in (merge.stderr or ""):
        return (
            StepResult(
                "pr.automerge",
                False,
                merge.stderr.strip()[:400],
                "enable auto-merge manually: gh pr merge <url> --auto --squash",
            ),
            pr_url,
        )
    return StepResult("pr", True, f"PR open with auto-merge armed: {pr_url}"), pr_url


def watch_checks(repo: Path, pr_url: str, slug: str, timeout_s: int) -> StepResult:
    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        state = gh(repo, "pr", "view", pr_url, "--repo", slug, "--json", "state")
        try:
            if json.loads(state.stdout).get("state") == "MERGED":
                return StepResult("watch", True, "PR merged")
        except (json.JSONDecodeError, AttributeError):
            pass
        checks = gh(repo, "pr", "checks", pr_url, "--repo", slug)
        rows = [r for r in checks.stdout.splitlines() if r.strip()]
        fails = [r for r in rows if "\tfail\t" in r]
        pending = [r for r in rows if "\tpending\t" in r]
        required_failed = [r for r in fails if r.startswith(("gates-required", "signed-commits-check"))]
        if required_failed:
            names = ", ".join(r.split("\t")[0] for r in required_failed)
            return StepResult(
                "watch",
                False,
                f"required checks failed: {names}\n" + "\n".join(fails[:6]),
                "pull the failing gate log: gh run view <run-id> --log-failed; fix; commit; re-run land.py "
                "(auto-merge stays armed — a green re-push merges itself)",
            )
        last = f"{len(pending)} pending / {len(fails)} failing (non-required)"
        time.sleep(10 if not pending else WATCH_INTERVAL_SECONDS)
    return StepResult(
        "watch",
        False,
        f"timed out after {timeout_s}s ({last})",
        "checks still running; auto-merge stays armed. Re-check later: gh pr view <url>",
    )


def finish(repo: Path, base: str, remote: str, branch: str) -> StepResult:
    dirty = git(repo, "status", "--porcelain").stdout.strip()
    if dirty:
        return StepResult(
            "finish.sync",
            False,
            "working tree gained changes during landing; not resetting",
            f"stash or commit them, then: git checkout {base} && git fetch {remote} && "
            f"git reset --hard {remote}/{base} && git branch -D {branch}",
        )
    checkout = git(repo, "checkout", base)
    if checkout.returncode != 0:
        # e.g. base is checked out in another worktree — resetting HERE would
        # mangle the feature branch (codex review finding, PR 103).
        return StepResult(
            "finish.sync",
            False,
            f"could not check out {base}:\n{checkout.stderr.strip()[:300]}",
            f"sync manually from the worktree that owns {base}: git fetch {remote} && "
            f"git reset --hard {remote}/{base}; then delete this branch: git branch -D {branch}",
        )
    fetch = git(repo, "fetch", remote, base)
    if fetch.returncode != 0:
        return StepResult("finish.sync", False, fetch.stderr.strip()[:300], "fetch failed; sync manually")
    reset = git(repo, "reset", "--hard", f"{remote}/{base}")
    if reset.returncode != 0:
        return StepResult("finish.sync", False, reset.stderr.strip()[:300], "reset failed; inspect state manually")
    delete = git(repo, "branch", "-D", branch)
    note = "" if delete.returncode == 0 else f" (branch delete failed: {delete.stderr.strip()[:120]})"
    return StepResult("finish.sync", True, f"{base} synced to {remote}/{base}; {branch} deleted{note}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Finish a unit: rebase, preflight, push, PR, auto-merge, cleanup.")
    parser.add_argument("--agent", required=True, help="Agent id (audit trail).")
    parser.add_argument("--title", default="", help="PR title (required unless --dry-run).")
    parser.add_argument("--body", default="", help="PR body text.")
    parser.add_argument("--body-file", default="", help="Path to PR body markdown.")
    parser.add_argument("--repo-root", default=str(_REPO_ROOT))
    parser.add_argument("--remote", default=DEFAULT_REMOTE)
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--slug", default=DEFAULT_REPO_SLUG)
    parser.add_argument("--no-watch", action="store_true", help="Arm auto-merge and exit without polling.")
    parser.add_argument("--no-cleanup", action="store_true", help="Skip base sync/branch delete after merge.")
    parser.add_argument("--watch-timeout", type=int, default=WATCH_TIMEOUT_SECONDS)
    parser.add_argument("--dry-run", action="store_true", help="Preflight only: no push, no PR.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    repo = Path(args.repo_root).resolve()
    report = LandReport(ok=True)
    report.branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def add(steps: list[StepResult] | StepResult) -> bool:
        items = steps if isinstance(steps, list) else [steps]
        for s in items:
            report.steps.append(s)
            if not args.json:
                print(card(s))
            if not s.ok:
                report.ok = False
        return report.ok

    base_ref = f"{args.remote}/{args.base}"
    preflight_ok = (
        add(check_preconditions(repo, args.base, args.remote))
        and add(rebase_onto_base(repo, args.base, args.remote))
        and add(detect_protected(repo, base_ref))
        and add(verify_signatures(repo, args.base, args.remote))
        and add(check_growth(repo, base_ref))
    )
    if preflight_ok:
        add(rehearse_gates(repo))

    if report.ok and not args.dry_run:
        if not args.title:
            add(StepResult("pr.title", False, "no --title given", "re-run with --title '<conventional title>'"))
        else:
            body = args.body
            if args.body_file:
                body = Path(args.body_file).read_text(encoding="utf-8")
            body = (body or "Landed via scripts/crew/land.py.") + (
                "\n\n🤖 Landed by agent `" + args.agent + "` via the Landing Lane."
            )
            step, pr_url = push_and_pr(
                repo, remote=args.remote, base=args.base, slug=args.slug, title=args.title, body=body
            )
            report.pr_url = pr_url
            if add(step) and not args.no_watch:
                watch = watch_checks(repo, pr_url, args.slug, args.watch_timeout)
                add(watch)
                report.merged = watch.ok and "merged" in watch.detail
                if report.merged and not args.no_cleanup:
                    add(finish(repo, args.base, args.remote, report.branch))

    if args.json:
        print(report.to_json())
    elif report.ok:
        print(
            "\nLANDED" if report.merged else "\nPREFLIGHT GREEN" if args.dry_run else "\nIN FLIGHT (auto-merge armed)"
        )
    else:
        print("\nBLOCKED — fix the cards above and re-run. Do not fork a new branch to escape a blocker.")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
