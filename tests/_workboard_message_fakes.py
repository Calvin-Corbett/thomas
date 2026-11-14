"""A workboard file with a message section, shared by the message script tests."""

from __future__ import annotations

from pathlib import Path


def _write_workboard(
    tmp_path: Path,
    *,
    claims_block: str = "- none",
    active_tasks_block: str = "- none",
    issues_block: str = "- none",
    up_for_grabs_block: str = "- none",
) -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(
        (
            "# Thomas Workboard\n\n"
            "## Agent Claims (Active)\n\n"
            "Claim format:\n"
            "`- \\`agent=<id>; scope=<path[,path...]>; task=<short text>\\``\n\n"
            f"{claims_block}\n\n"
            "## Active Tasks\n\n"
            "Task format:\n"
            "`- \\`task_id=<id>; agent=<id>; scope=<path[,path...]>; summary=<short text>; status=<active|blocked>\\``\n\n"
            f"{active_tasks_block}\n\n"
            "## Issues / Blockers\n\n"
            "Issue format:\n"
            "`- \\`issue_id=<id>; task_id=<task_id>; reporter=<id>; owner=<id|unassigned>; state=<open|triaged|resolved>; summary=<short text>\\``\n\n"
            f"{issues_block}\n\n"
            "## Up For Grabs\n\n"
            "Task format:\n"
            "`- \\`task_id=<id>; scope=<path[,path...]>; summary=<short text>; reported_by=<id>\\``\n\n"
            f"{up_for_grabs_block}\n\n"
            "## Supporting Docs (Not Plan Sources)\n\n"
            "- docs/PROJECT_SCOPE.md\n"
        ),
        encoding="utf-8",
    )
    return path
