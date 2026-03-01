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


def test_bootstrap_parent_defaults_to_dispatcher_name(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    def _fake_dispatch_workers(
        workboard_path,  # noqa: ARG001
        *,
        parent_agent: str,
        target_workers: int,
        **kwargs: object,  # noqa: ANN401
    ) -> tuple[bool, dict[str, object]]:
        return True, {"target_workers": int(target_workers), "claimed_workers": [], "released_workers": [], "temp_task_creator": {"status": "not_needed"}}

    monkeypatch.setattr(mod.claim_tool, "dispatch_workers", _fake_dispatch_workers)

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--agent",
            "Codex 2",
            "--scope",
            "thomas/cli/main.py",
            "--task",
            "dispatcher defaults",
            "--ticket",
            "HSK-901",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["name"] == "dispatcher"
    assert payload["auto_dispatched"] is True
    assert payload["dispatch_target_workers"] == 3
    assert payload["dispatch"]["target_workers"] == 3


def test_bootstrap_parent_debug_includes_resolution_metadata(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(tmp_path)

    def _fake_dispatch_workers(
        workboard_path,  # noqa: ARG001
        *,
        parent_agent: str,
        target_workers: int,
        **kwargs: object,  # noqa: ANN401
    ) -> tuple[bool, dict[str, object]]:
        assert parent_agent == "Codex 3"
        assert target_workers == 2
        return True, {"target_workers": 2, "claimed_workers": [], "released_workers": []}

    monkeypatch.setattr(mod.claim_tool, "dispatch_workers", _fake_dispatch_workers)

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--agent",
            "Codex 3",
            "--scope",
            "thomas/cli/main.py",
            "--task",
            "dispatcher debug",
            "--ticket",
            "HSK-902",
            "--dispatch-target-workers",
            "2",
            "--json",
            "--debug",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["debug"]["dispatch_called"] is True
    assert payload["debug"]["dispatch_target_workers"] == 2
    assert payload["debug"]["run_worker_loop"] is False
    assert payload["debug"]["name_resolution_source"] == "dispatcher-default"


def test_bootstrap_parent_no_auto_dispatch_still_dispatcher_identity(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--agent",
            "Codex 4",
            "--scope",
            "thomas/cli/main.py",
            "--task",
            "dispatcher still named",
            "--ticket",
            "HSK-910",
            "--no-auto-dispatch",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["auto_dispatch_enabled"] is False
    assert payload["auto_dispatched"] is False
    assert payload["name"] == "dispatcher"


def test_bootstrap_parent_debug_includes_resolution_source_when_auto_disabled(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--agent",
            "Codex 4",
            "--scope",
            "thomas/cli/main.py",
            "--task",
            "dispatcher debug no auto",
            "--ticket",
            "HSK-911",
            "--no-auto-dispatch",
            "--debug",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["debug"]["name_resolution_source"] == "dispatcher-default-no-auto"
    assert payload["debug"]["auto_dispatch_requested"] is False
    assert payload["debug"]["dispatch_called"] is False


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


def test_normalize_dispatch_target_workers_minimum(tmp_path: Path) -> None:
    assert mod._normalize_dispatch_target_workers(1) == 2
    assert mod._normalize_dispatch_target_workers(0) == 2
    assert mod._normalize_dispatch_target_workers(3) == 3


def test_bootstrap_dispatch_target_is_clamped_to_minimum_two(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(tmp_path)
    call: dict[str, int] = {}

    def _fake_dispatch_workers(
        workboard_path,  # noqa: ARG001
        *,
        parent_agent: str,
        target_workers: int,
        **kwargs: object,  # noqa: ANN401
    ) -> tuple[bool, dict[str, object]]:
        call["target_workers"] = int(target_workers)
        return True, {"target_workers": int(target_workers), "claimed_workers": []}

    monkeypatch.setattr(mod.claim_tool, "dispatch_workers", _fake_dispatch_workers)

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--agent",
            "Codex 2",
            "--scope",
            "thomas/cli/main.py",
            "--task",
            "minimum target check",
            "--ticket",
            "HSK-901",
            "--dispatch-target-workers",
            "1",
            "--dispatch-no-temp-creator",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["dispatch_target_workers"] == 2
    assert call["target_workers"] == 2
