from __future__ import annotations

import json
from pathlib import Path

import scripts.check_workboard_claims as gate
import scripts.workboard_issue as mod


def _write_workboard(
    tmp_path: Path,
    claims_block: str,
    *,
    active_tasks_block: str,
    issues_block: str = "- none",
    up_for_grabs_block: str = "- none",
) -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(
        (
            "# Thomas Workboard\n\n"
            "## Agent Claims (Active)\n\n"
            "Use this section to announce active ownership and prevent conflicting edits.\n"
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
            f"{up_for_grabs_block}\n"
        ),
        encoding="utf-8",
    )
    return path


def test_block_task_sets_status_and_creates_issue(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; task=dom snapshot runtime fix",
        active_tasks_block="- task_id=dom-snapshot-runtime; agent=Codex 3; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; summary=dom snapshot runtime fix; status=active",
    )
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--block",
            "--task-id",
            "dom-snapshot-runtime",
            "--reporter",
            "Codex 3",
            "--summary",
            "No browser session available in runtime.",
        ]
    )
    out = capsys.readouterr().out
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert "Workboard issue tool: PASS" in out
    assert "status=blocked" in text
    assert "issue_id=dom-snapshot-runtime-issue;" in text
    assert "state=open;" in text
    assert gate.evaluate(workboard) == []


def test_triage_issue_updates_state_and_owner(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; task=dom snapshot runtime fix",
        active_tasks_block="- task_id=dom-snapshot-runtime; agent=Codex 3; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; summary=dom snapshot runtime fix; status=blocked",
        issues_block="- issue_id=dom-snapshot-runtime-issue; task_id=dom-snapshot-runtime; reporter=Codex 3; owner=unassigned; state=open; summary=No browser session available in runtime.",
    )
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--triage",
            "--issue-id",
            "dom-snapshot-runtime-issue",
            "--owner",
            "Codex Ops",
        ]
    )
    out = capsys.readouterr().out
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert "Workboard issue tool: PASS" in out
    assert "issue_id=dom-snapshot-runtime-issue;" in text
    assert "owner=Codex Ops;" in text
    assert "state=triaged;" in text
    assert gate.evaluate(workboard) == []


def test_resolve_issue_reactivates_task(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; task=dom snapshot runtime fix",
        active_tasks_block="- task_id=dom-snapshot-runtime; agent=Codex 3; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; summary=dom snapshot runtime fix; status=blocked",
        issues_block="- issue_id=dom-snapshot-runtime-issue; task_id=dom-snapshot-runtime; reporter=Codex 3; owner=Codex Ops; state=triaged; summary=No browser session available in runtime.",
    )
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--resolve",
            "--issue-id",
            "dom-snapshot-runtime-issue",
        ]
    )
    out = capsys.readouterr().out
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert "Workboard issue tool: PASS" in out
    assert "status=active" in text
    assert "issue_id=dom-snapshot-runtime-issue;" in text
    assert "state=resolved;" in text
    assert gate.evaluate(workboard) == []


def test_up_for_grabs_moves_task_and_releases_final_claim(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; task=dom snapshot runtime fix",
        active_tasks_block="- task_id=dom-snapshot-runtime; agent=Codex 3; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; summary=dom snapshot runtime fix; status=active",
    )
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--up-for-grabs",
            "--task-id",
            "dom-snapshot-runtime",
            "--reported-by",
            "Codex 3",
        ]
    )
    out = capsys.readouterr().out
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert "Workboard issue tool: PASS" in out
    assert "## Agent Claims (Active)" in text
    assert "- none" in text
    assert "## Active Tasks" in text
    assert "task_id=dom-snapshot-runtime; agent=Codex 3;" not in text
    assert "## Up For Grabs" in text
    assert "task_id=dom-snapshot-runtime;" in text
    assert "reported_by=Codex 3" in text
    assert gate.evaluate(workboard) == []


def test_up_for_grabs_keeps_claim_when_agent_has_other_task(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 3; scope=thomas/cli/commands/browser,tests/prompt_pack; task=dom+tests",
        active_tasks_block="\n".join(
            [
                "- task_id=dom-snapshot-runtime; agent=Codex 3; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; summary=dom snapshot runtime fix; status=active",
                "- task_id=dom-tests; agent=Codex 3; scope=tests/prompt_pack; summary=dom snapshot tests; status=active",
            ]
        ),
    )
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--up-for-grabs",
            "--task-id",
            "dom-snapshot-runtime",
            "--reported-by",
            "Codex 3",
        ]
    )
    out = capsys.readouterr().out
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert "Workboard issue tool: PASS" in out
    assert "agent=Codex 3;" in text
    assert "task_id=dom-tests;" in text
    assert "task_id=dom-snapshot-runtime; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py;" in text
    assert gate.evaluate(workboard) == []


def test_block_task_json_failure_payload(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- none",
        active_tasks_block="- none",
    )
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--block",
            "--task-id",
            "missing-task",
            "--reporter",
            "Codex 3",
            "--summary",
            "Missing task.",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["action"] == "block"
    assert "active task `missing-task` not found" in payload["error"]
