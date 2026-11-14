"""Real worker event shapes remain truthful when a Build agent delegates."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from tests.test_agent_worker_parity import _app_with_model, _FakeLLM
from thomas.core.events import AgentEvent, EventType
from thomas.server import agent_spawn_tool, worker_runtime
from thomas.server.chat_delegation_build_transcript import forge_line


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    lines: list[dict] = []
    monkeypatch.setattr(agent_spawn_tool, "record_line", lambda _execution, line: lines.append(json.loads(line)))
    return lines


def worker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, events: list[AgentEvent]):
    """Use the production worker adapter, with only paid execution substituted."""

    class Loop:
        def __init__(self, *_args, **_kwargs):
            pass

        async def run(self, *_args, **_kwargs):
            for event in events:
                yield event

    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("THOMAS_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(worker_runtime, "LLMClient", _FakeLLM)
    monkeypatch.setattr(worker_runtime, "AgentLoop", Loop)
    monkeypatch.setattr(worker_runtime, "_resolve_profile", lambda *_args: "local")

    async def run_child(_title: str, instructions: str):
        async for event in worker_runtime.run_agent_worker_events(
            _app_with_model("fixture", "stub", "local"),
            prompt=instructions,
            instructions=instructions,
            work_dir=tmp_path,
            profile="local",
            tools_enabled=False,
            memory_enabled=False,
            can_spawn=False,
        ):
            yield event

    return run_child


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", [EventType.AGENT_ERROR, EventType.AGENT_END])
async def test_yielded_terminal_errors_fail_the_child_result(monkeypatch, tmp_path, recorded, terminal):
    run_child = worker(
        monkeypatch,
        tmp_path,
        [
            AgentEvent.text_delta("Started the page. "),
            AgentEvent(terminal, {"error": "provider failed", "reason": "provider failed"}),
        ],
    )
    result = await agent_spawn_tool.SpawnAgentTool(execution_id="parent", run_child=run_child).execute(
        {"title": "about page", "instructions": "Write about.html"}
    )
    assert result.ok is False
    assert "provider failed" in result.error
    assert "about page" in result.error
    assert any(line.get("fc") == "error" and "about page" in line["text"] for line in recorded)
    assert not any(line.get("text") == "about page finished" for line in recorded)


@pytest.mark.asyncio
async def test_child_stream_end_without_terminal_is_not_accepted(monkeypatch, tmp_path, recorded):
    run_child = worker(monkeypatch, tmp_path, [AgentEvent.text_delta("Partial work")])
    result = await agent_spawn_tool.SpawnAgentTool(execution_id="parent", run_child=run_child).execute(
        {"title": "about page", "instructions": "Write about.html"}
    )
    assert result.ok is False
    assert "without a terminal result" in result.error
    assert not any(line.get("text") == "about page finished" for line in recorded)


@pytest.mark.asyncio
async def test_worker_tool_failure_and_recovery_remain_visible(monkeypatch, tmp_path, recorded):
    run_child = worker(
        monkeypatch,
        tmp_path,
        [
            AgentEvent.tool_call_start("first", "fs.write_file"),
            AgentEvent.tool_result("first", "fs.write_file", "Permission denied", False, 1),
            AgentEvent.tool_call_start("retry", "fs.write_file"),
            AgentEvent.tool_result("retry", "fs.write_file", "Wrote about.html", True, 1),
            AgentEvent.agent_done("Wrote about.html", iterations=1, tool_calls=2),
        ],
    )
    result = await agent_spawn_tool.SpawnAgentTool(execution_id="parent", run_child=run_child).execute(
        {"title": "about page", "instructions": "Write about.html"}
    )
    assert result.ok is True
    assert result.data == "Wrote about.html"
    tool_results = [line for line in recorded if line.get("fc") == "tool_result"]
    assert [(line.get("text"), line["is_error"]) for line in tool_results] == [
        ("Permission denied", True),
        ("Wrote about.html", False),
    ]
    assert all(line["name"] == "about page > fs.write_file" for line in tool_results)


@pytest.mark.asyncio
async def test_worker_error_detail_survives_without_result_text(monkeypatch, tmp_path):
    run_child = worker(
        monkeypatch,
        tmp_path,
        [
            AgentEvent(EventType.TOOL_RESULT, {"tool_name": "shell.exec", "ok": False, "error": "process refused"}),
            AgentEvent.agent_done("The command failed", iterations=1, tool_calls=1),
        ],
    )
    events = [event async for event in run_child("helper", "Run a command")]
    output = next(event for event in events if event["type"] == "tool_output")
    translated = json.loads(forge_line(output))
    assert translated["text"] == "process refused"
    assert translated["is_error"] is True


@pytest.mark.parametrize(
    "payload,expected_text,failed",
    [
        ({"result_text": "exit 1", "ok": False, "error": "permission denied"}, "exit 1\npermission denied", True),
        ({"result_text": "permission denied", "ok": False, "error": "permission denied"}, "permission denied", True),
        ({"result_text": "result", "ok": False}, "result", True),
        ({"text": "legacy result", "is_error": True}, "legacy result", True),
        ({"output": "legacy success", "is_error": False}, "legacy success", False),
    ],
)
def test_tool_results_preserve_native_and_legacy_diagnostics(payload, expected_text, failed):
    translated = json.loads(forge_line({"type": "tool_output", "name": "shell.exec", **payload}))
    assert translated["text"] == expected_text
    assert translated["is_error"] is failed


@pytest.mark.asyncio
async def test_cancellation_propagates_without_claiming_the_child_finished(recorded):
    async def cancelled(_title: str, _instructions: str):
        yield {"type": "progress", "text": "Starting"}
        raise asyncio.CancelledError

    tool = agent_spawn_tool.SpawnAgentTool(execution_id="parent", run_child=cancelled)
    with pytest.raises(asyncio.CancelledError):
        await tool.execute({"title": "helper", "instructions": "Build something"})
    assert not any(line.get("text") == "helper finished" for line in recorded)


def test_child_limits_do_not_become_the_leads_refusal(tmp_path):
    from thomas.forge.anvil import dispatch_agent_loop as dispatch

    def runner(_prompt, _cwd, _timeout, emit):
        emit({"fc": "say", "agent_id": "reviewer", "text": "I cannot edit files in this environment."})
        (tmp_path / "index.html").write_text("<h1>Built by lead</h1>", encoding="utf-8")
        emit({"fc": "final", "text": "Built index.html."})
        return 0, "Built index.html."

    result = dispatch.dispatch_via_agent_loop(
        "Build index.html",
        cwd=tmp_path,
        dry_run=False,
        runner=runner,
        verify=False,
        token_check=lambda: True,
        allow_without_history=True,
    )
    assert result.ok and "index.html" in result.changed_files
