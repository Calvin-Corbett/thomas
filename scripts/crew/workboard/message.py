#!/usr/bin/env python3
"""Manage agent-to-agent coordination traffic in WORKBOARD.md."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.crew.workboard import issue as workboard_issue
    from scripts.forge.gates import workboard_claims as claims_gate
except Exception:  # pragma: no cover
    from forge.gates import workboard_claims as claims_gate  # type: ignore

    from scripts.crew.workboard import issue as workboard_issue  # type: ignore


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"
MESSAGE_HEADING = "Agent Message Traffic"
NONE_ENTRY = "- none"

MESSAGE_STATES = {"open", "acked", "resolved"}
MESSAGE_PRIORITIES = {"p0", "p1", "p2"}
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


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _is_task_manager_agent(agent: str) -> bool:
    return _norm(agent) in {"thomas", "task-manager-agent", "task-manager"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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


def _sanitize(label: str, value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{label} is required")
    if ";" in cleaned or "\n" in cleaned or "\r" in cleaned:
        raise ValueError(f"{label} cannot include ';' or newline characters")
    return cleaned


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
    for part in [x.strip() for x in token.split(";") if x.strip()]:
        if "=" not in part:
            return token, None, f"line {line_no}: invalid field `{part}`"
        key, value = part.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
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
    return (
        f"- msg_id={msg_id}; from={sender}; to={recipient}; task_id={task_id}; "
        f"kind={kind}; priority={priority}; state={state}; summary={summary}; "
        f"requested_action={requested_action}; decision={decision}; created_at={created_at}; "
        f"updated_at={updated_at}; updated_by={updated_by}"
    )


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
    out: list[dict[str, str]] = []
    for row in rows:
        if sender_key and _norm(row.get("from", "")) != sender_key:
            continue
        if recipient_key and _norm(row.get("to", "")) != recipient_key:
            continue
        if state_key and _norm(row.get("state", "")) != state_key:
            continue
        if task_key and _norm(row.get("task_id", "")) != task_key:
            continue
        out.append(dict(row))
    return True, {"messages": out, "message_count": len(out)}


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
    require_claims_to_have_active_task: bool = True,
) -> tuple[bool, dict[str, object]]:
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
    rows.append(row)
    ok, violations = _write_messages(
        workboard_path,
        messages=rows,
        require_claims_to_have_active_task=bool(require_claims_to_have_active_task),
    )
    if not ok:
        return False, {"error": "message update rejected by gate", "violations": violations}
    return True, {"message": row}


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


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage agent message traffic in WORKBOARD.md.")
    parser.add_argument("--workboard", default=str(DEFAULT_WORKBOARD))
    parser.add_argument("--json", action="store_true")

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--send", action="store_true")
    action.add_argument("--ack", action="store_true")
    action.add_argument("--resolve", action="store_true")
    action.add_argument("--list", action="store_true")

    parser.add_argument("--msg-id", default="")
    parser.add_argument("--from-agent", default="")
    parser.add_argument("--to-agent", default="")
    parser.add_argument("--by", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--task-id", default="none")
    parser.add_argument("--kind", default="coordination")
    parser.add_argument("--priority", default="p1")
    parser.add_argument("--requested-action", default="none")
    parser.add_argument("--decision", default="")
    parser.add_argument("--state", default="")
    args = parser.parse_args(argv)

    workboard_path = Path(args.workboard).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (ROOT / workboard_path).resolve()
    if not workboard_path.exists():
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
            )
            action_name = "send"
        elif args.ack:
            if not str(args.msg_id).strip() or not str(args.by).strip():
                raise ValueError("--msg-id and --by are required for --ack")
            ok, payload = ack_message(
                workboard_path,
                msg_id=args.msg_id,
                actor=args.by,
                decision=args.decision,
            )
            action_name = "ack"
        elif args.resolve:
            if not str(args.msg_id).strip() or not str(args.by).strip():
                raise ValueError("--msg-id and --by are required for --resolve")
            ok, payload = resolve_message(
                workboard_path,
                msg_id=args.msg_id,
                actor=args.by,
                decision=args.decision,
            )
            action_name = "resolve"
        else:
            ok, payload = list_messages(
                workboard_path,
                sender=args.from_agent,
                recipient=args.to_agent,
                state=args.state,
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
            if action_name == "list":
                for row in list(payload.get("messages") or []):
                    print(
                        f"- {row.get('msg_id')}: {row.get('from')} -> {row.get('to')} "
                        f"[{row.get('state')}] {row.get('summary')}"
                    )
            else:
                row = dict(payload.get("message") or {})
                print(
                    f"- {row.get('msg_id')}: {row.get('from')} -> {row.get('to')} "
                    f"[{row.get('state')}] {row.get('summary')}"
                )
        else:
            print(f"- {payload.get('error', 'unknown error')}")
            for item in list(payload.get("violations") or []):
                print(f"- {item}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
