"""A delegated (Code) task is held to the same acceptance contract as the agent loop."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from thomas.core import task_bot_runtime
from thomas.core.task_checklist_runtime import attach_contract

PROMPT = "Fix `dispatch.py` so it honours every limit in `data/aircraft.json`."


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.delenv("THOMAS_VERIFICATION_CONTRACT", raising=False)
    monkeypatch.setenv("THOMAS_TASK_CHECKLISTS", "0")  # isolate the contract from the June checklist
    ws = tmp_path / "work"
    (ws / "data").mkdir(parents=True)
    (ws / "data" / "aircraft.json").write_text(
        json.dumps({"fuel_flow_gph": 60.0, "turnaround_time_min": 25}), encoding="utf-8"
    )
    (ws / "dispatch.py").write_text("burn = aircraft['fuel_flow_gph']\n", encoding="utf-8")
    return ws


def _execution(tmp_path: Path) -> str:
    rec = task_bot_runtime.create_execution(session_id="s1", summary=PROMPT, intent="chat_task", repo_root=tmp_path)
    return str(rec["execution_id"])


def test_contract_is_in_the_brief_and_holds_completion_until_the_field_is_consumed(
    tmp_path: Path, workspace: Path
) -> None:
    execution_id = _execution(tmp_path)
    block = attach_contract(execution_id, PROMPT, workspace, repo_root=tmp_path)
    assert block.startswith("--- Acceptance Contract ---") and "turnaround_time_min" in block
    stored = task_bot_runtime.get_execution(execution_id, tmp_path)
    assert stored["workspace"] == str(workspace) and stored["acceptance_contract"]

    task_bot_runtime.record_checklist_evidence(execution_id, output_text="All limits honoured.", repo_root=tmp_path)
    held = task_bot_runtime.complete_execution(
        execution_id, actor="bot", summary="done", repo_root=tmp_path, verified_success=True
    )
    assert held["state"] == "awaiting_proof"
    assert "turnaround_time_min" in str(held.get("blocker") or "")

    (workspace / "dispatch.py").write_text(
        "burn = aircraft['fuel_flow_gph']\nt = aircraft['turnaround_time_min']\n", encoding="utf-8"
    )
    task_bot_runtime.record_checklist_evidence(execution_id, output_text="Turnaround added.", repo_root=tmp_path)
    done = task_bot_runtime.complete_execution(
        execution_id, actor="bot", summary="done", repo_root=tmp_path, verified_success=True
    )
    assert done["state"] == "completed", done.get("blocker")


def test_flag_off_attaches_nothing_and_never_holds(tmp_path: Path, workspace: Path, monkeypatch) -> None:
    monkeypatch.setenv("THOMAS_VERIFICATION_CONTRACT", "0")
    execution_id = _execution(tmp_path)
    assert attach_contract(execution_id, PROMPT, workspace, repo_root=tmp_path) == ""
    task_bot_runtime.record_checklist_evidence(execution_id, output_text="done", repo_root=tmp_path)
    done = task_bot_runtime.complete_execution(
        execution_id, actor="bot", summary="done", repo_root=tmp_path, verified_success=True
    )
    assert done["state"] == "completed"
