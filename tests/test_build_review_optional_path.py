"""The actual lead executor preserves optional review paths and writer policy."""

from __future__ import annotations

import json

import pytest

from tests.test_agent_loop_tool_exec import _SpyRunner
from tests.test_build_agent_team import OfflineClient, runtime  # noqa: F401
from tests.test_task_spawn_policy import restricted
from thomas.agent import loop_tool_paths
from thomas.agent.loop import AgentLoop
from thomas.core.events import AgentEvent, EventType
from thomas.core.llm import StreamEvent
from thomas.forge.anvil import build_agent_team as team
from thomas.forge.anvil.forge_code_roles import ROLE_ENV
from thomas.server.chat_tool_policy import PolicyToolRegistryView
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.registry import ToolRegistry


class _Lead:
    def __init__(self, config, name, args):
        self.config, self.name, self.args = config, name, args
        self.called = False

    async def stream_chat(self, messages, tools):
        if not self.called:
            self.called = True
            yield StreamEvent(type="tool_call_start", data={"id": "helper", "name": self.name})
            yield StreamEvent(
                type="tool_call_end", data={"id": "helper", "name": self.name, "arguments": json.dumps(self.args)}
            )
        else:
            yield StreamEvent(type="token", data={"text": "Helper result received."})
        yield StreamEvent(type="done", data={})


class _RegisteringPolicyView(PolicyToolRegistryView):
    """Retain the real policy view while exposing the host registration seam."""

    def register(self, tool):
        self._base.register(tool)


async def _run(monkeypatch, runtime, tmp_path, args, *, guarded=False, policy=False, name="task.spawn", can_write=True):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("THOMAS_VERIFICATION_CONTRACT", "0")
    monkeypatch.setenv(ROLE_ENV, json.dumps({"builder": "gpt-5.6-luna", "reviewer": "gpt-5.6-sol"}))
    runtime.models["selected"].model = "gpt-5.6-sol"
    child_models = []
    allowed = tmp_path / "allowed"
    allowed.mkdir(exist_ok=True)
    (allowed / "inside.txt").write_text("inside", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("outside", encoding="utf-8")

    class Child:
        def __init__(self, config, client, tools, **kwargs):
            self.client, self.tools = client, tools

        async def run(self, prompt, **kwargs):
            child_models.append(self.client.config.model)
            writer = self.tools.get("fs.write_file")
            if writer is not None:
                assert self.client.config.model == "gpt-5.6-luna"
                assert (await self.tools.execute("fs.write_file", {"path": "owned.txt", "content": "built"})).ok
            else:
                assert self.client.config.model == "gpt-5.6-sol"
                assert (await self.tools.execute("fs.read_file", {"path": str(allowed / "inside.txt")})).ok
                if policy:
                    denied = await self.tools.execute("fs.read_file", {"path": str(tmp_path / "outside.txt")})
                    assert not denied.ok and "allowed_paths" in denied.error
            yield AgentEvent.agent_done("Assigned work complete", iterations=1, tool_calls=1)

    monkeypatch.setattr(team, "AgentLoop", Child)
    registry = ToolRegistry()
    register_filesystem_tools(registry, tmp_path)
    if policy:
        registry = _RegisteringPolicyView(registry, restricted(allowed), base_root=tmp_path)
    team.register_build_team(
        registry,
        config=runtime,
        model_config=runtime.models["selected"],
        emit=lambda _: None,
        timeout=10,
        autonomy_level=3,
        tools_policy="always",
        token_economy="normal",
        protected_paths=["keep.txt"],
        can_write=can_write,
    )
    lead = AgentLoop(
        runtime,
        _Lead(
            runtime.models["selected"],
            name,
            {"title": "Review builder title", "instructions": "Inspect or build the assigned file", **args},
        ),
        registry,
        conversation=[],
    )
    lead._guarded_tool_runner = _SpyRunner() if guarded else None
    lead.protected_paths = ["keep.txt"]
    events = [event async for event in lead.run("Delegate this project task", tools_policy="always", max_iterations=2)]
    result = next(event for event in events if event.type == EventType.TOOL_RESULT)
    assert all(client.closed for client in OfflineClient.instances)
    return result, child_models


@pytest.mark.asyncio
@pytest.mark.parametrize("guarded", [False, True])
@pytest.mark.parametrize("args", [{}, {"path": ""}])
@pytest.mark.parametrize("name", ["task.spawn", "functions.task_spawn"])
async def test_omitted_or_empty_path_uses_saved_reviewer(monkeypatch, runtime, tmp_path, guarded, args, name):
    result, models = await _run(monkeypatch, runtime, tmp_path, args, guarded=guarded, name=name)
    assert result.data["ok"], result.data["result_text"]
    assert models == ["gpt-5.6-sol"]
    assert not (tmp_path / "owned.txt").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("guarded", [False, True])
async def test_nonempty_path_selects_builder_despite_review_title(monkeypatch, runtime, tmp_path, guarded):
    result, models = await _run(monkeypatch, runtime, tmp_path, {"path": "owned.txt"}, guarded=guarded)
    assert result.data["ok"], result.data["result_text"]
    assert models == ["gpt-5.6-luna"]
    assert (tmp_path / "owned.txt").read_text() == "built"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["   ", "\t", ".", "../escape.txt", "keep.txt", None, False, []])
async def test_invalid_or_fenced_path_never_becomes_review(monkeypatch, runtime, tmp_path, path):
    result, models = await _run(monkeypatch, runtime, tmp_path, {"path": path})
    assert not result.data["ok"] and not models
    assert not (tmp_path / "keep.txt").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("guarded", [False, True])
@pytest.mark.parametrize("path", ["", "owned.txt"])
async def test_policy_wrapper_keeps_metadata_and_read_write_authority(monkeypatch, runtime, tmp_path, guarded, path):
    result, models = await _run(
        monkeypatch, runtime, tmp_path, {"path": path}, guarded=guarded, policy=True, name="functions.task_spawn"
    )
    assert result.data["ok"] is (path == ""), result.data["result_text"]
    assert models == (["gpt-5.6-sol"] if path == "" else [])
    assert not (tmp_path / "owned.txt").exists()


@pytest.mark.asyncio
async def test_readonly_run_still_refuses_real_builder_path(monkeypatch, runtime, tmp_path):
    result, models = await _run(monkeypatch, runtime, tmp_path, {"path": "owned.txt"}, can_write=False)
    assert not result.data["ok"] and not models


def test_other_empty_paths_and_required_path_schemas_keep_existing_validation():
    arguments = {"path": ""}
    assert loop_tool_paths._sanitize_write_tool_path(arguments) == (".", None)
    assert arguments == {"path": "."}
    registry = ToolRegistry()
    from thomas.tools.base import Tool

    class RequiredPath(Tool):
        name = "required.path"
        optional_empty_path_keys = ("path",)
        parameters = {"properties": {"path": {"type": "string"}}, "required": ["path"]}

    registry.register(RequiredPath())
    assert loop_tool_paths._optional_empty_path_keys(registry, "required.path") == frozenset()
