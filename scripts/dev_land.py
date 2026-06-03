#!/usr/bin/env python3
"""Land a PR into a protected branch with a Windows-Hello-approved owner override.

The "approve, don't block" flow: GitHub branch protection stays ON for everyone,
and a human with admin lands a specific PR by *approving it with a Windows
credential tap*. The script then lifts ``enforce_admins`` on the base branch,
merges the PR with ``--admin`` (bypassing the stale/infra required checks), and
ALWAYS restores protection afterwards -- even if the merge errors.

Usage (from the Thomas repo root):
    python scripts/dev_land.py <PR-number>
        [--repo OWNER/REPO] [--base dev] [--merge squash|merge|rebase] [--delete-branch]

Requires:
  * admin on the repo (gh auth), and
  * an interactive Windows session for the approval tap.
A headless agent cannot produce the credential prompt, so it cannot land a PR
through this tool -- the human tap is the gate.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Put the repo root on sys.path so `from scripts.breakglass_auth import ...`
# resolves when invoked as `python scripts/dev_land.py` (sys.path[0] is scripts/).
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _gh(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()}")
    return proc


def _is_admin(repo: str) -> bool:
    proc = _gh(["api", f"repos/{repo}", "--jq", ".permissions.admin"], check=False)
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def _enforce_admins_enabled(repo: str, base: str) -> bool:
    proc = _gh(["api", f"repos/{repo}/branches/{base}/protection/enforce_admins"], check=False)
    if proc.returncode != 0:
        return False
    try:
        return bool(json.loads(proc.stdout).get("enabled"))
    except (ValueError, json.JSONDecodeError):
        return False


def _approve_with_windows_credential(repo: str, pr: str, base: str) -> bool:
    """Require a Windows credential tap before the owner-override merge."""
    if os.name != "nt":
        print("ERROR: the approval tap requires an interactive Windows session.")
        return False
    try:
        from scripts.breakglass_auth import (
            BreakglassAuthorization,
            _current_windows_sam_name,
            _run_windows_credential_prompt,
        )
    except ImportError:
        from breakglass_auth import (  # type: ignore[no-redef]
            BreakglassAuthorization,
            _current_windows_sam_name,
            _run_windows_credential_prompt,
        )

    user = _current_windows_sam_name() or "unknown"
    print(f"\n  Account: {user}")
    print(f"  Approve landing PR #{pr} into {repo}:{base} (owner override past branch protection).")
    print("  A Windows sign-in prompt will appear.\n")
    result: BreakglassAuthorization = _run_windows_credential_prompt(
        prompt_caption="Thomas dev-land approval",
        prompt_message=(
            f"Approve owner-override merge of PR #{pr} into {repo}:{base}.\n"
            f"Account: {user}\nWindows may offer PIN, password, or Windows Hello."
        ),
    )
    if result.ok:
        print(f"  Approved by: {result.actor}")
        return True
    print("  Approval cancelled." if result.cancelled else f"  Approval failed: {result.message}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pr", help="PR number to land")
    parser.add_argument("--repo", default="Calvin-Corbett/thomas-dev")
    parser.add_argument("--base", default="dev")
    parser.add_argument("--merge", choices=["squash", "merge", "rebase"], default="squash")
    parser.add_argument("--delete-branch", action="store_true")
    args = parser.parse_args()

    if not _is_admin(args.repo):
        print(f"ERROR: you are not an admin on {args.repo}; cannot owner-override.")
        return 1

    if not _approve_with_windows_credential(args.repo, str(args.pr), args.base):
        return 1

    was_enabled = _enforce_admins_enabled(args.repo, args.base)
    print(f"  enforce_admins on {args.base}: {'ON' if was_enabled else 'OFF'}")
    lifted = False
    try:
        if was_enabled:
            print("  Lifting enforce_admins...")
            _gh(["api", "-X", "DELETE", f"repos/{args.repo}/branches/{args.base}/protection/enforce_admins"])
            lifted = True
        print(f"  Merging PR #{args.pr} (--{args.merge} --admin)...")
        merge_args = ["pr", "merge", str(args.pr), "--repo", args.repo, f"--{args.merge}", "--admin"]
        if args.delete_branch:
            merge_args.append("--delete-branch")
        proc = _gh(merge_args, check=False)
        if proc.returncode != 0:
            print(f"  MERGE FAILED: {(proc.stderr or proc.stdout).strip()}")
            return 1
        print(f"  PR #{args.pr} merged into {args.base}.")
        return 0
    finally:
        if lifted:
            restore = _gh(
                ["api", "-X", "POST", f"repos/{args.repo}/branches/{args.base}/protection/enforce_admins"],
                check=False,
            )
            ok = False
            try:
                ok = bool(json.loads(restore.stdout).get("enabled"))
            except (ValueError, json.JSONDecodeError):
                ok = False
            print(f"  enforce_admins restored: {'ON' if ok else 'FAILED -- RE-ENABLE MANUALLY'}")


if __name__ == "__main__":
    raise SystemExit(main())
