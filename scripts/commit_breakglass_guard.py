#!/usr/bin/env python3
"""Require native-auth breakglass for commits that skip local gates.

Git's ``--no-verify`` flag skips ``pre-commit`` and ``commit-msg`` hooks, but
it does not skip ``prepare-commit-msg``.  Thomas uses that non-bypassable local
hook as the local choke point:

* the pre-commit wrapper clears any stale marker before running gates;
* after a successful full pre-commit run, it writes a marker for the exact
  staged tree;
* prepare-commit-msg blocks the commit unless the marker still matches the
  current index tree, or the user completes Windows breakglass auth.

Local hooks are not a replacement for server-side branch protection.  This
guard closes the ordinary ``git commit --no-verify`` path and records explicit
breakglass metadata when a human intentionally uses it.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.breakglass_context import breakglass_context_from_env

SUCCESS_MARKER_NAME = "thomas_precommit_success.json"
BREAKGLASS_MARKER_NAME = "thomas_commit_breakglass_authorized.json"
AUDIT_LOG_NAME = "thomas_commit_breakglass_audit.jsonl"
MARKER_VERSION = 1
DEFAULT_MARKER_MAX_AGE_MINUTES = 30

BREAKGLASS_ENV = "THOMAS_SKIP_BREAKGLASS"
BREAKGLASS_TICKET_ENV = "THOMAS_SKIP_TICKET"
BREAKGLASS_REASON_ENV = "THOMAS_SKIP_REASON"

AGENT_ENV_KEYS: tuple[str, ...] = (
    "AGENT_ID",
    "THOMAS_AGENT_ID",
    "THOMAS_AGENT_NAME",
    "CODEX_AGENT_ID",
    "CODEX_AGENT_NAME",
    "AGENT_NAME",
)

# ---------------------------------------------------------------------------
# Success-marker authentication (closes the marker-forgery bypass, B1).
#
# The success marker (.git/thomas_precommit_success.json) is the local choke
# point: prepare-commit-msg (which --no-verify does NOT skip) refuses a commit
# unless a marker for the exact staged tree exists.  Originally the marker was
# unauthenticated JSON in an agent-writable dir, so an agent could forge it
# (compute git write-tree, write the JSON) and skip every gate with no
# --no-verify and zero gate runs.
#
# Fix: the pre-commit-success step HMAC-signs the marker with a per-install
# key.  prepare-commit-msg verifies the signature and fails CLOSED (block →
# breakglass) on any missing key / missing or bad signature.  The key lives
# OUTSIDE the repo worktree (default ~/.thomas/praxis/), so an agent confined
# to the repo sandbox cannot read it to sign a forgery.
#
# Residual (documented, not closed locally): a same-OS-user shell can read the
# key file, redirect $HOME, or invoke pre-commit-success directly to mint a
# signed marker.  That is the fundamental limit of any local-only control and
# is what the server-side layer (gates.yml required + branch protection,
# escalation E1/B2) closes.  This HMAC closes only the casual forge (writing
# JSON, or — as codex's re-attack showed — pointing an env override at an
# attacker key).  See
# plans/thomas/problems/praxis-unbypassable-2026-05-29/PROBLEM.md.
#
# NOTE: there is deliberately NO environment override for the key path.  An
# earlier draft honored THOMAS_PRAXIS_MARKER_KEY_FILE; codex's re-attack showed
# a hook-time attacker could point it at their own key and sign a forgery.
# Tests inject a key path by monkeypatching _marker_key_path, never via env.
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _marker_key_path() -> Path:
    """Path to the per-install HMAC key for the success marker.

    Stored outside the repo worktree so an agent sandboxed to the project
    directory cannot read it.  Per-repo (keyed on the resolved root) so
    separate clones do not share a signing key.  Intentionally NOT
    configurable via environment — see the module note above.
    """
    repo_id = hashlib.sha256(str(ROOT.resolve()).encode("utf-8")).hexdigest()[:16]
    return Path.home() / ".thomas" / "praxis" / f"marker_hmac_{repo_id}.key"


def _load_or_create_marker_key(*, create: bool) -> bytes | None:
    """Load the marker HMAC key; mint a fresh one if absent and create=True.

    Returns None if the key is absent (create=False) or could not be created.
    Callers treat a None key as fail-closed (marker cannot be authenticated).
    """
    path = _marker_key_path()
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if raw:
            return bytes.fromhex(raw)
    except (OSError, ValueError):
        pass
    if not create:
        return None
    key = secrets.token_bytes(32)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(key.hex(), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError:
        return None
    return key


def _marker_signing_payload(payload: dict[str, object]) -> bytes:
    """Canonical, order-stable byte string over the security-relevant fields.

    Only the fields that bind the marker to a specific staged tree + HEAD are
    signed; ``signature`` and advisory metadata (agent, branch, file list) are
    intentionally excluded so they cannot weaken the binding.
    """
    return "|".join(
        [
            str(int(payload.get("version", 0) or 0)),
            str(payload.get("created_at_utc", "") or ""),
            str(payload.get("head", "") or ""),
            str(payload.get("index_tree", "") or ""),
        ]
    ).encode("utf-8")


def _marker_signature(payload: dict[str, object], key: bytes) -> str:
    return hmac.new(key, _marker_signing_payload(payload), hashlib.sha256).hexdigest()


def _is_truthy(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _run_git(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _git_output(args: Sequence[str]) -> str:
    proc = _run_git(args)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"git {' '.join(args)} failed")
    return str(proc.stdout or "").strip()


def _git_path(name: str) -> Path:
    raw = _git_output(["rev-parse", "--git-path", name])
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path


def _success_marker_path() -> Path:
    return _git_path(SUCCESS_MARKER_NAME)


def _breakglass_marker_path() -> Path:
    return _git_path(BREAKGLASS_MARKER_NAME)


def _audit_log_path() -> Path:
    return _git_path(AUDIT_LOG_NAME)


def _current_index_tree() -> str:
    return _git_output(["write-tree"])


def _current_head() -> str:
    proc = _run_git(["rev-parse", "--verify", "HEAD"])
    if proc.returncode != 0:
        return ""
    return str(proc.stdout or "").strip()


def _current_branch() -> str:
    proc = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    if proc.returncode != 0:
        return ""
    return str(proc.stdout or "").strip()


def _staged_files() -> list[str]:
    proc = _run_git(["diff", "--cached", "--name-only"])
    if proc.returncode != 0:
        return []
    return [line.strip().replace("\\", "/") for line in str(proc.stdout or "").splitlines() if line.strip()]


def _resolve_agent() -> str:
    for key in AGENT_ENV_KEYS:
        value = str(os.getenv(key, "")).strip()
        if value:
            return value
    return getpass.getuser() or "unknown"


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def _parse_iso_utc(raw: object) -> datetime | None:
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


def validate_success_marker(*, max_age_minutes: int = DEFAULT_MARKER_MAX_AGE_MINUTES) -> tuple[bool, str]:
    marker = _success_marker_path()
    payload = _read_json(marker)
    if not payload:
        return False, "no successful pre-commit marker exists"
    if int(payload.get("version", 0) or 0) != MARKER_VERSION:
        return False, "successful pre-commit marker has an unsupported version"

    created_at = _parse_iso_utc(payload.get("created_at_utc"))
    if created_at is None:
        return False, "successful pre-commit marker has no valid timestamp"
    if _now_utc() - created_at > timedelta(minutes=max(1, int(max_age_minutes))):
        return False, "successful pre-commit marker is stale"

    marker_tree = str(payload.get("index_tree", "") or "").strip()
    current_tree = _current_index_tree()
    if not marker_tree or marker_tree != current_tree:
        return False, "successful pre-commit marker does not match the staged tree"

    marker_head = str(payload.get("head", "") or "").strip()
    current_head = _current_head()
    if marker_head != current_head:
        return False, "successful pre-commit marker was created for a different HEAD"

    # Authenticate the marker (B1).  A forged marker (correct tree/head/age but
    # written by an agent that ran no gates) has no valid signature because the
    # signing key lives outside the repo worktree.  Fail closed on any missing
    # key / missing or mismatched signature.
    key = _load_or_create_marker_key(create=False)
    if key is None:
        return False, "marker signing key is unavailable; cannot authenticate the pre-commit marker"
    actual_sig = str(payload.get("signature", "") or "")
    expected_sig = _marker_signature(payload, key)
    if not actual_sig or not hmac.compare_digest(actual_sig, expected_sig):
        return False, "successful pre-commit marker signature is invalid (possible forgery)"

    return True, "successful pre-commit marker matches the staged tree"


def cmd_pre_commit_start(_args: argparse.Namespace) -> int:
    _unlink_quietly(_success_marker_path())
    _unlink_quietly(_breakglass_marker_path())
    return 0


def cmd_pre_commit_success(_args: argparse.Namespace) -> int:
    now = _now_utc().isoformat()
    payload: dict[str, object] = {
        "version": MARKER_VERSION,
        "created_at_utc": now,
        "agent": _resolve_agent(),
        "branch": _current_branch(),
        "head": _current_head(),
        "index_tree": _current_index_tree(),
        "staged_files": _staged_files()[:100],
    }
    # Authenticate the marker so it cannot be forged by writing JSON (B1).
    # If the key cannot be created, the marker is written unsigned and will be
    # rejected at verify time (fail-closed → breakglass), which is safe.
    key = _load_or_create_marker_key(create=True)
    if key is not None:
        payload["signature"] = _marker_signature(payload, key)
    _write_json_atomic(_success_marker_path(), payload)
    _unlink_quietly(_breakglass_marker_path())
    return 0


def _append_audit(payload: dict[str, object]) -> None:
    path = _audit_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _append_breakglass_trailer(commit_msg_path: str, *, ticket: str, reason: str, actor: str) -> None:
    path = Path(commit_msg_path)
    try:
        original = path.read_text(encoding="utf-8")
    except OSError:
        return
    lowered = original.lower()
    if "thomas-breakglass:" in lowered or "thomas-local-commit-breakglass:" in lowered:
        return
    cleaned_reason = " ".join(str(reason or "").split()).strip()
    cleaned_ticket = " ".join(str(ticket or "").split()).strip()
    cleaned_actor = " ".join(str(actor or "").split()).strip()
    trailer = (
        "\n\n"
        f"Thomas-Breakglass: {cleaned_ticket} authorized local commit gate bypass by {cleaned_actor}\n"
        f"Thomas-Breakglass-Reason: {cleaned_reason}\n"
    )
    path.write_text(original.rstrip() + trailer, encoding="utf-8")


def _load_breakglass_auth():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if str(ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from scripts.breakglass_auth import authorize_breakglass
    except ImportError:
        from breakglass_auth import authorize_breakglass  # type: ignore[no-redef]
    return authorize_breakglass


def _block_without_breakglass(detail: str) -> int:
    print("Thomas commit breakglass guard: BLOCKED")
    print(f"Reason: {detail}")
    print()
    print("A commit without a successful local pre-commit run is breakglass-only.")
    print("To use breakglass, set all three environment variables, then retry:")
    print(f"  {BREAKGLASS_ENV}=1")
    print(f"  {BREAKGLASS_TICKET_ENV}=<ticket-or-approval-id>")
    print(f"  {BREAKGLASS_REASON_ENV}=<why-this-local-bypass-is-needed>")
    print()
    print("The retry will require the user's native Windows sign-in prompt.")
    return 1


def _authorize_breakglass(*, detail: str, commit_msg_path: str) -> int:
    if not _is_truthy(os.getenv(BREAKGLASS_ENV, "")):
        return _block_without_breakglass(detail)

    ticket = " ".join(str(os.getenv(BREAKGLASS_TICKET_ENV, "") or "").split()).strip()
    reason = " ".join(str(os.getenv(BREAKGLASS_REASON_ENV, "") or "").split()).strip()
    if not ticket or not reason:
        return _block_without_breakglass(f"{detail}; missing {BREAKGLASS_TICKET_ENV} or {BREAKGLASS_REASON_ENV}")

    agent = _resolve_agent()
    context_payload = breakglass_context_from_env(os.environ)
    try:
        authorize_breakglass = _load_breakglass_auth()
        result = authorize_breakglass(
            purpose="commit without a successful local pre-commit run",
            agent=agent,
            ticket=ticket,
            reason=reason,
            skip_hooks=["all local pre-commit hooks"],
            context=context_payload,
        )
    except Exception as exc:
        print("Thomas commit breakglass guard: BLOCKED")
        print(f"Breakglass authorization failed closed: {exc}")
        return 1

    base_payload: dict[str, object] = {
        "version": MARKER_VERSION,
        "gate": "commit_breakglass_guard",
        "timestamp_utc": _now_utc().isoformat(),
        "agent": agent,
        "branch": _current_branch(),
        "head": _current_head(),
        "index_tree": _current_index_tree(),
        "staged_file_count": len(_staged_files()),
        "staged_files": _staged_files()[:100],
        "ticket": ticket,
        "reason": reason,
        "marker_failure": detail,
        "breakglass_human_verified": bool(getattr(result, "ok", False)),
        "breakglass_auth_method": str(getattr(result, "method", "") or ""),
        "breakglass_authorized_by": str(getattr(result, "actor", "") or ""),
        "breakglass_message": str(getattr(result, "message", "") or ""),
        "breakglass_action_requested": bool(getattr(result, "action_requested", False)),
        "breakglass_action_prompt": str(getattr(result, "action_prompt", "") or ""),
        "breakglass_context_summary": str(getattr(context_payload, "summary", "") or ""),
        "breakglass_context_issue_count": len(tuple(getattr(context_payload, "issues", ()) or ())),
    }

    if not getattr(result, "ok", False):
        _append_audit({**base_payload, "event": "breakglass_denied"})
        print("Thomas commit breakglass guard: BLOCKED")
        print(f"Breakglass authorization denied: {getattr(result, 'message', 'unknown error')}")
        if getattr(result, "action_requested", False):
            prompt = str(getattr(result, "action_prompt", "") or "").strip()
            if prompt:
                print("Recommended action requested:")
                print(prompt)
        return 1

    actor = str(getattr(result, "actor", "") or agent)
    _append_breakglass_trailer(commit_msg_path, ticket=ticket, reason=reason, actor=actor)
    _write_json_atomic(
        _breakglass_marker_path(),
        {
            **base_payload,
            "event": "breakglass_authorized",
            "breakglass_authorized_by": actor,
        },
    )
    _append_audit({**base_payload, "event": "breakglass_authorized", "breakglass_authorized_by": actor})
    print("Thomas commit breakglass guard: breakglass authorized by native OS sign-in.")
    return 0


def cmd_prepare_commit_msg(args: argparse.Namespace) -> int:
    ok, detail = validate_success_marker(max_age_minutes=args.max_marker_age_minutes)
    if ok:
        return 0
    return _authorize_breakglass(detail=detail, commit_msg_path=args.commit_msg_file)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    pre_start = sub.add_parser("pre-commit-start", help="Clear stale commit gate markers before pre-commit runs.")
    pre_start.set_defaults(func=cmd_pre_commit_start)

    pre_success = sub.add_parser("pre-commit-success", help="Record that pre-commit passed for the current index.")
    pre_success.set_defaults(func=cmd_pre_commit_success)

    prepare = sub.add_parser(
        "prepare-commit-msg",
        help="Block commits unless pre-commit passed or native-auth breakglass is approved.",
    )
    prepare.add_argument("commit_msg_file")
    prepare.add_argument("commit_source", nargs="?")
    prepare.add_argument("commit_sha", nargs="?")
    prepare.add_argument("--max-marker-age-minutes", type=int, default=DEFAULT_MARKER_MAX_AGE_MINUTES)
    prepare.set_defaults(func=cmd_prepare_commit_msg)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
