#!/usr/bin/env python3
"""Run a normal commit, then offer contextual breakglass when gates block it."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.breakglass_context import (
    BREAKGLASS_CONTEXT_ENV,
    breakglass_context_to_json,
    build_commit_blocker_context,
)

BREAKGLASS_ENV = "THOMAS_SKIP_BREAKGLASS"
BREAKGLASS_TICKET_ENV = "THOMAS_SKIP_TICKET"
BREAKGLASS_REASON_ENV = "THOMAS_SKIP_REASON"
AGENT_ENV_KEYS: tuple[str, ...] = (
    "AGENT_ID",
    "THOMAS_AGENT_ID",
    "CODEX_AGENT_ID",
    "CODEX_AGENT_NAME",
    "AGENT_NAME",
)


def _resolve_agent(cli_agent: str) -> str:
    explicit = str(cli_agent or "").strip()
    if explicit:
        return explicit
    for key in AGENT_ENV_KEYS:
        value = str(os.getenv(key, "") or "").strip()
        if value:
            return value
    return ""


def _commit_command(messages: Sequence[str], *, no_verify: bool = False) -> list[str]:
    command = ["git", "commit"]
    if no_verify:
        command.append("--no-verify")
    for message in messages:
        command.extend(["-m", str(message)])
    return command


def _run_command(repo_root: Path, command: Sequence[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_process_output(proc: subprocess.CompletedProcess[str]) -> None:
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)


def _default_ticket() -> str:
    return "COMMIT-BLOCKER-" + datetime.now().strftime("%Y%m%d-%H%M%S")


def _context_summary_lines(context) -> list[str]:
    lines = [context.summary, "Thomas recommendation: " + context.recommendation]
    for issue in context.issues[:5]:
        reason = getattr(issue, "plain_reason", "") or issue.why
        lines.append(f"- {issue.gate}: {reason}")
        if getattr(issue, "impact", ""):
            lines.append(f"  Why it matters: {issue.impact}")
        for evidence in issue.evidence[:2]:
            if str(evidence).strip().lower() == str(reason).strip().lower():
                continue
            lines.append(f"  {evidence}")
        if getattr(issue, "recommendation", ""):
            lines.append(f"  What I recommend: {issue.recommendation}")
        if getattr(issue, "next_step", ""):
            lines.append(f"  Next step: {issue.next_step}")
    if getattr(context, "resolution_label", "") and getattr(context, "resolution_prompt", ""):
        lines.append(f"Action button: {context.resolution_label}")
    return lines


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-m", "--message", action="append", required=True, help="Commit message paragraph.")
    parser.add_argument("--repo-root", default=str(ROOT), help="Repository root.")
    parser.add_argument("--agent", default="", help="Agent id for audit metadata.")
    parser.add_argument("--ticket", default="", help="Breakglass ticket/id. Generated when omitted.")
    parser.add_argument("--reason", default="", help="Breakglass reason. Defaults to the recommendation.")
    parser.add_argument(
        "--ai-recommendation",
        default="",
        help="AI-authored recommendation shown to the user before Windows authorization.",
    )
    parser.add_argument(
        "--ai-guidance-json",
        default="",
        help=(
            "Model-authored JSON guidance with per-gate plain-English explanations, "
            "recommendations, and optional resolution action."
        ),
    )
    parser.add_argument(
        "--ai-guidance-file",
        default="",
        help="Path to a model-authored JSON guidance file.",
    )
    parser.add_argument(
        "--no-breakglass",
        action="store_true",
        help="Only show the blocker summary; do not retry through breakglass.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    messages = [str(item) for item in args.message if str(item).strip()]
    env = dict(os.environ)
    agent = _resolve_agent(str(args.agent or ""))
    if agent:
        env["AGENT_ID"] = agent
        env["THOMAS_AGENT_ID"] = agent

    normal_proc = _run_command(repo_root, _commit_command(messages), env)
    if normal_proc.returncode == 0:
        _write_process_output(normal_proc)
        return 0

    combined = (normal_proc.stdout or "") + (normal_proc.stderr or "")
    ai_guidance_json = str(args.ai_guidance_json or "").strip()
    if args.ai_guidance_file and not ai_guidance_json:
        try:
            ai_guidance_json = Path(str(args.ai_guidance_file)).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"Could not read AI guidance file: {exc}", file=sys.stderr)

    context = build_commit_blocker_context(
        combined,
        ai_recommendation=str(args.ai_recommendation or "").strip(),
        ai_guidance_json=ai_guidance_json,
    )
    print("Thomas commit blocker summary:")
    for line in _context_summary_lines(context):
        print(line)

    if args.no_breakglass:
        _write_process_output(normal_proc)
        return int(normal_proc.returncode)

    ticket = str(args.ticket or "").strip() or _default_ticket()
    reason = str(args.reason or "").strip() or context.recommendation
    breakglass_env = dict(env)
    breakglass_env[BREAKGLASS_ENV] = "1"
    breakglass_env[BREAKGLASS_TICKET_ENV] = ticket
    breakglass_env[BREAKGLASS_REASON_ENV] = reason
    breakglass_env[BREAKGLASS_CONTEXT_ENV] = breakglass_context_to_json(context)

    retry_proc = _run_command(repo_root, _commit_command(messages, no_verify=True), breakglass_env)
    _write_process_output(retry_proc)
    return int(retry_proc.returncode)


if __name__ == "__main__":
    raise SystemExit(run())
