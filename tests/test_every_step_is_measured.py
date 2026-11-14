"""Every step Thomas takes is timed into one log, and the report says where the time went (2026-10-25).

"every single thing should be measured and tracked so we have data to pull from when we decide what to improve": the
speed board left 78% of a week's time "unattributed". Each test points the step log at its own folder.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from thomas.core import capture_context, machine_load, step_log, step_report
from thomas.core.llm_shared import StreamEvent, TokenUsage
from thomas.forge.anvil import forge_code_store


@pytest.fixture
def steps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "metrics"
    monkeypatch.setenv(step_log.DIR_ENV, str(folder))
    monkeypatch.delenv(step_log.OFF_ENV, raising=False)
    monkeypatch.delenv(machine_load.CAPPED_ENV, raising=False)  # a run started by the capped server inherits it
    return folder


def _rows(folder: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for path in sorted(folder.glob("steps-*.jsonl")) for line in path.read_text().splitlines()]


def test_a_step_is_one_line_with_its_time_and_fields(steps: Path) -> None:
    step_log.record("tool", seconds=1.23456, tool="fs.read_file", outcome="EXECUTED", nothing=None)
    [row] = _rows(steps)
    assert row["step"] == "tool" and row["seconds"] == 1.235 and row["tool"] == "fs.read_file"
    assert "nothing" not in row and row["pid"] > 0 and row["ts"] > 0


def test_a_timed_block_records_its_outcome_and_a_raise(steps: Path) -> None:
    with step_log.timed("check", execution_id="e1") as noted:
        noted["outcome"] = "passed"
    with pytest.raises(ValueError), step_log.timed("second_look"):
        raise ValueError("no verdict")
    first, second = _rows(steps)
    assert first["outcome"] == "passed" and first["execution_id"] == "e1" and first["seconds"] >= 0
    assert second["outcome"] == "raised ValueError"


def test_the_log_is_off_under_pytest_and_when_switched_off(steps: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(step_log.OFF_ENV, "off")
    step_log.record("tool", seconds=1)
    monkeypatch.delenv(step_log.OFF_ENV)
    monkeypatch.delenv(step_log.DIR_ENV)
    assert step_log.folder() is None, "the suite must not write into the real record"
    assert not steps.exists()


def test_read_returns_the_last_days_oldest_first_and_skips_a_bad_line(steps: Path) -> None:
    step_log.record("model", seconds=2)
    step_log.record("tool", seconds=1)
    with open(next(steps.glob("steps-*.jsonl")), "a", encoding="utf-8") as handle:
        handle.write("not json\n")
    assert [row["step"] for row in step_log.read(1)] == ["model", "tool"]


def test_a_new_day_packs_past_days_and_deletes_the_days_older_than_the_keep(steps: Path) -> None:
    steps.mkdir(parents=True)
    now = 1_800_000_000.0
    old = step_log.day_file(steps, now - (step_log.KEEP_DAYS + 1) * 86400)
    yesterday = step_log.day_file(steps, now - 86400)
    today = step_log.day_file(steps, now)
    old.write_text("{}\n")
    yesterday.write_text(json.dumps({"ts": now - 86400, "step": "tool", "seconds": 1.0}) + "\n")
    today.write_text(json.dumps({"ts": now, "step": "model", "seconds": 2.0}) + "\n")
    step_log.prune(steps, now)
    packed = yesterday.with_name(yesterday.name + ".gz")
    assert not old.exists() and not yesterday.exists() and packed.exists() and today.exists()
    assert [row["step"] for row in step_log.read(2, base=steps, now=now)] == ["tool", "model"], "packed days still read"
    step_log.prune(steps, now + (step_log.KEEP_DAYS + 2) * 86400)
    assert not packed.exists(), "a packed day is deleted after the keep too"


def test_a_model_call_is_timed_with_its_tokens(steps: Path) -> None:
    state = capture_context.CaptureState(run_id="run-1", correlation="contextvar")
    usage = TokenUsage(prompt_tokens=120, completion_tokens=30, total_tokens=150)
    capture_context.record_stream_event(state, StreamEvent(type="usage", data={"usage": usage}))
    capture_context.end_model_capture(
        state, interrupted=False, served_by_model="gpt-6.1-sol", served_by_provider="openai_codex",
        provider_attempts=1, merged_partial_output=False,
    )  # fmt: skip
    [row] = _rows(steps)
    assert row["step"] == "model" and row["model"] == "gpt-6.1-sol" and row["run"] == "run-1"
    assert row["prompt_tokens"] == 120 and row["completion_tokens"] == 30


def test_every_finished_tool_call_is_timed(steps: Path) -> None:
    from tests.test_agent_loop_tool_exec import _LoopStub, _run_execute_tools, _SpyRunner

    loop = _LoopStub(autonomy_level=4, runner=_SpyRunner())
    calls = [{"id": "t1", "name": "dummy.echo", "arguments": "{}"}, {"id": "t2", "name": "fs.read", "arguments": "{}"}]
    events = asyncio.run(_run_execute_tools(loop, calls))
    rows = _rows(steps)
    assert len(events) == 2 and sorted(row["tool"] for row in rows) == ["dummy.echo", "fs.read"]
    assert all(row["step"] == "tool" and row["outcome"] == "ok" and row["run"] == "run-1" for row in rows)
    assert all(row["seconds"] >= 0 for row in rows)


def test_a_tool_that_timed_out_is_recorded_as_a_timeout(steps: Path) -> None:
    data = {"tool_name": "check.run", "ok": False, "duration_ms": 600_000, "result_text": "Tool timed out after 600s"}
    event = SimpleNamespace(data=data)
    assert step_log.tool_finished(event, run="r") is event
    [row] = _rows(steps)
    assert (row["tool"], row["outcome"], row["seconds"]) == ("check.run", "timeout", 600.0)


def test_a_finished_run_is_timed_from_its_request_with_how_it_ended(steps: Path, tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    cid = str(forge_code_store.new_conversation(root, title="t")["id"])
    forge_code_store.append_user_turn(root, cid, "do it")
    forge_code_store.append_agent_turn(
        root, cid, model="codex:gpt", transcript="", changed_files=["a.py"], returncode=0, ok=True, noop=False,
        reason="", run_id="run-3", outcome="reload_yielded", model_used="gpt-6.1-sol",
    )  # fmt: skip
    [row] = [row for row in _rows(steps) if row["step"] == "run"]
    assert row["outcome"] == "reload_yielded" and row["run"] == "run-3" and row["changed_files"] == 1
    assert row["model"] == "gpt-6.1-sol" and row["seconds"] >= 0 and row["cid"] == cid


def test_a_wait_for_room_is_recorded_with_what_waited(steps: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(machine_load.LIMIT_ENV, "90")
    busy = machine_load.Reading(cpu=99.0, memory=10.0, samples=1)
    clock = iter([0.0, 0.0, 7.0, 7.0])
    machine_load.wait_for_room(max_wait_s=5, label="check.run", read=lambda: busy, sleep=lambda _s: None,
                               clock=lambda: next(clock))  # fmt: skip
    machine_load.wait_for_room(max_wait_s=5, label="calm", read=lambda: machine_load.Reading(5.0, 5.0, 1))
    [row] = _rows(steps)
    assert row["step"] == "load_wait" and row["where"] == "check.run" and "CPU is at 99%" in row["why"]


def test_the_report_says_where_the_time_went() -> None:
    rows = [
        {"ts": 1, "step": "run", "seconds": 600, "outcome": "completed", "cpu": 95.0},
        {"ts": 2, "step": "run", "seconds": 300, "outcome": "reload_yielded", "cpu": 50.0},
        {"ts": 3, "step": "model", "seconds": 4, "model": "gpt-6.1-sol", "prompt_tokens": 100, "completion_tokens": 20},
        {"ts": 4, "step": "tool", "seconds": 90, "tool": "check.run"},
        {"ts": 5, "step": "tool", "seconds": 1, "tool": "fs.read_file"},
        {"ts": 6, "step": "load_wait", "seconds": 30, "where": "check shard"},
        {"ts": 7, "step": "project_start", "seconds": 1690, "copy_s": 22, "bind_s": 1, "start_s": 1667},
        {"ts": 8, "step": "check", "seconds": 1800, "outcome": "passed"},
    ]
    report = step_report.summarize(rows)
    assert report["steps"] == 8 and report["runs"]["count"] == 2
    assert report["runs"]["by_outcome"] == {"completed": 1, "reload_yielded": 1}
    assert report["model"]["prompt_tokens"] == 100 and report["model"]["by_model"]["gpt-6.1-sol"]["count"] == 1
    assert [tool["tool"] for tool in report["tools"]] == ["check.run", "fs.read_file"], "slowest first"
    assert report["load_waits"]["check shard"]["total_s"] == 30.0
    assert report["project_starts"]["first_run"]["median_s"] == 1667.0
    assert report["checks"]["by_outcome"] == {"passed": 1}
    assert report["machine"]["share_at_or_over_limit"] == 0.5


def test_an_empty_log_reports_nothing_rather_than_failing() -> None:
    report = step_report.summarize([])
    assert report["steps"] == 0 and report["machine"]["average_cpu"] is None and report["tools"] == []
