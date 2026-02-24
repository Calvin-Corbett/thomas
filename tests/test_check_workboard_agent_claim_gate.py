from __future__ import annotations

import json
from pathlib import Path

import scripts.check_workboard_agent_claim as mod


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


def test_gate_passes_with_matching_agent_claim(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 2; scope=thomas/cli/main.py,tests/test_models_cli_scan_alias.py; task=models scan",
        active_tasks_block="- task_id=models-scan; agent=Codex 2; scope=thomas/cli/main.py,tests/test_models_cli_scan_alias.py; summary=models scan; status=active",
    )
    monkeypatch.setenv("AGENT_ID", "codex 2")

    rc = mod.run(["--workboard", str(workboard)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Workboard agent claim gate: PASS" in out
    assert "matching claims: 1" in out


def test_gate_fails_when_agent_id_missing(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(tmp_path, "- none")
    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.delenv("THOMAS_AGENT_ID", raising=False)
    monkeypatch.delenv("THOMAS_AGENT_NAME", raising=False)
    monkeypatch.delenv("CODEX_AGENT_NAME", raising=False)
    monkeypatch.delenv("AGENT_NAME", raising=False)

    rc = mod.run(["--workboard", str(workboard)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "agent id is required" in out


def test_gate_fails_when_agent_has_no_claim(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 1; scope=thomas/cli/parity_compat.py; task=browser parity",
        active_tasks_block="- task_id=browser-parity; agent=Codex 1; scope=thomas/cli/parity_compat.py; summary=browser parity; status=active",
    )
    monkeypatch.setenv("AGENT_ID", "Codex 2")

    rc = mod.run(["--workboard", str(workboard)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "no active workboard claim found for 'Codex 2'" in out


def test_gate_json_pass_payload(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 2; scope=thomas/cli/main.py,tests/test_models_cli_scan_alias.py; task=models scan",
        active_tasks_block="- task_id=models-scan; agent=Codex 2; scope=thomas/cli/main.py,tests/test_models_cli_scan_alias.py; summary=models scan; status=active",
    )
    monkeypatch.setenv("AGENT_ID", "Codex 2")

    rc = mod.run(["--workboard", str(workboard), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["gate"] == "workboard_agent_claim"
    assert payload["matching_claim_count"] == 1
    assert "thomas/cli/main.py" in payload["scopes"]


def test_gate_json_fail_payload_for_missing_claim(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 1; scope=thomas/cli/parity_compat.py; task=browser parity",
        active_tasks_block="- task_id=browser-parity; agent=Codex 1; scope=thomas/cli/parity_compat.py; summary=browser parity; status=active",
    )
    monkeypatch.setenv("AGENT_ID", "Codex 2")

    rc = mod.run(["--workboard", str(workboard), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["gate"] == "workboard_agent_claim"
    assert payload["matching_claim_count"] == 0
    assert "no active workboard claim found" in payload["error"]


def test_gate_accepts_codex_agent_id_env(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex ID; scope=thomas/cli/main.py; task=models scan",
        active_tasks_block="- task_id=models-scan; agent=Codex ID; scope=thomas/cli/main.py; summary=models scan; status=active",
    )
    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.delenv("THOMAS_AGENT_ID", raising=False)
    monkeypatch.setenv("CODEX_AGENT_ID", "codex id")

    rc = mod.run(["--workboard", str(workboard)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Workboard agent claim gate: PASS" in out
