"""Regression for bc4c642a: first-call memory, library context, and acceptance guidance were lost."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.core.llm import StreamEvent
from thomas.library import ResearchLibrary, default_library_root
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry

PROMPT = "Explain HTTP retry patterns"
MEMORY_SENTENCE = "The saved retry advice recommends bounded backoff."
TITLE = "HTTP Retry Patterns"


class _NoopTool(Tool):
    name = "test.noop"
    category = "test"
    description = "Does nothing successfully."
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args):  # noqa: ANN001
        return ToolResult(ok=True, data={})


class _ScriptedModel:
    def __init__(self, steps: list[str]) -> None:
        self.config = ModelConfig(name="dummy", model="dummy", context_window=32768, max_tokens=256)
        self.steps = iter(steps)
        self.calls: list[list[dict]] = []

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        self.calls.append([dict(m) for m in messages])
        step = next(self.steps)
        if step == "tool":
            tool_id = f"noop_{len(self.calls)}"
            yield StreamEvent(type="tool_call_start", data={"id": tool_id, "name": "test.noop"})
            yield StreamEvent(
                type="tool_call_end",
                data={"id": tool_id, "name": "test.noop", "arguments": "{}"},
            )
        else:
            yield StreamEvent(type="token", data={"text": "Here is the answer."})
        yield StreamEvent(type="done", data={})


class _Memory:
    started = True

    def __init__(self) -> None:
        self.queries: list[str] = []

    def retrieve(self, *, query, thread, budget, mode):  # noqa: ANN001
        self.queries.append(query)
        return SimpleNamespace(text=MEMORY_SENTENCE)

    def add_event(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return 1


@pytest.fixture
def workspace(tmp_path, monkeypatch):  # noqa: ANN001
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("THOMAS_LIBRARY_ENABLED", "1")
    monkeypatch.setenv("THOMAS_LIBRARY_AUTO_CAPTURE_RESEARCH", "0")
    monkeypatch.delenv("THOMAS_VERIFICATION_CONTRACT", raising=False)
    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path / "runtime")),
    )
    library = ResearchLibrary(default_library_root(cfg))
    library.add_entry(
        title=TITLE,
        category="research",
        summary="Reference guidance for HTTP retries.",
        source="local",
        tags=["http", "retry", "patterns"],
        content="Use bounded backoff for transient failures.",
    )
    return cfg


def _agent(cfg: AppConfig, steps: list[str]) -> tuple[AgentLoop, _ScriptedModel, _Memory]:
    model = _ScriptedModel(steps)
    memory = _Memory()
    tools = ToolRegistry()
    tools.register(_NoopTool())
    return AgentLoop(cfg, model, tools, conversation=[], memory=memory, thread_id="memory-test"), model, memory


def _run(agent: AgentLoop) -> None:
    async def collect() -> None:
        async for _ in agent.run(PROMPT, tools_policy="always"):
            pass

    asyncio.run(collect())


def _system(messages: list[dict]) -> str:
    return " ".join(str(m.get("content") or "") for m in messages if m.get("role") == "system")


def test_first_call_receives_retrieved_memory_and_library(workspace: AppConfig) -> None:
    agent, model, memory = _agent(workspace, ["tool", "answer"])
    _run(agent)

    assert len(model.calls) == 2
    assert memory.queries == [PROMPT]
    first_system = _system(model.calls[0])
    assert MEMORY_SENTENCE in first_system
    assert "<library_context>" in first_system
    assert TITLE in first_system


def test_later_calls_do_not_receive_the_turn_context(workspace: AppConfig) -> None:
    agent, model, _ = _agent(workspace, ["tool", "tool", "answer"])
    _run(agent)

    assert len(model.calls) == 3
    for messages in model.calls[1:]:
        for message in messages:
            content = str(message.get("content") or "")
            assert MEMORY_SENTENCE not in content
            assert "<library_context>" not in content
            assert TITLE not in content


def test_each_new_run_receives_its_own_first_call_context(workspace: AppConfig) -> None:
    agent, model, memory = _agent(workspace, ["answer", "answer"])
    _run(agent)
    assert len(model.calls) == 1
    _run(agent)

    assert len(model.calls) == 2
    assert memory.queries == [PROMPT, PROMPT]
    for messages in model.calls:
        system = _system(messages)
        assert MEMORY_SENTENCE in system
        assert TITLE in system
