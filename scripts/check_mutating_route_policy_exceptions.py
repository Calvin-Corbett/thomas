#!/usr/bin/env python3
"""Validate mutating-route policy exceptions against runtime snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from thomas.marketplace.security.mutating_route_policy import evaluate_mutating_route_policy_exceptions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check mutating API route policy exceptions against runtime policy snapshot."
    )
    parser.add_argument("--repo-root", default=".", help="Repository root path.")
    parser.add_argument("--manifest", default="", help="Optional manifest path override.")
    parser.add_argument("--strict", action="store_true", help="Fail when warnings are present.")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve()
    manifest = Path(args.manifest).resolve() if str(args.manifest or "").strip() else None
    report = evaluate_mutating_route_policy_exceptions(root, manifest_path=manifest)

    ok = bool(report.get("ok", False))
    warnings = list(report.get("warnings") or [])
    errors = list(report.get("errors") or [])
    if bool(args.strict) and warnings:
        ok = False
        errors.append(
            {
                "code": "mutating_route_policy.strict_warning_block",
                "message": "strict mode enabled and warnings were present",
                "remediation": "Resolve warnings or run without --strict for advisory-only warnings.",
            }
        )

    payload = dict(report)
    payload["ok"] = bool(ok)
    payload["warnings"] = warnings
    payload["errors"] = errors

    if bool(args.as_json):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        summary = dict(payload.get("summary") or {})
        print("Mutating route policy exceptions")
        print(f"- repo root: {root}")
        print(f"- manifest: {payload.get('manifest_path', '')}")
        print(f"- ok: {payload.get('ok')}")
        print(f"- route count: {int(summary.get('route_count', 0))}")
        print(f"- observed exceptions: {int(summary.get('observed_exception_count', 0))}")
        print(f"- approved exceptions: {int(summary.get('approved_exception_count', 0))}")
        print(f"- errors: {len(errors)}")
        print(f"- warnings: {len(warnings)}")
        for row in errors:
            print(f"  ERROR: {str((row or {}).get('message') or '').strip()}")
        for row in warnings:
            print(f"  WARN: {str((row or {}).get('message') or '').strip()}")

    return 0 if bool(ok) else 2


if __name__ == "__main__":
    raise SystemExit(main())
