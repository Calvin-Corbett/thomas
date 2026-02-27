#!/usr/bin/env python3
"""Spawn and manage multi-terminal agent swarms from WORKBOARD.md."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts import check_workboard_claims as claims_gate
    from scripts import workboard_issue, workboard_message
except Exception:  # pragma: no cover
    import check_workboard_claims as claims_gate  # type: ignore
    import workboard_issue  # type: ignore
    import workboard_message  # type: ignore


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"
DEFAULT_COORDINATOR = "task-manager-agent"
SWARM_HEADING = "Swarm Sessions"
NONE_ENTRY = "- none"
SWARM_STATES = {"planned", "active", "completed", "cancelled"}
PRIORITIES = {"p0", "p1", "p2"}


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sanitize(label: str, value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{label} is required")
    if ";" in cleaned or "\n" in cleaned or "\r" in cleaned:
        raise ValueError(f"{label} cannot include ';' or newline characters")
    return cleaned


def _validate_priority(priority: str) -> str:
    normalized = _norm(priority)
    if normalized not in PRIORITIES:
        allowed = ", ".join(sorted(PRIORITIES))
        raise ValueError(f"priority must be one of: {allowed}")
    return normalized


def _validate_state(state: str) -> str:
    normalized = _norm(state)
    if normalized not in SWARM_STATES:
        allowed = ", ".join(sorted(SWARM_STATES))
        raise ValueError(f"state must be one of: {allowed}")
    return normalized


def _split_agents(raw: str) -> list[str]:
    rows: list[str] = []
    for token in str(raw or "").split(","):
        clean = str(token or "").strip()
        if clean:
            rows.append(clean)
    return rows


def _format_agents(values: Sequence[str]) -> str:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in values:
        clean = str(item or "").strip()
        key = _norm(clean)
        if not clean or key in seen:
            continue
        _sanitize("agent", clean)
        seen.add(key)
        deduped.append(clean)
    return ",".join(deduped) if deduped else "none"


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
        except Exception as exc:
            errors.append(f"line {idx + 1}: {exc}")
    return rows, errors


def _write_sessions(workboard_path: Path, sessions: Sequence[dict[str, str]]) -> tuple[bool, list[str]]:
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


def _next_swarm_id(rows: Sequence[dict[str, str]], task_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", _norm(task_id)).strip("-") or "task"
    candidate = f"swarm-{stamp}-{slug}"
    seen = {_norm(row.get("swarm_id", "")) for row in rows}
    if _norm(candidate) not in seen:
        return candidate
    suffix = 2
    while True:
        variant = f"{candidate}-{suffix}"
        if _norm(variant) not in seen:
            return variant
        suffix += 1


def _manifest_path_for(swarm_id: str) -> Path:
    return ROOT / "plans" / "thomas" / "swarm" / f"{swarm_id}.json"


def _swarm_dir(swarm_id: str) -> Path:
    return ROOT / "plans" / "thomas" / "swarm" / swarm_id


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _norm(value)).strip("-") or "agent"


def _ps_single_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _make_manifest(
    *,
    swarm_id: str,
    task_id: str,
    agents: Sequence[str],
    spawn_command: str,
    task_summary: str,
    suggested_scopes: Sequence[str],
    coordinator: str,
    existing_claim_agents: set[str],
    workboard_path: Path,
) -> Path:
    manifest_path = _manifest_path_for(swarm_id)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    swarm_dir = _swarm_dir(swarm_id)
    prompt_dir = swarm_dir / "prompts"
    lane_dir = swarm_dir / "lanes"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    lane_dir.mkdir(parents=True, exist_ok=True)

    scope_rows = [str(item or "").strip() for item in suggested_scopes if str(item or "").strip()]
    entries: list[dict[str, str]] = []
    root_path = str(ROOT).replace("\\", "/")
    for idx, agent in enumerate(agents):
        agent_slug = _slug(agent)
        lane_scope = (
            scope_rows[idx] if idx < len(scope_rows) else f"plans/thomas/swarm/{swarm_id}/lanes/{agent_slug}.md"
        )
        lane_path = ROOT / lane_scope
        lane_path.parent.mkdir(parents=True, exist_ok=True)
        if not lane_path.exists():
            lane_path.write_text(
                (
                    f"# Swarm Lane: {agent}\n\n"
                    f"- swarm_id: `{swarm_id}`\n"
                    f"- task_id: `{task_id}`\n"
                    f"- suggested_scope: `{lane_scope}`\n"
                ),
                encoding="utf-8",
            )

        prompt_path = prompt_dir / f"{agent_slug}.txt"
        has_active_claim = _norm(agent) in existing_claim_agents
        prompt_text = (
            f"You are {agent} in swarm {swarm_id} for task {task_id}.\n"
            f"Task summary: {task_summary}\n"
            f"Coordinator: {coordinator}\n"
            f"Suggested working scope: {lane_scope}\n\n"
            "Execution protocol:\n"
            f"1) Read open messages for this task assigned to {agent}.\n"
            f"2) {'Keep your existing claim unless coordinator approves scope change.' if has_active_claim else 'Claim the suggested scope before editing.'}\n"
            f"3) Send a status update to {coordinator} with progress and blockers.\n"
            "4) Execute only non-overlapping changes, run tests, and post handoff notes.\n"
        )
        prompt_path.write_text(prompt_text, encoding="utf-8")

        startup_status_cmd = (
            "python scripts/workboard_message.py "
            f'--send --from-agent "{agent}" --to-agent "{coordinator}" '
            f'--task-id "{task_id}" --kind status --priority p0 '
            f'--summary "swarm {swarm_id} terminal online" --requested-action none --decision pending'
        )
        claim_cmd = (
            "python scripts/workboard_claim.py "
            f'--claim --agent "{agent}" --name "{agent}" --role solo --parent none '
            f'--scope "{lane_scope}" --task "[WIP][SWARM:{swarm_id}] {task_id} lane"'
        )
        bootstrap_parts = [
            f'Set-Location "{root_path}"',
            f'$env:THOMAS_AGENT_NAME="{agent}"',
            f'$env:CODEX_AGENT_NAME="{agent}"',
        ]
        if not has_active_claim:
            bootstrap_parts.append(claim_cmd)
        bootstrap_parts.append(startup_status_cmd)
        if _norm(spawn_command).startswith("codex"):
            bootstrap_parts.append(f"$prompt = Get-Content {_ps_single_quote(str(prompt_path))} -Raw")
            bootstrap_parts.append(f"{spawn_command} $prompt")
        else:
            bootstrap_parts.append(spawn_command)
        bootstrap = "; ".join(bootstrap_parts)

        entries.append(
            {
                "agent": agent,
                "task_id": task_id,
                "coordinator": coordinator,
                "lane_scope": lane_scope,
                "has_active_claim": "true" if has_active_claim else "false",
                "prompt_path": str(prompt_path),
                "workboard": str(workboard_path),
                "bootstrap": bootstrap,
            }
        )
    payload = {
        "swarm_id": swarm_id,
        "task_id": task_id,
        "generated_at": _now_iso(),
        "entry_count": len(entries),
        "entries": entries,
    }
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return manifest_path


def _spawn_entries(entries: Sequence[dict[str, str]], *, dry_run: bool, limit: int) -> int:
    launched = 0
    cap = limit if limit > 0 else len(entries)
    for row in list(entries)[:cap]:
        if dry_run:
            launched += 1
            continue
        bootstrap = str(row.get("bootstrap", "")).strip()
        if not bootstrap:
            continue
        subprocess.run(
            ["cmd", "/c", "start", "", "powershell", "-NoExit", "-Command", bootstrap],
            check=False,
        )
        launched += 1
    return launched


def _ordered_unique(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        clean = str(item or "").strip()
        key = _norm(clean)
        if not clean or key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def _online_agents_for_swarm(
    workboard_path: Path,
    *,
    swarm_id: str,
    task_id: str,
    coordinator: str,
) -> tuple[bool, dict[str, object]]:
    ok, payload = workboard_message.list_messages(
        workboard_path,
        recipient=coordinator,
        task_id=task_id,
    )
    if not ok:
        return False, {
            "error": "message section parse failed while reading swarm online status",
            **payload,
        }

    swarm_token = _norm(f"swarm {swarm_id}")
    online: list[str] = []
    for row in list(payload.get("messages") or []):
        if _norm(str(row.get("kind", ""))) != "status":
            continue
        summary = _norm(str(row.get("summary", "")))
        if "terminal online" not in summary:
            continue
        if swarm_token not in summary:
            continue
        online.append(str(row.get("from", "")).strip())
    return True, {"online_agents": _ordered_unique(online)}


def _lookup_session(rows: Sequence[dict[str, str]], swarm_id: str) -> dict[str, str] | None:
    key = _norm(swarm_id)
    for row in rows:
        if _norm(row.get("swarm_id", "")) == key:
            return row
    return None


def _task_exists(workboard_path: Path, task_id: str) -> bool:
    violations, _claims, active_tasks, up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return False
    task_key = _norm(task_id)
    known = {_norm(row.task_id) for row in active_tasks} | {_norm(row.task_id) for row in up_for_grabs}
    return task_key in known


def _task_context(
    workboard_path: Path,
    *,
    task_id: str,
) -> tuple[bool, dict[str, object]]:
    violations, claims, active_tasks, up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return False, {"error": "workboard invalid", "violations": list(violations)}
    task_key = _norm(task_id)
    for row in active_tasks:
        if _norm(row.task_id) == task_key:
            return True, {
                "claims": claims,
                "summary": row.summary,
                "scopes": list(row.scopes),
                "status": row.status,
            }
    for row in up_for_grabs:
        if _norm(row.task_id) == task_key:
            return True, {
                "claims": claims,
                "summary": row.summary,
                "scopes": list(row.scopes),
                "status": "up_for_grabs",
            }
    return False, {"error": f"task `{task_id}` must exist in active tasks or up-for-grabs"}


def create_swarm(
    workboard_path: Path,
    *,
    task_id: str,
    coordinator: str,
    size: int,
    agents_csv: str,
    agent_prefix: str,
    agent_start: int,
    spawn_command: str,
    priority: str,
    spawn_now: bool,
    dry_run: bool,
    send_summons: bool,
    allow_existing_agents: bool,
) -> tuple[bool, dict[str, object]]:
    task_clean = _sanitize("task_id", task_id)
    coordinator_clean = _sanitize("coordinator", coordinator)
    _validate_priority(priority)
    ok_task, task_payload = _task_context(workboard_path, task_id=task_clean)
    if not ok_task:
        return False, task_payload
    claims = list(task_payload.get("claims") or [])
    task_summary = str(task_payload.get("summary", "")).strip() or task_clean
    task_scopes = [str(item or "").strip() for item in list(task_payload.get("scopes") or [])]
    claim_agents = {_norm(row.agent) for row in claims}

    lines = workboard_path.read_text(encoding="utf-8").splitlines()
    section = _ensure_section(lines, heading=SWARM_HEADING)
    sessions, errors = _load_sessions(lines, section)
    if errors:
        return False, {"error": "swarm section parse failed", "violations": errors}

    agents = _split_agents(agents_csv)
    if not agents:
        if size <= 0:
            return False, {"error": "--size must be > 0 when --agents is not provided"}
        agents = [f"{agent_prefix} {agent_start + idx}" for idx in range(size)]
    agents_clean = _format_agents(agents)
    parsed_agents = _split_agents(agents_clean)

    if not allow_existing_agents:
        overlaps = sorted([agent for agent in parsed_agents if _norm(agent) in claim_agents])
        if overlaps:
            return False, {
                "error": "generated agents overlap active claims",
                "overlapping_agents": overlaps,
                "hint": "use --allow-existing-agents to bypass",
            }

    swarm_id = _next_swarm_id(sessions, task_clean)
    manifest = _make_manifest(
        swarm_id=swarm_id,
        task_id=task_clean,
        agents=parsed_agents,
        spawn_command=str(spawn_command).strip() or "codex",
        task_summary=task_summary,
        suggested_scopes=task_scopes,
        coordinator=coordinator_clean,
        existing_claim_agents=claim_agents,
        workboard_path=workboard_path,
    )
    now_iso = _now_iso()
    row = _normalize_session_fields(
        {
            "swarm_id": swarm_id,
            "task_id": task_clean,
            "coordinator": coordinator_clean,
            "state": "planned",
            "size": str(len(parsed_agents)),
            "agents": agents_clean,
            "manifest": str(manifest.relative_to(ROOT)).replace("\\", "/"),
            "created_at": now_iso,
            "updated_at": now_iso,
        }
    )
    sessions.append(row)
    ok_write, violations_write = _write_sessions(workboard_path, sessions)
    if not ok_write:
        return False, {"error": "swarm create rejected by gate", "violations": violations_write}

    sent = 0
    if send_summons:
        for agent in parsed_agents:
            ok_msg, payload_msg = workboard_message.send_message(
                workboard_path,
                sender=coordinator_clean,
                recipient=agent,
                summary=f"swarm summon {swarm_id} for task {task_clean}",
                task_id=task_clean,
                kind="coordination",
                priority=priority,
                requested_action=f"launch and claim lane for swarm {swarm_id}",
                decision="pending",
            )
            if not ok_msg:
                return False, {"error": f"failed to send summon to `{agent}`", **payload_msg}
            sent += 1

    launched = 0
    if spawn_now:
        launched = launch_swarm(
            workboard_path,
            swarm_id=swarm_id,
            dry_run=dry_run,
            limit=0,
        )[1].get("launched_count", 0)

    return True, {
        "session": row,
        "agent_count": len(parsed_agents),
        "summon_count": sent,
        "launched_count": int(launched),
    }


def launch_swarm(
    workboard_path: Path,
    *,
    swarm_id: str,
    dry_run: bool,
    limit: int,
) -> tuple[bool, dict[str, object]]:
    swarm_clean = _sanitize("swarm_id", swarm_id)
    lines = workboard_path.read_text(encoding="utf-8").splitlines()
    section = _ensure_section(lines, heading=SWARM_HEADING)
    sessions, errors = _load_sessions(lines, section)
    if errors:
        return False, {"error": "swarm section parse failed", "violations": errors}
    session = _lookup_session(sessions, swarm_clean)
    if session is None:
        return False, {"error": f"swarm `{swarm_clean}` not found"}
    if _norm(session.get("state", "")) in {"completed", "cancelled"}:
        return False, {"error": f"swarm `{swarm_clean}` is already closed"}

    manifest_rel = str(session.get("manifest", "")).strip()
    manifest_path = (ROOT / manifest_rel).resolve()
    if not manifest_path.exists():
        return False, {"error": f"manifest file missing: {manifest_path}"}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = list(payload.get("entries") or [])
    launched = _spawn_entries(entries, dry_run=dry_run, limit=limit)

    if launched > 0 and not dry_run:
        session["state"] = "active"
        session["updated_at"] = _now_iso()
        ok_write, violations_write = _write_sessions(workboard_path, sessions)
        if not ok_write:
            return False, {"error": "swarm launch state update rejected by gate", "violations": violations_write}

    return True, {
        "swarm_id": swarm_clean,
        "dry_run": bool(dry_run),
        "launched_count": int(launched),
        "entry_count": len(entries),
        "state": session.get("state", "planned"),
    }


def launch_missing_swarm(
    workboard_path: Path,
    *,
    swarm_id: str,
    dry_run: bool,
    limit: int,
) -> tuple[bool, dict[str, object]]:
    swarm_clean = _sanitize("swarm_id", swarm_id)
    lines = workboard_path.read_text(encoding="utf-8").splitlines()
    section = _ensure_section(lines, heading=SWARM_HEADING)
    sessions, errors = _load_sessions(lines, section)
    if errors:
        return False, {"error": "swarm section parse failed", "violations": errors}
    session = _lookup_session(sessions, swarm_clean)
    if session is None:
        return False, {"error": f"swarm `{swarm_clean}` not found"}
    if _norm(session.get("state", "")) in {"completed", "cancelled"}:
        return False, {"error": f"swarm `{swarm_clean}` is already closed"}

    task_id = str(session.get("task_id", "")).strip()
    coordinator = str(session.get("coordinator", "")).strip() or DEFAULT_COORDINATOR
    manifest_rel = str(session.get("manifest", "")).strip()
    manifest_path = (ROOT / manifest_rel).resolve()
    if not manifest_path.exists():
        return False, {"error": f"manifest file missing: {manifest_path}"}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = list(payload.get("entries") or [])
    entry_agents = _ordered_unique([str(row.get("agent", "")).strip() for row in entries])

    ok_online, payload_online = _online_agents_for_swarm(
        workboard_path,
        swarm_id=swarm_clean,
        task_id=task_id,
        coordinator=coordinator,
    )
    if not ok_online:
        return False, payload_online
    online_set = {_norm(agent) for agent in list(payload_online.get("online_agents") or [])}
    missing_entries = [row for row in entries if _norm(str(row.get("agent", "")).strip()) not in online_set]
    missing_agents = _ordered_unique([str(row.get("agent", "")).strip() for row in missing_entries])
    online_agents = [agent for agent in entry_agents if _norm(agent) in online_set]

    launched = _spawn_entries(missing_entries, dry_run=dry_run, limit=limit)

    if launched > 0 and not dry_run:
        session["state"] = "active"
        session["updated_at"] = _now_iso()
        ok_write, violations_write = _write_sessions(workboard_path, sessions)
        if not ok_write:
            return False, {"error": "swarm launch state update rejected by gate", "violations": violations_write}

    return True, {
        "swarm_id": swarm_clean,
        "dry_run": bool(dry_run),
        "launched_count": int(launched),
        "entry_count": len(entries),
        "online_count": len(online_agents),
        "missing_count": len(missing_agents),
        "online_agents": online_agents,
        "missing_agents": missing_agents,
        "state": session.get("state", "planned"),
    }


def set_swarm_state(
    workboard_path: Path,
    *,
    swarm_id: str,
    state: str,
) -> tuple[bool, dict[str, object]]:
    swarm_clean = _sanitize("swarm_id", swarm_id)
    state_clean = _validate_state(state)
    lines = workboard_path.read_text(encoding="utf-8").splitlines()
    section = _ensure_section(lines, heading=SWARM_HEADING)
    sessions, errors = _load_sessions(lines, section)
    if errors:
        return False, {"error": "swarm section parse failed", "violations": errors}
    row = _lookup_session(sessions, swarm_clean)
    if row is None:
        return False, {"error": f"swarm `{swarm_clean}` not found"}
    row["state"] = state_clean
    row["updated_at"] = _now_iso()
    ok_write, violations_write = _write_sessions(workboard_path, sessions)
    if not ok_write:
        return False, {"error": "swarm state update rejected by gate", "violations": violations_write}
    return True, {"session": row}


def status_swarm(workboard_path: Path, *, swarm_id: str) -> tuple[bool, dict[str, object]]:
    swarm_clean = _sanitize("swarm_id", swarm_id)
    lines = workboard_path.read_text(encoding="utf-8").splitlines()
    section = _find_section(lines, heading_prefix=SWARM_HEADING)
    if section is None:
        return False, {"error": "missing `## Swarm Sessions` section"}
    sessions, errors = _load_sessions(lines, section)
    if errors:
        return False, {"error": "swarm section parse failed", "violations": errors}
    row = _lookup_session(sessions, swarm_clean)
    if row is None:
        return False, {"error": f"swarm `{swarm_clean}` not found"}
    return True, {"session": row}


def list_swarms(workboard_path: Path, *, state: str) -> tuple[bool, dict[str, object]]:
    lines = workboard_path.read_text(encoding="utf-8").splitlines()
    section = _find_section(lines, heading_prefix=SWARM_HEADING)
    if section is None:
        return True, {"sessions": [], "session_count": 0}
    sessions, errors = _load_sessions(lines, section)
    if errors:
        return False, {"error": "swarm section parse failed", "violations": errors}
    key = _norm(state)
    out: list[dict[str, str]] = []
    for row in sessions:
        if key and _norm(row.get("state", "")) != key:
            continue
        out.append(dict(row))
    return True, {"sessions": out, "session_count": len(out)}


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage multi-terminal swarm sessions in WORKBOARD.md.")
    parser.add_argument("--workboard", default=str(DEFAULT_WORKBOARD))
    parser.add_argument("--json", action="store_true")

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--create", action="store_true")
    action.add_argument("--launch", action="store_true")
    action.add_argument("--launch-missing", action="store_true")
    action.add_argument("--complete", action="store_true")
    action.add_argument("--cancel", action="store_true")
    action.add_argument("--status", action="store_true")
    action.add_argument("--list", action="store_true")

    parser.add_argument("--swarm-id", default="")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--coordinator", default=DEFAULT_COORDINATOR)
    parser.add_argument("--size", type=int, default=0)
    parser.add_argument("--agents", default="")
    parser.add_argument("--agent-prefix", default="Codex")
    parser.add_argument("--agent-start", type=int, default=1)
    parser.add_argument("--spawn-command", default="codex")
    parser.add_argument("--priority", default="p1")
    parser.add_argument("--spawn-now", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--state", default="")
    parser.add_argument("--no-summons", action="store_true")
    parser.add_argument("--allow-existing-agents", action="store_true")
    args = parser.parse_args(argv)

    workboard_path = Path(args.workboard).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (ROOT / workboard_path).resolve()
    if not workboard_path.exists():
        payload = {"ok": False, "error": f"missing workboard file: {workboard_path}"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard swarm tool: FAIL")
            print(f"- {payload['error']}")
        return 1

    try:
        if args.create:
            ok, payload = create_swarm(
                workboard_path,
                task_id=str(args.task_id).strip(),
                coordinator=str(args.coordinator).strip() or DEFAULT_COORDINATOR,
                size=int(args.size),
                agents_csv=str(args.agents).strip(),
                agent_prefix=str(args.agent_prefix).strip() or "Codex",
                agent_start=int(args.agent_start),
                spawn_command=str(args.spawn_command).strip() or "codex",
                priority=str(args.priority).strip() or "p1",
                spawn_now=bool(args.spawn_now),
                dry_run=bool(args.dry_run),
                send_summons=not bool(args.no_summons),
                allow_existing_agents=bool(args.allow_existing_agents),
            )
            action_name = "create"
        elif args.launch:
            ok, payload = launch_swarm(
                workboard_path,
                swarm_id=str(args.swarm_id).strip(),
                dry_run=bool(args.dry_run),
                limit=int(args.limit),
            )
            action_name = "launch"
        elif args.launch_missing:
            ok, payload = launch_missing_swarm(
                workboard_path,
                swarm_id=str(args.swarm_id).strip(),
                dry_run=bool(args.dry_run),
                limit=int(args.limit),
            )
            action_name = "launch_missing"
        elif args.complete:
            ok, payload = set_swarm_state(workboard_path, swarm_id=str(args.swarm_id).strip(), state="completed")
            action_name = "complete"
        elif args.cancel:
            ok, payload = set_swarm_state(workboard_path, swarm_id=str(args.swarm_id).strip(), state="cancelled")
            action_name = "cancel"
        elif args.status:
            ok, payload = status_swarm(workboard_path, swarm_id=str(args.swarm_id).strip())
            action_name = "status"
        else:
            ok, payload = list_swarms(workboard_path, state=str(args.state).strip())
            action_name = "list"
    except ValueError as exc:
        ok = False
        payload = {"error": str(exc)}
        action_name = "error"

    envelope = {"ok": bool(ok), "action": action_name, "workboard": str(workboard_path), **payload}
    if args.json:
        print(json.dumps(envelope, sort_keys=True))
    else:
        print("Workboard swarm tool: PASS" if ok else "Workboard swarm tool: FAIL")
        if ok:
            if action_name == "list":
                for row in list(payload.get("sessions") or []):
                    print(f"- {row.get('swarm_id')}: {row.get('state')} task={row.get('task_id')}")
            else:
                row = dict(payload.get("session") or {})
                if row:
                    print(f"- {row.get('swarm_id')}: {row.get('state')}")
                else:
                    print(f"- action `{action_name}` completed")
        else:
            print(f"- {payload.get('error', 'unknown error')}")
            for item in list(payload.get("violations") or []):
                print(f"- {item}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
