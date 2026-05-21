from __future__ import annotations

import json
from pathlib import Path

import scripts.forge.gates.workboard_claim_freshness as mod


def _write_workboard(
    tmp_path: Path,
    claims_block: str,
    *,
    active_tasks_block: str,
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


def test_freshness_gate_passes_for_recent_claim(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 2; scope=thomas/cli/main.py; task=models scan",
        active_tasks_block="- task_id=models-scan; agent=Codex 2; scope=thomas/cli/main.py; summary=models scan; status=active",
    )
    now = "2026-02-25T12:00:00+00:00"
    monkeypatch.setattr(mod, "_line_commit_unix", lambda *_args, **_kwargs: 1772019000)  # 2026-02-25T10:10:00Z

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--max-age-hours",
            "24",
            "--now",
            now,
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "Workboard claim freshness gate: PASS" in out


def test_freshness_gate_fails_for_stale_claim(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 2; scope=thomas/cli/main.py; task=models scan",
        active_tasks_block="- task_id=models-scan; agent=Codex 2; scope=thomas/cli/main.py; summary=models scan; status=active",
    )
    now = "2026-02-25T12:00:00+00:00"
    monkeypatch.setattr(mod, "_line_commit_unix", lambda *_args, **_kwargs: 1771846200)  # ~48h old

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--max-age-hours",
            "24",
            "--now",
            now,
        ]
    )
    out = capsys.readouterr().out

    assert rc == 1
    assert "Workboard claim freshness gate: FAIL" in out
    assert "stale active claims detected" in out


def test_freshness_gate_json_reports_stale_claims(tmp_path: Path, monkeypatch, capsys) -> None:
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
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["stale_claim_count"] == 1
    assert payload["stale_claims"][0]["agent"] == "Codex 2"


def test_freshness_gate_fails_when_blame_timestamp_missing(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 2; scope=thomas/cli/main.py; task=models scan",
        active_tasks_block="- task_id=models-scan; agent=Codex 2; scope=thomas/cli/main.py; summary=models scan; status=active",
    )
    monkeypatch.setattr(mod, "_line_commit_unix", lambda *_args, **_kwargs: None)

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--max-age-hours",
            "24",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["stale_claim_count"] == 1
    assert payload["stale_claims"][0]["issue"] == "missing_blame_timestamp"
