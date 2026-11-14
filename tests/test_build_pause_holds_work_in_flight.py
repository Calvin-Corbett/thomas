"""A pause gives its time back to work already running, ends only when you resume, and keeps what you told the lead.

Review findings on the Build run controls (thomas/forge/anvil/run_control.py), 2026-10-29:

* The pass clock stopped, but every helper and team call already running held a deadline fixed when it started: a
  reviewer's 300 s cap, a builder's pass deadline, the lead's task.spawn / task.team wait, the team's own wait. A
  pause longer than the time they had left killed them mid-pause ("read_only helper deadline reached before
  completion"). Each now waits on a :class:`HeldDeadline` that a pause moves out while it lasts.
* A holder cancelled while you still had the run paused ended the pause: ``resumed`` was written and the pass clock
  restarted with the flag still set. Only the flag going away ends one now.
* A message the lead read in one pass was gone from every later pass, which starts from an empty conversation and
  the original goal, while the screen showed it as read. Every later pass's prompt now carries it.
"""

from __future__ import annotations

import asyncio
import queue
from pathlib import Path
from typing import Any

import pytest

from tests.test_build_agent_team import OfflineClient, runtime  # noqa: F401
from tests.test_build_helper_deadlines import execute, executor
from thomas.core.events import AgentEvent
from thomas.forge.anvil import build_agent_team as team
from thomas.forge.anvil import dispatch_agent_loop as dispatch
from thomas.forge.anvil import run_control
from thomas.forge.anvil.bridge_prompts import pin_your_messages
from thomas.forge.anvil.build_team_tasks import owned_events
from thomas.forge.anvil.run_control import HeldDeadline, PassClock, RunControl
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.registry import ToolRegistry


@pytest.fixture
def fast_hold(monkeypatch):
    monkeypatch.setattr(run_control, "HOLD_POLL_S", 0.02)


def _resume_after(control: RunControl, seconds: float) -> asyncio.Task[None]:
    async def resume() -> None:
        await asyncio.sleep(seconds)
        run_control.set_paused(control.directory, False)

    return asyncio.create_task(resume())


@pytest.mark.asyncio
async def test_a_held_deadline_stands_still_while_held_and_keeps_the_time_it_had(fast_hold):
    clock = PassClock()
    loop = asyncio.get_running_loop()
    assert HeldDeadline(123.0)() == 123.0  # no clock: the fixed deadline it was given
    due = HeldDeadline(loop.time() + 0.3, clock)
    clock.hold()
    await asyncio.sleep(0.45)  # past the deadline, but held
    assert due() - loop.time() >= run_control.HOLD_POLL_S * 0.9
    clock.release()
    left = due() - loop.time()
    assert 0.15 < left < 0.3 + 1e-6  # the 0.3 s it had when the hold began (one clock tick reads as no time)


@pytest.mark.asyncio
async def test_a_stream_already_waiting_survives_a_pause_longer_than_its_deadline(tmp_path, fast_hold):
    control = RunControl(tmp_path / "run", emit=lambda _e: None)
    clock = control.new_pass_clock()
    run_control.set_paused(control.directory, True)

    async def helper_stream():
        yield "read the files"
        await control.hold()  # you paused: the helper holds at its next step, for longer than it has left
        yield "reported"

    resumer = _resume_after(control, 1.0)
    deadline = HeldDeadline(asyncio.get_running_loop().time() + 0.4, clock)
    async with owned_events(helper_stream(), deadline=deadline, name="t") as events:
        seen = [event async for event in events]
    await resumer
    assert seen == ["read the files", "reported"]

    # A fixed deadline still ends a stream that goes past it.
    async def slow():
        await asyncio.sleep(0.3)
        yield "late"

    with pytest.raises(asyncio.TimeoutError):
        async with owned_events(slow(), deadline=asyncio.get_running_loop().time() + 0.05, name="t") as events:
            [event async for event in events]


def _registered(runtime, root: Path, control: RunControl, *, timeout: float) -> ToolRegistry:  # noqa: F811
    tools = ToolRegistry()
    register_filesystem_tools(tools, root)
    team.register_build_team(
        tools,
        config=runtime,
        model_config=runtime.models["selected"],
        emit=lambda _e: None,
        timeout=timeout,
        autonomy_level=3,
        tools_policy="auto",
        token_economy="cheap",
        protected_paths=[],
        can_write=True,
        control=control,
    )
    return tools


@pytest.mark.asyncio
async def test_a_pause_longer_than_a_reviewers_cap_does_not_kill_it(monkeypatch, runtime, tmp_path, fast_hold):  # noqa: F811
    monkeypatch.setattr(team, "_REVIEW_CAP_S", 0.4)  # the 300 s read-only cap, scaled down
    control = RunControl(tmp_path / "control", emit=lambda _e: None)
    control.new_pass_clock()

    class Loop:
        def __init__(self, config, client, tools, **kwargs):
            self.tools = tools

        async def run(self, *_args, **_kwargs):
            run_control.set_paused(control.directory, True)
            await self.run_hold(1)  # held for 1 s, past the 0.4 s it had
            yield AgentEvent.agent_done("Reviewed after the pause", iterations=1, tool_calls=0)

    monkeypatch.setattr(team, "AgentLoop", Loop)
    tools = _registered(runtime, tmp_path, control, timeout=900)
    resumer = _resume_after(control, 1.0)
    result = await tools.execute("task.spawn", {"title": "Reviewer", "instructions": "Inspect it"})
    await resumer
    assert result.ok, result.error
    assert "Reviewed after the pause" in str(result.data)


@pytest.mark.asyncio
async def test_a_pause_longer_than_the_pass_does_not_kill_a_team_builder(monkeypatch, runtime, tmp_path, fast_hold):  # noqa: F811
    control = RunControl(tmp_path / "control", emit=lambda _e: None)
    clock = control.new_pass_clock()

    class Loop:
        def __init__(self, config, client, tools, **kwargs):
            self.tools = tools

        async def run(self, *_args, **_kwargs):
            assert (await self.tools.execute("fs.write_file", {"path": "owned.txt", "content": "built"})).ok
            run_control.set_paused(control.directory, True)
            await self.run_hold(1)  # held past the whole 0.6 s pass deadline the builder and the team wait on
            yield AgentEvent.agent_done("Built the assigned file", iterations=1, tool_calls=1)

    monkeypatch.setattr(team, "AgentLoop", Loop)
    tools = _registered(runtime, tmp_path, control, timeout=0.6)
    token = run_control.bind_pass_clock(clock)  # what _agent_loop_pass_async does for the pass
    try:
        resumer = _resume_after(control, 1.4)
        brief = {"title": "Builder", "instructions": "Write it", "path": "owned.txt", "context_files": []}
        result = await tools.execute("task.team", {"assignments": [brief]})
        await resumer
    finally:
        run_control.unbind_pass_clock(token)
    assert result.ok, result.error
    assert (tmp_path / "owned.txt").read_text(encoding="utf-8") == "built"


@pytest.mark.asyncio
@pytest.mark.parametrize("guarded", [False, True])
async def test_the_leads_delegation_wait_is_held_time_too(tmp_path, guarded):
    loop, probe = executor(tmp_path, "task.team", guarded)
    clock = PassClock()
    loop._tool_deadlines = {"task.team": HeldDeadline(asyncio.get_running_loop().time() + 0.4, clock)}
    pending = asyncio.create_task(execute(loop, "task.team"))
    try:
        await asyncio.wait_for(probe.entered.wait(), timeout=1)
        clock.hold()  # paused while the team works, past the 0.4 s the call had
        await asyncio.sleep(0.8)
        assert not pending.done()
        clock.release()
        probe.release.set()
        events = await asyncio.wait_for(pending, timeout=1)
        assert events[-1].data["ok"], events[-1].data
    finally:
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_a_moving_deadline_still_ends_a_call_that_overruns_it(tmp_path):
    loop, probe = executor(tmp_path, "task.team", False)
    loop._tool_deadlines = {"task.team": HeldDeadline(asyncio.get_running_loop().time() + 0.1, PassClock())}
    events = await asyncio.wait_for(execute(loop, "task.team"), timeout=2)
    assert not events[-1].data["ok"] and "timed out" in events[-1].data["result"].lower()
    assert probe.closed.is_set()  # cancelled and joined, as wait_for did


def test_a_cancelled_holder_leaves_the_pause_open_until_you_resume(tmp_path, fast_hold):
    events: list[dict[str, Any]] = []
    control = RunControl(tmp_path / "run", emit=events.append)
    run_control.set_paused(control.directory, True)

    async def scenario() -> None:
        holder = asyncio.create_task(control.hold())
        await asyncio.sleep(0.08)
        holder.cancel()  # a sibling tool cancelled, a team stopped: you still have the run paused
        await asyncio.gather(holder, return_exceptions=True)
        assert [e["fc"] for e in events] == ["paused"] and control.clock.held
        # A new pass while the pause is still open starts held too.
        assert control.new_pass_clock().held
        second = asyncio.create_task(control.hold())  # the next agent to reach a step boundary
        await asyncio.sleep(0.06)
        assert not second.done() and [e["fc"] for e in events] == ["paused"]  # one pause, said once
        second.cancel()
        await asyncio.gather(second, return_exceptions=True)
        run_control.set_paused(control.directory, False)
        await control.hold()  # not paused: closes the pause the cancelled holder left open
        assert not control.clock.held

    asyncio.run(scenario())
    assert [e["fc"] for e in events] == ["paused", "resumed"]
    assert events[1]["paused_ms"] >= 100


def test_messages_ride_the_prompt_in_the_order_sent():
    assert pin_your_messages("Build a page", []) == "Build a page"
    pinned = pin_your_messages("Build a page", ["use PostgreSQL, not SQLite", "and\ndark mode"])
    assert pinned.startswith("Build a page\n\n## Messages the person sent you during this run\n")
    assert pinned.endswith("1. use PostgreSQL, not SQLite\n2. and\n   dark mode")


@pytest.mark.asyncio
async def test_a_message_the_lead_read_in_one_pass_is_in_every_later_pass(monkeypatch, tmp_path, runtime):  # noqa: F811
    events: list[dict[str, Any]] = []
    control = RunControl(tmp_path / "control", emit=events.append)
    lead_tools = dispatch.build_lead_tools(control, events.append)
    prompts: list[str] = []

    class Loop:
        def __init__(self, config, llm, tools, **kwargs):
            self.tools = tools

        async def run(self, prompt, **kwargs):
            prompts.append(prompt)
            yield AgentEvent.agent_done("Pass done", iterations=1, tool_calls=0)

    monkeypatch.setattr("thomas.agent.loop.AgentLoop", Loop)

    async def one_pass(prompt: str) -> None:
        await dispatch._agent_loop_pass_async(
            prompt,
            str(tmp_path),
            900,
            events.append,
            profile="selected",
            oauth_access_token="fixture-token",
            control=control,
            lead_tools=lead_tools,
        )

    await one_pass("Build a page")
    run_control.queue_message(control.directory, run_control.LEAD, "use PostgreSQL, not SQLite")
    assert control.inbox(run_control.LEAD).get_nowait() == "use PostgreSQL, not SQLite"  # read late in pass 1
    await one_pass("Build a page\n\ncontinue exactly where it left off")
    await one_pass("Build a page\n\nFIX pass")
    assert prompts[0] == "Build a page"
    assert all("use PostgreSQL, not SQLite" in prompt for prompt in prompts[1:])
    with pytest.raises(queue.Empty):  # still read once: carried on the prompt, never delivered again
        control.inbox(run_control.LEAD).get_nowait()
    assert [e["fc"] for e in events if e.get("fc") == "steering"] == ["steering"]
