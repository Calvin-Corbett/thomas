#!/usr/bin/env python3
"""Run git push with audited, scoped hook skips instead of --no-verify."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shlex
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from thomas.core import agent_presence

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AUTO_SKIP_HOOK = "thomas-repo-clean-worktree-gate"
AGENT_ENV_KEYS: tuple[str, ...] = (
    "AGENT_ID",
    "THOMAS_AGENT_ID",
    "THOMAS_AGENT_NAME",
    "CODEX_AGENT_NAME",
    "AGENT_NAME",
)
BROAD_SKIP_TOKENS = {"*", "all", "any"}


def _normalize_skip_hook(value: str) -> str:
    token = str(value or "").strip()
    if not token:
        raise ValueError("skip hook ids cannot be empty")
    lowered = token.lower()
    if lowered in BROAD_SKIP_TOKENS or any(ch in lowered for ch in ("*", "?", "[")):
        raise ValueError(f"broad skip token is not allowed: {token}")
    return token


def _resolve_agent(cli_agent: str) -> str | None:
    explicit = str(cli_agent or "").strip()
    if explicit:
        return explicit
    for env_key in AGENT_ENV_KEYS:
        value = str(os.getenv(env_key, "")).strip()
        if value:
            return value
    fallback = str(getpass.getuser() or "").strip()
    return fallback or None


def _validate_reason(value: str) -> str:
    reason = str(value or "").strip()
    if not reason:
        raise ValueError("reason is required when SKIP hooks are used")
    if len(reason) < 12:
        raise ValueError("reason must be at least 12 characters")
    if any(ch in reason for ch in ("\n", "\r")):
        raise ValueError("reason cannot contain newlines")
    return reason


def _git_status_porcelain(repo_root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "").strip() or "git status --porcelain failed")
    return [line.rstrip() for line in str(proc.stdout or "").splitlines() if line.strip()]


def _run_push_command(
    repo_root: Path,
    command: Sequence[str],
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True))


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run git push with auditable SKIP metadata and no --no-verify bypass.")
    parser.add_argument("--repo-root", default=None, help="Repository root (default: inferred from script path).")
    parser.add_argument("--agent", default="", help="Agent id for audited SKIP usage.")
    parser.add_argument("--reason", default="", help="Reason required when SKIP is used.")
    parser.add_argument(
        "--skip-hook",
        action="append",
        default=[],
        help="Explicit pre-commit hook id to skip. Repeat to add multiple ids.",
    )
    parser.add_argument(
        "--auto-skip-dirty-worktree",
        dest="auto_skip_dirty_worktree",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=f"Auto-add {DEFAULT_AUTO_SKIP_HOOK} when git worktree is dirty (default: enabled).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print resolved push plan without executing push.")
    parser.add_argument(
        "--allow-presence-override",
        action="store_true",
        help="Allow push when the repo presence monitor detects other active or unregistered agents.",
    )
    parser.add_argument(
        "--presence-override-reason",
        default="",
        help="Required reason (>=12 chars) when --allow-presence-override is used.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("push_args", nargs=argparse.REMAINDER, help="Args forwarded to git push.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve() if args.repo_root else ROOT
    push_args = list(args.push_args or [])
    if push_args and push_args[0] == "--":
        push_args = push_args[1:]

    if any(str(part or "").strip() == "--no-verify" for part in push_args):
        message = "Do not pass --no-verify. Use scoped --skip-hook with --reason for audited bypass."
        payload = {"mode": "guarded_push", "ok": False, "exit_code": 1, "error": message}
        if args.json:
            _print_json(payload)
        else:
            print(f"Guarded push FAILED: {message}")
        return 1

    try:
        dirty_worktree = bool(_git_status_porcelain(repo_root))
    except Exception as exc:
        message = f"unable to inspect git worktree: {exc}"
        payload = {"mode": "guarded_push", "ok": False, "exit_code": 1, "error": message}
        if args.json:
            _print_json(payload)
        else:
            print(f"Guarded push FAILED: {message}")
        return 1

    skip_hooks: list[str] = []
    seen: set[str] = set()
    try:
        for raw in list(args.skip_hook or []):
            hook_id = _normalize_skip_hook(raw)
            if hook_id not in seen:
                seen.add(hook_id)
                skip_hooks.append(hook_id)
        if bool(args.auto_skip_dirty_worktree) and dirty_worktree:
            hook_id = _normalize_skip_hook(DEFAULT_AUTO_SKIP_HOOK)
            if hook_id not in seen:
                seen.add(hook_id)
                skip_hooks.append(hook_id)
    except Exception as exc:
        message = str(exc)
        payload = {"mode": "guarded_push", "ok": False, "exit_code": 1, "error": message}
        if args.json:
            _print_json(payload)
        else:
            print(f"Guarded push FAILED: {message}")
        return 1

    reason = ""
    agent = str(_resolve_agent(args.agent) or "").strip()
    env = dict(os.environ)
    try:
        presence_gate = agent_presence.evaluate_soft_gate(
            purpose="guarded_push",
            repo_root=repo_root,
            actor_agent=agent,
            allow_override=bool(args.allow_presence_override),
            override_reason=str(args.presence_override_reason or ""),
        )
    except ValueError as exc:
        message = str(exc)
        payload = {"mode": "guarded_push", "ok": False, "exit_code": 1, "error": message}
        if args.json:
            _print_json(payload)
        else:
            print(f"Guarded push FAILED: {message}")
        return 1
    except Exception as exc:
        message = f"presence gate failed: {exc}"
        payload = {"mode": "guarded_push", "ok": False, "exit_code": 1, "error": message}
        if args.json:
            _print_json(payload)
        else:
            print(f"Guarded push FAILED: {message}")
        return 1
    if not bool(presence_gate.get("ok", False)):
        message = str(presence_gate.get("message") or "presence gate requires override")
        payload = {
            "mode": "guarded_push",
            "ok": False,
            "exit_code": 1,
            "error": message,
            "presence_gate": presence_gate,
        }
        if args.json:
            _print_json(payload)
        else:
            print(f"Guarded push FAILED: {message}")
        return 1
    if skip_hooks:
        try:
            reason = _validate_reason(args.reason or os.getenv("THOMAS_SKIP_REASON", ""))
        except Exception as exc:
            message = str(exc)
            payload = {"mode": "guarded_push", "ok": False, "exit_code": 1, "error": message}
            if args.json:
                _print_json(payload)
            else:
                print(f"Guarded push FAILED: {message}")
            return 1
        if not agent:
            message = "agent id is required when SKIP is used"
            payload = {"mode": "guarded_push", "ok": False, "exit_code": 1, "error": message}
            if args.json:
                _print_json(payload)
            else:
                print(f"Guarded push FAILED: {message}")
            return 1
        env["SKIP"] = ",".join(skip_hooks)
        env["THOMAS_SKIP_REASON"] = reason
        env["AGENT_ID"] = agent

    command = ["git", "push", *push_args]
    command_text = shlex.join(command)
    base_payload: dict[str, object] = {
        "mode": "guarded_push",
        "command": command,
        "command_text": command_text,
        "repo_root": str(repo_root),
        "dirty_worktree": dirty_worktree,
        "skip_hooks": list(skip_hooks),
        "agent": agent,
        "reason": reason,
        "dry_run": bool(args.dry_run),
        "presence_gate": presence_gate,
    }

    if args.dry_run:
        payload = dict(base_payload)
        payload.update({"ok": True, "exit_code": 0})
        if args.json:
            _print_json(payload)
        else:
            print(f"Guarded push plan: {command_text}")
            print(f"- repo: {repo_root}")
            print(f"- dirty_worktree: {dirty_worktree}")
            if skip_hooks:
                print(f"- SKIP hooks: {', '.join(skip_hooks)}")
                print(f"- agent: {agent}")
                print(f"- reason: {reason}")
            else:
                print("- SKIP hooks: none")
        return 0

    proc = _run_push_command(repo_root, command, env)
    if args.json:
        payload = dict(base_payload)
        payload.update(
            {
                "ok": proc.returncode == 0,
                "exit_code": int(proc.returncode),
                "stdout": str(proc.stdout or ""),
                "stderr": str(proc.stderr or ""),
            }
        )
        _print_json(payload)
    else:
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
        if proc.returncode == 0:
            print("Guarded push OK")
        else:
            print(f"Guarded push FAILED (exit {proc.returncode})")
    return int(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(run())
