#!/usr/bin/env python3
"""Manage agent-to-agent coordination traffic in WORKBOARD.md."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# The `_REPO_ROOT` sys.path insert above this block guarantees `scripts.*` is
# importable in both Windows local and Linux CI environments, so a fallback
# branch with the truncated `crew.*` / `forge.*` paths is no longer needed
# (see scripts/crew/tasks/messages.py for the same simplification).
from scripts.crew.workboard import issue as workboard_issue
from scripts.forge.gates import workboard_claims as claims_gate


def _canonical_repo_root() -> Path:
    """Resolve the PRIMARY (main) worktree root so every worktree shares ONE
    coordination board + lock.

    ``Path(__file__).parents[3]`` resolves to *this script copy's* worktree. Each
    linked git worktree has its own copy of this script AND its own checked-out
    ``plans/thomas/WORKBOARD.md`` + ``runtime/coordination`` lock -- so an agent
    running the tool from a worktree silently reads/writes a DIFFERENT board than
    an agent in the main checkout, and their locks don't interlock. That fragments
    agent-to-agent messages (a real, observed misdelivery). Anchoring to the main
    worktree via git's shared common-dir makes all copies converge on one board.
    Falls back to the local script root if git is unavailable.
    """
    local_root = Path(__file__).resolve().parents[3]
    try:
        import subprocess

        out = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=str(local_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            common = Path(out.stdout.strip())
            # The shared common dir is "<main-worktree>/.git" (a dir for normal
            # repos). Its parent is the main worktree root, identical for the main
            # checkout and every linked worktree.
            if common.name == ".git" and common.parent.exists():
                return common.parent
    except Exception:
        pass
    return local_root


ROOT = _canonical_repo_root()
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"
COORDINATION_DIR = ROOT / "runtime" / "coordination"
LOCK_FILE = COORDINATION_DIR / "workboard_message.lock"
LOCK_TIMEOUT_SECONDS = 10.0
LOCK_STALE_SECONDS = 60.0
MESSAGE_HEADING = "Agent Message Traffic"
NONE_ENTRY = "- none"

MESSAGE_STATES = {"open", "acked", "resolved"}
MESSAGE_PRIORITIES = {"p0", "p1", "p2"}
ESCALATION_MINUTES = {"p0": 15, "p1": 60}
IDENTITY_MISMATCH_STALE_SECONDS = 24 * 60 * 60
PRIORITY_SORT = {"p0": 0, "p1": 1, "p2": 2}
AGENT_ENV_KEYS = (
    "THOMAS_AGENT_ID",
    "AGENT_ID",
    "CODEX_AGENT_ID",
    "CLAUDE_AGENT_ID",
    "GEMINI_AGENT_ID",
)
MESSAGE_KINDS = {
    "coordination",
    "scope_change",
    "blocker",
    "handoff",
    "status",
    "decision",
    "ping",
    "brainstorm_call",
    "brainstorm_note",
    "brainstorm_decision",
}
MESSAGE_DECISIONS = {"none", "pending", "approved", "rejected"}
TASK_ID_OPTIONAL_KINDS = {"coordination", "ping"}
ACTION_FLAGS = {"send", "ack", "resolve", "list", "inbox", "current", "audit", "wait"}


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _is_task_manager_agent(agent: str) -> bool:
    return _norm(agent) in {"thomas", "task-manager-agent", "task-manager"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def _file_lock(lock_file: Path = LOCK_FILE, timeout: float = LOCK_TIMEOUT_SECONDS):
    COORDINATION_DIR.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout
    fd: int | None = None
    while True:
        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"pid={os.getpid()} ts={time.time():.3f}".encode("utf-8", errors="ignore"))
            break
        except (FileExistsError, PermissionError):
            try:
                age = time.time() - lock_file.stat().st_mtime
            except FileNotFoundError:
                age = 0.0
            if age > LOCK_STALE_SECONDS:
                try:
                    lock_file.unlink()
                except (FileNotFoundError, PermissionError):
                    pass
                continue
            if time.time() >= deadline:
                raise TimeoutError(f"Timed out waiting for lock: {lock_file}")
            time.sleep(0.05)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            lock_file.unlink()
        except FileNotFoundError:
            pass


def resolve_current_agent(explicit: str = "") -> str:
    candidate = str(explicit or "").strip()
    if candidate:
        return candidate
    for key in AGENT_ENV_KEYS:
        value = str(os.getenv(key) or "").strip()
        if value:
            return value
    if str(os.getenv("CODEX_SHELL") or "").strip() or str(os.getenv("CODEX_THREAD_ID") or "").strip():
        return "codex"
    return ""


def _parse_iso_utc(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _message_age_seconds(row: dict[str, str], *, now: datetime | None = None) -> int:
    stamp = _parse_iso_utc(str(row.get("updated_at") or row.get("created_at") or ""))
    if stamp is None:
        return 0
    current = now or datetime.now(timezone.utc)
    return max(0, int((current - stamp).total_seconds()))


def _escalation(row: dict[str, str], *, now: datetime | None = None) -> str:
    if _norm(row.get("state", "")) != "open":
        return ""
    threshold = ESCALATION_MINUTES.get(_norm(row.get("priority", "")))
    if threshold is None:
        return ""
    age_seconds = _message_age_seconds(row, now=now)
    if age_seconds >= threshold * 60:
        return f"stale_{_norm(row.get('priority', ''))}"
    return ""


def _decorate_message(row: dict[str, str], *, now: datetime | None = None) -> dict[str, str]:
    out = dict(row)
    out["age_seconds"] = str(_message_age_seconds(row, now=now))
    out["escalation"] = _escalation(row, now=now)
    return out


def _identity_terms(agent: str) -> set[str]:
    key = _norm(agent)
    if not key:
        return set()
    terms = {key}
    first = re.split(r"[^a-z0-9]+", key, maxsplit=1)[0]
    if first in {"claude", "codex", "gemini"}:
        terms.add(first)
    if _is_task_manager_agent(agent):
        terms.update({"thomas", "task-manager", "task-manager-agent"})
    return terms


def _mentions_any_identity(text: str, terms: set[str]) -> bool:
    haystack = _norm(text)
    for term in terms:
        if not term:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", haystack):
            return True
    return False


def _mentions_agent_context(text: str, *, agent: str, peer: str = "") -> bool:
    agent_terms = _identity_terms(agent)
    if not agent_terms or not _mentions_any_identity(text, agent_terms):
        return False
    peer_terms = _identity_terms(peer)
    if peer_terms:
        return _mentions_any_identity(text, peer_terms)
    return True


def _is_ephemeral_agent_identity(value: str) -> bool:
    key = _norm(value)
    return key.startswith("process:") or key in {
        "process",
        "unregistered",
        "unregistered-worktree",
        "unknown",
    }


def _message_search_text(row: dict[str, str]) -> str:
    return " ".join(
        str(row.get(key, "") or "")
        for key in (
            "msg_id",
            "from",
            "to",
            "task_id",
            "kind",
            "summary",
            "requested_action",
        )
    )


def _sanitize(label: str, value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{label} is required")
    return cleaned


def _escape_field_value(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n").replace(";", "\\;")


def _unescape_field_value(value: str) -> str:
    out: list[str] = []
    escaped = False
    for char in str(value or ""):
        if escaped:
            if char == "n":
                out.append("\n")
            elif char == "r":
                out.append("\r")
            elif char in {";", "\\"}:
                out.append(char)
            else:
                out.append("\\")
                out.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        out.append(char)
    if escaped:
        out.append("\\")
    return "".join(out)


def _split_kv_parts(token: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    escaped = False
    for char in str(token or ""):
        if escaped:
            current.append("\\")
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == ";":
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            continue
        current.append(char)
    if escaped:
        current.append("\\")
    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts


def _find_section(lines: Sequence[str], *, heading_prefix: str) -> tuple[int, int] | None:
    start: int | None = None
    end = len(lines)
    wanted = str(heading_prefix or "").strip().lower()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped[3:].strip().lower()
            if start is None:
                if heading.startswith(wanted):
                    start = idx + 1
            else:
                end = idx
                break
    if start is None:
        return None
    return start, end


def _ensure_section(lines: list[str], *, heading: str) -> tuple[int, int]:
    existing = _find_section(lines, heading_prefix=heading)
    if existing is not None:
        return existing

    insert_idx = len(lines)
    supporting = _find_section(lines, heading_prefix="supporting docs")
    if supporting is not None:
        insert_idx = max(0, supporting[0] - 1)

    payload = [f"## {heading}", "", NONE_ENTRY, ""]
    if insert_idx > 0 and lines[insert_idx - 1].strip():
        payload.insert(0, "")
    lines[insert_idx:insert_idx] = payload
    ensured = _find_section(lines, heading_prefix=heading)
    if ensured is None:
        raise ValueError(f"failed to create `## {heading}` section")
    return ensured


def _bullet_indices(lines: Sequence[str], start: int, end: int) -> list[int]:
    out: list[int] = []
    for idx in range(start, end):
        if lines[idx].strip().startswith("- "):
            out.append(idx)
    return out


def _parse_kv_entry(line_no: int, line: str) -> tuple[str | None, dict[str, str] | None, str | None]:
    stripped = line.strip()
    if not stripped.startswith("- "):
        return None, None, f"line {line_no}: expected bullet entry"
    token = stripped[2:].strip()
    if token.lower() in claims_gate.NONE_TOKENS:
        return token, None, None

    fields: dict[str, str] = {}
    for part in _split_kv_parts(token):
        if "=" not in part:
            return token, None, f"line {line_no}: invalid field `{part}`"
        key, value = part.split("=", 1)
        key = key.strip().lower()
        value = _unescape_field_value(value.strip())
        if not key or not value:
            return token, None, f"line {line_no}: invalid key/value field `{part}`"
        fields[key] = value
    return token, fields, None


def _write_entries(lines: list[str], *, section_start: int, section_end: int, entries: list[str]) -> None:
    for idx in sorted(_bullet_indices(lines, section_start, section_end), reverse=True):
        del lines[idx]
        if idx < section_end:
            section_end -= 1
    if not entries:
        lines.insert(section_end, NONE_ENTRY)
        return
    for entry in entries:
        lines.insert(section_end, entry)
        section_end += 1


def _validate_state(state: str) -> str:
    normalized = _norm(state)
    if normalized not in MESSAGE_STATES:
        allowed = ", ".join(sorted(MESSAGE_STATES))
        raise ValueError(f"state must be one of: {allowed}")
    return normalized


def _validate_priority(priority: str) -> str:
    normalized = _norm(priority)
    if normalized not in MESSAGE_PRIORITIES:
        allowed = ", ".join(sorted(MESSAGE_PRIORITIES))
        raise ValueError(f"priority must be one of: {allowed}")
    return normalized


def _validate_kind(kind: str) -> str:
    normalized = _norm(kind)
    if normalized not in MESSAGE_KINDS:
        allowed = ", ".join(sorted(MESSAGE_KINDS))
        raise ValueError(f"kind must be one of: {allowed}")
    return normalized


def _validate_decision(decision: str) -> str:
    normalized = _norm(decision or "none")
    if normalized not in MESSAGE_DECISIONS:
        allowed = ", ".join(sorted(MESSAGE_DECISIONS))
        raise ValueError(f"decision must be one of: {allowed}")
    return normalized


def _format_message(fields: dict[str, str]) -> str:
    msg_id = _sanitize("msg_id", fields.get("msg_id", ""))
    sender = _sanitize("from", fields.get("from", ""))
    recipient = _sanitize("to", fields.get("to", ""))
    task_id = _sanitize("task_id", fields.get("task_id", "none"))
    kind = _validate_kind(fields.get("kind", "coordination"))
    priority = _validate_priority(fields.get("priority", "p1"))
    state = _validate_state(fields.get("state", "open"))
    summary = _sanitize("summary", fields.get("summary", ""))
    requested_action = _sanitize("requested_action", fields.get("requested_action", "none"))
    decision = _validate_decision(fields.get("decision", "none"))
    created_at = _sanitize("created_at", fields.get("created_at", ""))
    updated_at = _sanitize("updated_at", fields.get("updated_at", created_at))
    updated_by = _sanitize("updated_by", fields.get("updated_by", sender))
    parts = {
        "msg_id": msg_id,
        "from": sender,
        "to": recipient,
        "task_id": task_id,
        "kind": kind,
        "priority": priority,
        "state": state,
        "summary": summary,
        "requested_action": requested_action,
        "decision": decision,
        "created_at": created_at,
        "updated_at": updated_at,
        "updated_by": updated_by,
    }
    rendered = "; ".join(f"{key}={_escape_field_value(value)}" for key, value in parts.items())
    return f"- {rendered}"


def _normalize_message_fields(fields: dict[str, str]) -> dict[str, str]:
    now_iso = _now_iso()
    out = {
        "msg_id": str(fields.get("msg_id", "")).strip(),
        "from": str(fields.get("from", "")).strip(),
        "to": str(fields.get("to", "")).strip(),
        "task_id": str(fields.get("task_id", "none")).strip() or "none",
        "kind": str(fields.get("kind", "coordination")).strip() or "coordination",
        "priority": str(fields.get("priority", "p1")).strip() or "p1",
        "state": str(fields.get("state", "open")).strip() or "open",
        "summary": str(fields.get("summary", "")).strip(),
        "requested_action": str(fields.get("requested_action", "none")).strip() or "none",
        "decision": str(fields.get("decision", "none")).strip() or "none",
        "created_at": str(fields.get("created_at", now_iso)).strip() or now_iso,
        "updated_at": str(fields.get("updated_at", now_iso)).strip() or now_iso,
        "updated_by": str(fields.get("updated_by", fields.get("from", ""))).strip()
        or str(fields.get("from", "")).strip(),
    }
    # Validate all fields through canonical formatter.
    _format_message(out)
    return out


def _load_messages(lines: Sequence[str], section: tuple[int, int]) -> tuple[list[dict[str, str]], list[str]]:
    rows: list[dict[str, str]] = []
    errors: list[str] = []
    for idx in _bullet_indices(lines, section[0], section[1]):
        entry, fields, err = _parse_kv_entry(idx + 1, lines[idx])
        if err:
            errors.append(err)
            continue
        if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        try:
            rows.append(_normalize_message_fields(fields))
        except Exception as exc:
            errors.append(f"line {idx + 1}: {exc}")
    return rows, errors


def _next_message_id(messages: Sequence[dict[str, str]], sender: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", _norm(sender)).strip("-") or "agent"
    candidate = f"msg-{stamp}-{slug}"
    seen = {_norm(row.get("msg_id", "")) for row in messages}
    if _norm(candidate) not in seen:
        return candidate
    counter = 2
    while True:
        variant = f"{candidate}-{counter}"
        if _norm(variant) not in seen:
            return variant
        counter += 1


def _write_messages(
    workboard_path: Path,
    *,
    messages: Sequence[dict[str, str]],
    require_claims_to_have_active_task: bool,
) -> tuple[bool, list[str]]:
    original_text = workboard_path.read_text(encoding="utf-8")
    lines = original_text.splitlines()
    section = _ensure_section(lines, heading=MESSAGE_HEADING)
    entries = [_format_message(dict(row)) for row in messages]
    _write_entries(lines, section_start=section[0], section_end=section[1], entries=entries)
    new_text = "\n".join(lines) + ("\n" if original_text.endswith("\n") else "")
    ok, violations = workboard_issue._validate_and_write(  # type: ignore[attr-defined]
        workboard_path,
        original_text,
        new_text,
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
    )
    return ok, list(violations)


def list_messages(
    workboard_path: Path,
    *,
    sender: str = "",
    recipient: str = "",
    state: str = "",
    task_id: str = "",
) -> tuple[bool, dict[str, object]]:
    if not workboard_path.exists():
        return True, {"messages": [], "message_count": 0, "missing_workboard": True}
    lines = workboard_path.read_text(encoding="utf-8").splitlines()
    section = _find_section(lines, heading_prefix=MESSAGE_HEADING)
    if section is None:
        return True, {"messages": [], "message_count": 0}
    rows, errors = _load_messages(lines, section)
    if errors:
        return False, {"error": "message section parse failed", "violations": errors}

    sender_key = _norm(sender)
    recipient_key = _norm(recipient)
    state_key = _norm(state)
    task_key = _norm(task_id)
    # Treat the task-manager aliases (thomas / task-manager-agent /
    # task-manager) as interchangeable for sender + recipient filters so
    # callers like swarm.cli::_online_agents_for_swarm (which queries with
    # coordinator="thomas") still see messages addressed to
    # "task-manager-agent" — and vice versa.
    sender_is_tm = _is_task_manager_agent(sender)
    recipient_is_tm = _is_task_manager_agent(recipient)
    now = datetime.now(timezone.utc)
    out: list[dict[str, str]] = []
    for row in rows:
        row_from = _norm(row.get("from", ""))
        row_to = _norm(row.get("to", ""))
        if sender_key:
            sender_match = (sender_is_tm and _is_task_manager_agent(row.get("from", ""))) or row_from == sender_key
            if not sender_match:
                continue
        if recipient_key:
            recipient_match = (recipient_is_tm and _is_task_manager_agent(row.get("to", ""))) or row_to == recipient_key
            if not recipient_match:
                continue
        if state_key and _norm(row.get("state", "")) != state_key:
            continue
        if task_key and _norm(row.get("task_id", "")) != task_key:
            continue
        out.append(_decorate_message(dict(row), now=now))
    if recipient_key and (not state_key or state_key == "open"):
        out.sort(
            key=lambda row: (
                PRIORITY_SORT.get(_norm(row.get("priority", "")), 99),
                0 if str(row.get("escalation") or "").strip() else 1,
                -int(str(row.get("age_seconds") or "0") or "0"),
                str(row.get("created_at") or ""),
            )
        )
    return True, {"messages": out, "message_count": len(out)}


def current_messages(
    workboard_path: Path,
    *,
    agent: str,
    peer: str = "",
    task_id: str = "",
    limit: int = 20,
) -> tuple[bool, dict[str, object]]:
    agent_clean = str(agent or "").strip()
    if not agent_clean:
        return False, {"error": "agent identity is required for current-thread checks"}
    ok, payload = list_messages(workboard_path)
    if not ok:
        return False, payload

    agent_key = _norm(agent_clean)
    peer_key = _norm(peer)
    task_key = _norm(task_id)
    agent_is_tm = _is_task_manager_agent(agent_clean)
    peer_is_tm = _is_task_manager_agent(peer)

    def _matches_identity(value: str, key: str, is_task_manager: bool) -> bool:
        return (is_task_manager and _is_task_manager_agent(value)) or _norm(value) == key

    rows: list[dict[str, str]] = []
    for row in list(payload.get("messages") or []):
        if _norm(str(row.get("state", ""))) == "resolved":
            continue
        if task_key and _norm(str(row.get("task_id", ""))) != task_key:
            continue
        sender = str(row.get("from") or "")
        recipient = str(row.get("to") or "")
        from_agent = _matches_identity(sender, agent_key, agent_is_tm)
        to_agent = _matches_identity(recipient, agent_key, agent_is_tm)
        if not (from_agent or to_agent):
            continue
        if peer_key:
            from_peer = _matches_identity(sender, peer_key, peer_is_tm)
            to_peer = _matches_identity(recipient, peer_key, peer_is_tm)
            if not (from_peer or to_peer):
                continue
        next_row = dict(row)
        if to_agent:
            next_row["direction"] = "incoming"
            next_row["awaiting"] = "me" if _norm(str(row.get("state", ""))) == "open" else "thread"
        else:
            next_row["direction"] = "outgoing"
            next_row["awaiting"] = "peer" if _norm(str(row.get("state", ""))) == "open" else "thread"
        rows.append(next_row)

    def _stamp(row: dict[str, str]) -> datetime:
        return _parse_iso_utc(str(row.get("updated_at") or row.get("created_at") or "")) or datetime.min.replace(
            tzinfo=timezone.utc
        )

    rows.sort(
        key=lambda row: (
            _stamp(row),
            -PRIORITY_SORT.get(_norm(row.get("priority", "")), 99),
            str(row.get("msg_id") or ""),
        ),
        reverse=True,
    )
    max_rows = max(1, int(limit or 20))
    rows = rows[:max_rows]
    result = {
        "messages": rows,
        "message_count": len(rows),
        "agent": agent_clean,
        "peer": str(peer or "").strip(),
        "task_id": str(task_id or "").strip(),
    }
    if payload.get("missing_workboard"):
        result["missing_workboard"] = True
    return True, result


def audit_messages(
    workboard_path: Path,
    *,
    agent: str = "",
    peer: str = "",
    task_id: str = "",
    limit: int = 20,
) -> tuple[bool, dict[str, object]]:
    agent_clean = str(agent or "").strip()
    peer_clean = str(peer or "").strip()
    task_key = _norm(task_id)
    max_rows = max(1, int(limit or 20))
    if not workboard_path.exists():
        return True, {
            "agent": agent_clean,
            "peer": peer_clean,
            "task_id": str(task_id or "").strip(),
            "canonical_inbox_count": 0,
            "canonical_current_count": 0,
            "awaiting_me": 0,
            "awaiting_peer": 0,
            "awaiting_peer_oldest_seconds": 0,
            "awaiting_peer_msg_id": "",
            "parse_error_count": 0,
            "candidate_mention_count": 0,
            "identity_mismatch_count": 0,
            "stale_identity_mismatch_count": 0,
            "cross_task_open_p0_count": 0,
            "problem_count": 0,
            "parse_errors": [],
            "candidate_mentions": [],
            "identity_mismatches": [],
            "stale_identity_mismatches": [],
            "cross_task_open_p0": [],
            "diagnosis": "workboard missing; no message lane state is available",
            "missing_workboard": True,
        }

    lines = workboard_path.read_text(encoding="utf-8").splitlines()
    section = _find_section(lines, heading_prefix=MESSAGE_HEADING)
    if section is None:
        return True, {
            "agent": agent_clean,
            "peer": peer_clean,
            "task_id": str(task_id or "").strip(),
            "canonical_inbox_count": 0,
            "canonical_current_count": 0,
            "awaiting_me": 0,
            "awaiting_peer": 0,
            "awaiting_peer_oldest_seconds": 0,
            "awaiting_peer_msg_id": "",
            "parse_error_count": 0,
            "candidate_mention_count": 0,
            "identity_mismatch_count": 0,
            "stale_identity_mismatch_count": 0,
            "cross_task_open_p0_count": 0,
            "problem_count": 0,
            "parse_errors": [],
            "candidate_mentions": [],
            "identity_mismatches": [],
            "stale_identity_mismatches": [],
            "cross_task_open_p0": [],
            "diagnosis": "missing Agent Message Traffic section",
            "missing_section": True,
        }

    rows: list[dict[str, str]] = []
    parse_errors: list[dict[str, object]] = []
    candidate_mentions: list[dict[str, object]] = []
    identity_mismatches: list[dict[str, object]] = []
    stale_identity_mismatches: list[dict[str, object]] = []
    for idx in range(section[0], section[1]):
        raw = lines[idx]
        stripped = raw.strip()
        if not stripped or stripped.startswith("<!--"):
            continue
        if stripped.startswith("- "):
            entry, fields, err = _parse_kv_entry(idx + 1, raw)
            if err:
                parse_errors.append({"line": idx + 1, "error": err, "text": stripped})
                if _mentions_agent_context(stripped, agent=agent_clean, peer=peer_clean):
                    candidate_mentions.append({"line": idx + 1, "kind": "malformed_bullet", "text": stripped})
                continue
            if entry is not None and entry.lower() in claims_gate.NONE_TOKENS:
                continue
            if not fields:
                continue
            try:
                rows.append(_normalize_message_fields(fields))
            except Exception as exc:
                parse_errors.append({"line": idx + 1, "error": str(exc), "text": stripped})
                if _mentions_agent_context(stripped, agent=agent_clean, peer=peer_clean):
                    candidate_mentions.append({"line": idx + 1, "kind": "invalid_bullet", "text": stripped})
            continue
        if _mentions_agent_context(stripped, agent=agent_clean, peer=peer_clean):
            candidate_mentions.append({"line": idx + 1, "kind": "noncanonical_text", "text": stripped})

    agent_key = _norm(agent_clean)
    peer_key = _norm(peer_clean)
    agent_is_tm = _is_task_manager_agent(agent_clean)
    peer_is_tm = _is_task_manager_agent(peer_clean)

    def _matches(value: str, key: str, is_task_manager: bool) -> bool:
        return (is_task_manager and _is_task_manager_agent(value)) or _norm(value) == key

    inbox_rows: list[dict[str, str]] = []
    current_rows: list[dict[str, str]] = []
    cross_task_open_p0: list[dict[str, str]] = []
    awaiting_me = 0
    awaiting_peer = 0
    awaiting_peer_oldest: dict[str, str] | None = None
    for row in rows:
        state = _norm(row.get("state", ""))
        sender = str(row.get("from") or "")
        recipient = str(row.get("to") or "")
        from_agent = bool(agent_key) and _matches(sender, agent_key, agent_is_tm)
        to_agent = bool(agent_key) and _matches(recipient, agent_key, agent_is_tm)
        from_peer = bool(peer_key) and _matches(sender, peer_key, peer_is_tm)
        row_task_key = _norm(row.get("task_id", ""))
        if task_key and row_task_key != task_key:
            if state == "open" and to_agent and (not peer_key or from_peer) and _norm(row.get("priority", "")) == "p0":
                cross_task_open_p0.append(_decorate_message(dict(row)))
            continue
        message_text = _message_search_text(row)
        if to_agent and state == "open":
            inbox_rows.append(_decorate_message(dict(row)))
        elif (
            state == "open"
            and agent_key
            and not from_agent
            and (
                (from_peer and _is_ephemeral_agent_identity(recipient))
                or _mentions_agent_context(message_text, agent=agent_clean, peer=peer_clean)
            )
        ):
            mismatch = _decorate_message(dict(row))
            mismatch["expected_to"] = agent_clean
            mismatch["actual_to"] = recipient
            mismatch["reason"] = (
                "open peer message is addressed to an ephemeral/unregistered identity"
                if _is_ephemeral_agent_identity(recipient)
                else "open message mentions this agent but is not addressed to its canonical identity"
            )
            if not task_key and int(mismatch.get("age_seconds") or 0) > IDENTITY_MISMATCH_STALE_SECONDS:
                stale_identity_mismatches.append(mismatch)
            else:
                identity_mismatches.append(mismatch)
        if not (from_agent or to_agent):
            continue
        if peer_key:
            to_peer = _matches(recipient, peer_key, peer_is_tm)
            if not (from_peer or to_peer):
                continue
        if state == "resolved":
            continue
        next_row = _decorate_message(dict(row))
        if to_agent:
            next_row["direction"] = "incoming"
            next_row["awaiting"] = "me" if state == "open" else "thread"
            if state == "open":
                awaiting_me += 1
        else:
            next_row["direction"] = "outgoing"
            next_row["awaiting"] = "peer" if state == "open" else "thread"
            if state == "open":
                awaiting_peer += 1
                if awaiting_peer_oldest is None or int(next_row.get("age_seconds") or 0) > int(
                    awaiting_peer_oldest.get("age_seconds") or 0
                ):
                    awaiting_peer_oldest = next_row
        current_rows.append(next_row)

    current_rows.sort(
        key=lambda row: (
            _parse_iso_utc(str(row.get("updated_at") or row.get("created_at") or ""))
            or datetime.min.replace(tzinfo=timezone.utc),
            str(row.get("msg_id") or ""),
        ),
        reverse=True,
    )
    problem_count = len(parse_errors) + len(candidate_mentions) + len(identity_mismatches) + len(cross_task_open_p0)
    if parse_errors:
        diagnosis = "message section has parse errors; canonical inbox/current views may be incomplete"
    elif candidate_mentions:
        diagnosis = "message section contains noncanonical agent mentions that inbox/current views ignore"
    elif identity_mismatches:
        diagnosis = (
            "message section has open messages routed to noncanonical identities; canonical inbox may be incomplete"
        )
    elif cross_task_open_p0:
        diagnosis = "task filter hides open p0 inbound message(s) on other task ids"
    elif inbox_rows:
        diagnosis = "canonical inbox has open messages for this agent"
    elif awaiting_peer:
        diagnosis = "canonical inbox is empty; current thread is waiting on the peer"
    else:
        diagnosis = "canonical inbox is empty and no suspicious message-section mentions were found"
    payload: dict[str, object] = {
        "agent": agent_clean,
        "peer": peer_clean,
        "task_id": str(task_id or "").strip(),
        "canonical_inbox_count": len(inbox_rows),
        "canonical_current_count": len(current_rows),
        "awaiting_me": awaiting_me,
        "awaiting_peer": awaiting_peer,
        "awaiting_peer_oldest_seconds": int(awaiting_peer_oldest.get("age_seconds") or 0)
        if awaiting_peer_oldest
        else 0,
        "awaiting_peer_msg_id": str(awaiting_peer_oldest.get("msg_id") or "") if awaiting_peer_oldest else "",
        "parse_error_count": len(parse_errors),
        "candidate_mention_count": len(candidate_mentions),
        "identity_mismatch_count": len(identity_mismatches),
        "stale_identity_mismatch_count": len(stale_identity_mismatches),
        "cross_task_open_p0_count": len(cross_task_open_p0),
        "problem_count": problem_count,
        "parse_errors": parse_errors[:max_rows],
        "candidate_mentions": candidate_mentions[:max_rows],
        "identity_mismatches": identity_mismatches[:max_rows],
        "stale_identity_mismatches": stale_identity_mismatches[:max_rows],
        "cross_task_open_p0": cross_task_open_p0[:max_rows],
        "messages": current_rows[:max_rows],
        "diagnosis": diagnosis,
    }
    if problem_count:
        payload["error"] = "message lane audit found problems"
    return problem_count == 0, payload


def wait_for_messages(
    workboard_path: Path,
    *,
    agent: str = "",
    peer: str = "",
    task_id: str = "",
    limit: int = 20,
    timeout_seconds: float = 60.0,
    poll_interval_seconds: float = 5.0,
) -> tuple[bool, dict[str, object]]:
    deadline = time.monotonic() + max(0.0, float(timeout_seconds or 0.0))
    poll_interval = max(0.05, float(poll_interval_seconds or 0.0))
    attempts = 0
    while True:
        attempts += 1
        ok, payload = audit_messages(
            workboard_path,
            agent=agent,
            peer=peer,
            task_id=task_id,
            limit=limit,
        )
        payload["wait_attempts"] = attempts
        payload["timeout_seconds"] = float(timeout_seconds or 0.0)
        payload["poll_interval_seconds"] = poll_interval
        if not ok:
            payload["wait_status"] = "problem"
            return False, payload
        if int(payload.get("awaiting_me") or 0) > 0:
            payload["wait_status"] = "ready"
            payload["timed_out"] = False
            return True, payload
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            payload["wait_status"] = "timeout"
            payload["timed_out"] = True
            return True, payload
        time.sleep(min(poll_interval, remaining))


def unread_messages(
    workboard_path: Path,
    *,
    agent: str,
) -> tuple[bool, dict[str, object]]:
    agent_clean = str(agent or "").strip()
    if not agent_clean:
        return False, {"error": "agent identity is required for inbox checks"}
    return list_messages(workboard_path, recipient=agent_clean, state="open")


def send_message(
    workboard_path: Path,
    *,
    sender: str,
    recipient: str,
    summary: str,
    task_id: str = "none",
    kind: str = "coordination",
    priority: str = "p1",
    requested_action: str = "none",
    decision: str = "pending",
    msg_id: str = "",
    replace_open: bool = False,
    replace_open_peer: bool = False,
    require_claims_to_have_active_task: bool = True,
) -> tuple[bool, dict[str, object]]:
    with _file_lock():
        sender_clean = _sanitize("from", sender)
        recipient_clean = _sanitize("to", recipient)
        summary_clean = _sanitize("summary", summary)
        task_clean = _sanitize("task_id", task_id or "none")
        kind_clean = _validate_kind(kind)
        priority_clean = _validate_priority(priority)
        requested_clean = _sanitize("requested_action", requested_action or "none")
        decision_clean = _validate_decision(decision or "pending")
        if _norm(kind_clean) not in TASK_ID_OPTIONAL_KINDS and _norm(task_clean) in {"", "none", "_none_"}:
            return False, {
                "error": (f"task_id is required for kind `{kind_clean}` (only coordination/ping may use task_id=none)")
            }
        if replace_open and not replace_open_peer and _norm(task_clean) in {"", "none", "_none_"}:
            return False, {"error": "--replace-open requires a non-none --task-id"}

        lines = workboard_path.read_text(encoding="utf-8").splitlines()
        section = _ensure_section(lines, heading=MESSAGE_HEADING)
        rows, errors = _load_messages(lines, section)
        if errors:
            return False, {"error": "message section parse failed", "violations": errors}

        message_id = str(msg_id or "").strip() or _next_message_id(rows, sender_clean)
        if any(_norm(row.get("msg_id", "")) == _norm(message_id) for row in rows):
            return False, {"error": f"message id `{message_id}` already exists"}

        now_iso = _now_iso()
        row = _normalize_message_fields(
            {
                "msg_id": message_id,
                "from": sender_clean,
                "to": recipient_clean,
                "task_id": task_clean,
                "kind": kind_clean,
                "priority": priority_clean,
                "state": "open",
                "summary": summary_clean,
                "requested_action": requested_clean,
                "decision": decision_clean,
                "created_at": now_iso,
                "updated_at": now_iso,
                "updated_by": sender_clean,
            }
        )
        replaced: list[dict[str, str]] = []
        if replace_open or replace_open_peer:
            for existing in rows:
                if _norm(existing.get("state", "")) != "open":
                    continue
                if _norm(existing.get("from", "")) != _norm(sender_clean):
                    continue
                if _norm(existing.get("to", "")) != _norm(recipient_clean):
                    continue
                if not replace_open_peer:
                    if _norm(existing.get("task_id", "")) != _norm(task_clean):
                        continue
                    if _norm(existing.get("kind", "")) != _norm(kind_clean):
                        continue
                existing["state"] = "resolved"
                existing["decision"] = "none"
                existing["updated_at"] = now_iso
                existing["updated_by"] = sender_clean
                replaced.append(dict(existing))
        rows.append(row)
        ok, violations = _write_messages(
            workboard_path,
            messages=rows,
            require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
        )
        if not ok:
            return False, {"error": "message update rejected by gate", "violations": violations}
        # Delivery verification: re-read the board we just wrote and confirm the
        # row is really there. A misrouted write (wrong worktree board), a lost
        # lock race, or a silent truncation can otherwise report PASS while the
        # recipient never sees the message. Always surface the resolved path.
        try:
            written_back = workboard_path.read_text(encoding="utf-8")
        except OSError as exc:
            return False, {
                "error": f"delivery verification failed: cannot re-read workboard ({exc})",
                "workboard": str(workboard_path),
            }
        if message_id not in written_back:
            return False, {
                "error": "delivery verification failed: message absent from workboard after write",
                "workboard": str(workboard_path),
            }
        return True, {
            "message": row,
            "replaced_messages": replaced,
            "replaced_count": len(replaced),
            "workboard": str(workboard_path),
        }


def latest_activity_by_task(
    workboard_path: Path,
    *,
    kinds: Sequence[str] | None = None,
) -> tuple[bool, dict[str, object]]:
    ok, payload = list_messages(workboard_path)
    if not ok:
        return False, payload
    allowed = {_norm(item) for item in list(kinds or []) if _norm(item)}
    latest: dict[str, datetime] = {}
    for row in list(payload.get("messages") or []):
        task_key = _norm(str(row.get("task_id", "")))
        if task_key in {"", "none", "_none_"}:
            continue
        kind = _norm(str(row.get("kind", "")))
        if allowed and kind not in allowed:
            continue
        stamp = _parse_iso_utc(str(row.get("updated_at", "")).strip() or str(row.get("created_at", "")).strip())
        if stamp is None:
            continue
        prior = latest.get(task_key)
        if prior is None or stamp > prior:
            latest[task_key] = stamp
    return True, {
        "task_count": len(latest),
        "latest_by_task": {task_id: stamp.isoformat() for task_id, stamp in sorted(latest.items())},
    }


def _set_message_state(
    workboard_path: Path,
    *,
    msg_id: str,
    actor: str,
    state: str,
    decision: str = "",
    require_claims_to_have_active_task: bool = True,
) -> tuple[bool, dict[str, object]]:
    with _file_lock():
        msg_key = _norm(msg_id)
        if not msg_key:
            return False, {"error": "msg_id is required"}
        actor_clean = _sanitize("by", actor)
        state_clean = _validate_state(state)

        lines = workboard_path.read_text(encoding="utf-8").splitlines()
        section = _find_section(lines, heading_prefix=MESSAGE_HEADING)
        if section is None:
            return False, {"error": "missing `## Agent Message Traffic` section"}
        rows, errors = _load_messages(lines, section)
        if errors:
            return False, {"error": "message section parse failed", "violations": errors}

        target: dict[str, str] | None = None
        for row in rows:
            if _norm(row.get("msg_id", "")) == msg_key:
                target = row
                break
        if target is None:
            return False, {"error": f"message `{msg_id}` not found"}

        current_state = _validate_state(target.get("state", "open"))
        if current_state == state_clean:
            return False, {"error": f"message `{msg_id}` already in state `{state_clean}`"}
        if current_state == "resolved":
            return False, {"error": f"message `{msg_id}` is already resolved"}
        if current_state == "acked" and state_clean != "resolved":
            return False, {"error": f"invalid state transition `{current_state}` -> `{state_clean}`"}

        actor_key = _norm(actor_clean)
        sender_key = _norm(target.get("from", ""))
        recipient_key = _norm(target.get("to", ""))
        if state_clean == "acked" and actor_key != recipient_key:
            return False, {
                "error": (f"only recipient `{target.get('to', '')}` can ack message `{target.get('msg_id', msg_id)}`")
            }
        if state_clean == "resolved":
            allowed = {sender_key, recipient_key}
            if actor_key not in allowed and not _is_task_manager_agent(actor_clean):
                return False, {
                    "error": (
                        f"only sender `{target.get('from', '')}` or recipient `{target.get('to', '')}` "
                        f"can resolve message `{target.get('msg_id', msg_id)}`"
                    )
                }

        target["state"] = state_clean
        target["updated_at"] = _now_iso()
        target["updated_by"] = actor_clean
        if decision:
            target["decision"] = _validate_decision(decision)

        ok, violations = _write_messages(
            workboard_path,
            messages=rows,
            require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
        )
        if not ok:
            return False, {"error": "message update rejected by gate", "violations": violations}
        return True, {"message": target}


def ack_message(
    workboard_path: Path,
    *,
    msg_id: str,
    actor: str,
    decision: str = "",
) -> tuple[bool, dict[str, object]]:
    return _set_message_state(
        workboard_path,
        msg_id=msg_id,
        actor=actor,
        state="acked",
        decision=decision,
    )


def resolve_message(
    workboard_path: Path,
    *,
    msg_id: str,
    actor: str,
    decision: str = "",
) -> tuple[bool, dict[str, object]]:
    return _set_message_state(
        workboard_path,
        msg_id=msg_id,
        actor=actor,
        state="resolved",
        decision=decision,
    )


def _normalize_argv(argv: Sequence[str] | None) -> list[str] | None:
    if argv is None:
        argv = sys.argv[1:]
    args = list(argv)
    if args and args[0].lower() in ACTION_FLAGS:
        args[0] = f"--{args[0].lower()}"
    return ["--workboard" if arg == "--board" else arg for arg in args]


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage agent message traffic in WORKBOARD.md.")
    parser.add_argument("--workboard", default=str(DEFAULT_WORKBOARD))
    parser.add_argument("--json", action="store_true")

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--send", action="store_true")
    action.add_argument("--ack", action="store_true")
    action.add_argument("--resolve", action="store_true")
    action.add_argument("--list", action="store_true")
    action.add_argument("--inbox", action="store_true")
    action.add_argument("--current", action="store_true")
    action.add_argument("--audit", action="store_true")
    action.add_argument("--wait", action="store_true")

    parser.add_argument("--msg-id", default="")
    parser.add_argument("--from-agent", default="")
    parser.add_argument("--to-agent", default="")
    parser.add_argument("--by", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--task-id", default="none", help="Task id for send or filtering list/inbox/current output.")
    parser.add_argument("--kind", default="coordination")
    parser.add_argument("--priority", default="p1")
    parser.add_argument("--requested-action", default="none")
    parser.add_argument("--decision", default="")
    parser.add_argument("--state", default="")
    parser.add_argument("--agent", default="", help="Current agent identity for default inbox/sent modes.")
    parser.add_argument("--peer", default="", help="With --current, narrow the thread to this peer agent.")
    parser.add_argument("--limit", type=int, default=20, help="With --current, maximum rows to show.")
    parser.add_argument("--timeout-seconds", type=float, default=60.0, help="With --wait, maximum seconds to poll.")
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=5.0,
        help="With --wait, seconds between polls.",
    )
    parser.add_argument(
        "--fail-on-timeout",
        action="store_true",
        help="With --wait, return nonzero if no inbound message arrives before timeout.",
    )
    parser.add_argument("--all", action="store_true", help="With --list, show all messages instead of my unread inbox.")
    parser.add_argument("--sent", action="store_true", help="With --list, show messages sent by the current agent.")
    parser.add_argument(
        "--replace-open",
        action="store_true",
        help="With --send, resolve older open same sender/to/task/kind messages before appending the new message.",
    )
    parser.add_argument(
        "--replace-open-peer",
        action="store_true",
        help="With --send, resolve older open same sender/to messages before appending the new message.",
    )
    args = parser.parse_args(_normalize_argv(argv))

    workboard_path = Path(args.workboard).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (ROOT / workboard_path).resolve()
    if not workboard_path.exists() and (args.send or args.ack or args.resolve):
        payload = {"ok": False, "error": f"missing workboard file: {workboard_path}"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard message tool: FAIL")
            print(f"- {payload['error']}")
        return 1

    try:
        if args.send:
            ok, payload = send_message(
                workboard_path,
                sender=args.from_agent,
                recipient=args.to_agent,
                summary=args.summary,
                task_id=args.task_id,
                kind=args.kind,
                priority=args.priority,
                requested_action=args.requested_action,
                decision=args.decision or "pending",
                msg_id=args.msg_id,
                replace_open=bool(args.replace_open),
                replace_open_peer=bool(args.replace_open_peer),
            )
            action_name = "send"
        elif args.ack:
            actor = str(args.by or "").strip() or resolve_current_agent(args.agent)
            if not str(args.msg_id).strip() or not actor:
                raise ValueError("--msg-id and --by/--agent are required for --ack")
            ok, payload = ack_message(
                workboard_path,
                msg_id=args.msg_id,
                actor=actor,
                decision=args.decision,
            )
            action_name = "ack"
        elif args.resolve:
            actor = str(args.by or "").strip() or resolve_current_agent(args.agent)
            if not str(args.msg_id).strip() or not actor:
                raise ValueError("--msg-id and --by/--agent are required for --resolve")
            ok, payload = resolve_message(
                workboard_path,
                msg_id=args.msg_id,
                actor=actor,
                decision=args.decision,
            )
            action_name = "resolve"
        elif args.inbox:
            recipient = args.to_agent or resolve_current_agent(args.agent)
            if not recipient:
                raise ValueError("--inbox requires --agent/--to-agent or an agent identity environment variable")
            ok, payload = list_messages(
                workboard_path,
                recipient=recipient,
                state=args.state or "open",
                task_id=args.task_id if _norm(args.task_id) not in {"", "none"} else "",
            )
            action_name = "inbox"
        elif args.current:
            actor = resolve_current_agent(args.agent)
            if not actor:
                raise ValueError("--current requires --agent or an agent identity environment variable")
            ok, payload = current_messages(
                workboard_path,
                agent=actor,
                peer=args.peer,
                task_id=args.task_id if _norm(args.task_id) not in {"", "none"} else "",
                limit=int(args.limit or 20),
            )
            action_name = "current"
        elif args.audit:
            actor = resolve_current_agent(args.agent)
            ok, payload = audit_messages(
                workboard_path,
                agent=actor,
                peer=args.peer,
                task_id=args.task_id if _norm(args.task_id) not in {"", "none"} else "",
                limit=int(args.limit or 20),
            )
            action_name = "audit"
        elif args.wait:
            actor = resolve_current_agent(args.agent)
            if not actor:
                raise ValueError("--wait requires --agent or an agent identity environment variable")
            ok, payload = wait_for_messages(
                workboard_path,
                agent=actor,
                peer=args.peer,
                task_id=args.task_id if _norm(args.task_id) not in {"", "none"} else "",
                limit=int(args.limit or 20),
                timeout_seconds=float(args.timeout_seconds or 0.0),
                poll_interval_seconds=float(args.poll_interval_seconds or 0.0),
            )
            action_name = "wait"
            if bool(args.fail_on_timeout) and payload.get("wait_status") == "timeout":
                ok = False
                payload["error"] = "timed out waiting for inbound message"
        else:
            sender = args.from_agent
            recipient = args.to_agent
            state = args.state
            if args.sent:
                sender = sender or resolve_current_agent(args.agent)
                if not sender:
                    raise ValueError("--sent requires --agent or an agent identity environment variable")
            elif not args.all and not sender and not recipient and not state:
                recipient = resolve_current_agent(args.agent)
                if not recipient:
                    raise ValueError(
                        "--list defaults to this agent's unread inbox; pass --agent, set AGENT_ID/THOMAS_AGENT_ID, "
                        "or use --all"
                    )
                state = "open"
            ok, payload = list_messages(
                workboard_path,
                sender=sender,
                recipient=recipient,
                state=state,
                task_id=args.task_id if _norm(args.task_id) not in {"", "none"} else "",
            )
            action_name = "list"
    except ValueError as exc:
        ok = False
        payload = {"error": str(exc)}
        action_name = "error"

    envelope = {"ok": bool(ok), "action": action_name, "workboard": str(workboard_path), **payload}
    if args.json:
        print(json.dumps(envelope, sort_keys=True))
    else:
        print("Workboard message tool: PASS" if ok else "Workboard message tool: FAIL")
        if ok:
            if action_name in {"list", "inbox", "current"}:
                for row in list(payload.get("messages") or []):
                    priority = str(row.get("priority") or "").strip()
                    escalation = str(row.get("escalation") or "").strip()
                    state_label = str(row.get("state") or "").strip()
                    badge = f"{state_label} {priority}".strip()
                    if escalation:
                        badge = f"{badge} ESCALATED"
                    print(f"- {row.get('msg_id')}: {row.get('from')} -> {row.get('to')} [{badge}] {row.get('summary')}")
            elif action_name in {"audit", "wait"}:
                if action_name == "wait":
                    print(f"- wait_status: {payload.get('wait_status', '')}")
                print(f"- diagnosis: {payload.get('diagnosis', '')}")
                print(
                    "- counts: "
                    f"inbox={payload.get('canonical_inbox_count', 0)}; "
                    f"current={payload.get('canonical_current_count', 0)}; "
                    f"parse_errors={payload.get('parse_error_count', 0)}; "
                    f"candidate_mentions={payload.get('candidate_mention_count', 0)}; "
                    f"identity_mismatches={payload.get('identity_mismatch_count', 0)}; "
                    f"stale_identity_mismatches={payload.get('stale_identity_mismatch_count', 0)}; "
                    f"cross_task_open_p0={payload.get('cross_task_open_p0_count', 0)}"
                )
            else:
                row = dict(payload.get("message") or {})
                print(
                    f"- {row.get('msg_id')}: {row.get('from')} -> {row.get('to')} "
                    f"[{row.get('state')}] {row.get('summary')}"
                )
                delivered_to = payload.get("workboard") or str(workboard_path)
                print(f"- delivered to: {delivered_to}")
        else:
            print(f"- {payload.get('error', 'unknown error')}")
            for item in list(payload.get("violations") or []):
                print(f"- {item}")
            if action_name in {"audit", "wait"}:
                print(f"- diagnosis: {payload.get('diagnosis', '')}")
                for item in list(payload.get("parse_errors") or []):
                    print(f"- parse_error line {item.get('line')}: {item.get('error')}")
                for item in list(payload.get("candidate_mentions") or []):
                    print(f"- candidate_mention line {item.get('line')}: {item.get('text')}")
                for item in list(payload.get("identity_mismatches") or []):
                    print(
                        f"- identity_mismatch {item.get('msg_id')}: "
                        f"{item.get('from')} -> {item.get('actual_to')} "
                        f"(expected {item.get('expected_to')})"
                    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
