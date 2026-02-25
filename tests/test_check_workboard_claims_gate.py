from __future__ import annotations

import json
from pathlib import Path

import scripts.check_workboard_claims as mod


def _write_workboard(
    tmp_path: Path,
    claims_block: str,
    *,
    active_tasks_block: str = "- none",
    issues_block: str = "- none",
    up_for_grabs_block: str = "- none",
) -> Path:
    text = (
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
    )
    path = tmp_path / "WORKBOARD.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_workboard_claims_gate_passes_with_none_placeholder(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path, "- none")
    rc = mod.run(["--workboard", str(workboard)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Workboard claims gate: PASS" in out


def test_workboard_claims_gate_fails_for_duplicate_agent(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "\n".join(
            [
                "- agent=Codex 3; scope=thomas/cli/commands/browser; task=dom snapshot runtime",
                "- agent=codex 3; scope=tests/prompt_pack; task=dom snapshot tests",
            ]
        ),
        active_tasks_block="- task_id=dom-snapshot; agent=Codex 3; scope=thomas/cli/commands/browser; summary=dom snapshot runtime; status=active",
    )
    rc = mod.run(["--workboard", str(workboard)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "duplicate active claim for agent" in out


def test_workboard_claims_gate_fails_for_scope_overlap(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "\n".join(
            [
                "- agent=Codex 1; scope=thomas/cli/commands/browser; task=bridge parity",
                "- agent=Codex 3; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; task=dom snapshot",
            ]
        ),
        active_tasks_block="\n".join(
            [
                "- task_id=bridge-parity; agent=Codex 1; scope=thomas/cli/commands/browser; summary=bridge parity; status=active",
                "- task_id=dom-snapshot; agent=Codex 3; scope=thomas/cli/commands/browser/p011_browser_artifact_dom_snapshot.py; summary=dom snapshot; status=active",
            ]
        ),
    )
    rc = mod.run(["--workboard", str(workboard)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "scope overlap between" in out


def test_workboard_claims_gate_fails_for_missing_required_field(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path, "- agent=Codex 2; task=models scan crash fix")
    rc = mod.run(["--workboard", str(workboard)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "missing required field(s): scope" in out


def test_workboard_claims_gate_fails_when_section_missing(tmp_path: Path, capsys) -> None:
    workboard = tmp_path / "WORKBOARD.md"
    workboard.write_text("# Thomas Workboard\n\n## Current Priorities\n\n- Placeholder\n", encoding="utf-8")
    rc = mod.run(["--workboard", str(workboard)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "missing `## Agent Claims` section in workboard" in out


def test_workboard_claims_gate_json_pass_payload(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path, "- none")
    rc = mod.run(["--workboard", str(workboard), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["ok"] is True
    assert payload["gate"] == "workboard_claims"
    assert payload["violation_count"] == 0
    assert payload["violations"] == []
    assert payload["active_claim_count"] == 0
    assert str(workboard) == payload["workboard"]


def test_workboard_claims_gate_json_fail_payload(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path, "- agent=Codex 2; task=models scan crash fix")
    rc = mod.run(["--workboard", str(workboard), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False
    assert payload["gate"] == "workboard_claims"
    assert payload["violation_count"] == 1
    assert payload["active_claim_count"] == 0
    assert "missing required field(s): scope" in payload["violations"][0]


def test_claim_requires_matching_active_task(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 7; scope=thomas/cli/main.py; task=main lane",
        active_tasks_block="- none",
    )
    rc = mod.run(["--workboard", str(workboard)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "has active claim but no matching entry in `## Active Tasks`" in out


def test_active_task_requires_matching_claim(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- none",
        active_tasks_block="- task_id=main-lane; agent=Codex 7; scope=thomas/cli/main.py; summary=main lane; status=active",
    )
    rc = mod.run(["--workboard", str(workboard)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "without a matching active claim" in out


def test_blocked_task_requires_open_issue(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 9; scope=thomas/cli/main.py; task=blocked lane",
        active_tasks_block="- task_id=blocked-lane; agent=Codex 9; scope=thomas/cli/main.py; summary=blocked lane; status=blocked",
        issues_block="- none",
    )
    rc = mod.run(["--workboard", str(workboard)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "blocked task `blocked-lane` must have an open/triaged entry" in out
