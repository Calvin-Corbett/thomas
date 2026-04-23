from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def evaluate_endurance_report_contract(report_payload: Mapping[str, Any], commits: Sequence[str]) -> dict[str, Any]:
    required_keys = (
        "commit_shas_created",
        "verification_runs",
        "remaining_blockers",
        "best_next_step",
        "recovery_actions",
        "guardrail_violation_count",
        "protected_file_attempt_count",
    )
    keys_present = all(key in report_payload for key in required_keys)
    commit_rows = list(report_payload.get("commit_shas_created") or [])
    remaining_blockers = list(report_payload.get("remaining_blockers") or [])
    recovery_actions = list(report_payload.get("recovery_actions") or [])
    verification_runs = list(report_payload.get("verification_runs") or [])
    best_next_step = str(report_payload.get("best_next_step") or "").strip()
    productive_progress = bool(list(commits))
    actionable_no_progress = not productive_progress and bool(remaining_blockers) and bool(best_next_step)
    report_contract_success = (
        keys_present
        and isinstance(report_payload.get("guardrail_violation_count"), int)
        and isinstance(report_payload.get("protected_file_attempt_count"), int)
        and isinstance(report_payload.get("best_next_step"), str)
        and isinstance(report_payload.get("commit_shas_created"), list)
        and isinstance(report_payload.get("verification_runs"), list)
        and isinstance(report_payload.get("remaining_blockers"), list)
        and isinstance(report_payload.get("recovery_actions"), list)
        and (productive_progress or actionable_no_progress)
    )
    return {
        "report_contract_success": report_contract_success,
        "productive_progress": productive_progress,
        "actionable_no_progress": actionable_no_progress,
        "commit_shas_created": commit_rows,
        "verification_runs": verification_runs,
        "remaining_blockers": remaining_blockers,
        "recovery_actions": recovery_actions,
        "best_next_step": best_next_step,
    }


def snapshot_changed(initial: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    return (
        str(initial.get("head") or "") != str(current.get("head") or "")
        or int(initial.get("dirty_file_count") or 0) != int(current.get("dirty_file_count") or 0)
        or int(initial.get("dirty_line_total") or 0) != int(current.get("dirty_line_total") or 0)
        or list(initial.get("dirty_paths") or []) != list(current.get("dirty_paths") or [])
    )
