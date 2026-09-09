#!/usr/bin/env python3
"""Apply/check GitHub branch protection for dev/prod release lanes."""

from __future__ import annotations

import argparse
import getpass
import json
import os
from collections.abc import Sequence
from typing import Any

import scripts.configure_github_branch_protection as branch_protection


def _branch_exists(repo: str, branch: str, token: str) -> bool:
    path = f"/repos/{repo}/branches/{branch}"
    try:
        branch_protection._request_github(method="GET", path=path, token=token)
        return True
    except Exception as exc:
        text = str(exc).lower()
        if "404" in text or "not found" in text:
            return False
        raise


def _set_default_branch(repo: str, branch: str, token: str) -> None:
    branch_protection._request_github(
        method="PATCH",
        path=f"/repos/{repo}",
        token=token,
        payload={"default_branch": branch},
    )


def _build_profile(*, required_checks: tuple[str, ...], approvals: int) -> branch_protection.ProtectionProfile:
    return branch_protection.ProtectionProfile(
        strict_checks=True,
        required_checks=required_checks,
        enforce_admins=True,
        dismiss_stale_reviews=True,
        require_code_owner_reviews=False,
        required_approvals=max(1, int(approvals)),
        require_conversation_resolution=True,
        require_linear_history=True,
        allow_force_pushes=False,
        allow_deletions=False,
    )


def _apply_or_check_branch(
    *,
    mode: str,
    repo: str,
    branch: str,
    profile: branch_protection.ProtectionProfile,
    token: str,
) -> dict[str, Any]:
    path = f"/repos/{repo}/branches/{branch}/protection"
    expected = branch_protection._expected_normalized(profile)

    if mode == "apply":
        branch_protection._request_github(
            method="PUT",
            path=path,
            token=token,
            payload=profile.to_payload(),
        )

    current_response = branch_protection._request_github(method="GET", path=path, token=token)
    current = branch_protection._normalize_current(current_response)
    mismatches = branch_protection._diff_profile(expected=expected, current=current)
    return {
        "branch": branch,
        "ok": not mismatches,
        "required_checks": list(profile.required_checks),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
    }


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Configure dev/prod GitHub release lanes with hardened branch protection."
    )
    parser.add_argument("--repo", default="", help="GitHub repo slug owner/repo (default: origin remote).")
    parser.add_argument("--dev-branch", default="dev", help="Development branch name (default: dev).")
    parser.add_argument("--prod-branch", default="prod", help="Production branch name (default: prod).")
    parser.add_argument(
        "--required-check",
        action="append",
        default=["required-gates"],
        help="Required status check context (repeatable).",
    )
    parser.add_argument(
        "--dev-approvals",
        type=int,
        default=1,
        help="Required approvals for dev branch (default: 1).",
    )
    parser.add_argument(
        "--prod-approvals",
        type=int,
        default=1,
        help="Required approvals for prod branch (default: 1).",
    )
    parser.add_argument("--token", default="", help="GitHub token with administration permission.")
    parser.add_argument(
        "--token-env",
        default="GH_TOKEN",
        help="Environment variable for GitHub token (default: GH_TOKEN).",
    )
    parser.add_argument(
        "--set-default-dev",
        action="store_true",
        help="Set repository default branch to the dev branch after protections are verified.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true", help="Apply protections and verify.")
    mode.add_argument("--check", action="store_true", help="Check existing protections.")
    mode.add_argument("--dry-run", action="store_true", help="Print intended settings only.")
    args = parser.parse_args(argv)

    repo = str(args.repo or "").strip() or (branch_protection._default_repo_slug() or "")
    if not repo:
        message = "repo is required (pass --repo owner/repo or set git origin)"
        if args.json:
            print(json.dumps({"ok": False, "error": message}, sort_keys=True))
        else:
            print("GitHub release lanes: FAIL")
            print(f"- {message}")
        return 1

    required_checks = branch_protection._required_checks(args.required_check or [])
    dev_profile = _build_profile(required_checks=required_checks, approvals=int(args.dev_approvals))
    prod_profile = _build_profile(required_checks=required_checks, approvals=int(args.prod_approvals))

    output: dict[str, Any] = {
        "ok": True,
        "repo": repo,
        "dev_branch": str(args.dev_branch),
        "prod_branch": str(args.prod_branch),
        "required_checks": list(required_checks),
        "mode": "dry_run" if args.dry_run else ("apply" if args.apply else "check"),
        "results": [],
    }

    if args.dry_run:
        output["results"] = [
            {
                "branch": str(args.dev_branch),
                "profile": dev_profile.to_payload(),
            },
            {
                "branch": str(args.prod_branch),
                "profile": prod_profile.to_payload(),
            },
        ]
        if args.set_default_dev:
            output["set_default_branch"] = str(args.dev_branch)
        if args.json:
            print(json.dumps(output, sort_keys=True))
        else:
            print("GitHub release lanes: PASS (dry-run)")
            print(f"- repo: {repo}")
            print(f"- dev branch: {args.dev_branch}")
            print(f"- prod branch: {args.prod_branch}")
            print(f"- required checks: {', '.join(required_checks)}")
            if args.set_default_dev:
                print(f"- default branch will be set to: {args.dev_branch}")
        return 0

    token = str(args.token or "").strip() or str(os.environ.get(str(args.token_env or "").strip(), "")).strip()
    if not token and not args.json and os.isatty(0):
        token = getpass.getpass("GitHub token (repo administration scope): ").strip()
    if not token:
        message = f"token required (pass --token or set {args.token_env})"
        if args.json:
            print(json.dumps({"ok": False, "repo": repo, "error": message}, sort_keys=True))
        else:
            print("GitHub release lanes: FAIL")
            print(f"- {message}")
        return 1

    try:
        missing_branches = [
            name for name in (str(args.dev_branch), str(args.prod_branch)) if not _branch_exists(repo, name, token)
        ]
        if missing_branches:
            output["ok"] = False
            output["missing_branches"] = missing_branches
            output["error"] = (
                "remote branch(es) missing: " + ", ".join(missing_branches) + ". Create/push these branches first."
            )
        else:
            dev_result = _apply_or_check_branch(
                mode="apply" if args.apply else "check",
                repo=repo,
                branch=str(args.dev_branch),
                profile=dev_profile,
                token=token,
            )
            prod_result = _apply_or_check_branch(
                mode="apply" if args.apply else "check",
                repo=repo,
                branch=str(args.prod_branch),
                profile=prod_profile,
                token=token,
            )
            output["results"] = [dev_result, prod_result]
            output["ok"] = bool(dev_result.get("ok")) and bool(prod_result.get("ok"))

            if output["ok"] and bool(args.set_default_dev):
                _set_default_branch(repo, str(args.dev_branch), token)
                output["default_branch_set_to"] = str(args.dev_branch)
    except Exception as exc:
        output["ok"] = False
        output["error"] = str(exc)

    if args.json:
        print(json.dumps(output, sort_keys=True))
    else:
        if output["ok"]:
            print("GitHub release lanes: PASS")
            print(f"- repo: {repo}")
            for result in list(output.get("results") or []):
                print(f"- branch {result['branch']}: ok={result['ok']} (mismatches={result['mismatch_count']})")
            if output.get("default_branch_set_to"):
                print(f"- default branch set to: {output['default_branch_set_to']}")
        else:
            print("GitHub release lanes: FAIL")
            if output.get("error"):
                print(f"- {output['error']}")
            if output.get("missing_branches"):
                print("- missing branches: " + ", ".join(list(output.get("missing_branches") or [])))
            for result in list(output.get("results") or []):
                if not bool(result.get("ok")):
                    print(f"- branch {result['branch']} mismatches:")
                    for item in list(result.get("mismatches") or []):
                        print(f"  - {item}")

    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(run())
