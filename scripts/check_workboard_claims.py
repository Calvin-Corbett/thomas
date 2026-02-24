#!/usr/bin/env python3
"""Validate active agent ownership claims and task board contract in WORKBOARD.md."""

from __future__ import annotations

import argparse
import fnmatch
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"

REQUIRED_CLAIM_FIELDS: Tuple[str, ...] = ("agent", "scope", "task")
REQUIRED_ACTIVE_TASK_FIELDS: Tuple[str, ...] = ("task_id", "agent", "scope", "summary", "status")
REQUIRED_UP_FOR_GRABS_FIELDS: Tuple[str, ...] = ("task_id", "scope", "summary", "reported_by")
REQUIRED_ISSUE_FIELDS: Tuple[str, ...] = (
    "issue_id",
    "task_id",
    "reporter",
    "owner",
    "state",
    "summary",
)

ACTIVE_TASK_STATES: Tuple[str, ...] = ("active", "blocked")
ISSUE_STATES: Tuple[str, ...] = ("open", "triaged", "resolved")

NONE_TOKENS = {"none", "_none_", "`none`", "`_none_`"}


@dataclass(frozen=True)
class Claim:
    line_no: int
    agent: str
    scopes: Tuple[str, ...]
    task: str


@dataclass(frozen=True)
class ActiveTask:
    line_no: int
    task_id: str
    agent: str
    scopes: Tuple[str, ...]
    summary: str
    status: str


@dataclass(frozen=True)
class UpForGrabTask:
    line_no: int
    task_id: str
    scopes: Tuple[str, ...]
    summary: str
    reported_by: str


@dataclass(frozen=True)
class WorkboardIssue:
    line_no: int
    issue_id: str
    task_id: str
    reporter: str
    owner: str
    state: str
    summary: str


def _normalize_scope(scope: str) -> str:
    normalized = str(scope or "").strip().replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return normalized.rstrip("/")


def _normalize_agent(agent: str) -> str:
    return str(agent or "").strip().lower()


def _is_glob(scope: str) -> bool:
    return any(ch in scope for ch in "*?[")


def _glob_prefix(pattern: str) -> str:
    out: List[str] = []
    for ch in pattern:
        if ch in "*?[":
            break
        out.append(ch)
    return "".join(out).rstrip("/")


def _literal_overlap(a: str, b: str) -> bool:
    if a == b:
        return True
    return a.startswith(b + "/") or b.startswith(a + "/")


def _pattern_matches_literal(pattern: str, literal: str) -> bool:
    if fnmatch.fnmatchcase(literal, pattern):
        return True
    if pattern.endswith("/**"):
        base = pattern[:-3].rstrip("/")
        return bool(base) and (literal == base or literal.startswith(base + "/"))
    return False


def _scope_overlaps(a: str, b: str) -> bool:
    left = _normalize_scope(a).lower()
    right = _normalize_scope(b).lower()
    if not left or not right:
        return False

    left_glob = _is_glob(left)
    right_glob = _is_glob(right)

    if not left_glob and not right_glob:
        return _literal_overlap(left, right)

    if left_glob and not right_glob:
        return _pattern_matches_literal(left, right)

    if right_glob and not left_glob:
        return _pattern_matches_literal(right, left)

    if left == right:
        return True
    left_prefix = _glob_prefix(left)
    right_prefix = _glob_prefix(right)
    if not left_prefix or not right_prefix:
        return True
    return _literal_overlap(left_prefix, right_prefix)


def _extract_section_entries(
    text: str,
    *,
    heading_prefix: str,
    heading_label: str,
) -> Tuple[List[Tuple[int, str]], List[str]]:
    entries: List[Tuple[int, str]] = []
    errors: List[str] = []

    in_section = False
    found_section = False
    want = str(heading_prefix or "").strip().lower()
    for line_no, raw in enumerate((text or "").splitlines(), start=1):
        stripped = raw.strip()

        if stripped.startswith("## "):
            heading = stripped[3:].strip().lower()
            if in_section:
                break
            if heading.startswith(want):
                found_section = True
                in_section = True
            continue

        if not in_section:
            continue
        if not stripped:
            continue
        if stripped.startswith("- "):
            entries.append((line_no, stripped[2:].strip()))

    if not found_section:
        errors.append(f"missing `## {heading_label}` section in workboard")
    if found_section and not entries:
        errors.append(
            f"`## {heading_label}` must include `- none` or at least one structured entry"
        )
    return entries, errors


def _parse_kv_fields(
    line_no: int,
    entry: str,
    *,
    required_fields: Sequence[str],
) -> Tuple[Dict[str, str] | None, str | None]:
    token = str(entry or "").strip()
    if not token:
        return None, f"line {line_no}: empty entry"
    if token.lower() in NONE_TOKENS:
        return None, None
    if token.startswith("`") and token.endswith("`") and len(token) >= 2:
        token = token[1:-1].strip()

    fields: Dict[str, str] = {}
    for part in [p.strip() for p in token.split(";") if p.strip()]:
        if "=" not in part:
            return None, f"line {line_no}: invalid field format `{part}` (expected key=value)"
        key, value = part.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if not key or not value:
            return None, f"line {line_no}: invalid field `{part}` (expected non-empty key=value)"
        fields[key] = value

    missing = [name for name in required_fields if not fields.get(name)]
    if missing:
        return None, f"line {line_no}: missing required field(s): {', '.join(missing)}"
    return fields, None


def _parse_scope_field(line_no: int, scope: str) -> Tuple[Tuple[str, ...] | None, str | None]:
    scopes = tuple(_normalize_scope(item) for item in str(scope or "").split(",") if _normalize_scope(item))
    if not scopes:
        return None, f"line {line_no}: scope must include at least one non-empty path token"
    return scopes, None


def _parse_claim_entry(line_no: int, entry: str) -> Tuple[Claim | None, str | None]:
    fields, err = _parse_kv_fields(line_no, entry, required_fields=REQUIRED_CLAIM_FIELDS)
    if err:
        return None, err
    if fields is None:
        return None, None
    scopes, scope_err = _parse_scope_field(line_no, fields["scope"])
    if scope_err:
        return None, scope_err

    claim = Claim(
        line_no=line_no,
        agent=fields["agent"],
        scopes=scopes or tuple(),
        task=fields["task"],
    )
    return claim, None


def _parse_active_task_entry(line_no: int, entry: str) -> Tuple[ActiveTask | None, str | None]:
    fields, err = _parse_kv_fields(line_no, entry, required_fields=REQUIRED_ACTIVE_TASK_FIELDS)
    if err:
        return None, err
    if fields is None:
        return None, None
    scopes, scope_err = _parse_scope_field(line_no, fields["scope"])
    if scope_err:
        return None, scope_err
    status = str(fields["status"]).strip().lower()
    if status not in ACTIVE_TASK_STATES:
        allowed = ", ".join(ACTIVE_TASK_STATES)
        return None, f"line {line_no}: invalid active task status `{fields['status']}` (allowed: {allowed})"

    item = ActiveTask(
        line_no=line_no,
        task_id=fields["task_id"],
        agent=fields["agent"],
        scopes=scopes or tuple(),
        summary=fields["summary"],
        status=status,
    )
    return item, None


def _parse_up_for_grabs_entry(line_no: int, entry: str) -> Tuple[UpForGrabTask | None, str | None]:
    fields, err = _parse_kv_fields(line_no, entry, required_fields=REQUIRED_UP_FOR_GRABS_FIELDS)
    if err:
        return None, err
    if fields is None:
        return None, None
    scopes, scope_err = _parse_scope_field(line_no, fields["scope"])
    if scope_err:
        return None, scope_err

    item = UpForGrabTask(
        line_no=line_no,
        task_id=fields["task_id"],
        scopes=scopes or tuple(),
        summary=fields["summary"],
        reported_by=fields["reported_by"],
    )
    return item, None


def _parse_issue_entry(line_no: int, entry: str) -> Tuple[WorkboardIssue | None, str | None]:
    fields, err = _parse_kv_fields(line_no, entry, required_fields=REQUIRED_ISSUE_FIELDS)
    if err:
        return None, err
    if fields is None:
        return None, None

    state = str(fields["state"]).strip().lower()
    if state not in ISSUE_STATES:
        allowed = ", ".join(ISSUE_STATES)
        return None, f"line {line_no}: invalid issue state `{fields['state']}` (allowed: {allowed})"

    issue = WorkboardIssue(
        line_no=line_no,
        issue_id=fields["issue_id"],
        task_id=fields["task_id"],
        reporter=fields["reporter"],
        owner=fields["owner"],
        state=state,
        summary=fields["summary"],
    )
    return issue, None


def _evaluate_board(
    workboard_path: Path = DEFAULT_WORKBOARD,
) -> Tuple[List[str], List[Claim], List[ActiveTask], List[UpForGrabTask], List[WorkboardIssue]]:
    violations: List[str] = []
    claims: List[Claim] = []
    active_tasks: List[ActiveTask] = []
    up_for_grabs: List[UpForGrabTask] = []
    issues: List[WorkboardIssue] = []

    if not workboard_path.exists():
        return [f"missing workboard file: {workboard_path}"], claims, active_tasks, up_for_grabs, issues

    text = workboard_path.read_text(encoding="utf-8")

    claim_lines, claim_errors = _extract_section_entries(
        text,
        heading_prefix="agent claims",
        heading_label="Agent Claims",
    )
    violations.extend(claim_errors)
    for line_no, entry in claim_lines:
        claim, err = _parse_claim_entry(line_no, entry)
        if err:
            violations.append(err)
            continue
        if claim is not None:
            claims.append(claim)

    active_task_lines, active_task_errors = _extract_section_entries(
        text,
        heading_prefix="active tasks",
        heading_label="Active Tasks",
    )
    violations.extend(active_task_errors)
    for line_no, entry in active_task_lines:
        task, err = _parse_active_task_entry(line_no, entry)
        if err:
            violations.append(err)
            continue
        if task is not None:
            active_tasks.append(task)

    up_for_grabs_lines, up_for_grabs_errors = _extract_section_entries(
        text,
        heading_prefix="up for grabs",
        heading_label="Up For Grabs",
    )
    violations.extend(up_for_grabs_errors)
    for line_no, entry in up_for_grabs_lines:
        item, err = _parse_up_for_grabs_entry(line_no, entry)
        if err:
            violations.append(err)
            continue
        if item is not None:
            up_for_grabs.append(item)

    issue_lines, issue_errors = _extract_section_entries(
        text,
        heading_prefix="issues / blockers",
        heading_label="Issues / Blockers",
    )
    violations.extend(issue_errors)
    for line_no, entry in issue_lines:
        item, err = _parse_issue_entry(line_no, entry)
        if err:
            violations.append(err)
            continue
        if item is not None:
            issues.append(item)

    claims_by_agent: Dict[str, List[Claim]] = {}
    for claim in claims:
        key = _normalize_agent(claim.agent)
        prior = claims_by_agent.get(key)
        if prior:
            violations.append(
                "duplicate active claim for agent "
                f"`{claim.agent}` (lines {prior[0].line_no} and {claim.line_no})"
            )
        claims_by_agent.setdefault(key, []).append(claim)

    for idx in range(len(claims)):
        left = claims[idx]
        for jdx in range(idx + 1, len(claims)):
            right = claims[jdx]
            overlaps: List[Tuple[str, str]] = []
            for left_scope in left.scopes:
                for right_scope in right.scopes:
                    if _scope_overlaps(left_scope, right_scope):
                        overlaps.append((left_scope, right_scope))
            if overlaps:
                examples = ", ".join(
                    f"`{left_scope}` vs `{right_scope}`" for left_scope, right_scope in overlaps[:2]
                )
                violations.append(
                    "scope overlap between "
                    f"`{left.agent}` (line {left.line_no}) and "
                    f"`{right.agent}` (line {right.line_no}): {examples}"
                )

    active_task_ids: Dict[str, ActiveTask] = {}
    for task in active_tasks:
        key = str(task.task_id).strip().lower()
        prior = active_task_ids.get(key)
        if prior is not None:
            violations.append(
                "duplicate active task_id "
                f"`{task.task_id}` (lines {prior.line_no} and {task.line_no})"
            )
        else:
            active_task_ids[key] = task

    up_for_grabs_ids: Dict[str, UpForGrabTask] = {}
    for item in up_for_grabs:
        key = str(item.task_id).strip().lower()
        prior = up_for_grabs_ids.get(key)
        if prior is not None:
            violations.append(
                "duplicate up-for-grabs task_id "
                f"`{item.task_id}` (lines {prior.line_no} and {item.line_no})"
            )
        else:
            up_for_grabs_ids[key] = item

    overlap_task_ids = sorted(set(active_task_ids).intersection(up_for_grabs_ids))
    for task_id in overlap_task_ids:
        active = active_task_ids[task_id]
        grab = up_for_grabs_ids[task_id]
        violations.append(
            "task_id appears in both active tasks and up-for-grabs: "
            f"`{active.task_id}` (lines {active.line_no} and {grab.line_no})"
        )

    issue_ids: Dict[str, WorkboardIssue] = {}
    for item in issues:
        key = str(item.issue_id).strip().lower()
        prior = issue_ids.get(key)
        if prior is not None:
            violations.append(
                f"duplicate issue_id `{item.issue_id}` (lines {prior.line_no} and {item.line_no})"
            )
        else:
            issue_ids[key] = item

    active_tasks_by_agent: Dict[str, List[ActiveTask]] = {}
    for task in active_tasks:
        active_tasks_by_agent.setdefault(_normalize_agent(task.agent), []).append(task)

    for agent_key, claim_rows in claims_by_agent.items():
        if not active_tasks_by_agent.get(agent_key):
            agent_label = claim_rows[0].agent
            violations.append(
                f"agent `{agent_label}` has active claim but no matching entry in `## Active Tasks`"
            )

    for task in active_tasks:
        agent_key = _normalize_agent(task.agent)
        agent_claims = claims_by_agent.get(agent_key, [])
        if not agent_claims:
            violations.append(
                f"active task `{task.task_id}` is assigned to `{task.agent}` without a matching active claim"
            )
            continue

        overlap = False
        for claim in agent_claims:
            for task_scope in task.scopes:
                for claim_scope in claim.scopes:
                    if _scope_overlaps(task_scope, claim_scope):
                        overlap = True
                        break
                if overlap:
                    break
            if overlap:
                break
        if not overlap:
            violations.append(
                f"active task `{task.task_id}` scopes do not overlap claim scopes for `{task.agent}`"
            )

    valid_task_ids = set(active_task_ids).union(up_for_grabs_ids)
    for issue in issues:
        if str(issue.task_id).strip().lower() not in valid_task_ids:
            violations.append(
                f"issue `{issue.issue_id}` references unknown task_id `{issue.task_id}`"
            )

    blocked_task_ids = {
        str(task.task_id).strip().lower() for task in active_tasks if task.status == "blocked"
    }
    open_issue_task_ids = {
        str(item.task_id).strip().lower() for item in issues if item.state in {"open", "triaged"}
    }
    for task_id in sorted(blocked_task_ids):
        if task_id not in open_issue_task_ids:
            label = active_task_ids[task_id].task_id if task_id in active_task_ids else task_id
            violations.append(
                f"blocked task `{label}` must have an open/triaged entry in `## Issues / Blockers`"
            )

    return violations, claims, active_tasks, up_for_grabs, issues


def _evaluate_claims(workboard_path: Path = DEFAULT_WORKBOARD) -> Tuple[List[str], List[Claim]]:
    violations, claims, _tasks, _grab, _issues = _evaluate_board(workboard_path)
    return violations, claims


def evaluate_claims(workboard_path: Path = DEFAULT_WORKBOARD) -> Tuple[List[str], List[Claim]]:
    """Public claims-only evaluation helper for other coordination scripts."""
    return _evaluate_claims(workboard_path)


def evaluate_board(
    workboard_path: Path = DEFAULT_WORKBOARD,
) -> Tuple[List[str], List[Claim], List[ActiveTask], List[UpForGrabTask], List[WorkboardIssue]]:
    """Public full-board evaluation helper for coordination gates."""
    return _evaluate_board(workboard_path)


def evaluate(workboard_path: Path = DEFAULT_WORKBOARD) -> List[str]:
    violations, _claims = evaluate_claims(workboard_path)
    return violations


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate WORKBOARD.md claim/task/issue contract for multi-agent coordination."
    )
    parser.add_argument(
        "--workboard",
        default=str(DEFAULT_WORKBOARD),
        help="Path to workboard markdown file (default: plans/thomas/WORKBOARD.md)",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    workboard_path = Path(args.workboard).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (ROOT / workboard_path).resolve()

    violations, claims, active_tasks, up_for_grabs, issues = _evaluate_board(workboard_path)
    ok = not violations
    if args.json:
        payload = {
            "active_claim_count": len(claims),
            "active_task_count": len(active_tasks),
            "gate": "workboard_claims",
            "issue_count": len(issues),
            "ok": ok,
            "up_for_grabs_count": len(up_for_grabs),
            "violation_count": len(violations),
            "violations": list(violations),
            "workboard": str(workboard_path),
        }
        print(json.dumps(payload, sort_keys=True))
        return 0 if ok else 1

    if violations:
        print("Workboard claims gate: FAIL")
        for item in violations:
            print(f"- {item}")
        return 1

    print("Workboard claims gate: PASS")
    print("- claims, active tasks, issues, and up-for-grabs are consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
