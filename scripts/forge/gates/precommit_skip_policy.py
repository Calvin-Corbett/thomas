#!/usr/bin/env python3
"""Enforce audited policy for local pre-commit hook skips."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from breakglass_auth import authorize_breakglass

    from scripts.crew.brief.safety_config import load_config
except ImportError:  # pragma: no cover
    from scripts.breakglass_auth import authorize_breakglass  # type: ignore
    from scripts.crew.brief.safety_config import load_config  # type: ignore

ROOT = Path(__file__).resolve().parents[3]


def _git_dir() -> Path:
    """Resolve the real git directory for the audit log.

    In a linked git worktree, ``ROOT/.git`` is a ``gitdir: <path>`` POINTER FILE,
    not a directory -- so writing the audit log under ``ROOT/.git`` fails with
    "cannot create a file when that file already exists". Follow the pointer to
    the real per-worktree git dir, which is always a writable directory. A normal
    checkout (``.git`` is a directory) is returned unchanged.
    """
    dot_git = ROOT / ".git"
    try:
        if dot_git.is_file():
            content = dot_git.read_text(encoding="utf-8").strip()
            if content.startswith("gitdir:"):
                target = Path(content.split(":", 1)[1].strip())
                if not target.is_absolute():
                    target = (ROOT / target).resolve()
                return target
    except OSError:
        pass
    return dot_git


DEFAULT_AUDIT_LOG = _git_dir() / "thomas_skip_audit.jsonl"


def _quickbuilder_active() -> bool:
    """True iff a validly SIGNED QuickBuilder flag is active.

    QuickBuilder disables the breakglass *cooldown* (not the human tap) so a
    person can iterate fast. The flag is HMAC-signed; a forged file is ignored.
    """
    try:
        from scripts.forge.gates._quickbuilder_guard import quickbuilder_active
    except ImportError:  # pragma: no cover - import path varies by run context
        try:
            from forge.gates._quickbuilder_guard import quickbuilder_active
        except ImportError:
            from _quickbuilder_guard import quickbuilder_active
    return quickbuilder_active(ROOT)


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
BREAKGLASS_REASON_ENV = "THOMAS_SKIP_REASON"
DEFAULT_MAX_SKIP_HOOKS = 4
DEFAULT_MAX_STAGED_FILES_WITH_SKIP = 200
DEFAULT_MAX_STAGED_FILES_WITH_BREAKGLASS = 60
DEFAULT_BREAKGLASS_MAX_PER_AGENT_24H = 3
DEFAULT_BREAKGLASS_COOLDOWN_MINUTES = 15
PROTECTED_SKIP_HOOKS: tuple[str, ...] = (
    "ruff",
    "ruff-format",
    "thomas-agent-safety-validation",
    "thomas-active-folder-guard",
    "thomas-precommit-skip-policy-gate",
    "thomas-enforcement-integrity",
    "thomas-protected-files-gate",
    "thomas-plan-structure-gate",
    "thomas-core-overhead-guard",
    "thomas-worktree-rules-gate",
    "thomas-worktree-branch-guard",
    "thomas-workboard-claims-gate",
    "thomas-workboard-task-problems-gate",
    "thomas-workboard-changed-files-gate",
    "thomas-workboard-agent-claim-gate",
    "thomas-workboard-issue-tool-smoke",
    "thomas-workboard-problem-record-smoke",
    "thomas-workboard-inbox-gate",
    "thomas-workboard-inbox-final-gate",
    "thomas-workboard-inbox-commit-msg-gate",
    "thomas-bulk-commit-guard",
    "thomas-commit-growth-guard",
    "thomas-monolith-guard",
    "thomas-protected-deletion-guard",
    "thomas-feature-registry-gate",
    "thomas-repo-identity-gate",
    "thomas-site-visual-proof-gate",
    "thomas-merge-readiness",
    "thomas-repo-hygiene-gate",
    "thomas-repo-clean-worktree-gate",
    "thomas-release-hygiene-gate",
    "thomas-release-update-gate",
    "thomas-architecture",
    "thomas-auto-checks-quick",
    "thomas-workboard-audit-backstop-gate",
    "thomas-monolith-filename-pattern-gate",
    "thomas-publish-preflight",
)


def _config():
    return load_config()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


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


def _sanitize_reason(raw: str) -> str:
    return " ".join(str(raw or "").split()).strip()


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


def _protected_skip_hooks() -> tuple[str, ...]:
    """Compatibility helper for tests and other gate auditors."""
    return tuple(PROTECTED_SKIP_HOOKS)


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
    breakglass_human_verified: bool,
    breakglass_auth_method: str,
    breakglass_authorized_by: str,
) -> None:
    payload: dict[str, object] = {
        "gate": "precommit_skip_policy",
        "timestamp_utc": _now_utc().isoformat(),
        "agent": agent,
        "skip_hooks": list(skip_hooks),
        "reason": reason,
        "breakglass_used": bool(breakglass_used),
        "skip_ticket": skip_ticket,
        "breakglass_human_verified": bool(breakglass_human_verified),
        "breakglass_auth_method": breakglass_auth_method,
        "breakglass_authorized_by": breakglass_authorized_by,
        "protected_hooks_skipped": list(protected_hooks_skipped),
        "branch": _run_git(["rev-parse", "--abbrev-ref", "HEAD"]) or "",
        "head": _run_git(["rev-parse", "HEAD"]) or "",
        "staged_file_count": len(list(staged_files)),
        "staged_files": list(staged_files)[:25],
    }
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    with audit_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _parse_iso_utc(raw: str) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_breakglass_history(*, audit_log: Path, agent: str, now: datetime) -> list[datetime]:
    if not audit_log.exists():
        return []
    out: list[datetime] = []
    agent_key = str(agent or "").strip().lower()
    try:
        lines = audit_log.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    for line in lines:
        token = str(line or "").strip()
        if not token:
            continue
        try:
            payload = json.loads(token)
        except Exception:
            continue
        if not bool(payload.get("breakglass_used", False)):
            continue
        # B5: match on the VERIFIED actor (breakglass_authorized_by) so the
        # quota cannot be reset by rotating the agent-controlled AGENT_ID. Fall
        # back to the advisory agent field for legacy rows that predate this.
        row_actor = str(payload.get("breakglass_authorized_by", "")).strip().lower()
        row_agent = str(payload.get("agent", "")).strip().lower()
        if agent_key not in {row_actor, row_agent}:
            continue
        stamp = _parse_iso_utc(str(payload.get("timestamp_utc", "")))
        if stamp is None:
            continue
        if stamp > now + timedelta(minutes=1):
            continue
        out.append(stamp)
    return sorted(out)


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Require explicit, auditable metadata for pre-commit SKIP usage.")
    cfg = _config()
    parser.add_argument(
        "--audit-log",
        default=str(DEFAULT_AUDIT_LOG),
        help="Path to audit jsonl log (default: .git/thomas_skip_audit.jsonl).",
    )
    parser.add_argument(
        "--max-skip-hooks",
        type=int,
        default=cfg.skip_policy_max_skip_hooks(),
        help="Maximum allowed skipped hook ids without breakglass (default: 4).",
    )
    parser.add_argument(
        "--max-staged-files-with-skip",
        type=int,
        default=cfg.skip_policy_max_staged_files_with_skip(),
        help="Maximum staged file count allowed with SKIP without breakglass (default: 200).",
    )
    parser.add_argument(
        "--max-staged-files-with-breakglass",
        type=int,
        default=cfg.skip_policy_max_staged_files_with_breakglass(),
        help="Maximum staged file count allowed with breakglass SKIP (default: 60).",
    )
    parser.add_argument(
        "--breakglass-max-per-agent-24h",
        type=int,
        default=cfg.skip_policy_breakglass_max_per_agent_24h(),
        help="Maximum breakglass SKIP uses per agent in rolling 24h window (default: 3).",
    )
    parser.add_argument(
        "--breakglass-cooldown-minutes",
        type=int,
        default=cfg.skip_policy_breakglass_cooldown_minutes(),
        help="Minimum minutes required between breakglass SKIP uses by same agent (default: 15).",
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
    if not breakglass_enabled:
        message = (
            "SKIP is breakglass-only. Fix the failing hooks and retry; "
            f"only emergency overrides may set {BREAKGLASS_ENV}=1 with {BREAKGLASS_TICKET_ENV}."
        )
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

    if len(unique_skip_hooks) > max_skip_hooks:
        message = (
            f"SKIP contains {len(unique_skip_hooks)} hook ids; max is {max_skip_hooks} even with {BREAKGLASS_ENV}=1"
        )
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
    protected_hooks.extend(str(item or "").strip() for item in cfg.skip_policy_protected_hooks())
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

    reason = _sanitize_reason(os.getenv("THOMAS_SKIP_REASON", ""))
    skip_ticket = str(os.getenv(BREAKGLASS_TICKET_ENV, "")).strip()
    if breakglass_enabled and len(reason) < 12:
        message = f"breakglass requires {BREAKGLASS_REASON_ENV} with at least 12 characters"
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
    if breakglass_enabled and len(skip_ticket) < 6:
        message = f"breakglass requires {BREAKGLASS_TICKET_ENV} with at least 6 characters"
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
    max_staged_files_with_breakglass = max(1, int(args.max_staged_files_with_breakglass))
    if breakglass_enabled and len(staged_files) > max_staged_files_with_breakglass:
        message = (
            f"breakglass SKIP with {len(staged_files)} staged files exceeds hard limit "
            f"{max_staged_files_with_breakglass}; split the commit before retrying"
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
    auth_method = ""
    authorized_by = ""
    if breakglass_enabled:
        now = _now_utc()
        # B4: there is NO env-based "CI-trusted" shortcut — this gate is local
        # only, so a `GITHUB_ACTIONS=true` branch was a spoofable way to skip the
        # human Windows confirmation. Breakglass always requires native-auth.
        #
        # B5 (praxis-unbypassable-2026-05-29): authenticate FIRST so the rate
        # limit binds to the VERIFIED OS actor returned by native-auth, not the
        # agent-controlled AGENT_ID. Otherwise an agent rotates AGENT_ID to reset
        # its own breakglass quota/cooldown. AGENT_ID stays as advisory metadata.
        auth = authorize_breakglass(
            purpose="pre-commit hook skip authorization",
            agent=agent,
            ticket=skip_ticket,
            reason=reason,
            skip_hooks=list(skip_hooks),
        )
        if not auth.ok:
            message = auth.message or "human breakglass authorization failed"
            if args.json:
                print(
                    json.dumps(
                        {
                            "gate": "precommit_skip_policy",
                            "ok": False,
                            "skip_hooks": list(skip_hooks),
                            "error": message,
                            "breakglass_human_verified": False,
                            "breakglass_cancelled": bool(auth.cancelled),
                        },
                        sort_keys=True,
                    )
                )
            else:
                print("Pre-commit skip policy gate: FAIL")
                print(f"- {message}")
            return 1
        auth_method = str(auth.method or "").strip()
        authorized_by = str(auth.actor or "").strip()
        # The rate-limit principal is the VERIFIED actor, not the spoofable
        # agent id. Fall back to agent only if native-auth returned no actor.
        principal = authorized_by or agent
        history = _load_breakglass_history(audit_log=audit_log, agent=principal, now=now)
        cooldown_minutes = max(0, int(args.breakglass_cooldown_minutes))
        if cooldown_minutes > 0 and _quickbuilder_active():
            # QuickBuilder mode (human-activated, signed flag) waives the cooldown
            # so protected-file edits can land back-to-back. The native-auth tap
            # itself is still required above; only the rate-limit is relaxed.
            if not args.json:
                print("  (QuickBuilder mode: breakglass cooldown waived)")
            cooldown_minutes = 0
        if cooldown_minutes > 0 and history:
            latest = history[-1]
            delta = now - latest
            if delta < timedelta(minutes=cooldown_minutes):
                remaining = max(1, int((timedelta(minutes=cooldown_minutes) - delta).total_seconds() // 60))
                message = (
                    f"breakglass cooldown active for `{principal}`; retry in ~{remaining} minute(s) "
                    f"(cooldown={cooldown_minutes}m)"
                )
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
        # `breakglass_max_per_agent_24h = 0` (or any non-positive value) means
        # "no per-agent quota" — local installs may opt out via the
        # agent_safety.local.toml overlay. The other safety layers (protected-
        # files-gate, signed-commits, server-side workflow mirror) still apply,
        # so opting out of this one quota doesn't disable safety, just removes
        # the per-actor rate-limit on breakglass events. The public default
        # remains 3.
        raw_quota = int(args.breakglass_max_per_agent_24h)
        if raw_quota <= 0 or _quickbuilder_active():
            # QuickBuilder waives the per-agent 24h breakglass quota as well as the
            # cooldown -- a human activated build-fast mode, and every protected
            # commit still requires its own native-auth tap, so only the rate-limit
            # and the daily count are relaxed, not the human authorization.
            max_breakglass_per_agent = 0  # 0 == unlimited (sentinel)
        else:
            max_breakglass_per_agent = raw_quota
        window_start = now - timedelta(hours=24)
        recent_24h = [stamp for stamp in history if stamp >= window_start]
        if max_breakglass_per_agent > 0 and len(recent_24h) >= max_breakglass_per_agent:
            message = (
                f"breakglass quota exceeded for `{principal}`: "
                f"{len(recent_24h)} uses in last 24h (max {max_breakglass_per_agent})"
            )
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
            breakglass_human_verified=breakglass_enabled,
            breakglass_auth_method=auth_method,
            breakglass_authorized_by=authorized_by,
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
                    "breakglass_human_verified": breakglass_enabled,
                    "breakglass_auth_method": auth_method,
                    "breakglass_authorized_by": authorized_by,
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
            if auth_method:
                print(f"- human authorization verified via {auth_method}")
            if authorized_by:
                print(f"- authorized by: {authorized_by}")
            if protected_skipped:
                print(f"- protected hooks skipped: {', '.join(protected_skipped)}")
        print(f"- audit log: {audit_log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
