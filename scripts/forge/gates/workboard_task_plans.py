#!/usr/bin/env python3
"""Require exact Workboard claim/task/Task-Plan/PLAN.md agreement."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.crew.tasks.plan_metadata import PlanMetadataError, normalize_scope, normalize_status, parse_metadata
from scripts.forge.gates import workboard_claims as claims_gate

DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"
PLAN_FIELDS = ("task_id", "plan", "owner", "status", "updated_at", "summary")


def _norm(value: str) -> str:
    return str(value or "").strip().casefold()


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _staged_text(path: str) -> str | None:
    proc = _git("show", f":{path}")
    return proc.stdout if proc.returncode == 0 else None


def _board_text(workboard: Path, staged: bool) -> str:
    if not staged:
        return workboard.read_text(encoding="utf-8")
    rel = workboard.resolve().relative_to(ROOT).as_posix()
    text = _staged_text(rel)
    if text is None:
        raise ValueError(f"workboard is not present in the selected index: {rel}")
    return text


def _evaluate_claims_text(text: str) -> tuple[list[str], list[object], list[object], list[object]]:
    with tempfile.TemporaryDirectory(prefix="thomas-plan-gate-") as folder:
        board = Path(folder) / "WORKBOARD.md"
        board.write_text(text, encoding="utf-8")
        violations, claims, active, queued, _issues = claims_gate.evaluate_board(board)
    return list(violations), list(claims), list(active), list(queued)


def _plan_rows(text: str) -> tuple[list[dict[str, str]], list[str]]:
    entries, errors = claims_gate._extract_section_entries(  # type: ignore[attr-defined]
        text,
        heading_prefix="task plans",
        heading_label="Task Plans",
    )
    rows: list[dict[str, str]] = []
    for line_no, entry in entries:
        fields, err = claims_gate._parse_kv_fields(  # type: ignore[attr-defined]
            line_no,
            entry,
            required_fields=PLAN_FIELDS,
        )
        if err:
            errors.append(err)
        elif fields is not None:
            rows.append(fields)
    return rows, errors


def _read_plan(path: str, staged: bool) -> tuple[str | None, str | None]:
    normalized = str(path or "").strip().replace("\\", "/").lstrip("./")
    if not normalized or Path(normalized).is_absolute() or ".." in Path(normalized).parts:
        return None, f"invalid repo-relative PLAN path `{path}`"
    if staged:
        text = _staged_text(normalized)
        return (text, None) if text is not None else (None, f"PLAN is not tracked in selected index: {normalized}")
    target = ROOT / normalized
    try:
        return target.read_text(encoding="utf-8"), None
    except OSError:
        return None, f"missing PLAN file: {normalized}"


def _within(path: str, scope: str) -> bool:
    """A staged path is inside a scope entry when it is that file or under that folder."""
    p = path.strip("/")
    s = scope.strip("/")
    return bool(s) and (p == s or p.startswith(s + "/"))


def evaluate(workboard: Path = DEFAULT_WORKBOARD, *, staged: bool = False, agent: str = "") -> list[str]:
    """Every finding, blocking or not, as one list (the pre-scoped contract)."""
    violations, warnings = evaluate_scoped(workboard, staged=staged, agent=agent)
    return violations + warnings


def evaluate_scoped(
    workboard: Path = DEFAULT_WORKBOARD, *, staged: bool = False, agent: str = ""
) -> tuple[list[str], list[str]]:
    """Findings split by ownership. With an ``agent``, only that agent's task can
    fail the gate; other agents' inconsistent, stale or missing plans are warnings.
    Board-level errors (claims that do not parse, malformed rows) always block.
    Until 2026-09-05 a commit was blocked by 34 findings about tasks that were not
    the committer's, exactly what the problems gate had already stopped doing."""
    warnings: list[str] = []
    agent_key = _norm(agent)
    try:
        text = _board_text(workboard, staged)
    except (OSError, UnicodeError, ValueError) as exc:
        return [str(exc)]
    violations, claims, active_tasks, queued_tasks = _evaluate_claims_text(text)
    rows, row_errors = _plan_rows(text)
    violations.extend(row_errors)

    row_by_id: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        row_by_id.setdefault(_norm(row["task_id"]), []).append(row)
    claim_by_agent: dict[str, list[object]] = {}
    for claim in claims:
        claim_by_agent.setdefault(_norm(claim.agent), []).append(claim)

    expected_ids: set[str] = set()
    plan_for_agent: dict[str, str] = {}
    scope_for_agent: dict[str, list[str]] = {}
    for task in active_tasks:
        sink = violations if not agent_key or _norm(task.agent) == agent_key else warnings
        key = _norm(task.task_id)
        expected_ids.add(key)
        matches = claim_by_agent.get(_norm(task.agent), [])
        exact = [claim for claim in matches if _norm(claim.task) == key and tuple(claim.scopes) == tuple(task.scopes)]
        if len(exact) != 1:
            sink.append(
                f"active task `{task.task_id}` requires exactly one claim with the same task, agent, and ordered scope"
            )
        task_rows = row_by_id.get(key, [])
        if len(task_rows) != 1:
            sink.append(f"task `{task.task_id}` requires exactly one `## Task Plans` row")
            continue
        row = task_rows[0]
        expected_scope = normalize_scope(",".join(task.scopes))
        expected_status = normalize_status(task.status)
        if _norm(row["owner"]) != _norm(task.agent):
            sink.append(f"task `{task.task_id}` Task Plans owner differs from Active Task agent")
        try:
            row_status = normalize_status(row["status"])
            row_scope = expected_scope
        except PlanMetadataError as exc:
            sink.append(f"task `{task.task_id}` Task Plans metadata invalid: {exc}")
            continue
        if row_status != expected_status:
            sink.append(f"task `{task.task_id}` Task Plans status differs from Active Task status")
        plan_text, plan_error = _read_plan(row["plan"], staged)
        if plan_error or plan_text is None:
            sink.append(plan_error or f"missing PLAN for `{task.task_id}`")
            continue
        if not plan_text.splitlines() or plan_text.splitlines()[0].strip() != f"# PLAN for {task.task_id}":
            sink.append(f"task `{task.task_id}` PLAN heading is not canonical")
        try:
            metadata = parse_metadata(plan_text)
        except PlanMetadataError as exc:
            sink.append(f"task `{task.task_id}` PLAN metadata invalid: {exc}")
            continue
        if _norm(metadata.owner) != _norm(task.agent):
            sink.append(f"task `{task.task_id}` PLAN owner differs from Active Task agent")
        if metadata.status != expected_status:
            sink.append(f"task `{task.task_id}` PLAN status differs from Active Task status")
        if metadata.scope != expected_scope:
            sink.append(f"task `{task.task_id}` PLAN scope differs from ordered Active Task scope")
        if _norm(task.agent) == _norm(agent):
            plan_for_agent[key] = str(row["plan"]).replace("\\", "/")
            scope_for_agent[key] = [str(p).replace("\\", "/").strip("/") for p in task.scopes]

    for task in queued_tasks:
        sink = warnings if agent_key else violations
        key = _norm(task.task_id)
        expected_ids.add(key)
        task_rows = row_by_id.get(key, [])
        if len(task_rows) != 1:
            sink.append(f"queued task `{task.task_id}` requires exactly one `## Task Plans` row")
            continue
        row = task_rows[0]
        try:
            row_status = normalize_status(row["status"])
        except PlanMetadataError as exc:
            sink.append(f"queued task `{task.task_id}` Task Plans metadata invalid: {exc}")
            continue
        if _norm(row["owner"]) != "unassigned" or row_status != "up_for_grabs":
            sink.append(f"queued task `{task.task_id}` Task Plans row must be unassigned/up_for_grabs")
        expected_scope = normalize_scope(",".join(task.scopes))
        plan_text, plan_error = _read_plan(row["plan"], staged)
        if plan_error or plan_text is None:
            sink.append(plan_error or f"missing PLAN for queued task `{task.task_id}`")
            continue
        if not plan_text.splitlines() or plan_text.splitlines()[0].strip() != f"# PLAN for {task.task_id}":
            sink.append(f"queued task `{task.task_id}` PLAN heading is not canonical")
        try:
            metadata = parse_metadata(plan_text)
        except PlanMetadataError as exc:
            sink.append(f"queued task `{task.task_id}` PLAN metadata invalid: {exc}")
            continue
        if _norm(metadata.owner) != "unassigned":
            sink.append(f"queued task `{task.task_id}` PLAN owner differs from unassigned")
        if metadata.status != "up_for_grabs":
            sink.append(f"queued task `{task.task_id}` PLAN status differs from up_for_grabs")
        if metadata.scope != expected_scope:
            sink.append(f"queued task `{task.task_id}` PLAN scope differs from ordered Up For Grabs scope")
    stale = sorted(set(row_by_id) - expected_ids)
    sink = warnings if agent_key else violations
    for key in stale:
        sink.append(f"stale Task Plans row for unknown task `{row_by_id[key][0]['task_id']}`")

    if staged and agent and plan_for_agent:
        changed = {
            line.strip().replace("\\", "/")
            for line in _git("diff", "--cached", "--name-only", "--diff-filter=ACMR").stdout.splitlines()
            if line.strip()
        }
        for key, plan_path in plan_for_agent.items():
            # The plan must move with the work: only a commit that touches the
            # task's own scope owes it an update. HEAD's board can keep listing a
            # finished task under an agent for days; refusing every unrelated
            # commit until that plan was touched again taught nothing (2026-09-05).
            touches_scope = any(_within(path, scope) for path in changed for scope in scope_for_agent.get(key, []))
            if touches_scope and plan_path not in changed:
                violations.append(f"committing agent must include an updated tracked PLAN: {plan_path}")
    return violations, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workboard", default=str(DEFAULT_WORKBOARD))
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--agent", default=os.getenv("THOMAS_AGENT_ID") or os.getenv("AGENT_ID") or "")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    violations, warnings = evaluate_scoped(
        Path(args.workboard).expanduser(), staged=bool(args.staged), agent=str(args.agent or "")
    )
    if args.json:
        print(json.dumps({"ok": not violations, "violations": violations, "warnings": warnings}, sort_keys=True))
    elif violations:
        print("Workboard task plan gate: FAIL")
        for item in violations:
            print(f"- {item}")
    else:
        print("Workboard task plan gate: PASS")
    if not args.json and warnings:
        print(f"- warnings ({len(warnings)}, other agents' tasks; not blocking this commit):")
        for item in warnings:
            print(f"  - {item}")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
