from __future__ import annotations

import json
from pathlib import Path

import scripts.check_workboard_claims as gate
import scripts.workboard_claim_cleanup as mod


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


def test_cleanup_reports_stale_claims_without_mutating_by_default(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 2; scope=thomas/cli/main.py; task=models scan",
        active_tasks_block="- task_id=models-scan; agent=Codex 2; scope=thomas/cli/main.py; summary=models scan; status=active",
        issues_block="- issue_id=models-scan-issue; task_id=models-scan; reporter=Codex 2; owner=Codex 2; state=open; summary=needs owner handoff",
    )
    before = workboard.read_text(encoding="utf-8")
    monkeypatch.setattr(mod, "_line_commit_unix", lambda *_args, **_kwargs: 1771846200)  # ~48h old

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--max-age-hours",
            "24",
            "--now",
            "2026-02-25T12:00:00+00:00",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    after = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["applied"] is False
    assert payload["stale_claim_count"] == 1
    assert payload["candidate_task_ids"] == ["models-scan"]
    assert payload["stale_claims"][0]["unresolved_issue_ids"] == ["models-scan-issue"]
    assert before == after


def test_cleanup_fail_on_stale_returns_nonzero(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 2; scope=thomas/cli/main.py; task=models scan",
        active_tasks_block="- task_id=models-scan; agent=Codex 2; scope=thomas/cli/main.py; summary=models scan; status=active",
    )
    monkeypatch.setattr(mod, "_line_commit_unix", lambda *_args, **_kwargs: 1771846200)

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--max-age-hours",
            "24",
            "--now",
            "2026-02-25T12:00:00+00:00",
            "--json",
            "--fail-on-stale",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["stale_claim_count"] == 1
    assert payload["applied"] is False


def test_cleanup_apply_moves_stale_tasks_and_releases_claim_and_issue_owner(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 2; scope=thomas/cli/main.py; task=models scan",
        active_tasks_block="- task_id=models-scan; agent=Codex 2; scope=thomas/cli/main.py; summary=models scan; status=blocked",
        issues_block="- issue_id=models-scan-issue; task_id=models-scan; reporter=Codex 2; owner=Codex 2; state=open; summary=needs owner handoff",
    )
    monkeypatch.setattr(mod, "_line_commit_unix", lambda *_args, **_kwargs: 1771846200)

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--max-age-hours",
            "24",
            "--now",
            "2026-02-25T12:00:00+00:00",
            "--apply",
            "--reported-by",
            "cleanup-bot",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["applied"] is True
    assert payload["moved_task_ids"] == ["models-scan"]
    assert payload["released_agents"] == ["Codex 2"]
    assert payload["reassigned_issue_ids"] == ["models-scan-issue"]
    assert "## Agent Claims (Active)" in text
    assert "agent=Codex 2; scope=thomas/cli/main.py; task=models scan" not in text
    assert "## Active Tasks" in text
    assert "task_id=models-scan; agent=Codex 2;" not in text
    assert "## Up For Grabs" in text
    assert "task_id=models-scan; scope=thomas/cli/main.py; summary=models scan; reported_by=cleanup-bot" in text
    assert "issue_id=models-scan-issue; task_id=models-scan;" in text
    assert "owner=unassigned;" in text
    assert gate.evaluate(workboard) == []
