"""Offline integration of direct Build's visible read-only model helpers."""

from __future__ import annotations

import asyncio

import pytest

from thomas.agent import loop as loop_module
from thomas.core import config as config_module
from thomas.core import llm_client
from thomas.core.config import AppConfig, ModelConfig
from thomas.core.events import AgentEvent, EventType
from thomas.core.file_access import parse_file_access_level
from thomas.forge.anvil import build_agent_team as team
from thomas.forge.anvil import dispatch_agent_loop as dispatch
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.registry import ToolRegistry


class OfflineClient:
    instances = []

    def __init__(self, config, **kwargs):
        self.config = config
        self.options = kwargs
        self.closed = False
        self.instances.append(self)

    async def close(self):
        self.closed = True


@pytest.fixture
def runtime(monkeypatch, tmp_path, tmp_path_factory):
    # Outside the project: engine loops left by earlier tests write wherever these point, and a file appearing in the
    # project between a builder's two snapshots refuses that builder, correctly.
    state = tmp_path_factory.mktemp("thomas-state")
    monkeypatch.setenv("THOMAS_DATA_DIR", str(state / "data"))
    monkeypatch.setenv("THOMAS_HOME", str(state / "home"))
    cfg = AppConfig(
        models={
            "selected": ModelConfig(
                name="selected",
                provider="openai_codex",
                model="gpt-5.6-luna",
                reasoning_effort="high",
            )
        },
        default_model="selected",
    )
    cfg.tools.sandbox_root = str(tmp_path)
    cfg.models["selected"]._openai_codex_token_ready = True
    OfflineClient.instances = []
    monkeypatch.setattr(config_module, "load_config", lambda *_: cfg)
    monkeypatch.setattr(llm_client, "LLMClient", OfflineClient)
    monkeypatch.setattr(team, "LLMClient", OfflineClient)
    return cfg


@pytest.mark.asyncio
async def test_actual_build_registration_drives_two_bounded_reviews(monkeypatch, tmp_path, runtime):
    (tmp_path / "source.txt").write_text("real project source", encoding="utf-8")
    loops = []
    entered = asyncio.Event()
    active = 0
    peak = 0

    class Loop:
        def __init__(self, config, llm, tools, **kwargs):
            self.config, self.llm, self.tools = config, llm, tools
            self.kwargs = kwargs
            loops.append(self)

        async def run(self, prompt, **kwargs):
            nonlocal active, peak
            self.prompt, self.run_options = prompt, kwargs
            if self.tools.get("task.spawn"):
                description = self.tools.get("task.spawn").description
                assert "read-only" in description and "cannot edit" in description
                results = await asyncio.gather(
                    *[
                        self.tools.execute("task.spawn", {"title": "review", "instructions": f"Inspect source {i}"})
                        for i in range(2)
                    ]
                )
                assert all(result.ok and "real project source" in result.data for result in results)
                yield AgentEvent.agent_done("Lead finished", iterations=1, tool_calls=2)
                return
            active += 1
            peak = max(peak, active)
            if active == 2:
                entered.set()
            await entered.wait()
            try:
                for forbidden in (
                    "fs.write_file",
                    "shell.exec",
                    "check.run",
                    "image.generate",
                    "web.playtest",
                    "task.spawn",
                ):
                    assert self.tools.get(forbidden) is None, forbidden
                result = await self.tools.execute("fs.read_file", {"path": "source.txt"})
                assert result.ok
                yield AgentEvent.text_delta("Reading ")
                yield AgentEvent.text_delta("source.")
                yield AgentEvent.tool_result("read", "fs.read_file", result.to_content(), True, 1)
                yield AgentEvent.agent_done(result.to_content(), iterations=1, tool_calls=1)
            finally:
                active -= 1

    monkeypatch.setattr(loop_module, "AgentLoop", Loop)
    monkeypatch.setattr(team, "AgentLoop", Loop)
    events = []
    acceptance = {}
    rc, final = await dispatch._agent_loop_pass_async(
        "Build a small page",
        str(tmp_path),
        15,
        events.append,
        intent_text="Build a small page",
        profile="selected",
        allow_shell=False,
        guardrails="guarded",
        oauth_access_token="fixture-token",
        protected_paths=["keep.txt"],
        acceptance_sink=acceptance,
    )
    assert rc == 0 and final == "Lead finished" and peak == 2 and active == 0
    assert len(OfflineClient.instances) == 3 and all(client.closed for client in OfflineClient.instances)
    for client in OfflineClient.instances:
        assert client.config.model == "gpt-5.6-luna"
        assert client.config.reasoning_effort == ("high" if client is OfflineClient.instances[0] else "medium")
        if client is not OfflineClient.instances[0]:
            key = client.config._build_prompt_cache_key
            assert key.startswith("build-helper:read_only:gpt-5.6-luna:") and len(key) > len(
                "build-helper:read_only:gpt-5.6-luna:"
            )
        assert client.config.api_key == "fixture-token" and client.config._openai_codex_token_ready
        assert client.options["fallback_configs"] == []
        assert client.options["failover_enabled"] is False
        assert client.options["request_admission"].snapshot()["closed"]
    for child in loops[1:]:
        assert child.config.tools.allow_shell is False
        assert child.config.tools.file_access == parse_file_access_level("read_only")
        assert child.protected_paths == ["keep.txt"] and child.kwargs["max_parallel_tools"] == 4
        assert child._build_read_parallel_only is True
        assert "read-only source-review helper" in child._build_helper_role_text
        assert child.prompt == child.run_options["intent_text"]
        assert child.run_options["tools_policy"] == "auto"
        assert child.run_options["intent_text"].startswith("Inspect source")
    children = [event for event in events if event.get("agent_id")]
    assert len({event["agent_id"] for event in children}) == 2  # duplicate titles are still distinct
    assert all(event["agent_mode"] == "read_only" for event in children)
    assert any(event.get("fc") == "tool_result" and event["name"] == "review > fs.read_file" for event in children)
    assert not any(event.get("fc") in {"final", "acceptance"} for event in children)
    assert [event["text"] for event in events if event.get("fc") == "final"] == ["Lead finished"]
    assert (tmp_path / "source.txt").read_text(encoding="utf-8") == "real project source"


def registered(runtime, tmp_path, events, *, timeout=10):
    registry = ToolRegistry()
    register_filesystem_tools(registry, tmp_path)
    team.register_build_team(
        registry,
        config=runtime,
        model_config=runtime.models["selected"],
        emit=events.append,
        timeout=timeout,
        autonomy_level=3,
        tools_policy="auto",
        token_economy="optimal",
        protected_paths=[],
    )
    return registry


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", [EventType.AGENT_ERROR, EventType.AGENT_END, None])
async def test_failed_or_incomplete_children_cannot_report_success(monkeypatch, tmp_path, runtime, terminal):
    class Loop:
        def __init__(self, *_args, **_kwargs):
            pass

        async def run(self, *_args, **_kwargs):
            yield AgentEvent.text_delta("Checking source")
            if terminal:
                yield AgentEvent(terminal, {"error": "provider refused", "reason": "cancelled upstream"})

    monkeypatch.setattr(team, "AgentLoop", Loop)
    events = []
    result = await registered(runtime, tmp_path, events).execute(
        "task.spawn", {"title": "helper", "instructions": "Review"}
    )
    assert not result.ok and "helper failed" in result.error
    assert any(event.get("is_error") for event in events)
    assert not any(event["text"].endswith("helper finished") for event in events)
    assert OfflineClient.instances[0].closed


@pytest.mark.asyncio
async def test_review_deadline_and_parent_cancellation_close_child(monkeypatch, tmp_path, runtime):
    class LegacyAsyncTimeout(Exception):
        """Before 3.11 asyncio.TimeoutError was separate from builtin TimeoutError."""

    monkeypatch.delattr(asyncio, "timeout", raising=False)
    monkeypatch.delattr(asyncio, "TaskGroup", raising=False)
    monkeypatch.setattr(asyncio, "TimeoutError", LegacyAsyncTimeout)
    started = asyncio.Event()
    exited = asyncio.Event()

    class Loop:
        def __init__(self, *_args, **_kwargs):
            pass

        async def run(self, *_args, **_kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
                yield AgentEvent.text_delta("unreachable")
            finally:
                exited.set()

    monkeypatch.setattr(team, "AgentLoop", Loop)
    events = []
    brief = {"title": "helper", "instructions": "Review"}
    result = await registered(runtime, tmp_path, events, timeout=1.0).execute("task.spawn", brief)
    assert not result.ok and "deadline" in result.error
    assert started.is_set() and exited.is_set() and OfflineClient.instances[-1].closed
    started.clear()
    exited.clear()
    pending = asyncio.create_task(registered(runtime, tmp_path, events).execute("task.spawn", brief))
    await started.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert exited.is_set() and OfflineClient.instances[-1].closed
    assert any("helper cancelled" in event["text"] for event in events)


@pytest.mark.asyncio
async def test_real_agent_loops_execute_delegation_with_only_model_substituted(monkeypatch, tmp_path, runtime):
    import json

    from thomas.agent import acceptance_runtime, loop_completion
    from thomas.core.llm import StreamEvent

    (tmp_path / "source.txt").write_text("ORANGE EVIDENCE", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("THOMAS_TASK_CHECKLISTS", "0")
    monkeypatch.setattr(acceptance_runtime, "load_learned", lambda *_: [])
    monkeypatch.setattr(acceptance_runtime, "record_misses", lambda *_: None)
    monkeypatch.setattr(loop_completion, "evaluate_rules", lambda **_: {"passed": True, "checks": []})
    runtime.models["selected"].context_window = 65536
    runtime.models["selected"].max_tokens = 512

    class Model(OfflineClient):
        def __init__(self, *args, **kwargs):
            self.is_child = bool(self.instances)
            self.calls = 0
            self.receipts = []
            super().__init__(*args, **kwargs)

        async def stream_chat(self, messages, tools):
            self.calls += 1
            self.receipts.extend(message for message in messages if message.get("role") == "tool")
            if self.calls == 1:
                if self.is_child:
                    name, args = "fs.read_file", {"path": "source.txt"}
                    assert not any(tool["function"]["name"] == "task.spawn" for tool in tools)
                else:
                    name, args = (
                        "task.spawn",
                        {"title": "Source reviewer", "instructions": "Read source.txt and report its contents."},
                    )
                yield StreamEvent(type="tool_call_start", data={"id": "call", "name": name})
                yield StreamEvent(
                    type="tool_call_end", data={"id": "call", "name": name, "arguments": json.dumps(args)}
                )
            else:
                yield StreamEvent(type="token", data={"text": "source.txt contains ORANGE EVIDENCE."})
            yield StreamEvent(type="done", data={})

    monkeypatch.setattr(llm_client, "LLMClient", Model)
    monkeypatch.setattr(team, "LLMClient", Model)
    events = []
    rc, final = await dispatch._agent_loop_pass_async(
        "Inspect source.txt and explain what it contains.",
        str(tmp_path),
        15,
        events.append,
        intent_text="Inspect source.txt and explain what it contains.",
        profile="selected",
        allow_shell=False,
        guardrails="guarded",
        autonomy_level=3,
    )
    assert rc == 0 and "ORANGE EVIDENCE" in final
    assert len(OfflineClient.instances) == 2
    lead, child = OfflineClient.instances
    assert any("ORANGE EVIDENCE" in str(receipt) for receipt in lead.receipts)
    assert any("ORANGE EVIDENCE" in str(receipt) for receipt in child.receipts)
    assert all(client.closed for client in OfflineClient.instances)
    assert any(event.get("agent_id") and event.get("fc") == "tool_result" for event in events)
