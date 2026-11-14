"""Direct Build delegates within its existing pass clock, with ordinary tool caps intact."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from tests.test_agent_loop_tool_exec import _LoopStub, _SpyRunner
from tests.test_build_agent_team import OfflineClient, runtime  # noqa: F401
from thomas.agent import loop_tool_exec
from thomas.core.events import AgentEvent
from thomas.forge.anvil import build_agent_team as team
from thomas.forge.anvil import dispatch_agent_loop as dispatch
from thomas.tools.base import Tool, ToolResult
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.registry import ToolRegistry


def registered(runtime, root, *, timeout):
    tools = ToolRegistry()
    register_filesystem_tools(tools, root)
    deadline = team.register_build_team(
        tools,
        config=runtime,
        model_config=runtime.models["selected"],
        emit=lambda _: None,
        timeout=timeout,
        autonomy_level=3,
        tools_policy="auto",
        token_economy="cheap",
        protected_paths=[],
        can_write=True,
    )
    assert deadline == tools.get("task.spawn")._deadline == tools.get("task.team")._deadline
    return tools, deadline


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", [60, 900])
@pytest.mark.parametrize("kind", ["review", "builder", "team"])
async def test_registered_helper_stream_uses_role_deadline(monkeypatch, runtime, tmp_path, budget, kind):
    observed = []
    real_owned = team.owned_events

    @asynccontextmanager
    async def observe(stream, *, deadline, name):
        observed.append((deadline, asyncio.get_running_loop().time()))
        async with real_owned(stream, deadline=deadline, name=name) as events:
            yield events

    class Loop:
        def __init__(self, config, client, tools, **kwargs):
            self.tools = tools

        async def run(self, *_args, **_kwargs):
            if self.tools.get("fs.write_file"):
                assert (await self.tools.execute("fs.write_file", {"path": "owned.txt", "content": "built"})).ok
            yield AgentEvent.agent_done("Reviewed or built assigned file", iterations=1, tool_calls=1)

    monkeypatch.setattr(team, "owned_events", observe)
    monkeypatch.setattr(team, "AgentLoop", Loop)
    tools, parent_deadline = registered(runtime, tmp_path, timeout=budget)
    brief = {"title": "helper", "instructions": "Complete the assigned work"}
    if kind != "review":
        brief.update(path="owned.txt", context_files=[])
    result = await tools.execute(
        "task.team" if kind == "team" else "task.spawn", {"assignments": [brief]} if kind == "team" else brief
    )
    assert result.ok, result.error
    assert len(observed) == 1
    child_deadline, observed_at = observed[0]
    assert child_deadline <= parent_deadline
    if kind == "review" and budget > 300:
        assert 299 < child_deadline - observed_at <= 300
    else:
        assert child_deadline == parent_deadline
        if budget > 300:
            assert child_deadline - observed_at > 300
    assert all(client.closed for client in OfflineClient.instances)


@pytest.mark.asyncio
@pytest.mark.parametrize("builder", [False, True])
async def test_exhausted_pass_refuses_helper_before_client_or_output(runtime, tmp_path, builder):
    tools, _ = registered(runtime, tmp_path, timeout=0.01)
    await asyncio.sleep(0.02)
    brief = {"title": "late helper", "instructions": "Do work"}
    if builder:
        brief["path"] = "owned.txt"
    result = await tools.execute("task.spawn", brief)
    assert not result.ok and "deadline" in result.error
    assert not OfflineClient.instances and not (tmp_path / "owned.txt").exists()


class Probe(Tool):
    parameters = {"type": "object", "properties": {}}

    def __init__(self, name):
        self.name = name
        self.entered = asyncio.Event()
        self.closed = asyncio.Event()
        self.release = asyncio.Event()

    async def execute(self, _args):
        self.entered.set()
        try:
            await self.release.wait()
            return ToolResult(ok=True, data="completed")
        finally:
            self.closed.set()


def executor(tmp_path, name, guarded):
    loop = _LoopStub(autonomy_level=3, runner=_SpyRunner() if guarded else None)
    loop.config.tools.sandbox_path = tmp_path
    loop.config.memory.root_path = tmp_path / "memory"
    loop._tool_timeout_s = 0.01
    loop.tools = ToolRegistry()
    probe = Probe(name)
    loop.tools.register(probe)
    return loop, probe


async def execute(loop, name):
    return [
        event
        async for event in loop_tool_exec.execute_tools(
            loop, [{"id": "one", "name": name, "arguments": "{}"}], 0, file_audit_module=None
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("guarded", [False, True])
@pytest.mark.parametrize("name", ["task.team", "task.spawn", "functions.task_spawn"])
async def test_registered_delegation_uses_absolute_deadline_in_both_wrappers(tmp_path, guarded, name):
    loop, probe = executor(tmp_path, "task.team" if name == "task.team" else "task.spawn", guarded)
    deadline = asyncio.get_running_loop().time() + 1
    loop._tool_deadlines = {probe.name: deadline}
    pending = asyncio.create_task(execute(loop, name))
    try:
        await asyncio.wait_for(probe.entered.wait(), timeout=1)
        await asyncio.sleep(0.03)  # Beyond the ordinary tool timeout, within the original parent clock.
        assert not pending.done()
        assert 0 < loop_tool_exec._tool_execution_timeout(loop, name) < 0.98
        probe.release.set()
        events = await asyncio.wait_for(pending, timeout=1)
        assert events[-1].data["ok"] and probe.closed.is_set()
    finally:
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("guarded", [False, True])
async def test_exhausted_delegate_deadline_never_invokes_tool(tmp_path, guarded):
    loop, probe = executor(tmp_path, "task.team", guarded)
    loop._tool_deadlines = {"task.team": asyncio.get_running_loop().time() - 1}
    events = await execute(loop, "task.team")
    assert not events[-1].data["ok"] and not probe.entered.is_set()
    assert "timed out" in events[-1].data["result"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("guarded", [False, True])
async def test_other_tools_keep_their_timeout_and_ask_user_exemption(tmp_path, guarded):
    loop, probe = executor(tmp_path, "ordinary.tool", guarded)
    loop._tool_deadlines = {"task.team": asyncio.get_running_loop().time() + 1000}
    assert loop_tool_exec._tool_execution_timeout(SimpleNamespace(_tool_timeout_s=600), "ordinary.tool") == 600
    assert loop_tool_exec._tool_execution_timeout(loop, "ask_user") is None
    events = await execute(loop, "ordinary.tool")
    assert not events[-1].data["ok"] and probe.entered.is_set() and probe.closed.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("guarded", [False, True])
async def test_cancelling_delegation_still_joins_tool(tmp_path, guarded):
    loop, probe = executor(tmp_path, "task.team", guarded)
    loop._tool_deadlines = {"task.team": asyncio.get_running_loop().time() + 1000}
    pending = asyncio.create_task(execute(loop, "task.team"))
    try:
        await asyncio.wait_for(probe.entered.wait(), timeout=1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert probe.closed.is_set()
    finally:
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_direct_build_lead_receives_only_registered_delegation_deadlines(monkeypatch, runtime, tmp_path):
    seen = []

    class Loop:
        def __init__(self, config, client, tools, **kwargs):
            self.tools = tools
            seen.append(self)

        async def run(self, *_args, **_kwargs):
            assert self._tool_deadlines == {
                name: self.tools.get(name)._deadline for name in ("task.spawn", "task.team")
            }
            yield AgentEvent.agent_done("No changes", iterations=1, tool_calls=0)

    monkeypatch.setattr("thomas.agent.loop.AgentLoop", Loop)
    rc, _ = await dispatch._agent_loop_pass_async(
        "Inspect this project",
        str(tmp_path),
        900,
        lambda _: None,
        profile="selected",
        oauth_access_token="fixture-token",
        allow_shell=False,
    )
    assert rc == 0 and len(seen) == 1
    assert all(client.closed for client in OfflineClient.instances)
