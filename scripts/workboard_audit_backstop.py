#!/usr/bin/env python3
"""Ensure WORKBOARD keeps a recurring 24h audit backstop task."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

try:
    from scripts.workboard_paths import default_workboard_path, resolve_workboard_path
except ImportError:  # pragma: no cover
    from workboard_paths import default_workboard_path, resolve_workboard_path  # type: ignore

try:
    from scripts import check_workboard_claims as claims_gate
    from scripts import workboard_issue
except Exception:  # pragma: no cover
    import check_workboard_claims as claims_gate  # type: ignore
    import workboard_issue  # type: ignore


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOARD = default_workboard_path(ROOT)

BACKSTOP_TASK_ID = "audit-24h-backstop"
BACKSTOP_SCOPE = "thomas"
BACKSTOP_SUMMARY = "ensure every major module is audited in last 24h and fix findings"
BACKSTOP_REPORTED_BY = "workboard-bot"


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _canonical_line() -> str:
    return workboard_issue._format_up_for_grabs(  # type: ignore[attr-defined]
        task_id=BACKSTOP_TASK_ID,
        scope=BACKSTOP_SCOPE,
        summary=BACKSTOP_SUMMARY,
        reported_by=BACKSTOP_REPORTED_BY,
    )


def _check(workboard_path: Path) -> tuple[bool, list[str]]:
    violations, _claims, _tasks, up_for_grabs, _issues = claims_gate.evaluate_board(workboard_path)
    if violations:
        return False, list(violations)

    matches = [item for item in up_for_grabs if _norm(item.task_id) == _norm(BACKSTOP_TASK_ID)]
    if not matches:
        return (
            False,
            [
                "missing recurring workboard audit backstop task in `## Up For Grabs`",
                f"required line: {_canonical_line()}",
            ],
        )
    if len(matches) > 1:
        lines = ", ".join(str(item.line_no) for item in matches)
        return False, [f"duplicate recurring workboard audit backstop task entries (lines {lines})"]

    entry = matches[0]
    if _norm(",".join(entry.scopes)) != _norm(BACKSTOP_SCOPE):
        return False, [f"backstop task `{entry.task_id}` has invalid scope `{','.join(entry.scopes)}`"]
    if _norm(entry.summary) != _norm(BACKSTOP_SUMMARY):
        return False, [f"backstop task `{entry.task_id}` has invalid summary"]
    if _norm(entry.reported_by) != _norm(BACKSTOP_REPORTED_BY):
        return False, [f"backstop task `{entry.task_id}` has invalid reported_by `{entry.reported_by}`"]

    last_line = max(item.line_no for item in up_for_grabs)
    if int(entry.line_no) != int(last_line):
        return False, [f"backstop task `{entry.task_id}` must be the last Up For Grabs entry"]

    return True, []


def _apply(workboard_path: Path) -> tuple[bool, str]:
    original_text = workboard_path.read_text(encoding="utf-8")
    lines = original_text.splitlines()

    section_start, section_end = workboard_issue._find_up_for_grabs_section(lines)  # type: ignore[attr-defined]
    bullet_idxs = workboard_issue._bullet_indices(lines, section_start, section_end)  # type: ignore[attr-defined]

    remove_idxs: list[int] = []
    found_idx: int | None = None
    for idx in bullet_idxs:
        entry, fields, err = workboard_issue._parse_up_for_grabs_line(idx + 1, lines[idx])  # type: ignore[attr-defined]
        if err:
            return False, err
        if entry is not None and workboard_issue._is_none_entry(entry):  # type: ignore[attr-defined]
            remove_idxs.append(idx)
            continue
        if not fields:
            continue
        if _norm(fields.get("task_id", "")) == _norm(BACKSTOP_TASK_ID):
            if found_idx is None:
                found_idx = idx
            else:
                remove_idxs.append(idx)

    for idx in sorted(remove_idxs, reverse=True):
        del lines[idx]
        if idx < section_end:
            section_end -= 1
        if found_idx is not None and idx < found_idx:
            found_idx -= 1

    canonical = _canonical_line()
    if found_idx is not None:
        del lines[found_idx]
        if found_idx < section_end:
            section_end -= 1

    lines.insert(section_end, canonical)

    new_text = "\n".join(lines) + ("\n" if original_text.endswith("\n") else "")
    ok, violations = workboard_issue._validate_and_write(  # type: ignore[attr-defined]
        workboard_path, original_text, new_text
    )
    if not ok:
        return False, "; ".join(violations)
    return True, "backstop task ensured"


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=("Ensure WORKBOARD keeps a recurring Up For Grabs task for 24h module-audit backstop work.")
    )
    parser.add_argument(
        "--workboard",
        default=str(DEFAULT_WORKBOARD),
        help=f"Path to workboard markdown file (default: {DEFAULT_WORKBOARD})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply canonical backstop entry before validating.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compatibility alias for check mode (default).",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    workboard_path = resolve_workboard_path(args.workboard, repo_root=ROOT)

    if not workboard_path.exists():
        payload = {
            "gate": "workboard_audit_backstop",
            "ok": False,
            "applied": False,
            "error": f"missing workboard file: {workboard_path}",
            "workboard": str(workboard_path),
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Workboard audit backstop: FAIL")
            print(f"- {payload['error']}")
        return 1

    applied = False
    if args.apply:
        ok_apply, msg_apply = _apply(workboard_path)
        if not ok_apply:
            payload = {
                "gate": "workboard_audit_backstop",
                "ok": False,
                "applied": False,
                "error": msg_apply,
                "workboard": str(workboard_path),
            }
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print("Workboard audit backstop: FAIL")
                print(f"- {msg_apply}")
            return 1
        applied = True

    ok, violations = _check(workboard_path)
    payload = {
        "gate": "workboard_audit_backstop",
        "ok": bool(ok),
        "applied": bool(applied),
        "task_id": BACKSTOP_TASK_ID,
        "workboard": str(workboard_path),
        "violations": list(violations),
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        if ok:
            print("Workboard audit backstop: PASS")
            print(f"- task `{BACKSTOP_TASK_ID}` present and canonical")
        else:
            print("Workboard audit backstop: FAIL")
            for item in violations:
                print(f"- {item}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
