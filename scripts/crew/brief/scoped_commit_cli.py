"""Command-line rendering for the scoped Thomas commit entrypoint."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from typing import Any


def render_result(result: Any) -> str:
    lines = ["Scoped agent commit: PASS" if result.ok else "Scoped agent commit: FAIL"]
    if result.ok and result.dry_run:
        lines[0] += " (dry-run)"
    if result.agent:
        lines.append(f"- agent: {result.agent}")
    if result.branch:
        lines.append(f"- branch: {result.branch}")
    if result.claim_scopes:
        lines.append(f"- claim scopes: {', '.join(result.claim_scopes)}")
    lines.append(f"- scope source: {result.scope_source}")
    lines.append(f"- message: {result.message}")
    if result.blocker_class:
        lines.append(f"- blocker_class: {result.blocker_class}")
    if result.commit_sha:
        lines.append(f"- commit: {result.commit_sha}")
    if result.selected_paths:
        lines.append("- selected paths:")
        lines.extend(f"  - {path}" for path in result.selected_paths)
    if result.gate_name:
        lines.append(f"- failed gate: {result.gate_name}")
    if result.gate_output:
        lines.append("- gate output:")
        lines.extend(f"  {row}" for row in result.gate_output.splitlines()[:20])
    if result.next_step:
        lines.append(f"- next step: {result.next_step}")
    if result.suggested_command:
        lines.append(f"- suggested command: {result.suggested_command}")
    return "\n".join(lines)


def run(argv: Sequence[str] | None = None, *, core: Any | None = None) -> int:
    if core is None:
        from scripts.crew.brief import commit as core

    parser = argparse.ArgumentParser(description="Create a scoped local commit for the current agent claim.")
    parser.add_argument("--message", required=True, help="Commit message subject/body.")
    parser.add_argument("--agent", default="", help="Agent id override.")
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="Optional in-claim path(s) to narrow the commit (repeatable or comma-separated).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate scoped commit selection and gates without creating a commit.",
    )
    parser.add_argument(
        "--allow-scope-fallback",
        action="store_true",
        help="Allow an explicit, audited fallback scope when the agent has no active workboard claim.",
    )
    parser.add_argument(
        "--fallback-reason",
        default="",
        help="Short approval/audit reason required with --allow-scope-fallback.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    args = parser.parse_args(argv)
    include_paths = [token.strip() for raw in args.include for token in str(raw or "").split(",") if token.strip()]
    result = core.commit_scoped_changes(
        message=args.message,
        agent=str(args.agent or "").strip() or None,
        include_paths=include_paths,
        dry_run=bool(args.dry_run),
        allow_scope_fallback=bool(args.allow_scope_fallback),
        fallback_reason=str(args.fallback_reason or ""),
    )
    print(json.dumps(core._result_payload(result), sort_keys=True) if args.json else render_result(result))
    return 0 if result.ok else 1
