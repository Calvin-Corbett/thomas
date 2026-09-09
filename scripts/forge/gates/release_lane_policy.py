#!/usr/bin/env python3
"""Enforce dev -> prod release lane policy for GitHub PRs."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence


def evaluate_lane_policy(
    *,
    base_branch: str,
    head_branch: str,
    required_base: str,
    required_head: str,
) -> dict[str, object]:
    base = str(base_branch or "").strip()
    head = str(head_branch or "").strip()
    req_base = str(required_base or "").strip()
    req_head = str(required_head or "").strip()

    violations: list[str] = []
    if not base:
        violations.append("base branch is empty")
    if not head:
        violations.append("head branch is empty")
    if base and head and base == head:
        violations.append("head branch cannot equal base branch")
    if req_base and base and base != req_base:
        violations.append(f"base branch must be '{req_base}' (got '{base}')")
    if req_head and head and head != req_head:
        violations.append(f"head branch must be '{req_head}' (got '{head}')")

    return {
        "ok": not violations,
        "base_branch": base,
        "head_branch": head,
        "required_base": req_base,
        "required_head": req_head,
        "violations": violations,
    }


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail unless release PRs follow required dev -> prod lane policy.")
    parser.add_argument(
        "--base",
        default=os.environ.get("GITHUB_BASE_REF", ""),
        help="PR base branch (default: GITHUB_BASE_REF).",
    )
    parser.add_argument(
        "--head",
        default=os.environ.get("GITHUB_HEAD_REF", ""),
        help="PR head branch (default: GITHUB_HEAD_REF).",
    )
    parser.add_argument(
        "--require-base",
        default="prod",
        help="Required base branch (default: prod).",
    )
    parser.add_argument(
        "--require-head",
        default="dev",
        help="Required head branch (default: dev).",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on violations (default behavior in CI).",
    )
    args = parser.parse_args(argv)

    result = evaluate_lane_policy(
        base_branch=str(args.base or ""),
        head_branch=str(args.head or ""),
        required_base=str(args.require_base or ""),
        required_head=str(args.require_head or ""),
    )
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        if result["ok"]:
            print(f"release lane policy: PASS (head={result['head_branch']}, base={result['base_branch']})")
        else:
            print("release lane policy: FAIL")
            for item in list(result["violations"]):
                print(f"- {item}")

    if bool(args.strict) and not bool(result["ok"]):
        return 1
    return 0 if bool(result["ok"]) else 1


if __name__ == "__main__":
    raise SystemExit(run())
