#!/usr/bin/env python3
"""Apply or verify GitHub branch protection for this repository."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
GITHUB_API = "https://api.github.com"
DEFAULT_REQUIRED_CHECKS: tuple[str, ...] = ("required-gates",)


@dataclass(frozen=True)
class ProtectionProfile:
    strict_checks: bool
    required_checks: tuple[str, ...]
    enforce_admins: bool
    dismiss_stale_reviews: bool
    require_code_owner_reviews: bool
    required_approvals: int
    require_conversation_resolution: bool
    require_linear_history: bool
    allow_force_pushes: bool
    allow_deletions: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "required_status_checks": {
                "strict": self.strict_checks,
                "contexts": list(self.required_checks),
            },
            "enforce_admins": self.enforce_admins,
            "required_pull_request_reviews": {
                "dismiss_stale_reviews": self.dismiss_stale_reviews,
                "require_code_owner_reviews": self.require_code_owner_reviews,
                "required_approving_review_count": self.required_approvals,
                "require_last_push_approval": False,
            },
            "restrictions": None,
            "required_linear_history": self.require_linear_history,
            "allow_force_pushes": self.allow_force_pushes,
            "allow_deletions": self.allow_deletions,
            "required_conversation_resolution": self.require_conversation_resolution,
            "lock_branch": False,
            "allow_fork_syncing": True,
        }


def _run_git(args: Sequence[str]) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    out = str(proc.stdout or "").strip()
    return out or None


def _repo_slug_from_remote(url: str) -> str | None:
    raw = str(url or "").strip()
    if not raw:
        return None
    text = raw.replace("\\", "/")
    https_match = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?$", text)
    if https_match:
        owner = https_match.group("owner").strip()
        repo = https_match.group("repo").strip()
        if owner and repo:
            return f"{owner}/{repo}"
    return None


def _default_repo_slug() -> str | None:
    remote = _run_git(["remote", "get-url", "origin"])
    if not remote:
        return None
    return _repo_slug_from_remote(remote)


def _required_checks(values: Sequence[str]) -> tuple[str, ...]:
    checks: list[str] = []
    for raw in values:
        token = str(raw or "").strip()
        if token:
            checks.append(token)
    if not checks:
        return DEFAULT_REQUIRED_CHECKS
    dedup: list[str] = []
    seen = set()
    for item in checks:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        dedup.append(item)
    return tuple(dedup)


def _request_github(
    *,
    method: str,
    path: str,
    token: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "thomas-branch-protection-script",
    }
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"

    req = urllib.request.Request(
        f"{GITHUB_API}{path}",
        data=body,
        headers=headers,
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        raise RuntimeError(f"GitHub API {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub API network error: {exc.reason}") from exc


def _normalize_current(response: dict[str, Any]) -> dict[str, Any]:
    required_status_checks = dict(response.get("required_status_checks") or {})
    pull_reviews = dict(response.get("required_pull_request_reviews") or {})
    return {
        "strict_checks": bool(required_status_checks.get("strict", False)),
        "required_checks": sorted([str(x) for x in (required_status_checks.get("contexts") or [])]),
        "enforce_admins": bool((response.get("enforce_admins") or {}).get("enabled", False)),
        "dismiss_stale_reviews": bool(pull_reviews.get("dismiss_stale_reviews", False)),
        "require_code_owner_reviews": bool(pull_reviews.get("require_code_owner_reviews", False)),
        "required_approvals": int(pull_reviews.get("required_approving_review_count") or 0),
        "require_conversation_resolution": bool(
            (response.get("required_conversation_resolution") or {}).get("enabled", False)
        ),
        "require_linear_history": bool((response.get("required_linear_history") or {}).get("enabled", False)),
        "allow_force_pushes": bool((response.get("allow_force_pushes") or {}).get("enabled", False)),
        "allow_deletions": bool((response.get("allow_deletions") or {}).get("enabled", False)),
    }


def _expected_normalized(profile: ProtectionProfile) -> dict[str, Any]:
    return {
        "strict_checks": profile.strict_checks,
        "required_checks": sorted(list(profile.required_checks)),
        "enforce_admins": profile.enforce_admins,
        "dismiss_stale_reviews": profile.dismiss_stale_reviews,
        "require_code_owner_reviews": profile.require_code_owner_reviews,
        "required_approvals": profile.required_approvals,
        "require_conversation_resolution": profile.require_conversation_resolution,
        "require_linear_history": profile.require_linear_history,
        "allow_force_pushes": profile.allow_force_pushes,
        "allow_deletions": profile.allow_deletions,
    }


def _diff_profile(*, expected: dict[str, Any], current: dict[str, Any]) -> list[str]:
    mismatches: list[str] = []
    for key in sorted(expected):
        if expected[key] != current.get(key):
            mismatches.append(f"{key}: expected={expected[key]!r} current={current.get(key)!r}")
    return mismatches


def _build_profile(args: argparse.Namespace) -> ProtectionProfile:
    required_checks = _required_checks(args.required_check or [])
    return ProtectionProfile(
        strict_checks=bool(args.strict_checks),
        required_checks=required_checks,
        enforce_admins=not bool(args.no_enforce_admins),
        dismiss_stale_reviews=not bool(args.no_dismiss_stale_reviews),
        require_code_owner_reviews=bool(args.require_code_owner_reviews),
        required_approvals=int(args.required_approvals),
        require_conversation_resolution=not bool(args.no_require_conversation_resolution),
        require_linear_history=not bool(args.no_require_linear_history),
        allow_force_pushes=bool(args.allow_force_pushes),
        allow_deletions=bool(args.allow_deletions),
    )


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply or verify GitHub branch protection settings for this repository."
    )
    parser.add_argument(
        "--repo",
        default="",
        help="GitHub repo slug (owner/repo). Defaults to git origin remote.",
    )
    parser.add_argument("--branch", default="main", help="Branch to protect (default: main).")
    parser.add_argument(
        "--token",
        default="",
        help="GitHub token with repository administration permission.",
    )
    parser.add_argument(
        "--token-env",
        default="GH_TOKEN",
        help="Environment variable to read token from when --token is omitted (default: GH_TOKEN).",
    )
    parser.add_argument(
        "--required-check",
        action="append",
        default=[],
        help="Required check context name (repeatable). Default: required-gates.",
    )
    parser.add_argument(
        "--required-approvals",
        type=int,
        default=1,
        help="Required PR approvals (default: 1).",
    )
    parser.add_argument(
        "--require-code-owner-reviews",
        action="store_true",
        help="Require CODEOWNERS review when CODEOWNERS exists.",
    )
    parser.add_argument(
        "--strict-checks",
        action="store_true",
        default=True,
        help="Require branch to be up to date before merge (default: true).",
    )
    parser.add_argument("--allow-force-pushes", action="store_true", help="Allow force pushes.")
    parser.add_argument("--allow-deletions", action="store_true", help="Allow branch deletions.")
    parser.add_argument("--no-enforce-admins", action="store_true", help="Do not enforce admins.")
    parser.add_argument(
        "--no-dismiss-stale-reviews",
        action="store_true",
        help="Do not dismiss stale reviews on new commits.",
    )
    parser.add_argument(
        "--no-require-conversation-resolution",
        action="store_true",
        help="Do not require conversation resolution before merge.",
    )
    parser.add_argument(
        "--no-require-linear-history",
        action="store_true",
        help="Do not require linear commit history.",
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true", help="Apply protection profile.")
    mode.add_argument("--check", action="store_true", help="Check current settings against desired profile.")
    mode.add_argument("--dry-run", action="store_true", help="Print desired profile payload without API calls.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    profile = _build_profile(args)
    repo = str(args.repo or "").strip() or (_default_repo_slug() or "")
    if not repo:
        message = "repo is required (pass --repo owner/repo or set git origin)"
        if args.json:
            print(json.dumps({"ok": False, "action": "configure_branch_protection", "error": message}, sort_keys=True))
        else:
            print("GitHub branch protection: FAIL")
            print(f"- {message}")
        return 1

    payload = profile.to_payload()
    if args.dry_run:
        out = {
            "ok": True,
            "action": "dry_run",
            "repo": repo,
            "branch": args.branch,
            "payload": payload,
        }
        if args.json:
            print(json.dumps(out, sort_keys=True))
        else:
            print("GitHub branch protection: PASS")
            print(f"- dry-run for {repo}:{args.branch}")
            print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    token = str(args.token or "").strip() or str(os.environ.get(str(args.token_env or "").strip(), "")).strip()
    if not token and not args.json and sys.stdin.isatty():
        prompted = getpass.getpass("GitHub token (repo admin scope): ").strip()
        if prompted:
            token = prompted
    if not token:
        message = (
            f"GitHub token required (pass --token or set {args.token_env}); "
            "needs repository administration permission"
        )
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "action": "configure_branch_protection",
                        "repo": repo,
                        "branch": args.branch,
                        "error": message,
                    },
                    sort_keys=True,
                )
            )
        else:
            print("GitHub branch protection: FAIL")
            print(f"- {message}")
        return 1

    path = f"/repos/{repo}/branches/{args.branch}/protection"
    try:
        if args.apply:
            _request_github(method="PUT", path=path, token=token, payload=payload)
            current_response = _request_github(method="GET", path=path, token=token)
            current = _normalize_current(current_response)
            expected = _expected_normalized(profile)
            mismatches = _diff_profile(expected=expected, current=current)
            ok = not mismatches
            result = {
                "ok": ok,
                "action": "apply",
                "repo": repo,
                "branch": args.branch,
                "required_checks": list(profile.required_checks),
                "mismatch_count": len(mismatches),
                "mismatches": mismatches,
            }
            if args.json:
                print(json.dumps(result, sort_keys=True))
            else:
                if ok:
                    print("GitHub branch protection: PASS")
                    print(f"- applied and verified for {repo}:{args.branch}")
                else:
                    print("GitHub branch protection: FAIL")
                    print(f"- applied but verification mismatches found for {repo}:{args.branch}")
                    for item in mismatches:
                        print(f"- {item}")
            return 0 if ok else 1

        current_response = _request_github(method="GET", path=path, token=token)
        current = _normalize_current(current_response)
        expected = _expected_normalized(profile)
        mismatches = _diff_profile(expected=expected, current=current)
        ok = not mismatches
        result = {
            "ok": ok,
            "action": "check",
            "repo": repo,
            "branch": args.branch,
            "required_checks": list(profile.required_checks),
            "mismatch_count": len(mismatches),
            "mismatches": mismatches,
            "current": current,
        }
        if args.json:
            print(json.dumps(result, sort_keys=True))
        else:
            if ok:
                print("GitHub branch protection: PASS")
                print(f"- matches desired profile for {repo}:{args.branch}")
            else:
                print("GitHub branch protection: FAIL")
                print(f"- profile mismatches for {repo}:{args.branch}")
                for item in mismatches:
                    print(f"- {item}")
        return 0 if ok else 1

    except RuntimeError as exc:
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "action": "configure_branch_protection",
                        "repo": repo,
                        "branch": args.branch,
                        "error": str(exc),
                    },
                    sort_keys=True,
                )
            )
        else:
            print("GitHub branch protection: FAIL")
            print(f"- {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
