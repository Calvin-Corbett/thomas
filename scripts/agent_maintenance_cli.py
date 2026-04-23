"""CLI entrypoint helpers for maintenance checkpoints."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.agent_maintenance_core import DEFAULT_WORKBOARD, attempt_maintenance_checkpoint
from scripts.agent_maintenance_window import (
    EVENT_TYPES,
    maintenance_quota_status,
    record_maintenance_event,
    reset_maintenance_window,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect or record Thomas maintenance-mode checkpoint events.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Show maintenance quota status for the last hour.")

    record_parser = subparsers.add_parser("record", help="Append a maintenance event.")
    record_parser.add_argument("--event", required=True, choices=sorted(EVENT_TYPES))
    record_parser.add_argument("--changed-lines", type=int, default=0)

    reset_parser = subparsers.add_parser("reset", help="Reset the maintenance quota window (requires interactive Windows approval).")
    reset_parser.add_argument("--reason", required=True, help="Human reason for resetting maintenance quota.")

    attempt_parser = subparsers.add_parser("attempt-checkpoint", help="Run an automatic private maintenance checkpoint.")
    attempt_parser.add_argument("--agent", required=True)
    attempt_parser.add_argument("--message", default="checkpoint: maintenance mode")
    attempt_parser.add_argument("--workboard", default=str(DEFAULT_WORKBOARD))

    parser.add_argument("--changed-lines", type=int, default=0, help="Prospective changed lines for status checks.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    return parser


def _text_status(payload: dict[str, Any]) -> str:
    if "can_attempt_checkpoint" not in payload:
        lines = [
            "Thomas maintenance checkpoint",
            f"- ok: {payload.get('ok')}",
            f"- attempted: {payload.get('attempted')}",
            f"- message: {payload.get('message', '')}",
        ]
        recovery_summary = str(payload.get("recovery_summary") or "").strip()
        if recovery_summary:
            lines.append(f"- recovery_summary: {recovery_summary}")
        if payload.get("commit_sha"):
            lines.append(f"- commit: {payload['commit_sha']}")
        if payload.get("blocker_class"):
            lines.append(f"- blocker_class: {payload['blocker_class']}")
        next_step = str(payload.get("next_step") or "").strip()
        if next_step:
            lines.append(f"- next_step: {next_step}")
        recovery_steps = list(payload.get("recovery_steps") or [])
        if recovery_steps:
            lines.append("- recovery_steps:")
            for step in recovery_steps:
                lines.append(f"  - {step}")
        suggested = str(payload.get("suggested_command") or "").strip()
        if suggested:
            lines.append(f"- suggested_command: {suggested}")
        return "\n".join(lines)

    lines = [
        "Thomas maintenance status",
        f"- can_attempt_checkpoint: {payload['can_attempt_checkpoint']}",
        f"- successful_checkpoints_last_hour: {payload['successful_checkpoints']}",
        f"- failed_checkpoints_last_hour: {payload['failed_checkpoints']}",
        f"- checkpointed_lines_last_hour: {payload['checkpointed_lines']}",
        f"- remaining_auto_checkpoints: {payload['remaining_auto_checkpoints']}",
        f"- remaining_checkpointed_lines: {payload['remaining_checkpointed_lines']}",
        f"- suggested_checkpoint_command: {payload['suggested_checkpoint_command']}",
        f"- log_path: {payload['log_path']}",
    ]
    blocked_reason = str(payload.get("blocked_reason") or "").strip()
    if blocked_reason:
        lines.append(f"- blocked_reason: {blocked_reason}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "record":
        path = record_maintenance_event(args.event, changed_lines=args.changed_lines)
        payload = {"recorded": True, "event": args.event, "log_path": str(path)}
    elif args.command == "reset":
        payload = reset_maintenance_window(reason=str(args.reason or "").strip())
    elif args.command == "attempt-checkpoint":
        payload = attempt_maintenance_checkpoint(
            agent=str(args.agent or "").strip(),
            message=str(args.message or "").strip() or "checkpoint: maintenance mode",
            total_changed_lines=int(args.changed_lines or 0),
            workboard_path=Path(str(args.workboard)).expanduser(),
        )
    else:
        payload = maintenance_quota_status(total_changed_lines=args.changed_lines)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_text_status(payload))
    return 0 if bool(payload.get("ok", True)) else 2
