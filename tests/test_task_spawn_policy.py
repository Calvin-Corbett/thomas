"""Delegation remains available without widening inherited tool authority."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from tests.test_agent_worker_parity import _app_with_model, _FakeLLM
from thomas.core.events import AgentEvent
from thomas.forge.anvil.build_agent_team import review_tools
from thomas.server import app_helpers, worker_runtime
from thomas.server.chat_tool_policy import PolicyToolRegistryView, tool_policy_from_payload
from thomas.tools.base import Tool, ToolResult
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.registry import ToolRegistry
from thomas.tools.shell import register_shell_tools
from thomas.tools.task_spawn import SpawnAgentTool


def restricted(root):
    return tool_policy_from_payload(
        {
            "allow_shell": False,
            "allow_file_write": False,
            "allow_network": False,
            "allow_browser": False,
            "allow_channels": False,
            "allow_git": False,
            "require_command_approval": True,
            "allowed_paths": [str(root)],
            "blocked_commands": ["remove-item"],
            "tool_timeout_s": 15,
            "max_parallel_tools": 1,
        }
    )


@pytest.mark.asyncio
async def test_review_proxies_retain_parent_argument_policy_even_through_aliases(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "inside.txt").write_text("inside", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    parent = ToolRegistry()
    register_filesystem_tools(parent, tmp_path)
    policy = restricted(allowed)
    view = PolicyToolRegistryView(parent, policy, base_root=tmp_path)
    child = review_tools(view)
    assert (await child.execute("functions.fs.read_file", {"path": str(allowed / "inside.txt")})).ok
    denied = await child.execute("fs_read_file", {"path": str(outside)})
    assert not denied.ok and "allowed_paths" in denied.error
    # Looking up a proxy directly cannot bypass the parent's argument checks.
    assert not (await child.get("fs.read_file").execute({"path": str(outside)})).ok
    assert child.get("fs.write_file") is None
    assert child.get("task.spawn") is None
    assert not (await child.execute("fs_write_file", {"path": str(allowed / "new.txt"), "content": "bad"})).ok
    assert not (allowed / "new.txt").exists()
    assert view.policy is policy


@pytest.mark.asyncio
async def test_spawn_is_neutral_but_unknown_tools_still_fail_closed(tmp_path):
    async def child(_child_id, _title, _instructions):
        yield {"type": "text", "text": "review complete"}

    class Unknown(Tool):
        name = "unknown.action"

        async def execute(self, _args):
            return ToolResult(ok=True)

    base = ToolRegistry()
    base.register(SpawnAgentTool(run_child=child, record_event=lambda *_: None))
    base.register(Unknown())
    view = PolicyToolRegistryView(base, restricted(tmp_path), base_root=tmp_path)
    assert view.get("functions.task.spawn") is not None
    assert view.get("unknown.action") is None
    result = await view.execute("task_spawn", {"title": "review", "instructions": "Inspect source"})
    assert result.ok and result.data == "review complete"


@pytest.mark.asyncio
async def test_server_worker_children_keep_actual_parent_policy(monkeypatch, tmp_path):
    policy = restricted(tmp_path)
    (tmp_path / "source.txt").write_text("source", encoding="utf-8")
    observed = []

    def tools(_config):
        registry = ToolRegistry()
        register_filesystem_tools(registry, tmp_path)
        register_shell_tools(registry, tmp_path, 10, allowed=True)
        return registry

    class Loop:
        def __init__(self, _config, _llm, registry, **kwargs):
            self.tools = registry
            observed.append((registry, kwargs))

        async def run(self, _prompt, **_kwargs):
            assert self.tools.get("fs.write_file") is None
            assert self.tools.get("shell.exec") is None
            assert (await self.tools.execute("fs.read_file", {"path": str(tmp_path / "source.txt")})).ok
            if self.tools.get("task.spawn"):
                result = await self.tools.execute("task.spawn", {"title": "review", "instructions": "Read source"})
                assert result.ok
            yield AgentEvent.agent_done("review complete", iterations=1, tool_calls=1)

    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("THOMAS_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(app_helpers, "_build_tools", tools)
    monkeypatch.setattr(worker_runtime, "LLMClient", _FakeLLM)
    monkeypatch.setattr(worker_runtime, "AgentLoop", Loop)
    monkeypatch.setattr(worker_runtime, "_resolve_profile", lambda *_: "local")
    events = [
        event
        async for event in worker_runtime.run_agent_worker_events(
            _app_with_model("fixture", "luna-fixture", "local"),
            prompt="Review source",
            instructions="Review source",
            work_dir=tmp_path,
            profile="local",
            memory_enabled=False,
            runtime_policy={"tools": asdict(policy)},
        )
    ]
    assert any(event["type"] == "done" for event in events)
    assert len(observed) == 2
    assert observed[1][0].get("task.spawn") is None
    for registry, kwargs in observed:
        assert registry.policy == policy
        assert kwargs["tool_timeout_s"] == 15
        assert kwargs["max_parallel_tools"] == 1
