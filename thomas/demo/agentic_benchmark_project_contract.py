from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def read_project_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def normalize_verification_run(item: Any) -> dict[str, Any] | None:
    if isinstance(item, Mapping):
        command = str(item.get("command") or item.get("cmd") or "").strip()
        if not command:
            return None
        return {
            "command": command,
            "passed": bool(item.get("passed")),
        }
    if isinstance(item, str):
        command = item.strip()
        if not command:
            return None
        lowered = command.lower()
        inferred_pass = "passed" in lowered and "failed" not in lowered
        return {
            "command": command,
            "passed": inferred_pass,
        }
    return None


def commit_sets_match(reported: Sequence[str], actual: Sequence[str]) -> bool:
    actual_list = [str(item or "").strip().lower() for item in actual if str(item or "").strip()]
    reported_list = [str(item or "").strip().lower() for item in reported if str(item or "").strip()]
    if not actual_list or len(actual_list) != len(reported_list):
        return False
    unmatched = list(actual_list)
    for candidate in reported_list:
        matches = [sha for sha in unmatched if sha == candidate or sha.startswith(candidate)]
        if len(matches) != 1:
            return False
        unmatched.remove(matches[0])
    return not unmatched


def evaluate_project_report_contract(report: Mapping[str, Any], commits: Sequence[str]) -> dict[str, Any]:
    commit_list = [
        str(item or "").strip() for item in list(report.get("commit_shas_created") or []) if str(item or "").strip()
    ]
    verification_runs = [
        normalized
        for normalized in (normalize_verification_run(item) for item in list(report.get("verification_runs") or []))
        if normalized is not None
    ]
    changed_files = [
        str(item or "").strip() for item in list(report.get("changed_files") or []) if str(item or "").strip()
    ]
    feature_summary = str(report.get("feature_summary") or "").strip()
    remaining_blockers = [
        str(item or "").strip() for item in list(report.get("remaining_blockers") or []) if str(item or "").strip()
    ]
    best_next_step = str(report.get("best_next_step") or "").strip()
    verification_pass_count = sum(1 for item in verification_runs if bool(item.get("passed")))
    verification_fail_count = max(0, len(verification_runs) - verification_pass_count)
    actual_commits = [str(item or "").strip() for item in commits if str(item or "").strip()]
    commit_match = commit_sets_match(commit_list, actual_commits)
    report_contract_success = bool(feature_summary) and bool(changed_files) and commit_match and bool(verification_runs)
    return {
        "report_contract_success": report_contract_success,
        "commit_shas_created": actual_commits,
        "reported_commit_shas": commit_list,
        "verification_runs": verification_runs,
        "verification_pass_count": verification_pass_count,
        "verification_fail_count": verification_fail_count,
        "changed_files": changed_files,
        "changed_file_count": len(changed_files),
        "feature_summary": feature_summary,
        "remaining_blockers": remaining_blockers,
        "remaining_blocker_count": len(remaining_blockers),
        "best_next_step": best_next_step,
    }
