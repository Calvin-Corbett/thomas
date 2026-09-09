#!/usr/bin/env python3
"""Apply (or verify) the Praxis server-side backstop: GitHub branch protection.

Part 4 of the cage (docs/BRANCH_PROTECTION_SETUP.md, docs/SAFETY_ARCHITECTURE.md).
This is the server-side mirror that catches anything the local cage misses -
the layer that is OUTSIDE every agent's reach.

It encodes the BRANCH_PROTECTION_SETUP.md ruleset as one idempotent command so
you don't hand-click the GitHub UI, and it fails *loudly and helpfully* when the
target repo's plan blocks protection (the current state of the private
``thomas-dev`` remote).

Usage:
    # Read-only: what is protected right now?
    python scripts/cage/apply_branch_protection.py verify --repo Calvin-Corbett/thomas-dev --branch dev
    python scripts/cage/apply_branch_protection.py verify --target both

    # Apply the full ruleset (requires gh auth with repo admin):
    python scripts/cage/apply_branch_protection.py apply --repo Calvin-Corbett/thomas-dev --branch dev

Requires the GitHub CLI (`gh`) authenticated as a repo admin.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any

# Convenience targets matching this project's remotes.
TARGETS = {
    "dev": ("Calvin-Corbett/thomas-dev", "dev"),
    "main": ("Calvin-Corbett/thomas", "main"),
}

# The required checks from BRANCH_PROTECTION_SETUP.md. gates-required is the
# aggregator; signed-commits-check enforces the signing story (B18).
REQUIRED_CONTEXTS = ["gates-required", "signed-commits-check"]

PLAN_BLOCK_HELP = """\
This repository's plan does not allow branch protection (HTTP 403:
"Upgrade to GitHub Pro or make this repository public").

The private 'thomas-dev' remote is on a free User plan, so its dev branch
cannot be protected via the API today. To unblock the server-side backstop,
pick ONE:

  (a) Upgrade the OWNER of thomas-dev (Calvin-Corbett) to GitHub Pro/Team, then
      re-run this 'apply'. (Note: protection keys off the REPO OWNER's plan, not
      the account you authenticate gh with.)
  (b) Make thomas-dev public, then re-run this 'apply'.
  (c) Move the protected integration branch to the public 'thomas' repo, whose
      'main' branch is ALREADY fully protected (verify with: ... verify --target main).

Until then the OS-level cage (Parts 1-3) is the enforcing layer; this server-side
backstop is enabled only on public 'thomas/main'.
"""


def _gh_api(args: list[str], *, method: str = "GET", body: dict[str, Any] | None = None) -> tuple[int, str]:
    cmd = ["gh", "api", "-X", method, *args]
    if body is not None:
        cmd += ["--input", "-"]
    proc = subprocess.run(
        cmd,
        input=json.dumps(body) if body is not None else None,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, (proc.stdout + proc.stderr)


def _protection_body() -> dict[str, Any]:
    return {
        "required_status_checks": {"strict": True, "contexts": REQUIRED_CONTEXTS},
        "enforce_admins": True,  # "do not allow bypassing"
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": True,
            "require_code_owner_reviews": True,
            "required_approving_review_count": 1,
        },
        "restrictions": None,
        "required_linear_history": True,
        "allow_force_pushes": False,
        "allow_deletions": False,
        "required_conversation_resolution": True,
        "block_creations": False,
    }


def verify(repo: str, branch: str) -> int:
    rc, out = _gh_api([f"repos/{repo}/branches/{branch}/protection"])
    if rc != 0:
        if "403" in out or "Upgrade to GitHub Pro" in out:
            print(f"[{repo}@{branch}] NOT PROTECTED - plan-blocked (403).")
            print(PLAN_BLOCK_HELP)
            return 2
        if "Branch not protected" in out or '"status":"404"' in out:
            print(f"[{repo}@{branch}] NOT PROTECTED - no protection rule exists yet.")
            print("  Run 'apply' to add one (will report a plan-block if the repo is private+free).")
            return 2
        print(f"[{repo}@{branch}] could not read protection: {out.strip()[:300]}")
        return 1
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        print(f"[{repo}@{branch}] unexpected response: {out.strip()[:300]}")
        return 1
    checks = (data.get("required_status_checks") or {}).get("contexts", [])
    sigs = (data.get("required_signatures") or {}).get("enabled")
    admins = (data.get("enforce_admins") or {}).get("enabled")
    pr = (data.get("required_pull_request_reviews") or {}).get("required_approving_review_count")
    linear = (data.get("required_linear_history") or {}).get("enabled")
    force = (data.get("allow_force_pushes") or {}).get("enabled")
    missing = [c for c in REQUIRED_CONTEXTS if c not in checks]
    print(f"[{repo}@{branch}] protected")
    print(f"  required checks : {checks}  {'OK' if not missing else 'MISSING ' + str(missing)}")
    print(f"  signed commits  : {sigs}")
    print(f"  enforce admins  : {admins}")
    print(f"  PR reviews req'd : {pr}")
    print(f"  linear history  : {linear}")
    print(f"  force pushes     : {force} (want False)")
    ok = not missing and bool(sigs) and bool(admins)
    print(f"  => {'FULLY ENFORCED' if ok else 'INCOMPLETE'}")
    return 0 if ok else 1


def apply(repo: str, branch: str) -> int:
    print(f"Applying branch protection to {repo}@{branch} ...")
    rc, out = _gh_api(
        [f"repos/{repo}/branches/{branch}/protection"],
        method="PUT",
        body=_protection_body(),
    )
    if rc != 0:
        if "403" in out or "Upgrade to GitHub Pro" in out:
            print(PLAN_BLOCK_HELP)
            return 2
        print(f"FAILED to apply protection: {out.strip()[:500]}")
        return 1
    print("  base protection applied.")

    # Required signatures is a separate endpoint; the project found PUT 404s but
    # POST works (see SCOREBOARD E1 notes).
    rc2, out2 = _gh_api(
        [f"repos/{repo}/branches/{branch}/protection/required_signatures"],
        method="POST",
    )
    if rc2 == 0:
        print("  required signatures enabled.")
    else:
        print(f"  WARN: could not enable required signatures: {out2.strip()[:300]}")
    print("\nVerifying result:")
    return verify(repo, branch)


def _resolve_targets(args: argparse.Namespace) -> list[tuple[str, str]]:
    if args.target:
        if args.target == "both":
            return [TARGETS["dev"], TARGETS["main"]]
        return [TARGETS[args.target]]
    if not args.repo or not args.branch:
        raise SystemExit("provide --target {dev,main,both} or both --repo and --branch")
    return [(args.repo, args.branch)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply/verify GitHub branch protection (Praxis Part 4).")
    parser.add_argument("command", choices=["apply", "verify"])
    parser.add_argument("--repo", default="", help="owner/name (or use --target)")
    parser.add_argument("--branch", default="", help="branch name (or use --target)")
    parser.add_argument("--target", choices=["dev", "main", "both"], default="", help="convenience preset")
    args = parser.parse_args(argv)

    worst = 0
    for repo, branch in _resolve_targets(args):
        rc = apply(repo, branch) if args.command == "apply" else verify(repo, branch)
        worst = max(worst, rc)
        print()
    return worst


if __name__ == "__main__":
    sys.exit(main())
