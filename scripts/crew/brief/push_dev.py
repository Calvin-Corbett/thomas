#!/usr/bin/env python3
"""Push ``dev`` to the dev remote after a landing, from a clean worktree, with the hooks running.

    python scripts/crew/brief/push_dev.py --agent <id> [--remote dev-origin] [--branch dev] [--json]

Why: nothing was pushed between 2026-09-07 and 2026-11-03, so one push carried 980 commits and every check that had
drifted in that time stopped it at once. Pushing after each landing keeps the range small and the drift visible the day
it appears.

What it does, in order, and stops at the first that says no:
  1. no such remote, or the branch is already on the remote: nothing to do, and it says which.
  2. adds a throwaway detached worktree at the tip, so the hooks judge the committed tree and not your working copy.
  3. pushes the tip commit to ``<remote> <branch>`` from that worktree with the hooks on (never ``--no-verify``, never
     ``--force``). The claim gate gets the explicit fallback of ``push_claim`` because a fresh worktree holds no claim.
  4. removes the worktree it added, whatever happened.

When the remote refuses the branch (protected, not a fast-forward, a server-side hook) nothing is changed anywhere and
the answer says so; branch protection is never touched. When a local hook fails, the answer carries the hook's output.

Exit codes: 0 pushed, already pushed, or the remote refused (said plainly); 1 a hook or the push failed (blocked); 2 usage.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.crew.brief.git_reads import run_git
from scripts.crew.brief.push_claim import landed_push_env

LOCK_NAME = "thomas-push-dev.lock"
LOCK_MAX_AGE_S = 2 * 3600.0
# Printed only by the remote step of a push, which comes after the local hooks passed.
REFUSED_MARKERS = ("[remote rejected]", "[rejected]", "protected branch")


@dataclass
class PushResult:
    status: str  # pushed | up_to_date | no_remote | no_branch | busy | refused | blocked
    pushed: bool
    message: str
    sha: str = ""
    output: str = ""

    @property
    def exit_code(self) -> int:
        return 1 if self.status == "blocked" else 0


def _git(root: Path, *args: str, env: dict[str, str] | None = None, timeout: float = 120.0) -> tuple[int, str]:
    done = run_git(root, args, env=env, timeout=timeout)
    text = (done.stdout or b"").decode("utf-8", "replace") + (done.stderr or b"").decode("utf-8", "replace")
    return done.returncode, text.strip()


def _take_lock(root: Path) -> Path | None:
    rc, common = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if rc != 0 or not common:
        return None
    lock = Path(common) / LOCK_NAME
    try:
        if lock.exists() and time.time() - lock.stat().st_mtime > LOCK_MAX_AGE_S:
            lock.unlink()
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return None
    os.close(fd)
    return lock


def push_landed(
    root: Path,
    *,
    agent: str,
    remote: str = "dev-origin",
    branch: str = "dev",
    base_env: dict[str, str] | None = None,
    timeout: float = 3600.0,
) -> PushResult:
    rc, _ = _git(root, "remote", "get-url", remote)
    if rc != 0:
        return PushResult("no_remote", False, f"nothing pushed: remote `{remote}` is not configured here")
    rc, sha = _git(root, "rev-parse", "--verify", f"refs/heads/{branch}")
    if rc != 0:
        return PushResult("no_branch", False, f"nothing pushed: there is no local branch `{branch}`")
    rc, ahead = _git(root, "rev-list", "--count", f"refs/remotes/{remote}/{branch}..{sha}")
    if rc == 0 and ahead.strip() == "0":
        return PushResult("up_to_date", False, f"nothing to push: `{remote}/{branch}` already has {sha[:12]}", sha=sha)
    env = landed_push_env(agent, os.environ if base_env is None else base_env)
    lock = _take_lock(root)
    if lock is None:
        return PushResult("busy", False, "nothing pushed: another push of this branch is running", sha=sha)
    work = Path(tempfile.mkdtemp(prefix="thomas-push-dev-"))
    tree = work / "tree"
    try:
        rc, out = _git(root, "worktree", "add", "--detach", str(tree), sha)
        if rc != 0:
            return PushResult(
                "blocked", False, f"nothing pushed: could not add a clean worktree: {out[-400:]}", sha=sha
            )
        rc, out = _git(tree, "push", remote, f"{sha}:refs/heads/{branch}", env=env, timeout=timeout)
        if rc == 0:
            return PushResult("pushed", True, f"pushed {sha[:12]} to `{remote}/{branch}`", sha=sha, output=out[-1500:])
        if any(marker in out.lower() for marker in REFUSED_MARKERS):
            return PushResult(
                "refused", False, f"nothing changed: `{remote}` refused `{branch}`: {out[-400:]}", sha=sha, output=out
            )
        return PushResult(
            "blocked", False, f"not pushed: the checks or the push failed: {out[-2000:]}", sha=sha, output=out
        )
    finally:
        _git(root, "worktree", "remove", "--force", str(tree))
        shutil.rmtree(work, ignore_errors=True)
        _git(root, "worktree", "prune")
        with contextlib.suppress(OSError):
            lock.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agent", default="", help="agent id (else AGENT_ID or THOMAS_AGENT_ID)")
    parser.add_argument("--remote", default="dev-origin")
    parser.add_argument("--branch", default="dev")
    parser.add_argument("--root", default=str(_REPO_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    agent = args.agent or os.environ.get("AGENT_ID", "") or os.environ.get("THOMAS_AGENT_ID", "")
    if not agent.strip():
        print("push_dev.py needs an agent id (--agent, AGENT_ID or THOMAS_AGENT_ID)", file=sys.stderr)
        return 2
    result = push_landed(Path(args.root), agent=agent, remote=args.remote, branch=args.branch)
    print(json.dumps(asdict(result), sort_keys=True) if args.json else result.message)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
