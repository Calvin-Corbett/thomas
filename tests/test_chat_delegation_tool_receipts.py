"""Completion follows ordered action receipts, including partial file failures."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from thomas.core import task_bot_runtime
from thomas.core.events import AgentEvent, EventType
from thomas.server import chat_delegation_runner as runner
from thomas.server import worker_runtime
from thomas.server.chat_delegation_tool_receipts import ToolReceiptLog, tool_action_id


def _call(call_id, arguments, ok, name="fs.write_file", workspace=None):
    return [
        {"type": "tool_start", "call_id": call_id, "name": name},
        {
            "type": "tool_output",
            "call_id": call_id,
            "name": name,
            "ok": ok,
            "action_id": tool_action_id(name, arguments, workspace=workspace),
        },
    ]


@pytest.mark.parametrize(
    ("first_ok", "second_args", "expected"),
    [
        (True, {"path": "invoice.txt"}, ["fs.write_file"]),
        (False, {"path": "report.txt"}, ["fs.write_file"]),
        (False, {"path": "invoice.txt"}, []),
    ],
)
def test_recovery_requires_a_later_success_for_the_same_action(first_ok, second_args, expected):
    first = _call("first", {"path": "invoice.txt"}, first_ok)
    second = _call("second", second_args, not first_ok)
    assert ToolReceiptLog(first + second).unrecovered_failures(["fs.write_file"]) == expected


def test_a_parallel_success_is_not_a_retry_after_the_failure():
    first = _call("first", {"path": "invoice.txt"}, False)
    second = _call("second", {"path": "invoice.txt"}, True)
    receipts = ToolReceiptLog([first[0], second[0], first[1], second[1]])
    assert receipts.unrecovered_failures(["fs.write_file"]) == ["fs.write_file"]


@pytest.mark.parametrize("missing", ["call_id", "action_id", "start"])
def test_incomplete_receipts_cannot_clear_a_failure(missing):
    events = _call("first", {"path": "invoice.txt"}, False) + _call("second", {"path": "invoice.txt"}, True)
    if missing == "start":
        events = [event for event in events if event["type"] != "tool_start"]
    else:
        for event in events:
            event.pop(missing, None)
    assert ToolReceiptLog(events).unrecovered_failures(["fs.write_file"]) == ["fs.write_file"]


def test_success_cannot_clear_an_unobserved_legacy_failure():
    receipts = ToolReceiptLog(_call("success", {"path": "invoice.txt"}, True))
    assert receipts.unrecovered_failures(["fs.write_file"]) == ["fs.write_file"]


def test_action_identity_is_canonical_and_does_not_expose_arguments():
    one = tool_action_id("api.send", {"path": "invoice.txt", "token": "private-value"})
    assert one == tool_action_id("api.send", {"token": "private-value", "path": "invoice.txt"})
    assert len(one) == 64 and "private-value" not in one
    assert one != tool_action_id("api.send", {"path": "report.txt", "token": "private-value"})
    assert tool_action_id("api.send", None) == ""


@pytest.fixture(autouse=True)
def isolated_data(monkeypatch, tmp_path):
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("THOMAS_TASK_CHECKLISTS", raising=False)


def test_agent_loop_result_carries_parsed_arguments_without_argument_deltas(monkeypatch, tmp_path):
    from tests.test_agent_loop_tool_args import _run_with_args

    # This provider emits arguments only at tool_call_end, with no delta events.
    monkeypatch.chdir(tmp_path)
    events = _run_with_args('```json\n{"message":"receipt evidence"}\n```')
    result = next(event for event in events if event.type == EventType.TOOL_RESULT)
    assert result.data["ok"] is True
    assert result.data["tool_id"] == "t1"
    assert result.data["arguments"] == {"message": "receipt evidence"}


def test_agent_loop_does_not_invent_arguments_for_an_unmatched_result(monkeypatch, tmp_path):
    from tests.test_agent_loop_tool_args import _run_with_args
    from thomas.agent.loop import AgentLoop

    async def orphan_result(*args, **kwargs):
        yield AgentEvent.tool_result("unknown-call", "dummy.echo", "result", True, 1)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(AgentLoop, "_execute_tools", orphan_result)
    events = _run_with_args('{"message":"receipt evidence"}')
    result = next(event for event in events if event.type == EventType.TOOL_RESULT)
    assert result.data["arguments"] is None


@pytest.mark.asyncio
async def test_native_adapter_preserves_actual_call_identity_without_raw_arguments(monkeypatch, tmp_path):
    from tests.test_agent_worker_parity import _app_with_model, _FakeLLM

    arguments = {"path": "invoice.txt", "content": "private invoice content"}

    class _Loop:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, *args, **kwargs):
            yield AgentEvent.tool_call_start("call-7", "fs.write_file")
            result = AgentEvent.tool_result("call-7", "fs.write_file", "saved", True, 1)
            result.data["arguments"] = arguments
            yield result
            yield AgentEvent.agent_done("Saved invoice.txt", iterations=1, tool_calls=1)

    monkeypatch.setattr(worker_runtime, "LLMClient", _FakeLLM)
    monkeypatch.setattr(worker_runtime, "AgentLoop", _Loop)
    monkeypatch.setattr(worker_runtime, "_resolve_profile", lambda *a: "local")
    events = [
        event
        async for event in worker_runtime.run_agent_worker_events(
            _app_with_model("fixture", "stub", "local"),
            prompt="Create invoice",
            instructions="Create invoice",
            work_dir=tmp_path,
            profile="local",
            tools_enabled=False,
        )
    ]
    start = next(event for event in events if event["type"] == "tool_start")
    result = next(event for event in events if event["type"] == "tool_output")
    assert start["call_id"] == result["call_id"] == "call-7"
    assert result["action_id"] == tool_action_id("fs.write_file", arguments, workspace=tmp_path)
    assert "private invoice content" not in str(events)


@pytest.mark.parametrize("change", ["different_file", "outside", "different_bounds", "earlier_success"])
def test_path_normalization_does_not_forgive_a_different_read(monkeypatch, tmp_path, change):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    failed = {"path": str(workspace / "report.txt"), "start_line": 1, "end_line": 10}
    retry = {"path": "report.txt", "start_line": 1, "end_line": 10}
    if change == "different_file":
        retry["path"] = "invoice.txt"
    elif change == "outside":
        failed["path"] = str(tmp_path / "report.txt")
    elif change == "different_bounds":
        retry["end_line"] = 20
    events = _call("failed", failed, False, "fs.read_file", workspace)
    success = _call("retry", retry, True, "fs.read_file", workspace)
    events = success + events if change == "earlier_success" else events + success
    assert ToolReceiptLog(events).unrecovered_failures(["fs.read_file"]) == ["fs.read_file"]


def test_symlink_escape_cannot_match_an_inside_file(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    try:
        (workspace / "escape.txt").symlink_to(outside)
    except OSError:
        pytest.skip("This platform does not permit unprivileged symlink creation")
    (workspace / "inside.txt").write_text("inside", encoding="utf-8")
    failed = _call("failed", {"path": "escape.txt"}, False, "fs.read_file", workspace)
    retry = _call("retry", {"path": "inside.txt"}, True, "fs.read_file", workspace)
    assert ToolReceiptLog(failed + retry).unrecovered_failures(["fs.read_file"]) == ["fs.read_file"]


@pytest.mark.asyncio
async def test_actual_inside_root_absolute_and_relative_reads_share_receipt_identity(monkeypatch, tmp_path):
    from tests.test_agent_worker_parity import _app_with_model, _FakeLLM
    from thomas.core.llm import StreamEvent
    from thomas.server import app_helpers
    from thomas.tools.filesystem import ReadFileTool
    from thomas.tools.registry import ToolRegistry

    monkeypatch.chdir(tmp_path)
    (tmp_path / "lantern-904.txt").write_bytes(b"LANTERN-904")
    registry = ToolRegistry()
    registry.register(ReadFileTool(tmp_path))

    class ReadLLM(_FakeLLM):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.step = 0

        async def stream_chat(self, messages, tools):
            self.step += 1
            if self.step <= 2:
                call_id = f"read-{self.step}"
                path = str(tmp_path / "lantern-904.txt") if self.step == 1 else "lantern-904.txt"
                args = {"path": path, "start_line": 1, "end_line": 10}
                yield StreamEvent(type="tool_call_start", data={"id": call_id, "name": "fs.read_file"})
                yield StreamEvent(
                    type="tool_call_end", data={"id": call_id, "name": "fs.read_file", "arguments": json.dumps(args)}
                )
            else:
                yield StreamEvent(type="token", data={"text": "Verified lantern-904.txt contains LANTERN-904."})
            yield StreamEvent(type="done", data={})

    monkeypatch.setattr(worker_runtime, "LLMClient", ReadLLM)
    monkeypatch.setattr(app_helpers, "_build_tools", lambda *_args, **_kwargs: registry)
    app = _app_with_model("fixture", "offline", "local")
    app[worker_runtime.APP_CONFIG].memory.root = str(tmp_path / "memory")
    events = [
        event
        async for event in worker_runtime.run_agent_worker_events(
            app,
            prompt="Read lantern-904.txt and report its exact contents.",
            instructions="Read the file.",
            work_dir=tmp_path,
            profile="local",
            reasoning_effort="low",
        )
    ]
    outputs = [event for event in events if event["type"] == "tool_output"]
    assert [event["ok"] for event in outputs] == [True, True]
    assert "LANTERN-904" in outputs[0]["result_text"]
    assert "LANTERN-904" in outputs[1]["result_text"]
    assert outputs[0]["action_id"] == outputs[1]["action_id"]
    assert ToolReceiptLog(events).unrecovered_failures([]) == []
    assert events[-1]["type"] == "done"


@pytest.mark.parametrize("recovered", [False, True])
@pytest.mark.parametrize("retry_provider", [False, True])
@pytest.mark.asyncio
async def test_two_file_task_only_completes_after_the_failed_file_is_recovered(
    monkeypatch,
    tmp_path,
    recovered,
    retry_provider,
):
    work = tmp_path / "artifacts"
    work.mkdir()
    record = task_bot_runtime.create_execution(
        session_id="proof",
        summary="Create report.txt and invoice.txt",
        intent="chat_task",
        repo_root=tmp_path,
    )
    eid = record["execution_id"]
    task_bot_runtime.update_execution(eid, state="executing", force=True, repo_root=tmp_path)
    # A previous attempt's proof must not override the current incomplete result.
    task_bot_runtime.attach_proof(eid, artifacts=[{"path": "old.txt"}], repo_root=tmp_path)
    report_args = {"path": "report.txt", "content": "report"}
    invoice_args = {"path": "invoice.txt", "content": "invoice"}
    attempts = 0

    async def _events(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        yield {"type": "model_runtime", "runtime": {"requested": {}, "active": {}}}
        for event in _call(f"report-{attempts}", report_args, True):
            if event["type"] == "tool_output":
                (work / "report.txt").write_text("report", encoding="utf-8")
            yield event
        if attempts == 1:
            for event in _call("invoice-failed", invoice_args, False):
                if event["type"] == "tool_output":
                    event["error"] = "Permission denied"
                    event["result_text"] = "Could not write invoice.txt"
                yield event
            if retry_provider:
                yield {"type": "error", "error": "provider connection lost", "retryable": True}
                return
        if recovered:
            for event in _call("invoice-retry", invoice_args, True):
                if event["type"] == "tool_output":
                    (work / "invoice.txt").write_text("invoice", encoding="utf-8")
                yield event
        yield {"type": "text", "text": "Created the files." if recovered else "Created report.txt; invoice.txt failed."}
        yield {"type": "done"}

    monkeypatch.setattr(runner, "run_agent_worker_events", _events)
    monkeypatch.setattr(runner, "validate_model_runtime_receipt", lambda *a, **k: {"ok": True})
    emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())
    await runner._run_agent_worker(
        SimpleNamespace(),
        execution_id=eid,
        prompt="Create report.txt and invoice.txt",
        specialist_id="coding",
        bot=SimpleNamespace(id="fixture", name="Fixture"),
        emitter=emitter,
        instructions="Create the files",
        repo_root=tmp_path,
        work_dir=work,
    )
    final = task_bot_runtime.get_execution(eid, tmp_path)
    assert final["state"] == ("completed" if recovered else "failed")
    assert final["proof_status"] == ("verified" if recovered else "failed")
    assert emitter.completed.await_count == int(recovered)
    assert emitter.failed.await_count == int(not recovered)
    assert (work / "invoice.txt").exists() == recovered
    assert attempts == (2 if retry_provider else 1)
    if not recovered:
        assert final["blocker"] == "unrecovered_tool_failure"
        assert "report.txt" in final["salvaged_artifacts"]
