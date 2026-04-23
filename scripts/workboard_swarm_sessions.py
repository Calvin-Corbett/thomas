#!/usr/bin/env python3
"""Workboard swarm session table helpers."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

try:
    from scripts import check_workboard_claims as claims_gate
    from scripts import workboard_issue
    from scripts.workboard_swarm_helpers import (
        DEFAULT_COORDINATOR,
        _format_agents,
        _now_iso,
        _sanitize,
        _split_agents,
        _validate_state,
    )
except ImportError:  # pragma: no cover
    import check_workboard_claims as claims_gate  # type: ignore
    import workboard_issue  # type: ignore
    from workboard_swarm_helpers import (  # type: ignore
        DEFAULT_COORDINATOR,
        _format_agents,
        _now_iso,
        _sanitize,
        _split_agents,
        _validate_state,
    )


SWARM_HEADING = "Swarm Sessions"
NONE_ENTRY = "- none"


def _workboard_lock():
    try:
        from scripts import workboard_claim_utils as claim_utils
    except ImportError:  # pragma: no cover
        import workboard_claim_utils as claim_utils  # type: ignore

    return claim_utils._file_lock(claim_utils.LOCK_FILE)  # type: ignore[attr-defined]


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


def _format_session(fields: dict[str, str]) -> str:
    swarm_id = _sanitize("swarm_id", fields.get("swarm_id", ""))
    task_id = _sanitize("task_id", fields.get("task_id", ""))
    coordinator = _sanitize("coordinator", fields.get("coordinator", DEFAULT_COORDINATOR))
    state = _validate_state(fields.get("state", "planned"))
    size = int(str(fields.get("size", "1")).strip() or "1")
    if size <= 0:
        raise ValueError("size must be positive")
    agents = _sanitize("agents", fields.get("agents", "none"))
    manifest = _sanitize("manifest", fields.get("manifest", ""))
    created_at = _sanitize("created_at", fields.get("created_at", ""))
    updated_at = _sanitize("updated_at", fields.get("updated_at", created_at))
    return (
        f"- swarm_id={swarm_id}; task_id={task_id}; coordinator={coordinator}; "
        f"state={state}; size={size}; agents={agents}; manifest={manifest}; "
        f"created_at={created_at}; updated_at={updated_at}"
    )


def _normalize_session_fields(fields: dict[str, str]) -> dict[str, str]:
    now_iso = _now_iso()
    out = {
        "swarm_id": str(fields.get("swarm_id", "")).strip(),
        "task_id": str(fields.get("task_id", "")).strip(),
        "coordinator": str(fields.get("coordinator", DEFAULT_COORDINATOR)).strip() or DEFAULT_COORDINATOR,
        "state": str(fields.get("state", "planned")).strip() or "planned",
        "size": str(fields.get("size", "1")).strip() or "1",
        "agents": _format_agents(_split_agents(str(fields.get("agents", "none")))),
        "manifest": str(fields.get("manifest", "")).strip(),
        "created_at": str(fields.get("created_at", now_iso)).strip() or now_iso,
        "updated_at": str(fields.get("updated_at", now_iso)).strip() or now_iso,
    }
    _format_session(out)
    return out


def _load_sessions(lines: Sequence[str], section: tuple[int, int]) -> tuple[list[dict[str, str]], list[str]]:
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
            rows.append(_normalize_session_fields(fields))
        except (TypeError, ValueError) as exc:
            errors.append(f"line {idx + 1}: {exc}")
    return rows, errors


def _write_sessions(workboard_path: Path, sessions: Sequence[dict[str, str]]) -> tuple[bool, list[str]]:
    with _workboard_lock():
        original_text = workboard_path.read_text(encoding="utf-8")
        lines = original_text.splitlines()
        section = _ensure_section(lines, heading=SWARM_HEADING)
        for idx in sorted(_bullet_indices(lines, section[0], section[1]), reverse=True):
            del lines[idx]
            if idx < section[1]:
                section = (section[0], section[1] - 1)
        entries = [_format_session(dict(row)) for row in sessions]
        insert_at = section[1]
        if not entries:
            lines.insert(insert_at, NONE_ENTRY)
        else:
            for entry in entries:
                lines.insert(insert_at, entry)
                insert_at += 1
        new_text = "\n".join(lines) + ("\n" if original_text.endswith("\n") else "")
        ok, violations = workboard_issue._validate_and_write(workboard_path, original_text, new_text)  # type: ignore[attr-defined]
        return ok, list(violations)
