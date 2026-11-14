"""Early closure must finish nested agent runs in the reader's task."""

import asyncio

from tests.test_agent_loop_rules_of_road import _WriteThenAnswerLLM, _WriteTool
from thomas.agent.loop import AgentLoop
from thomas.core import capture_context
from thomas.core.config import AppConfig, ModelConfig
from thomas.core.events import AgentEvent, EventType
from thomas.core.llm import StreamEvent
from thomas.server import worker_runtime
from thomas.server.app_keys import APP_CONFIG
from thomas.server.chat_delegation_runner_events import _close_worker_event_stream, _next_worker_event
from thomas.tools.registry import ToolRegistry


async def _bracketed_run(record):
    token = capture_context.set_capture_run("bracketed-run")
    try:
        yield AgentEvent(type=EventType.AGENT_ERROR, data={"error": "provider refused the request"})
        yield AgentEvent.text_delta("unread")
    finally:
        record.append("agent run closed")
        capture_context.reset(token)


def _real_loop(llm):
    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    tools = ToolRegistry()
    tools.register(_WriteTool())
    return AgentLoop(cfg, llm, tools, conversation=[])


class _RefusedFirstLLM:
    def __init__(self):
        self.config = ModelConfig(name="dummy", model="dummy", context_window=32768, max_tokens=64)

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        yield StreamEvent(type="error", data={"error": "provider refused the request"})


class _RefusedQualityRetryLLM(_WriteThenAnswerLLM):
    async def stream_chat(self, messages, tools):  # noqa: ANN001
        last_user = [message for message in messages if message.get("role") == "user"][-1]
        if str(last_user.get("content", "")).startswith("Quality gate failed"):
            yield StreamEvent(type="error", data={"error": "provider refused the request"})
        else:
            async for event in super().stream_chat(messages, tools):
                yield event


def test_agent_loop_run_closes_the_loop_generator_it_delegates_to(monkeypatch):
    record = []
    loop = AgentLoop.__new__(AgentLoop)
    loop._run_id = "bracketed-run"
    loop._session_id = "test-session"
    loop._run_plugin_hook = None
    monkeypatch.setattr("thomas.agent.loop._agent_loop_run", lambda *_args, **_kwargs: _bracketed_run(record))

    async def check():
        stream = loop.run("test")
        assert (await anext(stream)).type == EventType.AGENT_ERROR
        before = capture_context.cross_context_resets()
        await stream.aclose()
        after = capture_context.cross_context_resets()
        assert record == ["agent run closed"], "the inner finally has not run when aclose returned"
        assert capture_context.current() is None, "the run tag stayed set after closing the outer run"
        assert after == before, "the tag was reset later in another task"

    asyncio.run(check())


async def _close_real_run_at_refusal(loop, expected_starts):
    stream = loop.run("fix bug in app.py", tools_policy="always", job_type="coding")
    starts = 0
    async for event in stream:
        if event.type == EventType.AGENT_START:
            starts += 1
        if event.type == EventType.AGENT_ERROR and "provider refused the request" in str(event.data.get("error")):
            break
    else:
        raise AssertionError("the provider refusal was not yielded")
    assert starts == expected_starts
    before = capture_context.cross_context_resets()
    await stream.aclose()
    after = capture_context.cross_context_resets()
    assert capture_context.current() is None, "the run id stayed set after aclose returned"
    assert after == before, "the capture tag was reset from another task"


def test_closing_a_run_at_its_refused_model_call_clears_the_capture_tag(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    asyncio.run(_close_real_run_at_refusal(_real_loop(_RefusedFirstLLM()), expected_starts=1))


def test_closing_a_run_inside_its_quality_retry_closes_the_retry_too(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    asyncio.run(_close_real_run_at_refusal(_real_loop(_RefusedQualityRetryLLM()), expected_starts=2))


def test_the_worker_closes_the_agent_run_before_its_model_client(monkeypatch, tmp_path):
    record = []

    class QuietLLM:
        def __init__(self, config, **_kwargs):
            self.config = config

        def reset_runtime_trace(self):
            pass

        async def close(self):
            record.append("model client closed")

    async def worker_run(*_args, **_kwargs):
        try:
            yield AgentEvent(type=EventType.AGENT_ERROR, data={"error": "provider refused the request"})
            yield AgentEvent.text_delta("unread")
        finally:
            record.append("agent run closed")

    class BracketedAgent:
        def run(self, *_args, **_kwargs):
            return worker_run()

    monkeypatch.setattr(worker_runtime, "LLMClient", QuietLLM)
    monkeypatch.setattr(worker_runtime, "build_agent_loop", lambda *_args, **_kwargs: BracketedAgent())
    app = {APP_CONFIG: AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")}

    async def check():
        stream = worker_runtime.run_agent_worker_events(
            app, prompt="test", instructions="test", work_dir=tmp_path, profile="local", tools_enabled=False
        )
        errors = []
        while True:
            event = await _next_worker_event(stream, saw_event=True)
            assert event is not None, "the worker ended before forwarding the error"
            if event["type"] == "error":
                errors.append(event)
                break
        before = capture_context.cross_context_resets()
        await _close_worker_event_stream(stream)
        after = capture_context.cross_context_resets()
        assert len(errors) == 1
        assert record == ["agent run closed", "model client closed"], "the model client closed before the run"
        assert after == before, "closing the worker triggered a cross-task reset"

    asyncio.run(check())
