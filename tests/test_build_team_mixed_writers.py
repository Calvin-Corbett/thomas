"""Offline proof that file writers honor exact per-assignment model choices."""

from __future__ import annotations

import asyncio
import io
import json
from types import SimpleNamespace

import pytest

from tests.test_build_agent_team import runtime  # noqa: F401
from thomas.core.config import ModelConfig
from thomas.core.events import AgentEvent
from thomas.forge.anvil import build_agent_team as team
from thomas.forge.anvil import build_claude_writer as claude_writer
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_mixed_file_writer_profiles_keep_exact_runtime_receipts(runtime, tmp_path, monkeypatch):
    runtime.models["selected"].model = "gpt-5.6-luna"
    runtime.models["selected"].api_key = "primary-token"
    runtime.models["anthropic_api"] = ModelConfig(
        name="anthropic_api", provider="anthropic", model="claude-sonnet-4-5", api_key="configured-key"
    )
    events, clients = [], []

    class Client:
        def __init__(self, config, **options):
            self.config, self.options = config, options
            clients.append(self)

        def runtime_trace(self):
            return {
                "active": {"model": self.config.model, "provider": self.config.provider, "profile": self.config.name},
                "failover_used": False,
            }

        async def close(self):
            pass

    class Loop:
        def __init__(self, config, llm, tools, **kwargs):
            self.llm, self.tools = llm, tools

        async def run(self, prompt, **kwargs):
            path = "a.txt" if self.llm.config.provider == "openai_codex" else "b.txt"
            assert (await self.tools.execute("fs.write_file", {"path": path, "content": self.llm.config.model})).ok
            yield AgentEvent.agent_done("Wrote assigned file", iterations=1, tool_calls=1)

    monkeypatch.setattr(team, "LLMClient", Client)
    monkeypatch.setattr(team, "AgentLoop", Loop)
    registry = ToolRegistry()
    register_filesystem_tools(registry, tmp_path)
    team.register_build_team(
        registry,
        config=runtime,
        model_config=runtime.models["selected"],
        emit=events.append,
        timeout=20,
        autonomy_level=3,
        tools_policy="auto",
        token_economy="balanced",
        protected_paths=[],
        can_write=True,
    )
    result = await registry.execute(
        "task.team",
        {
            "assignments": [
                {"title": "Luna", "instructions": "Write a", "path": "a.txt"},
                {
                    "title": "API",
                    "instructions": "Write b",
                    "path": "b.txt",
                    "model_choice": {"profile": "anthropic_api", "model_id": "claude-sonnet-4-5"},
                },
            ]
        },
    )
    assert result.ok
    assert {child["model_used"] for child in result.data["children"]} == {"gpt-5.6-luna", "claude-sonnet-4-5"}
    assert (tmp_path / "a.txt").read_text() == "gpt-5.6-luna"
    assert (tmp_path / "b.txt").read_text() == "claude-sonnet-4-5"
    assert len(clients) == 2 and all(client.options["failover_enabled"] is False for client in clients)


@pytest.mark.asyncio
async def test_unavailable_api_key_refuses_before_writing(runtime, tmp_path):
    runtime.models["unconnected"] = ModelConfig(name="unconnected", provider="anthropic", model="claude-sonnet")
    registry = ToolRegistry()
    register_filesystem_tools(registry, tmp_path)
    team.register_build_team(
        registry,
        config=runtime,
        model_config=runtime.models["selected"],
        emit=lambda event: None,
        timeout=20,
        autonomy_level=3,
        tools_policy="auto",
        token_economy="balanced",
        protected_paths=[],
        can_write=True,
    )
    result = await registry.execute(
        "task.team",
        {
            "assignments": [
                {
                    "title": "API",
                    "instructions": "Write b",
                    "path": "b.txt",
                    "model_choice": {"profile": "unconnected", "model_id": "claude-sonnet"},
                },
            ]
        },
    )
    assert not result.ok and "API key is unavailable" in result.error
    assert not (tmp_path / "b.txt").exists()


@pytest.mark.asyncio
async def test_mismatched_runtime_model_never_integrates(runtime, tmp_path, monkeypatch):
    runtime.models["selected"].api_key = "primary-token"

    class WrongModel:
        def __init__(self, config, **options):
            self.config = config

        def runtime_trace(self):
            return {
                "active": {"model": "gpt-other", "provider": self.config.provider, "profile": self.config.name},
                "failover_used": False,
            }

        async def close(self):
            pass

    class Loop:
        def __init__(self, config, llm, tools, **kwargs):
            self.tools = tools

        async def run(self, prompt, **kwargs):
            assert (await self.tools.execute("fs.write_file", {"path": "wrong.txt", "content": "candidate"})).ok
            yield AgentEvent.agent_done("done", iterations=1, tool_calls=1)

    monkeypatch.setattr(team, "LLMClient", WrongModel)
    monkeypatch.setattr(team, "AgentLoop", Loop)
    registry = ToolRegistry()
    register_filesystem_tools(registry, tmp_path)
    team.register_build_team(
        registry,
        config=runtime,
        model_config=runtime.models["selected"],
        emit=lambda event: None,
        timeout=20,
        autonomy_level=3,
        tools_policy="auto",
        token_economy="balanced",
        protected_paths=[],
        can_write=True,
    )
    result = await registry.execute(
        "task.team",
        {
            "assignments": [
                {"title": "Wrong", "instructions": "Write file", "path": "wrong.txt"},
            ]
        },
    )
    assert not result.ok
    assert not (tmp_path / "wrong.txt").exists()


@pytest.mark.asyncio
async def test_claude_writer_accepts_only_matching_model_and_assigned_path(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_writer, "os", SimpleNamespace(name="posix", environ={}))
    monkeypatch.setattr(claude_writer.shutil, "which", lambda name: "claude" if name == "claude" else None)
    written = []

    class Proc:
        def __init__(self, command, **kwargs):
            self.stdin = io.BytesIO()
            self.stdout = io.BytesIO(
                b'{"type":"system","subtype":"init","model":"claude-sonnet-4-5"}\n'
                + json.dumps(
                    {
                        "type": "result",
                        "is_error": False,
                        "result": json.dumps({"path": "mine.txt", "content": "hello"}),
                    }
                ).encode()
                + b"\n"
            )
            self.returncode = 0

        def poll(self):
            return self.returncode

        def wait(self):
            return self.returncode

    async def execute(name, args):
        written.append((name, args))
        return SimpleNamespace(ok=True)

    monkeypatch.setattr(claude_writer.subprocess, "Popen", Proc)
    workspace = SimpleNamespace(path="mine.txt", root=tmp_path)
    events = [
        event
        async for event in claude_writer.run_claude_file_writer(
            workspace,
            SimpleNamespace(execute=execute),
            "Write hello",
            model_id="claude:sonnet",
            deadline=asyncio.get_running_loop().time() + 5,
        )
    ]
    assert written == [("fs.write_file", {"path": "mine.txt", "content": "hello"})]
    assert [event["type"] for event in events] == ["model_runtime", "text"]
    assert events[0]["model_used"] == "claude-sonnet-4-5"
