"""Immutable live session-to-agent bindings for coordination mutations."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

AGENT_KEYS = ("THOMAS_AGENT_ID", "AGENT_ID", "CODEX_AGENT_ID", "GEMINI_AGENT_ID", "CLAUDE_AGENT_ID")
SESSION_KEYS = ("THOMAS_AGENT_SESSION_ID", "AGENT_SESSION_ID")
ATTESTATION_ENV = "THOMAS_AGENT_CHILD_ATTESTATION"
ATTESTATION_SECRET_ENV = "THOMAS_AGENT_CHILD_SECRET"


class SessionIdentityError(ValueError):
    """Identity sources or a live session binding are invalid."""


@dataclass(frozen=True)
class SessionBinding:
    session_id: str
    agent_id: str
    pid: int
    state: str
    last_heartbeat_at: str
    handoff_key_sha256: str = ""


def _one_value(label: str, values: list[tuple[str, str]], *, casefold: bool) -> str:
    populated = [(name, value.strip()) for name, value in values if value and value.strip()]
    if not populated:
        raise SessionIdentityError(f"{label} is required")
    compare = {value.casefold() if casefold else value for _name, value in populated}
    if len(compare) != 1:
        shown = ", ".join(f"{name}={value}" for name, value in populated)
        raise SessionIdentityError(f"conflicting {label} sources: {shown}")
    return populated[0][1]


def resolve_agent_sources(explicit_agent: str | None, env: Mapping[str, str]) -> str:
    values = [("explicit", str(explicit_agent or ""))]
    values.extend((key, str(env.get(key) or "")) for key in AGENT_KEYS)
    return _one_value("agent identity", values, casefold=True)


def resolve_session_sources(env: Mapping[str, str]) -> str:
    return _one_value(
        "session identity",
        [(key, str(env.get(key) or "")) for key in SESSION_KEYS],
        casefold=False,
    )


def _parse_time(value: str) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SessionIdentityError("session heartbeat timestamp is invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def read_binding(repo: Path, session_id: str) -> SessionBinding:
    path = Path(repo) / "runtime" / "coordination" / "presence" / f"{session_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SessionIdentityError(f"session binding missing or unreadable: {session_id}") from exc
    if not isinstance(data, dict) or str(data.get("session_id") or "") != session_id:
        raise SessionIdentityError("session file id does not match its bound session")
    try:
        pid = int(data.get("pid") or 0)
    except (TypeError, ValueError) as exc:
        raise SessionIdentityError("session binding PID is invalid") from exc
    return SessionBinding(
        session_id=session_id,
        agent_id=str(data.get("agent_id") or "").strip(),
        pid=pid,
        state=str(data.get("state") or "").strip().casefold(),
        last_heartbeat_at=str(data.get("last_heartbeat_at") or ""),
        handoff_key_sha256=str(data.get("handoff_key_sha256") or "").strip(),
    )


def _attestation_payload(attestation: Mapping[str, object]) -> bytes:
    keys = ("parent_session_id", "agent_id", "child_pid", "issued_at", "expires_at", "nonce")
    return json.dumps(
        {key: attestation.get(key) for key in keys},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def create_child_attestation(
    binding: SessionBinding,
    *,
    secret: str,
    child_pid: int,
    now: datetime | None = None,
    ttl_seconds: int = 60,
) -> dict[str, object]:
    if not secret or hashlib.sha256(secret.encode()).hexdigest() != binding.handoff_key_sha256:
        raise SessionIdentityError("native handoff secret does not match the parent binding")
    issued = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload: dict[str, object] = {
        "parent_session_id": binding.session_id,
        "agent_id": binding.agent_id,
        "child_pid": int(child_pid),
        "issued_at": issued.isoformat(),
        "expires_at": (issued + timedelta(seconds=max(1, int(ttl_seconds)))).isoformat(),
        "nonce": secrets.token_hex(16),
    }
    payload["signature"] = hmac.new(secret.encode(), _attestation_payload(payload), hashlib.sha256).hexdigest()
    return payload


def validate_child_attestation(
    binding: SessionBinding,
    attestation: Mapping[str, object],
    *,
    secret: str,
    current_pid: int,
    now: datetime,
) -> bool:
    if not binding.handoff_key_sha256:
        return False
    if not hmac.compare_digest(hashlib.sha256(secret.encode()).hexdigest(), binding.handoff_key_sha256):
        return False
    if str(attestation.get("parent_session_id") or "") != binding.session_id:
        return False
    if str(attestation.get("agent_id") or "").casefold() != binding.agent_id.casefold():
        return False
    if int(attestation.get("child_pid") or 0) != int(current_pid):
        return False
    try:
        issued = _parse_time(str(attestation.get("issued_at") or ""))
        expires = _parse_time(str(attestation.get("expires_at") or ""))
    except SessionIdentityError:
        return False
    current = now.astimezone(timezone.utc)
    if issued > current or expires < current:
        return False
    expected = hmac.new(secret.encode(), _attestation_payload(attestation), hashlib.sha256).hexdigest()
    return hmac.compare_digest(str(attestation.get("signature") or ""), expected)


def validate_live_binding(
    repo: Path,
    *,
    explicit_agent: str | None,
    env: Mapping[str, str],
    current_pid: int | None = None,
    parent_pid: int | None = None,
    now: datetime | None = None,
    stale_seconds: int = 120,
) -> SessionBinding:
    requested_agent = resolve_agent_sources(explicit_agent, env)
    session_id = resolve_session_sources(env)
    binding = read_binding(repo, session_id)
    if requested_agent.casefold() != binding.agent_id.casefold():
        raise SessionIdentityError(f"session {session_id} is bound to {binding.agent_id}, not {requested_agent}")
    if binding.state not in {"active", "alive"}:
        raise SessionIdentityError(f"session {session_id} is {binding.state or 'missing'}, not active")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    this_pid = int(os.getpid() if current_pid is None else current_pid)
    parent = int(os.getppid() if parent_pid is None else parent_pid)
    process_owner = binding.pid in {this_pid, parent}
    child_ok = False
    raw_attestation = str(env.get(ATTESTATION_ENV) or "").strip()
    secret = str(env.get(ATTESTATION_SECRET_ENV) or "")
    if raw_attestation and secret:
        try:
            parsed = json.loads(raw_attestation)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            child_ok = validate_child_attestation(
                binding,
                parsed,
                secret=secret,
                current_pid=this_pid,
                now=current,
            )
    secret_ok = bool(
        not raw_attestation
        and secret
        and binding.handoff_key_sha256
        and hmac.compare_digest(hashlib.sha256(secret.encode()).hexdigest(), binding.handoff_key_sha256)
    )
    if not (process_owner or child_ok or secret_ok):
        raise SessionIdentityError("current process is not the bound session owner or an attested child")
    if not (child_ok or secret_ok):
        age = (current - _parse_time(binding.last_heartbeat_at)).total_seconds()
        if age < 0 or age > max(1, int(stale_seconds)):
            raise SessionIdentityError(f"session {session_id} is stale")
    return binding


def validate_recorded_binding(
    repo: Path,
    *,
    agent_id: str,
    session_id: str,
    now: datetime | None = None,
    stale_seconds: int = 120,
) -> SessionBinding:
    """Revalidate a recorded submitter binding without impersonating its PID."""
    binding = read_binding(repo, session_id)
    if binding.agent_id.casefold() != str(agent_id or "").strip().casefold():
        raise SessionIdentityError(f"session {session_id} is bound to {binding.agent_id}, not {agent_id}")
    if binding.state not in {"active", "alive"}:
        raise SessionIdentityError(f"session {session_id} is {binding.state or 'missing'}, not active")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age = (current - _parse_time(binding.last_heartbeat_at)).total_seconds()
    if age < 0 or age > max(1, int(stale_seconds)):
        raise SessionIdentityError(f"session {session_id} is stale")
    return binding


def native_handoff_exports(
    repo: Path,
    *,
    parent_session_id: str,
    secret: str,
    child_pid: int,
    now: datetime | None = None,
) -> dict[str, str]:
    binding = read_binding(repo, parent_session_id)
    attestation = create_child_attestation(binding, secret=secret, child_pid=child_pid, now=now)
    return {
        "THOMAS_AGENT_ID": binding.agent_id,
        "AGENT_ID": binding.agent_id,
        "THOMAS_AGENT_SESSION_ID": binding.session_id,
        "AGENT_SESSION_ID": binding.session_id,
        ATTESTATION_ENV: json.dumps(attestation, sort_keys=True, separators=(",", ":")),
        ATTESTATION_SECRET_ENV: secret,
    }
