from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def build_project_report_markdown(
    *,
    run_id: str,
    task_pack: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> str:
    competitors = dict(summary.get("competitors") or {})
    lines = [
        f"# Project Benchmark Report: {str(task_pack.get('name') or '')}",
        "",
        f"- run_id: {run_id}",
        f"- pack_id: {str(task_pack.get('id') or '')}",
        "",
    ]
    for name, metrics in competitors.items():
        row = dict(metrics or {})
        lines.extend(
            [
                f"## {name}",
                "",
                f"- validity: {row.get('validity')}",
                f"- success_count: {row.get('success_count')}",
                f"- report_contract_success_count: {row.get('report_contract_success_count')}",
                f"- commit_count: {row.get('commit_count')}",
                f"- verification_pass_count: {row.get('verification_pass_count')}",
                f"- verification_fail_count: {row.get('verification_fail_count')}",
                f"- changed_file_count: {row.get('changed_file_count')}",
                f"- avg_elapsed_seconds: {row.get('avg_elapsed_seconds')}",
                f"- follow_up_prompt_count: {row.get('follow_up_prompt_count')}",
                f"- tool_call_count: {row.get('tool_call_count')}",
                f"- timeout_count: {row.get('timeout_count')}",
                f"- runner_error_count: {row.get('runner_error_count')}",
                f"- remaining_blocker_count: {row.get('remaining_blocker_count')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
