#!/usr/bin/env python3
"""Enforce canonical task problem records for active and queued workboard tasks."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import sys
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.forge.gates import workboard_claims as claims_gate
except Exception:  # pragma: no cover
    from forge.gates import workboard_claims as claims_gate  # type: ignore


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"
TASK_PROBLEMS_HEADING = "Task Problems"
PROBLEMS_PREFIX = "plans/thomas/problems/"
REQUIRED_FIELDS: tuple[str, ...] = ("task_id", "problem", "owner", "status", "updated_at", "summary")


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _find_section(lines: Sequence[str], *, heading_prefix: str) -> tuple[int, int] | None:
    start: int | None = None
    end = len(lines)
    wanted = _norm(heading_prefix)
    for idx, line in enumerate(lines):
        stripped = str(line or "").strip()
        if stripped.startswith("## "):
            heading = _norm(stripped[3:])
            if start is None:
                if heading.startswith(wanted):
                    start = idx + 1
            else:
                end = idx
                break
    if start is None:
        return None
    return start, end


def _bullet_indices(lines: Sequence[str], start: int, end: int) -> list[int]:
    return [idx for idx in range(start, end) if str(lines[idx]).strip().startswith("- ")]


def _parse_kv_entry(
    line_no: int,
    line: str,
) -> tuple[str | None, dict[str, str] | None, str | None]:
    stripped = str(line or "").strip()
    if not stripped.startswith("- "):
        return None, None, f"line {line_no}: expected bullet entry"
    token = stripped[2:].strip()
    if _norm(token) in claims_gate.NONE_TOKENS:
        return token, None, None

    fields: dict[str, str] = {}
    for part in [item.strip() for item in token.split(";") if item.strip()]:
        if "=" not in part:
            return token, None, f"line {line_no}: invalid field `{part}`"
        key, value = part.split("=", 1)
        key = _norm(key)
        value = str(value or "").strip()
        if not key or not value:
            return token, None, f"line {line_no}: invalid key/value field `{part}`"
        fields[key] = value

    missing = [field for field in REQUIRED_FIELDS if not fields.get(field)]
    if missing:
        return token, None, f"line {line_no}: missing required field(s): {', '.join(missing)}"
    return token, fields, None


def evaluate(workboard_path: Path = DEFAULT_WORKBOARD) -> list[str]:
    violations: list[str] = []

    board_violations, _claims, active_tasks, up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    if board_violations:
        violations.extend([f"workboard invalid: {item}" for item in board_violations])
        return violations

    tracked: dict[str, str] = {}
    for row in active_tasks:
        task_id = str(row.task_id).strip()
        if task_id:
            tracked[_norm(task_id)] = task_id
    for row in up_for_grabs:
        task_id = str(row.task_id).strip()
        if task_id:
            tracked.setdefault(_norm(task_id), task_id)

    text = workboard_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    section = _find_section(lines, heading_prefix=TASK_PROBLEMS_HEADING)
    if section is None:
        return [f"missing `## {TASK_PROBLEMS_HEADING}` section in workboard"]

    entries: dict[str, dict[str, str]] = {}
    path_owners: dict[str, str] = {}
    has_none_entry = False
    bullets = _bullet_indices(lines, section[0], section[1])
    if not bullets:
        violations.append(f"`## {TASK_PROBLEMS_HEADING}` must include `- none` or at least one structured entry")

    for idx in bullets:
        entry, fields, err = _parse_kv_entry(idx + 1, lines[idx])
        if err:
            violations.append(err)
            continue
        if entry is not None and _norm(entry) in claims_gate.NONE_TOKENS:
            has_none_entry = True
            continue
        if not fields:
            continue
        task_id = str(fields.get("task_id", "")).strip()
        task_key = _norm(task_id)
        if task_key in entries:
            violations.append(f"duplicate task problem mapping for `{task_id}`")
            continue

        problem_path = str(fields.get("problem", "")).strip().replace("\\", "/")
        if not _norm(problem_path).startswith(PROBLEMS_PREFIX):
            violations.append(
                f"task `{task_id}` problem path must stay under `{PROBLEMS_PREFIX}` (found `{problem_path}`)"
            )
        if not _norm(problem_path).endswith("/problem.md"):
            violations.append(f"task `{task_id}` problem path must end with `/PROBLEM.md` (found `{problem_path}`)")

        problem_abs = (ROOT / problem_path).resolve()
        if not problem_abs.exists():
            violations.append(f"task `{task_id}` problem file missing: {problem_path}")
        else:
            body = problem_abs.read_text(encoding="utf-8")
            marker = f"task_id: `{task_id}`"
            if marker not in body:
                violations.append(f"task `{task_id}` problem file missing marker `{marker}`: {problem_path}")

        path_key = _norm(problem_path)
        prior_task = path_owners.get(path_key)
        if prior_task is not None and _norm(prior_task) != task_key:
            violations.append(
                f"duplicate problem path mapping `{problem_path}` for tasks `{prior_task}` and `{task_id}`"
            )
        else:
            path_owners[path_key] = task_id
        entries[task_key] = fields

    if tracked and has_none_entry:
        violations.append(f"`## {TASK_PROBLEMS_HEADING}` cannot contain `- none` while tasks are tracked")

    for task_key, task_id in tracked.items():
        if task_key not in entries:
            violations.append(
                f"missing task problem mapping for `{task_id}`; run "
                "`python scripts/crew/tasks/manager.py --sync-plans --apply`"
            )

    for task_key, fields in entries.items():
        if task_key not in tracked:
            task_id = str(fields.get("task_id", "")).strip() or task_key
            violations.append(f"stale task problem mapping without tracked task: `{task_id}`")

    return violations


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enforce task problem mapping and file coverage in WORKBOARD.md.")
    parser.add_argument("--workboard", default=str(DEFAULT_WORKBOARD))
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    args = parser.parse_args(argv)

    workboard_path = Path(args.workboard).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (ROOT / workboard_path).resolve()

    if not workboard_path.exists():
        payload = {
            "ok": False,
            "gate": "workboard_task_problems",
            "error": f"missing workboard file: {workboard_path}",
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard task problems gate: FAIL")
            print(f"- {payload['error']}")
        return 1

    violations = evaluate(workboard_path)
    payload = {
        "ok": not violations,
        "gate": "workboard_task_problems",
        "workboard": str(workboard_path),
        "violation_count": len(violations),
        "violations": violations,
    }

    if args.json:
        print(json.dumps(payload, sort_keys=True))
        return 0 if payload["ok"] else 1

    if violations:
        print("Workboard task problems gate: FAIL")
        for item in violations:
            print(f"- {item}")
        return 1

    print("Workboard task problems gate: PASS")
    print("- every tracked task has a canonical problem record")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
