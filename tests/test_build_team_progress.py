"""Frozen behavioral contract for the Luna native self-edit team.

Product owners: thomas/forge/anvil/build_team_ledger.py,
thomas/forge/anvil/build_agent_scheduler.py, thomas/forge/anvil/forge_code_http_stream.py.
These offline checks are not live-model capacity evidence.
"""

from __future__ import annotations

import asyncio
import copy
import json
import subprocess
from pathlib import Path

import pytest

from thomas.forge.anvil.build_agent_scheduler import BuildTeamScheduler
from thomas.forge.anvil.build_team_ledger import TeamLedger
from thomas.forge.anvil.forge_code_http_stream import line_to_sse_payload
from thomas.tools.base import ToolResult

COUNTS = ("queued", "running", "integrated", "failed", "cancelled", "interrupted")


def test_progress_counts_are_a_fresh_view_of_durable_child_states(tmp_path):
    data = {"team_id": "test", "state": "running", "children": [{"state": state} for state in COUNTS]}
    ledger = TeamLedger(tmp_path, data)
    original = copy.deepcopy(data)
    first = ledger.progress_snapshot()
    assert first == {"state": "running", "total": 6, **{state: 1 for state in COUNTS}}
    assert data == original
    ledger.data["children"][0]["state"] = "integrated"
    assert first["queued"] == 1
    second = ledger.progress_snapshot()
    assert second["queued"] == 0 and second["integrated"] == 2
    second["integrated"] = 99
    assert ledger.progress_snapshot()["integrated"] == 2
    assert not (tmp_path / "team.json").exists(), "A progress read cannot rewrite its ledger"


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["success", "mixed", "cancel", "deadline"])
async def test_visible_progress_matches_settled_ledger_including_stop(tmp_path, scenario):
    events, started = [], set()
    ready, release = asyncio.Event(), asyncio.Event()
    active = 0

    class Writer:
        async def execute_assigned(self, job, **kwargs):
            nonlocal active
            active += 1
            started.add(job["path"])
            if len(started) == 3:
                ready.set()
            try:
                await release.wait()
                if scenario == "mixed" and job["path"] == "file1.py":
                    return ToolResult(ok=False, error="A real assigned check failed")
                (tmp_path / job["path"]).write_text("integrated", encoding="utf-8")
                return ToolResult(ok=True, data="Integrated owned file")
            finally:
                active -= 1

    deadline = asyncio.get_running_loop().time() + (0.2 if scenario == "deadline" else 10)
    scheduler = BuildTeamScheduler(
        Writer(),
        project=tmp_path,
        model="selected-luna",
        provider="openai_codex",
        emit=events.append,
        deadline=deadline,
    )
    jobs = [{"title": f"Helper {i}", "path": f"file{i}.py", "instructions": "Implement your file"} for i in range(3)]
    task = asyncio.create_task(scheduler.execute({"assignments": jobs}))
    await asyncio.wait_for(ready.wait(), 5)
    visible = [event for event in events if event.get("name") == "team-progress"]
    if scenario == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        if scenario != "deadline":
            release.set()
        result = await asyncio.wait_for(task, 5)
        assert result.ok is (scenario == "success")
    assert active == 0
    assert visible, "Team progress must be visible before any helper finishes"
    assert visible[0]["team_progress"]["queued"] == 3
    assert visible[-1]["team_progress"]["running"] == 3
    paths = list(tmp_path.glob(".thomas/evolve/agent/team/team_*/team.json"))
    assert len(paths) == 1
    receipt = json.loads(paths[0].read_text())
    final = [event for event in events if event.get("name") == "team-progress"][-1]
    expected = {state: sum(child["state"] == state for child in receipt["children"]) for state in COUNTS}
    assert final["fc"] == "planning"
    assert final["team_id"] == receipt["team_id"]
    assert final["model"] == "selected-luna"
    assert final["team_progress"] == {"state": receipt["state"], "total": 3, **expected}
    assert "files integrated" in final["text"].lower()
    assert "verified" not in final["text"].lower()
    assert not any(event.get("fc") == "final" for event in events)
    for event in events:
        if event.get("name") == "team-progress":
            assert event["fc"] == "planning"
            assert len(event["text"]) <= 260, "Visible team summaries must stay readable as teams grow"
            summary = event["team_progress"]
            assert f"{summary['integrated']}/{summary['total']} files integrated" in event["text"]
            for state in COUNTS:
                assert f"{state} {summary[state]}" in event["text"]
            if summary["state"] == "running":
                assert "settled" not in event["text"].lower()
            assert sum(summary[state] for state in COUNTS) == summary["total"] == 3
    if scenario == "mixed":
        assert any("Helper 1: failed (file1.py)" in event.get("text", "") for event in events)
        assert expected["integrated"] == 2 and expected["failed"] == 1
    elif scenario in {"cancel", "deadline"}:
        assert expected["cancelled"] == 3 and expected["integrated"] == 0


def progress_frame(summary=None):
    return {
        "fc": "planning",
        "name": "team-progress",
        "team_id": "team-proof",
        "model": "gpt-5.6-luna",
        "text": "Team: 1/3 files integrated · 1 assignment in progress · 1 queued. The lead still checks the combined project.",
        "team_progress": summary
        if summary is not None
        else {
            "state": "running",
            "total": 3,
            "queued": 1,
            "running": 1,
            "integrated": 1,
            "failed": 0,
            "cancelled": 0,
            "interrupted": 0,
        },
    }


def test_http_stream_preserves_only_the_bounded_progress_contract():
    raw = progress_frame()
    expected = copy.deepcopy(raw["team_progress"])
    raw["team_progress"]["private_details"] = "must not cross the bridge"
    result = line_to_sse_payload(json.dumps(raw))
    assert result["team_progress"] == expected
    assert result["kind"] == "planning" and result["name"] == "team-progress"
    assert result["team_id"] == "team-proof" and result["model"] == "gpt-5.6-luna"


@pytest.mark.parametrize(
    "mutation",
    [
        {"running": True},
        {"failed": -1},
        {"total": 0},
        {"running": 1.0},
        {"queued": "1"},
        {"total": 4},
        {"state": "invented"},
        {"state": []},
        {"state": {}},
        {"state": None},
    ],
)
def test_http_stream_omits_invalid_progress_without_losing_the_narrative(mutation):
    raw = progress_frame()
    raw["team_progress"].update(mutation)
    result = line_to_sse_payload(json.dumps(raw))
    assert "team_progress" not in result
    assert result["text"] == raw["text"] and result["kind"] == "planning"


def test_http_stream_keeps_progress_above_one_hundred_agents():
    raw = progress_frame(
        {
            "state": "running",
            "total": 101,
            "queued": 100,
            "running": 1,
            "integrated": 0,
            "failed": 0,
            "cancelled": 0,
            "interrupted": 0,
        }
    )
    result = line_to_sse_payload(json.dumps(raw))
    assert result["team_progress"] == raw["team_progress"]


def test_team_progress_stays_visible_in_actual_live_and_replayed_browser_modules():
    root = Path(__file__).resolve().parents[1]
    raw = progress_frame()
    frame = line_to_sse_payload(json.dumps(raw))
    assert frame.get("team_progress") == raw["team_progress"]
    result = subprocess.run(
        ["node", str(root / "tests/web_node/build_team_progress.mjs")],
        cwd=root,
        input=json.dumps({"frame": frame, "raw": raw}),
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
