#!/usr/bin/env python3
"""Record failed automation steps in a task PROBLEM.md artifact."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.crew.tasks.base import (
        DEFAULT_PROBLEM_ROOT,
        DEFAULT_WORKBOARD,
        ROOT,
        TASK_PROBLEMS_HEADING,
        _bullet_indices,
        _ensure_section,
        _norm,
        _parse_kv_entry,
        _sanitize,
        _to_iso_utc,
        _write_section_entries,
    )
    from scripts.crew.tasks.plans import (
        _build_problem_template,
        _default_problem_path,
        _ensure_problem_marker,
        _normalize_artifact_path,
    )
    from scripts.crew.workboard import issue as workboard_issue
    from scripts.forge.gates import workboard_claims as claims_gate
except ImportError:  # pragma: no cover - script can run from scripts/crew/workboard
    from crew.tasks.base import (  # type: ignore
        DEFAULT_PROBLEM_ROOT,
        DEFAULT_WORKBOARD,
        ROOT,
        TASK_PROBLEMS_HEADING,
        _bullet_indices,
        _ensure_section,
        _norm,
        _parse_kv_entry,
        _sanitize,
        _to_iso_utc,
        _write_section_entries,
    )
    from crew.tasks.plans import (  # type: ignore
        _build_problem_template,
        _default_problem_path,
        _ensure_problem_marker,
        _normalize_artifact_path,
    )
    from crew.workboard import issue as workboard_issue  # type: ignore
    from forge.gates import workboard_claims as claims_gate  # type: ignore


DEFAULT_TASK_ID = "audit-24h-backstop"


@dataclass(frozen=True)
class TaskContext:
    task_id: str
    owner: str
    status: str
    scope: str
    summary: str
    problem_path: str


def _task_rows(workboard_path: Path) -> tuple[dict[str, TaskContext], list[str]]:
    violations, _claims, active_tasks, up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    contexts: dict[str, TaskContext] = {}

    for row in active_tasks:
        task_id = str(row.task_id).strip()
        if not task_id:
            continue
        contexts[_norm(task_id)] = TaskContext(
            task_id=task_id,
            owner=str(row.agent).strip() or "unassigned",
            status=str(row.status).strip() or "in_progress",
            scope=",".join(row.scopes),
            summary=str(row.summary).strip() or task_id,
            problem_path="",
        )

    for row in up_for_grabs:
        task_id = str(row.task_id).strip()
        if not task_id:
            continue
        contexts.setdefault(
            _norm(task_id),
            TaskContext(
                task_id=task_id,
                owner="unassigned",
                status="up_for_grabs",
                scope=",".join(row.scopes),
                summary=str(row.summary).strip() or task_id,
                problem_path="",
            ),
        )

    return contexts, list(violations)


def _problem_entries(lines: Sequence[str], section_start: int, section_end: int) -> tuple[list[str], dict[str, str]]:
    entries: list[str] = []
    paths: dict[str, str] = {}
    for idx in _bullet_indices(lines, section_start, section_end):
        entry, fields, err = _parse_kv_entry(idx + 1, lines[idx])
        if err:
            raise ValueError(err)
        if entry is not None and _norm(entry) in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        task_id = str(fields.get("task_id", "")).strip()
        problem_path = _normalize_artifact_path(str(fields.get("problem", "")).strip())
        if task_id and problem_path:
            paths[_norm(task_id)] = problem_path
    return entries, paths


def _resolve_context(
    *,
    task_id: str,
    agent: str,
    workboard_path: Path,
    problem_root: str,
) -> TaskContext:
    contexts, violations = _task_rows(workboard_path)
    if violations:
        raise ValueError("workboard invalid: " + "; ".join(violations[:3]))

    context = contexts.get(_norm(task_id))
    if context is None:
        raise ValueError(f"task `{task_id}` is not tracked in Active Tasks or Up For Grabs")

    text = workboard_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    section_start, section_end = _ensure_section(lines, heading=TASK_PROBLEMS_HEADING)
    _existing_entries, existing_paths = _problem_entries(lines, section_start, section_end)
    problem_path = existing_paths.get(_norm(task_id)) or _default_problem_path(task_id, problem_root)
    owner = str(agent).strip() or context.owner
    return TaskContext(
        task_id=context.task_id,
        owner=owner,
        status=context.status,
        scope=context.scope,
        summary=context.summary,
        problem_path=problem_path,
    )


def _problem_abs(problem_path: str) -> Path:
    normalized = _normalize_artifact_path(problem_path)
    candidate = Path(normalized)
    if candidate.is_absolute():
        return candidate.resolve()
    return (ROOT / normalized).resolve()


def _ensure_problem_file(context: TaskContext, *, now_iso: str) -> bool:
    problem_abs = _problem_abs(context.problem_path)
    if problem_abs.exists():
        _ensure_problem_marker(problem_abs, task_id=context.task_id)
        return False

    problem_abs.parent.mkdir(parents=True, exist_ok=True)
    problem_abs.write_text(
        _build_problem_template(
            task_id=context.task_id,
            owner=context.owner,
            summary=context.summary,
            scope=context.scope,
            status=context.status,
            now_iso=now_iso,
        ),
        encoding="utf-8",
    )
    return True


def _failure_entry(*, runner: str, step: str, exit_code: int, command: str, agent: str, now_iso: str) -> str:
    agent_line = f"- agent: `{agent}`\n" if agent else ""
    return (
        f"\n### {now_iso} - {runner}: {step}\n\n"
        f"- runner: `{runner}`\n"
        f"- step: `{step}`\n"
        f"- exit_code: `{exit_code}`\n"
        f"{agent_line}"
        f"- command: `{command}`\n"
    )


def _append_failure(
    context: TaskContext, *, runner: str, step: str, exit_code: int, command: str, agent: str, now_iso: str
) -> None:
    problem_abs = _problem_abs(context.problem_path)
    body = problem_abs.read_text(encoding="utf-8")
    if "## Failure Records" not in body:
        body = body.rstrip() + "\n\n## Failure Records\n"
    body = body.rstrip() + _failure_entry(
        runner=runner,
        step=step,
        exit_code=exit_code,
        command=command,
        agent=agent,
        now_iso=now_iso,
    )
    problem_abs.write_text(body.rstrip() + "\n", encoding="utf-8")


def _update_workboard_problem_entry(workboard_path: Path, context: TaskContext, *, now_iso: str) -> bool:
    original = workboard_path.read_text(encoding="utf-8")
    lines = original.splitlines()
    section_start, section_end = _ensure_section(lines, heading=TASK_PROBLEMS_HEADING)

    entries: list[str] = []
    found = False
    for idx in _bullet_indices(lines, section_start, section_end):
        entry, fields, err = _parse_kv_entry(idx + 1, lines[idx])
        if err:
            raise ValueError(err)
        if entry is not None and _norm(entry) in claims_gate.NONE_TOKENS:
            continue
        if not fields:
            continue
        task_id = str(fields.get("task_id", "")).strip()
        if _norm(task_id) == _norm(context.task_id):
            found = True
            entries.append(_problem_entry(context, now_iso=now_iso))
        else:
            entries.append(str(lines[idx]).strip())

    if not found:
        entries.append(_problem_entry(context, now_iso=now_iso))

    _write_section_entries(lines, section_start=section_start, section_end=section_end, entries=entries)
    updated = "\n".join(lines) + ("\n" if original.endswith("\n") else "")
    if updated == original:
        return False

    ok, violations = workboard_issue._validate_and_write(  # type: ignore[attr-defined]
        workboard_path,
        original,
        updated,
        require_claims_to_have_active_task=False,
    )
    if not ok:
        raise ValueError("workboard update rejected: " + "; ".join(violations[:3]))
    return True


def _problem_entry(context: TaskContext, *, now_iso: str) -> str:
    summary = context.summary or f"{context.task_id} failure record"
    return (
        f"- task_id={_sanitize('task_id', context.task_id)}; "
        f"problem={_sanitize('problem', context.problem_path)}; "
        f"owner={_sanitize('owner', context.owner)}; "
        f"status={_sanitize('status', context.status)}; "
        f"updated_at={_sanitize('updated_at', now_iso)}; "
        f"summary={_sanitize('summary', summary)}"
    )


def record_failure(
    *,
    runner: str,
    step: str,
    exit_code: int,
    command: str,
    task_id: str = DEFAULT_TASK_ID,
    agent: str = "",
    workboard: Path = DEFAULT_WORKBOARD,
    problem_root: str = DEFAULT_PROBLEM_ROOT,
    now: datetime | None = None,
) -> dict[str, object]:
    runner_clean = _sanitize("runner", runner)
    step_clean = _sanitize("step", step)
    command_clean = str(command or "").strip()
    if not command_clean:
        raise ValueError("command is required")
    task_clean = _sanitize("task_id", task_id)
    agent_clean = str(agent or "").strip()
    if ";" in agent_clean or "\n" in agent_clean or "\r" in agent_clean:
        raise ValueError("agent cannot include ';' or newline characters")

    workboard_path = Path(workboard).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (ROOT / workboard_path).resolve()
    if not workboard_path.exists():
        raise ValueError(f"missing workboard file: {workboard_path}")

    now_iso = _to_iso_utc(now or datetime.now(timezone.utc))
    context = _resolve_context(
        task_id=task_clean,
        agent=agent_clean,
        workboard_path=workboard_path,
        problem_root=problem_root,
    )
    created_problem = _ensure_problem_file(context, now_iso=now_iso)
    _append_failure(
        context,
        runner=runner_clean,
        step=step_clean,
        exit_code=int(exit_code),
        command=command_clean,
        agent=agent_clean,
        now_iso=now_iso,
    )
    updated_workboard = _update_workboard_problem_entry(workboard_path, context, now_iso=now_iso)
    return {
        "ok": True,
        "task_id": context.task_id,
        "problem_path": context.problem_path,
        "workboard": str(workboard_path),
        "created_problem": created_problem,
        "updated_workboard": updated_workboard,
        "runner": runner_clean,
        "step": step_clean,
        "exit_code": int(exit_code),
    }


def _print_payload(payload: dict[str, object], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, sort_keys=True))
        return
    if payload.get("ok"):
        print("Workboard problem recorder: PASS")
        print(f"- task `{payload.get('task_id')}` -> {payload.get('problem_path')}")
    else:
        print("Workboard problem recorder: FAIL")
        print(f"- {payload.get('error')}")


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record a failed automation step in the task's canonical PROBLEM.md artifact."
    )
    parser.add_argument("--runner", required=True, help="Runner name, such as auto_checks or doc.")
    parser.add_argument("--step", required=True, help="Failed step label.")
    parser.add_argument("--exit-code", required=True, type=int, help="Failed process exit code.")
    parser.add_argument("--command", required=True, help="Command that failed.")
    parser.add_argument("--task-id", default=DEFAULT_TASK_ID, help=f"Tracked task id (default: {DEFAULT_TASK_ID}).")
    parser.add_argument("--agent", default="", help="Agent id to record as owner for this update.")
    parser.add_argument("--workboard", default=str(DEFAULT_WORKBOARD), help="Path to WORKBOARD.md.")
    parser.add_argument("--problem-root", default=DEFAULT_PROBLEM_ROOT, help="Root for new PROBLEM.md artifacts.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    args = parser.parse_args(argv)

    try:
        payload = record_failure(
            runner=args.runner,
            step=args.step,
            exit_code=int(args.exit_code),
            command=args.command,
            task_id=args.task_id,
            agent=args.agent,
            workboard=Path(args.workboard),
            problem_root=str(args.problem_root),
        )
    # The CLI boundary: every fault must leave as {ok: false} plus exit 1,
    # because callers parse that. Named rather than bare so a genuine bug
    # (an ImportError, say) still escapes as a traceback.
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, json.JSONDecodeError) as exc:
        _print_payload({"ok": False, "error": str(exc)}, json_output=bool(args.json))
        return 1

    _print_payload(payload, json_output=bool(args.json))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
