"""A landed-code drain yields at a completed agent-tool-batch boundary."""

import asyncio
from pathlib import Path
from typing import Any

from aiohttp import web

from tests.test_evolve_agent_routes import _new_repo
from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, ModelConfig
from thomas.core.events import EventType
from thomas.core.llm import StreamEvent
from thomas.forge.anvil import forge_code_git, forge_code_store
from thomas.forge.anvil.dispatch_agent_loop import dispatch_via_agent_loop
from thomas.server.routes import evolve_agent_runtime
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry


class _BatchTool(Tool):
    name = "reload.batch"
    category = "test"
    description = "Finish a batch of work"
    parameters = {"type": "object", "properties": {}}

    def __init__(self, signal):
        self.signal = signal
        self.calls = 0

    async def execute(self, args):
        self.calls += 1
        self.signal.touch()
        return ToolResult(ok=True, data={"saved": True})


class _BatchLLM:
    def __init__(self):
        self.config = ModelConfig(name="local", provider="openai_compat", model="test", context_window=4096)
        self.calls = 0

    async def stream_chat(self, messages, tools):
        self.calls += 1
        yield StreamEvent(type="tool_call_end", data={"id": "first", "name": "reload.batch", "arguments": "{}"})
        yield StreamEvent(type="done", data={})


def test_reload_yields_after_a_completed_tool_batch(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    signal = tmp_path / "drain"
    monkeypatch.setenv("THOMAS_CODE_RELOAD_DRAIN_SIGNAL", str(signal))
    config = AppConfig(models={"local": ModelConfig(name="local", model="test")}, default_model="local")
    llm = _BatchLLM()
    tool = _BatchTool(signal)
    tools = ToolRegistry()
    tools.register(tool)
    agent = AgentLoop(config, llm, tools, conversation=[])

    async def run():
        return [event async for event in agent.run("Finish the batch", tools_policy="always", max_iterations=3)]

    events = asyncio.run(run())
    assert tool.calls == llm.calls == 1
    assert any(event.type == EventType.TOOL_RESULT for event in events)
    assert any(
        event.type == EventType.STATUS and "Yielding unfinished Build run" in str(event.data) for event in events
    )
    assert not any(event.type == EventType.AGENT_DONE for event in events)


def test_reload_yield_is_persisted_without_finishing_the_run(tmp_path: Path, monkeypatch: Any) -> None:
    repo = _new_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    transcript = repo / "reload-yield.txt"
    transcript.write_text(
        '{"fc":"meta","terminal":true,"yielded_for_reload":true,"text":"unfinished"}\n', encoding="utf-8"
    )
    monkeypatch.setattr(forge_code_git, "project_delta_since", lambda *_args: ["pending.txt"])

    class _EmptyStdout:
        async def read(self, _n: int = -1) -> bytes:
            return b""

    class _YieldedProcess:
        returncode = 75
        stdout = _EmptyStdout()

        async def wait(self) -> int:
            return 75

    async def _run() -> None:
        async def _confirmed_drain(_proc: Any, _transcript: Path) -> bool:
            return True

        monkeypatch.setattr(evolve_agent_runtime, "_drain", _confirmed_drain)
        result = await evolve_agent_runtime._drain_and_record(
            _YieldedProcess(), transcript, repo, conversation["id"], "test-model", {}, web.Application(), run_id="yield"
        )
        assert result["persistence_confirmed"] is True
        assert result["outcome"] == "reload_yielded", result
        assert result["ok"] is False
        saved = forge_code_store.load_conversation(repo, conversation["id"])
        assert saved["turns"][-1]["outcome"] == "reload_yielded"
        assert saved["turns"][-1]["changed_files"] == ["pending.txt"]

    asyncio.run(_run())


def test_reload_yield_during_verification_stays_unfinished(tmp_path: Path, monkeypatch: Any) -> None:
    repo = _new_repo(tmp_path)
    signal = tmp_path / "reload-drain"
    signal.touch()
    monkeypatch.setenv("THOMAS_CODE_RELOAD_DRAIN_SIGNAL", str(signal))
    monkeypatch.setattr(
        "thomas.forge.anvil.dispatch_agent_loop._clock_contract",
        lambda _cwd: {
            "active": True,
            "verdict": {},
            "items": [{"item_id": "finish", "checked": True, "satisfied": False, "detail": "unfinished"}],
        },
    )

    calls = 0

    def run_pass(_prompt: str, _cwd: str, _timeout: int, _emit: Any, **kwargs: Any) -> tuple[int, str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            (repo / "change.txt").write_text("pending\n", encoding="utf-8")
            return 0, "initial edit"
        kwargs["acceptance_sink"]["yielded_for_reload"] = True
        return 0, "unfinished"

    monkeypatch.setattr("thomas.forge.anvil.dispatch_agent_loop._run_agent_loop_pass", run_pass)
    result = dispatch_via_agent_loop(
        "finish the change",
        cwd=repo,
        verifier=lambda _cwd, _changed, _emit: (False, 1, "needs repair"),
        max_fix_iters=2,
        dry_run=False,
        token_check=lambda: True,
    )
    assert calls == 2, result
    assert result.ok is False
    assert result.returncode == 75
    assert "unfinished" in result.reason
