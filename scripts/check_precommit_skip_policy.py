#!/usr/bin/env python3
"""Enforce audited policy for local pre-commit hook skips."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AUDIT_LOG = ROOT / ".git" / "thomas_skip_audit.jsonl"
AGENT_ENV_KEYS: tuple[str, ...] = (
    "AGENT_ID",
    "THOMAS_AGENT_ID",
    "THOMAS_AGENT_NAME",
    "CODEX_AGENT_NAME",
    "AGENT_NAME",
)
BROAD_SKIP_TOKENS = {"*", "all", "any"}
BREAKGLASS_ENV = "THOMAS_SKIP_BREAKGLASS"
BREAKGLASS_TICKET_ENV = "THOMAS_SKIP_TICKET"
DEFAULT_MAX_SKIP_HOOKS = 4
DEFAULT_MAX_STAGED_FILES_WITH_SKIP = 200
PROTECTED_SKIP_HOOKS: tuple[str, ...] = (
    "ruff",
    "ruff-format",
    "thomas-plan-structure-gate",
    "thomas-workboard-claims-gate",
    "thomas-workboard-task-problems-gate",
    "thomas-workboard-changed-files-gate",
    "thomas-workboard-agent-claim-gate",
    "thomas-workboard-audit-backstop-gate",
    "thomas-repo-hygiene-gate",
    "thomas-repo-identity-gate",
    "thomas-repo-clean-worktree-gate",
    "thomas-architecture",
    "thomas-auto-checks-quick",
)


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


def _parse_skip_env(raw_skip: str) -> list[str]:
    tokens: list[str] = []
    for part in str(raw_skip or "").replace(";", ",").split(","):
        token = str(part or "").strip()
        if token:
            tokens.append(token)
    return tokens


def _find_broad_skip_tokens(tokens: Sequence[str]) -> list[str]:
    broad: list[str] = []
    for token in tokens:
        norm = str(token or "").strip().lower()
        if not norm:
            continue
        if norm in BROAD_SKIP_TOKENS:
            broad.append(token)
            continue
        if any(ch in norm for ch in ("*", "?", "[")):
            broad.append(token)
    return broad


def _is_truthy(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "yes", "y", "on"}


def _find_protected_skip_hooks(tokens: Sequence[str], *, protected_hooks: Sequence[str]) -> list[str]:
    protected = {str(item or "").strip().lower() for item in protected_hooks if str(item or "").strip()}
    matches: list[str] = []
    for token in tokens:
        normalized = str(token or "").strip().lower()
        if normalized and normalized in protected:
            matches.append(token)
    return sorted(set(matches), key=str.lower)


def _resolve_agent() -> str | None:
    for env_key in AGENT_ENV_KEYS:
        value = str(os.getenv(env_key, "")).strip()
        if value:
            return value
    user = str(getpass.getuser() or "").strip()
    return user or None


def _staged_files() -> list[str]:
    text = _run_git(["diff", "--cached", "--name-only"]) or ""
    return [line.strip() for line in text.splitlines() if line.strip()]


def _append_audit_log(
    *,
    audit_log: Path,
    agent: str,
    skip_hooks: Sequence[str],
    reason: str,
    staged_files: Sequence[str],
    breakglass_used: bool,
    skip_ticket: str,
    protected_hooks_skipped: Sequence[str],
) -> None:
    payload: dict[str, object] = {
        "gate": "precommit_skip_policy",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "skip_hooks": list(skip_hooks),
        "reason": reason,
        "breakglass_used": bool(breakglass_used),
        "skip_ticket": skip_ticket,
        "protected_hooks_skipped": list(protected_hooks_skipped),
        "branch": _run_git(["rev-parse", "--abbrev-ref", "HEAD"]) or "",
        "head": _run_git(["rev-parse", "HEAD"]) or "",
        "staged_file_count": len(list(staged_files)),
        "staged_files": list(staged_files)[:25],
    }
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    with audit_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Require explicit, auditable metadata for pre-commit SKIP usage.")
    parser.add_argument(
        "--audit-log",
        default=str(DEFAULT_AUDIT_LOG),
        help="Path to audit jsonl log (default: .git/thomas_skip_audit.jsonl).",
    )
    parser.add_argument(
        "--max-skip-hooks",
        type=int,
        default=DEFAULT_MAX_SKIP_HOOKS,
        help="Maximum allowed skipped hook ids without breakglass (default: 4).",
    )
    parser.add_argument(
        "--max-staged-files-with-skip",
        type=int,
        default=DEFAULT_MAX_STAGED_FILES_WITH_SKIP,
        help="Maximum staged file count allowed with SKIP without breakglass (default: 200).",
    )
    parser.add_argument(
        "--protected-hook",
        action="append",
        default=[],
        help=(
            "Hook id that cannot be skipped unless breakglass is enabled. "
            "Repeatable; defaults include core policy and architecture gates."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    audit_log = Path(args.audit_log).expanduser()
    if not audit_log.is_absolute():
        audit_log = (ROOT / audit_log).resolve()

    skip_hooks = _parse_skip_env(os.getenv("SKIP", ""))
    if not skip_hooks:
        if args.json:
            print(
                json.dumps(
                    {
                        "gate": "precommit_skip_policy",
                        "ok": True,
                        "skip_hook_count": 0,
                        "message": "no SKIP overrides detected",
                    },
                    sort_keys=True,
                )
            )
        else:
            print("Pre-commit skip policy gate: PASS")
            print("- no SKIP overrides detected")
        return 0

    broad_tokens = _find_broad_skip_tokens(skip_hooks)
    if broad_tokens:
        message = "broad SKIP tokens are not allowed; use explicit hook ids only: " + ", ".join(broad_tokens)
        if args.json:
            print(
                json.dumps(
                    {
                        "gate": "precommit_skip_policy",
                        "ok": False,
                        "skip_hooks": list(skip_hooks),
                        "error": message,
                    },
                    sort_keys=True,
                )
            )
        else:
            print("Pre-commit skip policy gate: FAIL")
            print(f"- {message}")
        return 1

    max_skip_hooks = max(1, int(args.max_skip_hooks))
    unique_skip_hooks = sorted(set(skip_hooks), key=str.lower)
    breakglass_enabled = _is_truthy(os.getenv(BREAKGLASS_ENV, ""))
    if len(unique_skip_hooks) > max_skip_hooks and not breakglass_enabled:
        message = f"SKIP contains {len(unique_skip_hooks)} hook ids; max is {max_skip_hooks} unless {BREAKGLASS_ENV}=1"
        if args.json:
            print(
                json.dumps(
                    {
                        "gate": "precommit_skip_policy",
                        "ok": False,
                        "skip_hooks": list(skip_hooks),
                        "error": message,
                    },
                    sort_keys=True,
                )
            )
        else:
            print("Pre-commit skip policy gate: FAIL")
            print(f"- {message}")
        return 1

    protected_hooks = list(PROTECTED_SKIP_HOOKS)
    protected_hooks.extend(str(item or "").strip() for item in args.protected_hook)
    protected_skipped = _find_protected_skip_hooks(skip_hooks, protected_hooks=protected_hooks)
    if protected_skipped and not breakglass_enabled:
        message = (
            "protected hooks cannot be skipped without breakglass; set "
            f"{BREAKGLASS_ENV}=1 and provide {BREAKGLASS_TICKET_ENV}"
        )
        if args.json:
            print(
                json.dumps(
                    {
                        "gate": "precommit_skip_policy",
                        "ok": False,
                        "skip_hooks": list(skip_hooks),
                        "protected_hooks_skipped": protected_skipped,
                        "error": message,
                    },
                    sort_keys=True,
                )
            )
        else:
            print("Pre-commit skip policy gate: FAIL")
            print(f"- {message}")
            print(f"- protected hooks: {', '.join(protected_skipped)}")
        return 1

    reason = str(os.getenv("THOMAS_SKIP_REASON", "")).strip()
    if not reason:
        message = "THOMAS_SKIP_REASON is required when SKIP is set"
        if args.json:
            print(
                json.dumps(
                    {
                        "gate": "precommit_skip_policy",
                        "ok": False,
                        "skip_hooks": list(skip_hooks),
                        "error": message,
                    },
                    sort_keys=True,
                )
            )
        else:
            print("Pre-commit skip policy gate: FAIL")
            print(f"- {message}")
        return 1
    if len(reason) < 12:
        message = "THOMAS_SKIP_REASON must be at least 12 characters"
        if args.json:
            print(
                json.dumps(
                    {
                        "gate": "precommit_skip_policy",
                        "ok": False,
                        "skip_hooks": list(skip_hooks),
                        "error": message,
                    },
                    sort_keys=True,
                )
            )
        else:
            print("Pre-commit skip policy gate: FAIL")
            print(f"- {message}")
        return 1
    if any(ch in reason for ch in ("\n", "\r")):
        message = "THOMAS_SKIP_REASON cannot contain newlines"
        if args.json:
            print(
                json.dumps(
                    {
                        "gate": "precommit_skip_policy",
                        "ok": False,
                        "skip_hooks": list(skip_hooks),
                        "error": message,
                    },
                    sort_keys=True,
                )
            )
        else:
            print("Pre-commit skip policy gate: FAIL")
            print(f"- {message}")
        return 1

    skip_ticket = str(os.getenv(BREAKGLASS_TICKET_ENV, "")).strip()
    if breakglass_enabled and len(skip_ticket) < 6:
        message = f"{BREAKGLASS_TICKET_ENV} is required (>=6 chars) when {BREAKGLASS_ENV}=1"
        if args.json:
            print(
                json.dumps(
                    {
                        "gate": "precommit_skip_policy",
                        "ok": False,
                        "skip_hooks": list(skip_hooks),
                        "error": message,
                    },
                    sort_keys=True,
                )
            )
        else:
            print("Pre-commit skip policy gate: FAIL")
            print(f"- {message}")
        return 1

    staged_files = _staged_files()
    max_staged_files_with_skip = max(1, int(args.max_staged_files_with_skip))
    if len(staged_files) > max_staged_files_with_skip and not breakglass_enabled:
        message = (
            f"SKIP with {len(staged_files)} staged files exceeds limit {max_staged_files_with_skip}; "
            f"use smaller commits or set {BREAKGLASS_ENV}=1 with {BREAKGLASS_TICKET_ENV}"
        )
        if args.json:
            print(
                json.dumps(
                    {
                        "gate": "precommit_skip_policy",
                        "ok": False,
                        "skip_hooks": list(skip_hooks),
                        "staged_file_count": len(staged_files),
                        "error": message,
                    },
                    sort_keys=True,
                )
            )
        else:
            print("Pre-commit skip policy gate: FAIL")
            print(f"- {message}")
        return 1

    agent = _resolve_agent()
    if not agent:
        message = "agent id is required when SKIP is set (set AGENT_ID or THOMAS_AGENT_ID)"
        if args.json:
            print(
                json.dumps(
                    {
                        "gate": "precommit_skip_policy",
                        "ok": False,
                        "skip_hooks": list(skip_hooks),
                        "error": message,
                    },
                    sort_keys=True,
                )
            )
        else:
            print("Pre-commit skip policy gate: FAIL")
            print(f"- {message}")
        return 1

    try:
        _append_audit_log(
            audit_log=audit_log,
            agent=agent,
            skip_hooks=skip_hooks,
            reason=reason,
            staged_files=staged_files,
            breakglass_used=breakglass_enabled,
            skip_ticket=skip_ticket,
            protected_hooks_skipped=protected_skipped,
        )
    except Exception as exc:
        message = f"failed to write skip audit log: {exc}"
        if args.json:
            print(
                json.dumps(
                    {
                        "gate": "precommit_skip_policy",
                        "ok": False,
                        "skip_hooks": list(skip_hooks),
                        "error": message,
                    },
                    sort_keys=True,
                )
            )
        else:
            print("Pre-commit skip policy gate: FAIL")
            print(f"- {message}")
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "gate": "precommit_skip_policy",
                    "ok": True,
                    "agent": agent,
                    "skip_hooks": list(skip_hooks),
                    "skip_hook_count": len(skip_hooks),
                    "breakglass_used": breakglass_enabled,
                    "protected_hooks_skipped": protected_skipped,
                    "staged_file_count": len(staged_files),
                    "audit_log": str(audit_log),
                },
                sort_keys=True,
            )
        )
    else:
        print("Pre-commit skip policy gate: PASS")
        print(f"- recorded {len(skip_hooks)} skipped hook(s) for `{agent}`")
        if breakglass_enabled:
            print(f"- breakglass enabled via {BREAKGLASS_ENV}")
            if protected_skipped:
                print(f"- protected hooks skipped: {', '.join(protected_skipped)}")
        print(f"- audit log: {audit_log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
