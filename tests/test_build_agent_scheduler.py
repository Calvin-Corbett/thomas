"""Offline product coordination checks; these do not prove live-model capacity."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from tests.test_build_agent_team import OfflineClient, runtime  # noqa: F401
from tests.test_task_spawn_policy import restricted
from thomas.core.events import AgentEvent
from thomas.forge.anvil import build_agent_team as team
from thomas.forge.anvil.build_agent_scheduler import BuildTeamScheduler
from thomas.server.chat_tool_policy import PolicyToolRegistryView
from thomas.tools.base import ToolResult
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.registry import ToolRegistry


def registry(runtime, tmp_path, events, *, timeout=30, can_write=True, protected=()):
    tools = ToolRegistry()
    register_filesystem_tools(tools, tmp_path)
    team.register_build_team(
        tools,
        config=runtime,
        model_config=runtime.models["selected"],
        emit=events.append,
        timeout=timeout,
        autonomy_level=3,
        tools_policy="normal",
        token_economy="normal",
        protected_paths=list(protected),
        can_write=can_write,
    )
    return tools


def assignments(count=3):
    return [
        {"title": f"Builder {i}", "instructions": f"Create file {i}", "path": f"parts/{i}.txt"} for i in range(count)
    ]


@pytest.mark.asyncio
async def test_team_forwards_explicit_bounded_context(runtime, tmp_path):
    tools = registry(runtime, tmp_path, [])
    tool = tools.get("task.team")
    jobs = assignments(2)
    jobs[0]["context_files"] = ["shared.txt"]
    parsed = tool._assignments({"assignments": jobs})
    assert parsed[0]["context_files"] == ["shared.txt"]
    assert "context_files" not in parsed[1]
    for bad in ("shared.txt", ["../escape"], [1], ["x"] * 101):
        jobs[0]["context_files"] = bad
        with pytest.raises(ValueError):
            tool._assignments({"assignments": jobs})


def receipts(tmp_path):
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in tmp_path.glob(".thomas/evolve/agent/team/team_*/team.json")
    ]


def test_thomas_state_stays_outside_the_project_a_builder_snapshots(runtime, tmp_path):
    for name in ("THOMAS_DATA_DIR", "THOMAS_HOME"):
        assert not Path(os.environ[name]).is_relative_to(tmp_path)


@pytest.mark.asyncio
async def test_registered_team_runs_100_offline_loops_with_shared_selected_model_admission(
    monkeypatch, runtime, tmp_path
):
    (tmp_path / "unmerged.txt").write_bytes(b"user edits\r\n")
    seen, reached = [], asyncio.Event()
    active = peak = 0

    class Loop:
        def __init__(self, config, client, tools, **kwargs):
            self.config, self.client, self.tools = config, client, tools

        async def run(self, _prompt, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            seen.append(self)
            if len(seen) == 100:
                reached.set()
            try:
                await reached.wait()
                assert self.client.config.model == "gpt-5.6-luna"
                assert self.client.config._openai_codex_token_ready
                assert self.client.options["failover_enabled"] is False
                assert self.client.options["fallback_configs"] == []
                assert self.config.tools.allow_shell is False
                assert self.tools.get("task.team") is None and self.tools.get("task.spawn") is None
                assert self.tools.get("shell.exec") is None
                assert (self.config.tools.sandbox_path / "unmerged.txt").read_bytes() == b"user edits\r\n"
                admission = self.client.options["request_admission"]
                ticket = await admission.acquire()
                try:
                    await asyncio.sleep(0.06)
                finally:
                    admission.release(ticket, status=200, complete=True)
                index = kwargs["intent_text"].rsplit(" ", 1)[-1]
                assert (await self.tools.execute("fs.write_file", {"path": f"parts/{index}.txt", "content": index})).ok
                yield AgentEvent.agent_done("Created assigned file", iterations=1, tool_calls=1)
            finally:
                active -= 1

    monkeypatch.setattr(team, "AgentLoop", Loop)
    events = []
    tools = registry(runtime, tmp_path, events, timeout=300)
    pending = asyncio.create_task(tools.execute("task.team", {"assignments": assignments(100)}))
    # One builder refused before run() means `reached` never comes, so a bare wait here would outlast the team.
    arrived = asyncio.create_task(reached.wait())
    await asyncio.wait({arrived, pending}, return_when=asyncio.FIRST_COMPLETED)
    arrived.cancel()
    assert reached.is_set(), pending.result().error
    assert not (await tools.execute("task.team", {"assignments": assignments(1)})).ok
    conflict = await tools.execute("task.spawn", assignments(1)[0])
    assert not conflict.ok and "already owns" in conflict.error
    result = await pending
    assert result.ok and result.data["integrated"] == 100
    assert peak == 100 and active == 0
    assert len({id(item.client.options["request_admission"]) for item in seen}) == 1
    admission = result.data["admission"]
    assert admission["admitted"] == admission["settled"] == 100
    assert 1 <= admission["peak_inflight"] <= 96
    assert admission["provider_peak_inflight"] >= admission["peak_inflight"]
    assert admission["reserved_interactive"] == 4
    assert admission["waiting"] == admission["inflight"] == 0 and admission["closed"]
    assert all(client.closed for client in OfflineClient.instances)
    assert [(tmp_path / f"parts/{i}.txt").read_text() for i in range(100)] == [str(i) for i in range(100)]
    ledger = receipts(tmp_path)[0]
    assert ledger["state"] == "completed"
    assert all(child["state"] == "integrated" and child["receipt"] for child in ledger["children"])
    assert len({event["agent_id"] for event in events if event.get("agent_id")}) == 100
    assert all(event.get("fc") != "final" for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["cancel", "deadline"])
async def test_team_stop_joins_children_keeps_candidates_and_never_applies(monkeypatch, runtime, tmp_path, stop):
    started, closed = asyncio.Event(), []
    seen = []

    class Loop:
        def __init__(self, config, client, tools, **kwargs):
            self.tools, self.client = tools, client

        async def run(self, _prompt, **kwargs):
            index = kwargs["intent_text"].rsplit(" ", 1)[-1]
            await self.tools.execute("fs.write_file", {"path": f"parts/{index}.txt", "content": "candidate"})
            seen.append(self)
            if len(seen) == 3:
                started.set()
            try:
                await asyncio.Event().wait()
                yield AgentEvent.agent_done("unreachable", iterations=1, tool_calls=1)
            finally:
                closed.append(index)

    monkeypatch.setattr(team, "AgentLoop", Loop)
    # This checks cleanup after started writes, not sub-second disk performance.
    tools = registry(runtime, tmp_path, [], timeout=3 if stop == "deadline" else 30)
    pending = asyncio.create_task(tools.execute("task.team", {"assignments": assignments()}))
    try:
        await asyncio.wait_for(started.wait(), timeout=10)
        if stop == "cancel":
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        else:
            ended = await asyncio.wait_for(pending, timeout=10)
            assert not ended.ok and "did not complete: TimeoutError;" in ended.error  # the bare error has no text
    finally:
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
    assert len(closed) == 3 and all(item.client.closed for item in seen)
    assert not (tmp_path / "parts").exists()
    assert len(list(tmp_path.glob(".thomas/evolve/agent/team/child_*/workspace/parts/*.txt"))) == 3
    ledger = receipts(tmp_path)[0]
    assert ledger["state"] == ("cancelled" if stop == "cancel" else "failed")
    assert all(child["state"] == "cancelled" for child in ledger["children"])
    assert ledger["admission"]["closed"]


@pytest.mark.asyncio
async def test_one_child_failure_does_not_hide_successes_or_apply_its_candidate(monkeypatch, runtime, tmp_path):
    class Loop:
        def __init__(self, config, client, tools, **kwargs):
            self.tools = tools

        async def run(self, _prompt, **kwargs):
            index = kwargs["intent_text"].rsplit(" ", 1)[-1]
            await self.tools.execute("fs.write_file", {"path": f"parts/{index}.txt", "content": index})
            if index == "1":
                raise RuntimeError("provider failed before completion")
            yield AgentEvent.agent_done("Created file", iterations=1, tool_calls=1)

    monkeypatch.setattr(team, "AgentLoop", Loop)
    events = []
    result = await registry(runtime, tmp_path, events).execute("task.team", {"assignments": assignments()})
    assert not result.ok and result.data["integrated"] == 2
    assert not (tmp_path / "parts/1.txt").exists()
    assert (tmp_path / "parts/0.txt").exists() and (tmp_path / "parts/2.txt").exists()
    assert [child["state"] for child in receipts(tmp_path)[0]["children"]] == ["integrated", "failed", "integrated"]
    assert any(event.get("is_error") and "provider failed" in event.get("text", "") for event in events)


@pytest.mark.asyncio
async def test_team_validates_whole_batch_and_is_hidden_under_added_policy(runtime, tmp_path):
    tools = registry(runtime, tmp_path, [])
    for jobs in (
        [],
        assignments(1) * 2,
        [{**assignments(1)[0], "path": "../escape.txt"}],
        [{**assignments(1)[0], "instructions": ""}],
        [{**assignments(1)[0], "path": "A.txt"}, {**assignments(1)[0], "path": "a.txt/child"}],
    ):
        assert not (await tools.execute("task.team", {"assignments": jobs})).ok
    assert not receipts(tmp_path) and not OfflineClient.instances
    wrapped = PolicyToolRegistryView(tools, restricted(tmp_path), base_root=tmp_path)
    assert wrapped.get("task.team") is None
    assert not (await wrapped.execute("task_team", {"assignments": assignments()})).ok
    assert registry(runtime, tmp_path, [], can_write=False).get("task.team") is None


@pytest.mark.asyncio
async def test_team_accepts_more_than_one_hundred_distinct_assignments(runtime, tmp_path):
    tool = registry(runtime, tmp_path, []).get("task.team")
    assert len(tool._assignments({"assignments": assignments(101)})) == 101


@pytest.mark.asyncio
async def test_failed_team_retries_only_unfinished_child(tmp_path):
    calls = []

    class Writer:
        async def execute_assigned(self, job, **_kwargs):
            calls.append(job["path"])
            if job["path"] == "1.txt" and calls.count("1.txt") == 1:
                return ToolResult(ok=False, error="temporary failure")
            (tmp_path / job["path"]).write_text(job["path"], encoding="utf-8")
            return ToolResult(ok=True, data="integrated")

    jobs = [{"title": str(i), "instructions": "write", "path": f"{i}.txt"} for i in range(2)]
    scheduler = BuildTeamScheduler(
        Writer(),
        project=tmp_path,
        model="luna",
        provider="test",
        emit=lambda _event: None,
        deadline=asyncio.get_running_loop().time() + 30,
    )
    assert not (await scheduler.execute({"assignments": jobs})).ok
    result = await scheduler.execute({"assignments": jobs})
    assert result.ok and result.data["integrated"] == 2
    assert calls == ["0.txt", "1.txt", "1.txt"]
    assert len(receipts(tmp_path)) == 1


@pytest.mark.asyncio
async def test_team_respects_parent_protected_paths_and_inflight_spawn(runtime, tmp_path):
    tools = registry(runtime, tmp_path, [], protected=["parts/0.txt"])
    result = await tools.execute("task.team", {"assignments": assignments(1)})
    assert not result.ok and not (tmp_path / "parts/0.txt").exists()
    assert not OfflineClient.instances


@pytest.mark.asyncio
async def test_team_and_existing_spawn_share_live_file_ownership(monkeypatch, runtime, tmp_path):
    started, release = asyncio.Event(), asyncio.Event()

    class Loop:
        def __init__(self, config, client, tools, **kwargs):
            self.tools = tools

        async def run(self, _prompt, **kwargs):
            started.set()
            await release.wait()
            await self.tools.execute("fs.write_file", {"path": "parts/0.txt", "content": "spawn result"})
            yield AgentEvent.agent_done("Created file", iterations=1, tool_calls=1)

    monkeypatch.setattr(team, "AgentLoop", Loop)
    tools = registry(runtime, tmp_path, [])
    spawn = asyncio.create_task(tools.execute("task.spawn", assignments(1)[0]))
    await started.wait()
    result = await tools.execute("task.team", {"assignments": assignments(1)})
    assert not result.ok and "already owns" in result.data["children"][0]["error"]
    assert len(OfflineClient.instances) == 1
    release.set()
    assert (await spawn).ok
    assert (tmp_path / "parts/0.txt").read_text() == "spawn result"
