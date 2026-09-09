"""The acceptance contract is derived before work and checked against the workspace, never against words."""

from __future__ import annotations

import json
from pathlib import Path

from thomas.core import acceptance_contract as ac

PROMPT = """A cargo airline's flight dispatch planner has been producing incorrect results.

The following data files describe the operation:

- `data/aircraft.json` — the Caravan's performance sheet including speed, fuel and turnaround limits
- `data/manifest.json` — today's cargo load

Fix the planning tool so that running `python dispatch.py --output out/flight_plan.json` produces a correct plan.
The data files are correct and should not be modified.
The output flight plan must be deterministic — same inputs produce the same plan every run.
Write any Python dependencies needed to run your code to `requirements.txt`.
Never run `rm -rf /` to clean up.
"""

RAN_OK = [{"name": "shell.exec", "ok": True, "command": "python dispatch.py --output out/flight_plan.json"}]


def _workspace(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    (data / "aircraft.json").write_text(
        json.dumps({"type": "C208B", "fuel_flow_gph": 60.0, "turnaround_time_min": 25, "_note": "x", "NAN": 1}),
        encoding="utf-8",
    )
    (data / "manifest.json").write_text(json.dumps({"items": [{"id": "PKG-001", "weight_lbs": 580}]}), encoding="utf-8")
    (tmp_path / "dispatch.py").write_text(
        "fuel = aircraft['fuel_flow_gph']\nw = manifest['items'][0]['weight_lbs']\n", encoding="utf-8"
    )
    return tmp_path


def test_contract_names_every_data_field_output_path_and_command(tmp_path: Path) -> None:
    items = ac.build_contract(PROMPT, _workspace(tmp_path))
    by_id = {it.item_id: it for it in items}
    assert "field:aircraft.json:turnaround_time_min" in by_id
    assert "field:aircraft.json:fuel_flow_gph" in by_id
    assert "field:manifest.json:weight_lbs" in by_id
    assert "field:aircraft.json:_note" not in by_id and "field:aircraft.json:NAN" not in by_id
    assert "field:aircraft.json:type" not in by_id  # a string-valued key is a label, not a feature
    assert "output:out/flight_plan.json" in by_id and "output:requirements.txt" in by_id
    assert any(it.kind == ac.KIND_COMMAND and it.target.startswith("python dispatch.py") for it in items)
    assert not any("rm -rf" in it.target for it in items if it.kind == ac.KIND_COMMAND)
    requirements = [it for it in items if it.kind == ac.KIND_REQUIREMENT]
    assert any("deterministic" in it.description for it in requirements)
    assert all(not it.checked for it in requirements)


def test_the_field_the_code_ignores_is_the_unmet_item(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    items = ac.build_contract(PROMPT, ws)
    runs: list[str] = []

    def runner(cmd: str, cwd: Path, timeout: float) -> tuple[int, str]:
        runs.append(cmd)
        return 0, "ok"

    evaluated = ac.evaluate_contract(items, workspace=ws, run_commands=True, runner=runner)
    verdict = ac.contract_verdict(evaluated)
    assert not verdict.met
    assert "field:aircraft.json:turnaround_time_min" in verdict.unmet
    assert "field:aircraft.json:fuel_flow_gph" not in verdict.unmet
    assert "output:out/flight_plan.json" in verdict.unmet
    assert runs == ["python dispatch.py --output out/flight_plan.json"]
    assert all(rid.startswith("req:") for rid in verdict.unchecked)

    prompt = ac.remediation_prompt(evaluated)
    assert "turnaround_time_min" in prompt and "flight_plan.json" in prompt


def test_consuming_the_field_and_writing_the_output_meets_the_contract(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    items = ac.build_contract(PROMPT, ws)
    (ws / "dispatch.py").write_text(
        "fuel = aircraft['fuel_flow_gph']\nw = manifest['items'][0]['weight_lbs']\nt = aircraft['turnaround_time_min']\n",
        encoding="utf-8",
    )
    (ws / "out").mkdir()
    (ws / "out" / "flight_plan.json").write_text("{}", encoding="utf-8")
    (ws / "requirements.txt").write_text("\n", encoding="utf-8")
    verdict = ac.contract_verdict(ac.evaluate_contract(items, workspace=ws, tool_events=RAN_OK))
    assert "output:requirements.txt" in verdict.unmet  # an empty file is not an output
    (ws / "requirements.txt").write_text("numpy\n", encoding="utf-8")
    verdict = ac.contract_verdict(ac.evaluate_contract(items, workspace=ws, tool_events=RAN_OK))
    assert verdict.met, verdict


def test_a_stated_unused_field_decision_counts_but_a_bare_claim_does_not(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    items = [it for it in ac.build_contract(PROMPT, ws) if it.item_id == "field:aircraft.json:turnaround_time_min"]
    claimed = ac.evaluate_contract(items, workspace=ws, response_text="I handled turnaround_time_min correctly.")
    assert not claimed[0].satisfied
    declared = ac.evaluate_contract(
        items,
        workspace=ws,
        response_text="UNUSED_FIELD: aircraft.json:turnaround_time_min - single-leg plan, no turnaround",
    )
    assert declared[0].satisfied and declared[0].detail.startswith("declared unused")


def test_a_changed_file_that_no_longer_parses_fails_the_compile_item(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    items = [it for it in ac.build_contract(PROMPT, ws) if it.kind == ac.KIND_COMPILES]
    (ws / "broken.py").write_text("def (:\n", encoding="utf-8")
    evaluated = ac.evaluate_contract(items, workspace=ws, started_at=0.0)
    assert evaluated[0].checked and not evaluated[0].satisfied and "broken.py" in evaluated[0].detail


def test_trailer_names_failures_and_everything_unchecked(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    evaluated = ac.evaluate_contract(ac.build_contract(PROMPT, ws), workspace=ws)
    trailer = ac.verification_trailer(evaluated)
    assert trailer.startswith("Verification: ")
    assert "FAILED" in trailer and "turnaround_time_min" in trailer
    assert "Unchecked" in trailer and "deterministic" in trailer


def test_learned_rows_join_the_contract_without_a_verdict(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    learned = [
        {
            "item_id": "learned:launch",
            "kind": "custom",
            "description": "The app opens without a console error.",
            "satisfied": True,
            "checked": True,
        },
        {
            "item_id": "field:aircraft.json:turnaround_time_min",
            "kind": ac.KIND_DATA_FIELD,
            "description": "dup",
            "target": "turnaround_time_min",
            "source": "aircraft.json",
        },
    ]
    items = ac.build_contract(PROMPT, ws, learned=learned)
    added = [it for it in items if it.item_id == "learned:launch"]
    assert added and added[0].kind == ac.KIND_LEARNED and not added[0].checked and not added[0].satisfied
    assert sum(1 for it in items if it.item_id == "field:aircraft.json:turnaround_time_min") == 1


def test_no_paths_no_data_no_commands_still_yields_a_contract(tmp_path: Path) -> None:
    items = ac.build_contract("make me a snake game that must open in the browser", tmp_path)
    kinds = {it.kind for it in items}
    assert ac.KIND_COMPILES in kinds and ac.KIND_REQUIREMENT in kinds
    assert ac.contract_prompt_block(items).startswith("--- Acceptance Contract ---")


def test_flag_is_on_by_default_and_zero_turns_it_off(monkeypatch) -> None:
    monkeypatch.delenv(ac.FLAG, raising=False)
    assert ac.contract_enabled() is True
    monkeypatch.setenv(ac.FLAG, "0")
    assert ac.contract_enabled() is False
    monkeypatch.setenv(ac.FLAG, "1")
    assert ac.contract_enabled() is True


def test_round_trip_through_dicts() -> None:
    items = ac.build_contract("Ensure every test passes.", Path("."))
    assert [it.to_dict() for it in ac.items_from_dicts(ac.items_to_dicts(items))] == [it.to_dict() for it in items]
