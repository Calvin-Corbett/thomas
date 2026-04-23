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
    from scripts.workboard_paths import (
        default_workboard_path,
        repo_relative_or_absolute,
        resolve_workboard_path,
        swarm_dir_for,
    )
except ImportError:  # pragma: no cover
    from workboard_paths import (  # type: ignore
        default_workboard_path,
        repo_relative_or_absolute,
        resolve_workboard_path,
        swarm_dir_for,
    )

try:
    from scripts import check_workboard_claims as claims_gate
    from scripts import workboard_message
    from scripts.workboard_swarm_helpers import (
        DEFAULT_COORDINATOR,
        _format_agents,
        _load_explicit_scopes,
        _norm,
        _now_iso,
        _parse_env_assignments,
        _ps_single_quote,
        _sanitize,
        _slug,
        _split_agents,
        _validate_priority,
        _validate_state,
    )
    from scripts.workboard_swarm_sessions import (
        SWARM_HEADING,
        _ensure_section,
        _find_section,
        _load_sessions,
        _normalize_session_fields,
        _write_sessions,
    )
except Exception:  # pragma: no cover
    import check_workboard_claims as claims_gate  # type: ignore
    import workboard_message  # type: ignore
    from workboard_swarm_helpers import (  # type: ignore
        DEFAULT_COORDINATOR,
        _format_agents,
        _load_explicit_scopes,
        _norm,
        _now_iso,
        _parse_env_assignments,
        _ps_single_quote,
        _sanitize,
        _slug,
        _split_agents,
        _validate_priority,
        _validate_state,
    )
    from workboard_swarm_sessions import (  # type: ignore
        SWARM_HEADING,
        _ensure_section,
        _find_section,
        _load_sessions,
        _normalize_session_fields,
        _write_sessions,
    )


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOARD = default_workboard_path(ROOT)


def _next_swarm_id(rows: Sequence[dict[str, str]], task_id: str, *, workboard_path: Path) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    slug = re.sub(r"[^a-z0-9]+", "-", _norm(task_id)).strip("-") or "task"
    candidate = f"swarm-{stamp}-{slug}"
    seen = {_norm(row.get("swarm_id", "")) for row in rows}
    if _norm(candidate) not in seen and not _manifest_path_for(candidate, workboard_path=workboard_path).exists():
        return candidate
    suffix = 2
    while True:
        variant = f"{candidate}-{suffix}"
        if _norm(variant) not in seen and not _manifest_path_for(variant, workboard_path=workboard_path).exists():
            return variant
        suffix += 1


def _manifest_path_for(swarm_id: str, *, workboard_path: Path = DEFAULT_WORKBOARD) -> Path:
    return swarm_dir_for(workboard_path, repo_root=ROOT) / f"{swarm_id}.json"


def _swarm_dir(swarm_id: str, *, workboard_path: Path = DEFAULT_WORKBOARD) -> Path:
    return swarm_dir_for(workboard_path, repo_root=ROOT) / swarm_id


def _make_manifest(
    *,
    swarm_id: str,
    task_id: str,
    agents: Sequence[str],
    spawn_command: str,
    env_vars: dict[str, str] | None,
    task_summary: str,
    suggested_scopes: Sequence[str],
    coordinator: str,
    existing_claim_agents: set[str],
    workboard_path: Path,
) -> Path:
    manifest_path = _manifest_path_for(swarm_id, workboard_path=workboard_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    swarm_dir = _swarm_dir(swarm_id, workboard_path=workboard_path)
    prompt_dir = swarm_dir / "prompts"
    lane_dir = swarm_dir / "lanes"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    lane_dir.mkdir(parents=True, exist_ok=True)

    scope_rows = [str(item or "").strip() for item in suggested_scopes if str(item or "").strip()]
    entries: list[dict[str, str]] = []
    root_path = str(ROOT).replace("\\", "/")
    bootstrap_env = dict(env_vars or {})
    for idx, agent in enumerate(agents):
        agent_slug = _slug(agent)
        lane_note_path = lane_dir / f"{agent_slug}.md"
        lane_scope = (
            scope_rows[idx] if idx < len(scope_rows) else repo_relative_or_absolute(lane_note_path, repo_root=ROOT)
        )
        lane_note_path.write_text(
            (
                f"# Swarm Lane: {agent}\n\n"
                f"- swarm_id: `{swarm_id}`\n"
                f"- task_id: `{task_id}`\n"
                f"- suggested_scope: `{lane_scope}`\n"
            ),
            encoding="utf-8",
        )

        prompt_path = prompt_dir / f"{agent_slug}.txt"
        lane_task_id = f"[WIP][SWARM:{swarm_id}] {task_id} lane {agent_slug}"
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
            f"--send --from-agent {_ps_single_quote(agent)} --to-agent {_ps_single_quote(coordinator)} "
            f"--task-id {_ps_single_quote(task_id)} --kind status --priority p0 "
            f"--summary {_ps_single_quote(f'swarm {swarm_id} terminal online')} "
            "--requested-action none --decision pending"
        )
        claim_cmd = (
            "python scripts/workboard_claim.py "
            f"--claim --agent {_ps_single_quote(agent)} --name {_ps_single_quote(agent)} --role solo --parent none "
            f"--scope {_ps_single_quote(lane_scope)} "
            f"--task {_ps_single_quote(lane_task_id)}"
        )
        claim_failure_cmd = (
            "python scripts/workboard_message.py "
            f"--send --from-agent {_ps_single_quote(agent)} --to-agent {_ps_single_quote(coordinator)} "
            f"--task-id {_ps_single_quote(task_id)} --kind status --priority p1 "
            f"--summary {_ps_single_quote(f'swarm {swarm_id} lane claim failed before launch')} "
            "--requested-action "
            f"{_ps_single_quote('inspect bootstrap claim failure; worker did not start codex')} "
            "--decision pending"
        )
        bootstrap_parts = [
            f"Set-Location {_ps_single_quote(root_path)}",
            f"$env:THOMAS_AGENT_NAME={_ps_single_quote(agent)}",
            f"$env:CODEX_AGENT_NAME={_ps_single_quote(agent)}",
        ]
        for key, value in sorted(bootstrap_env.items()):
            bootstrap_parts.append(f"$env:{key}={_ps_single_quote(value)}")
        if not has_active_claim:
            bootstrap_parts.append(claim_cmd)
            bootstrap_parts.append(
                f"if ($LASTEXITCODE -ne 0) {{ $claimExit = $LASTEXITCODE; {claim_failure_cmd}; exit $claimExit }}"
            )
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
                "lane_task_id": lane_task_id,
                "coordinator": coordinator,
                "lane_scope": lane_scope,
                "lane_note_path": str(lane_note_path),
                "has_active_claim": "true" if has_active_claim else "false",
                "prompt_path": str(prompt_path),
                "workboard": str(workboard_path),
                "env": dict(sorted(bootstrap_env.items())),
                "bootstrap": bootstrap,
            }
        )
    payload = {
        "swarm_id": swarm_id,
        "task_id": task_id,
        "generated_at": _now_iso(),
        "env": dict(sorted(bootstrap_env.items())),
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
    env_vars: dict[str, str] | None,
    priority: str,
    spawn_now: bool,
    dry_run: bool,
    send_summons: bool,
    allow_existing_agents: bool,
    explicit_scopes: Sequence[str] = (),
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
    explicit_scope_rows = [str(item or "").strip() for item in explicit_scopes if str(item or "").strip()]
    if explicit_scope_rows:
        task_scopes = explicit_scope_rows
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
    if explicit_scope_rows and len(explicit_scope_rows) != len(parsed_agents):
        return False, {
            "error": "explicit scope count must match agent count",
            "agent_count": len(parsed_agents),
            "scope_count": len(explicit_scope_rows),
        }

    if not allow_existing_agents:
        overlaps = sorted([agent for agent in parsed_agents if _norm(agent) in claim_agents])
        if overlaps:
            return False, {
                "error": "generated agents overlap active claims",
                "overlapping_agents": overlaps,
                "hint": "use --allow-existing-agents to bypass",
            }

    swarm_id = _next_swarm_id(sessions, task_clean, workboard_path=workboard_path)
    manifest = _make_manifest(
        swarm_id=swarm_id,
        task_id=task_clean,
        agents=parsed_agents,
        spawn_command=str(spawn_command).strip() or "codex",
        env_vars=env_vars,
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
            "manifest": repo_relative_or_absolute(manifest, repo_root=ROOT),
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
    manifest_path = Path(manifest_rel).expanduser()
    if not manifest_path.is_absolute():
        manifest_path = (ROOT / manifest_path).resolve()
    else:
        manifest_path = manifest_path.resolve()
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
    manifest_path = Path(manifest_rel).expanduser()
    if not manifest_path.is_absolute():
        manifest_path = (ROOT / manifest_path).resolve()
    else:
        manifest_path = manifest_path.resolve()
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
    parser.add_argument("--scopes", default="")
    parser.add_argument("--scopes-file", default="")
    parser.add_argument("--spawn-command", default="codex")
    parser.add_argument("--env", action="append", default=[], help="Worker environment assignment, KEY=VALUE.")
    parser.add_argument("--priority", default="p1")
    parser.add_argument("--spawn-now", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--state", default="")
    parser.add_argument("--no-summons", action="store_true")
    parser.add_argument("--allow-existing-agents", action="store_true")
    args = parser.parse_args(argv)

    workboard_path = resolve_workboard_path(args.workboard, repo_root=ROOT)
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
                env_vars=_parse_env_assignments(list(args.env or [])),
                priority=str(args.priority).strip() or "p1",
                spawn_now=bool(args.spawn_now),
                dry_run=bool(args.dry_run),
                send_summons=not bool(args.no_summons),
                allow_existing_agents=bool(args.allow_existing_agents),
                explicit_scopes=_load_explicit_scopes(str(args.scopes), str(args.scopes_file)),
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
