from __future__ import annotations

import json
from pathlib import Path

import scripts.agent_bootstrap_claim as mod
import scripts.check_workboard_claims as gate


def _write_workboard(
    tmp_path: Path,
    claims_block: str = "- none",
    *,
    active_tasks_block: str = "- none",
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


def test_bootstrap_claim_with_explicit_agent(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--agent",
            "Codex 2",
            "--scope",
            "thomas/cli/main.py,tests/test_models_cli_scan_alias.py",
            "--task",
            "models scan reliability",
            "--ticket",
            "HSK-777",
        ]
    )
    out = capsys.readouterr().out
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert "Agent bootstrap claim: PASS" in out
    assert "agent=Codex 2;" in text
    assert "task=[WIP][HSK-777] models scan reliability" in text
    assert '$env:AGENT_ID="Codex 2"' in out
    assert gate.evaluate(workboard) == []


def test_bootstrap_claim_uses_env_agent(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    monkeypatch.setenv("AGENT_ID", "Codex Env")

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--scope",
            "thomas/cli/main.py",
            "--task",
            "runtime lane",
            "--ticket",
            "HSK-778",
        ]
    )
    out = capsys.readouterr().out
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert "agent=Codex Env;" in text
    assert "task=[WIP][HSK-778] runtime lane" in text
    assert "Agent bootstrap claim: PASS" in out
    assert gate.evaluate(workboard) == []


def test_bootstrap_claim_fails_without_agent(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.delenv("THOMAS_AGENT_ID", raising=False)
    monkeypatch.delenv("THOMAS_AGENT_NAME", raising=False)
    monkeypatch.delenv("CODEX_AGENT_NAME", raising=False)
    monkeypatch.delenv("AGENT_NAME", raising=False)

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--scope",
            "thomas/cli/main.py",
            "--task",
            "runtime lane",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 1
    assert "agent id is required" in out
    assert "- none" in workboard.read_text(encoding="utf-8")


def test_bootstrap_claim_json_payload(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--agent",
            "Codex 9",
            "--scope",
            "tests",
            "--task",
            "json payload",
            "--ticket",
            "HSK-900",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["agent"] == "Codex 9"
    assert payload["task"] == "[WIP][HSK-900] json payload"
    assert "AGENT_ID" in payload["powershell_export"]


def test_bootstrap_claim_uses_codex_agent_id_env(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.delenv("THOMAS_AGENT_ID", raising=False)
    monkeypatch.setenv("CODEX_AGENT_ID", "Codex Numeric")

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--scope",
            "thomas/cli/main.py",
            "--task",
            "runtime lane",
            "--ticket",
            "HSK-999",
        ]
    )
    out = capsys.readouterr().out
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert "Agent bootstrap claim: PASS" in out
    assert "agent=Codex Numeric;" in text
    assert gate.evaluate(workboard) == []
