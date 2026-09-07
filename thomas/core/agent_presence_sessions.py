"""Persistent immutable session records used by Thomas agent presence."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from .agent_session_identity import ATTESTATION_SECRET_ENV, SessionIdentityError

ROOT = Path(__file__).resolve().parents[2]
AGENT_ENV_KEYS = ("THOMAS_AGENT_ID", "AGENT_ID", "CODEX_AGENT_ID", "GEMINI_AGENT_ID", "CLAUDE_AGENT_ID")
SESSION_ENV_KEYS = ("THOMAS_AGENT_SESSION_ID", "AGENT_SESSION_ID")


def _repo(repo_root: str | Path | None) -> Path:
    return (Path(repo_root).expanduser() if repo_root is not None else ROOT).resolve()


def _session_path(session_id: str, repo_root: str | Path | None) -> Path:
    return _repo(repo_root) / "runtime" / "coordination" / "presence" / f"{session_id}.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _dedupe(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = str(value or "").strip()
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _normalize_scope(scope: str | Sequence[str] | None) -> list[str]:
    if scope is None:
        return []
    values = scope.split(",") if isinstance(scope, str) else scope
    normalized: list[str] = []
    for item in values:
        token = str(item).strip().replace("\\", "/")
        while token.startswith("./"):
            token = token[2:]
        while "//" in token:
            token = token.replace("//", "/")
        normalized.append(token.rstrip("/"))
    return _dedupe(normalized)


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def current_session_id() -> str:
    populated = [(key, str(os.getenv(key, "")).strip()) for key in SESSION_ENV_KEYS if os.getenv(key, "").strip()]
    if not populated:
        return ""
    if len({value for _key, value in populated}) != 1:
        raise SessionIdentityError(
            "conflicting session identity sources: " + ", ".join(f"{key}={value}" for key, value in populated)
        )
    return populated[0][1]


def resolve_agent_id(explicit_agent: str | None = None) -> str:
    explicit = str(explicit_agent or "").strip()
    if explicit:
        return explicit
    for key in AGENT_ENV_KEYS:
        value = str(os.getenv(key, "")).strip()
        if value:
            return value
    return ""


def session_env_exports(session_id: str, *, handoff_secret: str = "") -> dict[str, str]:
    token = str(session_id or "").strip()
    if not token:
        return {}
    exports = {"THOMAS_AGENT_SESSION_ID": token, "AGENT_SESSION_ID": token}
    if handoff_secret:
        exports[ATTESTATION_SECRET_ENV] = str(handoff_secret)
    return exports


def register_session(
    *,
    repo_root: str | Path | None = None,
    session_id: str | None = None,
    agent_id: str | None = None,
    display_name: str | None = None,
    launcher: str = "",
    task_summary: str = "",
    scope: str | Sequence[str] | None = None,
    claim_status: str = "",
    folder_claims: Sequence[dict[str, Any]] | None = None,
    pid: int | None = None,
    command: str = "",
    warnings: Sequence[str] | None = None,
    origin: str = "explicit",
    handoff_secret: str = "",
) -> dict[str, Any]:
    repo = _repo(repo_root)
    sid = str(session_id or current_session_id() or uuid.uuid4()).strip()
    path = _session_path(sid, repo)
    existing = _read(path)
    resolved_agent = resolve_agent_id(agent_id)
    candidate_pid = int(pid if pid is not None else existing.get("pid") or os.getpid())
    if existing:
        existing_agent = str(existing.get("agent_id") or "").strip()
        if not existing_agent or existing_agent.casefold() != resolved_agent.casefold():
            raise SessionIdentityError(
                f"session {sid} is immutably bound to {existing_agent or '<missing>'}, not {resolved_agent or '<missing>'}"
            )
        existing_pid = int(existing.get("pid") or 0)
        if existing_pid and existing_pid != candidate_pid:
            raise SessionIdentityError(f"session {sid} is immutably bound to PID {existing_pid}, not {candidate_pid}")
        if str(existing.get("state") or "").strip().casefold() not in {"active", "alive"}:
            raise SessionIdentityError(f"session {sid} is closed and cannot be reopened")
    now = _now()
    payload = {
        "session_id": sid,
        "agent_id": resolved_agent,
        "display_name": str(display_name or existing.get("display_name") or resolved_agent or sid).strip(),
        "repo_root": str(repo),
        "pid": candidate_pid,
        "launcher": str(launcher or existing.get("launcher") or Path(sys.argv[0] or "python").name),
        "task_summary": str(task_summary or existing.get("task_summary") or "").strip(),
        "scope": _normalize_scope(scope if scope is not None else existing.get("scope")),
        "claim_status": str(claim_status or existing.get("claim_status") or "").strip(),
        "folder_claims": list(folder_claims if folder_claims is not None else existing.get("folder_claims") or []),
        "started_at": str(existing.get("started_at") or _to_iso(now)),
        "last_heartbeat_at": _to_iso(now),
        "last_activity_at": _to_iso(now),
        "state": "active",
        "confidence": "high",
        "source_signals": _dedupe([*list(existing.get("source_signals") or []), "session"]),
        "warnings": _dedupe([*list(existing.get("warnings") or []), *[str(item) for item in warnings or []]]),
        "command": str(command or existing.get("command") or " ".join(sys.argv)).strip(),
        "origin": str(origin or existing.get("origin") or "explicit").strip(),
        "handoff_key_sha256": (
            hashlib.sha256(handoff_secret.encode()).hexdigest()
            if handoff_secret
            else str(existing.get("handoff_key_sha256") or "")
        ),
    }
    _write(path, payload)
    return payload


def heartbeat_session(
    *,
    repo_root: str | Path | None = None,
    session_id: str | None = None,
    task_summary: str | None = None,
    scope: str | Sequence[str] | None = None,
    claim_status: str | None = None,
    folder_claims: Sequence[dict[str, Any]] | None = None,
    mark_active: bool = True,
    handoff_secret: str = "",
) -> dict[str, Any] | None:
    sid = str(session_id or current_session_id()).strip()
    if not sid:
        return None
    path = _session_path(sid, repo_root)
    payload = _read(path)
    if not payload:
        return None
    now = _now()
    payload["last_heartbeat_at"] = _to_iso(now)
    if mark_active:
        payload.update({"last_activity_at": _to_iso(now), "state": "active"})
    if task_summary is not None:
        payload["task_summary"] = str(task_summary).strip()
    if scope is not None:
        payload["scope"] = _normalize_scope(scope)
    if claim_status is not None:
        payload["claim_status"] = str(claim_status).strip()
    if folder_claims is not None:
        payload["folder_claims"] = list(folder_claims)
    if handoff_secret:
        payload["handoff_key_sha256"] = hashlib.sha256(handoff_secret.encode()).hexdigest()
    payload["source_signals"] = _dedupe([*list(payload.get("source_signals") or []), "session"])
    _write(path, payload)
    return payload


def close_session(*, repo_root: str | Path | None = None, session_id: str | None = None, state: str = "closed") -> bool:
    sid = str(session_id or current_session_id()).strip()
    if not sid:
        return False
    path = _session_path(sid, repo_root)
    payload = _read(path)
    if not payload:
        return False
    now = _now()
    payload.update({"state": str(state or "closed").strip() or "closed", "last_heartbeat_at": _to_iso(now)})
    payload["closed_at"] = _to_iso(now)
    _write(path, payload)
    return True


def _parse_iso(value: object) -> datetime | None:
    token = str(value or "").strip()
    if token.endswith("Z"):
        token = token[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(token)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _scope_string(value: object) -> str:
    values = value if isinstance(value, list) else str(value or "").split(",")
    return ",".join(_normalize_scope([str(item) for item in values]))


def evaluate_inactive_takeover_holder(
    *,
    repo_root: Path,
    holder: str,
    holder_task: str,
    scope: str,
    now: datetime,
    active_folders_path: Callable[[Path], Path],
    session_path_for: Callable[[str, Path], Path],
    process_rows: Callable[[Path], list[dict[str, Any]]],
    pid_alive: Callable[[int], bool],
    stale_seconds: int,
    agent_key: Callable[[str], str],
) -> tuple[bool, str, dict[str, object]]:
    """Prove one holder is stale/dead using exact lease, session, and process signals."""
    leases_payload = _read(active_folders_path(repo_root))
    all_leases = [row for row in list(leases_payload.get("claims") or []) if isinstance(row, dict)]
    holder_key = agent_key(holder)
    holder_leases = [row for row in all_leases if agent_key(str(row.get("agent_id") or "")) == holder_key]
    exact = [
        row
        for row in holder_leases
        if _scope_string(row.get("paths")) == scope and str(row.get("note") or "").strip() == holder_task
    ]
    if len(exact) != 1:
        return False, f"automatic takeover requires one exact immutable lease for `{holder}`", {}
    lease = exact[0]
    expires = _parse_iso(lease.get("expires_at"))
    if expires is None or expires > now:
        return False, f"automatic takeover lease for `{holder}` is not verifiably expired", {}
    if any((_parse_iso(row.get("expires_at")) or now) > now for row in holder_leases if row is not lease):
        return False, f"automatic takeover rejected: `{holder}` still has a live lease", {}
    session_id = str(lease.get("session_id") or "").strip()
    session_path = session_path_for(session_id, repo_root)
    session = _read(session_path)
    if (
        not session_id
        or str(session.get("session_id") or "") != session_id
        or agent_key(str(session.get("agent_id") or "")) != holder_key
        or _scope_string(session.get("scope")) != scope
    ):
        return False, f"automatic takeover has missing or ambiguous immutable session binding for `{holder}`", {}
    live_pids: set[int] = set()
    for row in [lease, session]:
        try:
            pid = int(row.get("pid") or 0)
        except (TypeError, ValueError):
            pid = 0
        if pid and pid_alive(pid):
            live_pids.add(pid)
    for row in process_rows(repo_root):
        identities = {agent_key(str(row.get(key) or "")) for key in ("agent_id", "agent_hint", "name", "display_name")}
        try:
            pid = int(row.get("pid") or 0)
        except (TypeError, ValueError):
            pid = 0
        if holder_key in identities and pid and pid_alive(pid):
            live_pids.add(pid)
    for candidate in session_path.parent.glob("*.json"):
        other = _read(candidate)
        if agent_key(str(other.get("agent_id") or "")) != holder_key:
            continue
        try:
            pid = int(other.get("pid") or 0)
        except (TypeError, ValueError):
            pid = 0
        heartbeat = _parse_iso(other.get("last_heartbeat_at"))
        state = str(other.get("state") or "").strip().casefold()
        if pid and pid_alive(pid):
            live_pids.add(pid)
        if state in {"active", "alive"} and heartbeat and (now - heartbeat).total_seconds() <= stale_seconds:
            return False, f"automatic takeover rejected: `{holder}` still has a live session", {}
    if live_pids:
        return False, f"automatic takeover rejected: `{holder}` still has live process PID(s) {sorted(live_pids)}", {}
    heartbeat = _parse_iso(session.get("last_heartbeat_at"))
    state = str(session.get("state") or "").strip().casefold()
    if state != "closed" and (heartbeat is None or (now - heartbeat).total_seconds() <= stale_seconds):
        return False, f"automatic takeover session for `{holder}` is not closed or stale", {}
    return (
        True,
        "expired exact lease and stale/dead immutable session verified",
        {
            "mode": "automatic_stale_dead",
            "holder": holder,
            "task": holder_task,
            "scope": scope,
            "session_id": session_id,
            "lease_expires_at": str(lease.get("expires_at") or ""),
        },
    )
