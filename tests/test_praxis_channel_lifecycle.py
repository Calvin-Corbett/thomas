"""Build child state observations feed Praxis without inventing acceptance."""

from __future__ import annotations

import asyncio

import pytest

from thomas.core.praxis.formation_state import N1_RULES, Cycle
from thomas.server.praxis.coordinator import PraxisBuildCoordinator
from thomas.server.praxis.run_channel import RunChannel


@pytest.mark.asyncio
async def test_channel_lifecycle_does_not_turn_done_into_accepted_candidate(tmp_path):
    release = asyncio.Event()

    async def child(_agent_id, _kind, _title, _brief):
        await release.wait()
        yield {"type": "done", "text": "I reviewed it"}

    channel = RunChannel("run", child)
    child_id = (await channel.spawn([{"kind": "review", "title": "Review", "brief": "Inspect"}]))[0]["agent_id"]

    def evaluate(_key, _cycle):
        raise AssertionError("a done event is not a candidate")

    coordinator = PraxisBuildCoordinator(
        run_id="run",
        owners=[child_id],
        cycles=[Cycle(1, "requirements", "acceptance")],
        log_path=tmp_path / "obligations.jsonl",
        evaluate=evaluate,
        manager_id="manager",
        rules=N1_RULES,
    )
    states = []

    def observe(agent_id, state):
        states.append((agent_id, state))
        coordinator.child_state(agent_id, state)

    channel.attach_state_observer(observe)
    release.set()
    await channel._tasks[child_id]
    assert [state for _, state in states] == ["starting", "running", "completed"]
    assert coordinator.report()["formation"]["accepted_cycles"] == []
    assert coordinator.report()["obligations"]["obligations"] == {}
    await channel.close()


@pytest.mark.asyncio
async def test_channel_observes_retry_and_stop_without_fake_completion():
    attempts = 0

    async def child(_agent_id, _kind, _title, _brief):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            yield {"type": "error", "error": "HTTP 429", "retryable": True}
        else:
            yield {"type": "progress", "text": "working"}
            await asyncio.Event().wait()

    states = []
    channel = RunChannel("retry", child, state_observer=lambda _child_id, state: states.append(state))
    child_id = (await channel.spawn([{"kind": "review", "title": "Review", "brief": "Inspect"}]))[0]["agent_id"]
    for _ in range(200):
        if states.count("running") == 2:
            break
        await asyncio.sleep(0.01)
    assert states[:4] == ["starting", "running", "retrying", "running"]
    await channel.stop_child(child_id)
    assert states[-1] == "stopped"
    assert "completed" not in states
