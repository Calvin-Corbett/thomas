"""CAP-058 acceptance: priority, aging, preemption, and starvation tests for the swarm task queue.

Unit tests drive TaskQueuePolicy with a fake clock; integration tests drive the
real SwarmOrchestrator selection point and the cooperative requeue-before-start
preemption wiring in swarm.py.
"""

import asyncio
import json

from thomas.agent.swarm import SwarmConfig, SwarmOrchestrator, TaskGraph, TaskResult
from thomas.agent.task_queue_policy import (
    DEFAULT_PRIORITY,
    PRIORITY_TIERS,
    QueuePolicyConfig,
    TaskQueuePolicy,
    parse_priority,
    preemptible_from_meta,
    priority_from_meta,
)


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def __call__(self) -> float:
        return self.now


def _policy(priorities=None, preemptible=None, rate=1.0, clock=None, preemption_enabled=True):
    return TaskQueuePolicy(
        priorities=priorities,
        preemptible=preemptible,
        config=QueuePolicyConfig(aging_rate_per_sec=rate, preemption_enabled=preemption_enabled),
        clock=clock or FakeClock(),
    )


# ---------------------------------------------------------------------------
# Priority parsing
# ---------------------------------------------------------------------------


def test_parse_priority_tiers_and_ints():
    assert parse_priority("critical") > parse_priority("high") > parse_priority("normal") > parse_priority("low")
    assert parse_priority(7) == 7
    assert parse_priority("15") == 15
    assert parse_priority(3.0) == 3
    # invalid values fall back to the documented default (no priority = unchanged behavior)
    assert parse_priority("urgent-ish") == DEFAULT_PRIORITY
    assert parse_priority(None) == DEFAULT_PRIORITY
    assert parse_priority(True) == DEFAULT_PRIORITY
    assert priority_from_meta({"priority": "high"}) == PRIORITY_TIERS["high"]
    assert priority_from_meta({}) == DEFAULT_PRIORITY
    assert priority_from_meta(None) == DEFAULT_PRIORITY
    assert preemptible_from_meta({"preemptible": False}) is False
    assert preemptible_from_meta({}) is True


# ---------------------------------------------------------------------------
# FIFO regression (no priorities declared)
# ---------------------------------------------------------------------------


def test_no_priorities_means_fifo():
    clock = FakeClock()
    policy = _policy(clock=clock)
    for tid in ("a", "b", "c", "d"):
        policy.mark_ready(tid)
    assert [policy.pop_next() for _ in range(4)] == ["a", "b", "c", "d"]
    assert policy.pop_next() is None


def test_no_priorities_fifo_holds_across_time_gaps():
    clock = FakeClock()
    policy = _policy(clock=clock)
    policy.mark_ready("first")
    clock.advance(5.0)
    policy.mark_ready("second")
    clock.advance(5.0)
    policy.mark_ready("third")
    # aging only reinforces arrival order when bases are equal
    assert [policy.pop_next() for _ in range(3)] == ["first", "second", "third"]


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------


def test_priority_order_beats_arrival_order():
    policy = _policy(priorities={"lo": -10, "hi": 10, "crit": 20})
    for tid in ("lo", "mid", "hi", "crit"):  # "mid" has no declared priority -> 0
        policy.mark_ready(tid)
    assert [policy.pop_next() for _ in range(4)] == ["crit", "hi", "mid", "lo"]


def test_equal_priority_ties_break_fifo():
    policy = _policy(priorities={"x": 5, "y": 5, "z": 5})
    for tid in ("x", "y", "z"):
        policy.mark_ready(tid)
    assert [policy.pop_next() for _ in range(3)] == ["x", "y", "z"]


# ---------------------------------------------------------------------------
# Aging
# ---------------------------------------------------------------------------


def test_aging_raises_effective_priority_at_configured_rate():
    clock = FakeClock()
    policy = _policy(priorities={"lo": -10}, rate=2.0, clock=clock)
    policy.mark_ready("lo")
    assert policy.effective_priority("lo") == -10.0
    clock.advance(3.0)
    assert policy.effective_priority("lo") == -10.0 + 3.0 * 2.0


def test_aged_low_priority_task_overtakes_fresh_high_priority():
    clock = FakeClock()
    policy = _policy(priorities={"lo": -10, "hi": 10}, rate=1.0, clock=clock)
    policy.mark_ready("lo")
    clock.advance(25.0)  # lo effective: -10 + 25 = 15 > 10
    policy.mark_ready("hi")
    assert policy.pop_next() == "lo"
    assert policy.pop_next() == "hi"


def test_zero_aging_rate_is_pure_strict_priority():
    clock = FakeClock()
    policy = _policy(priorities={"lo": -10, "hi": 10}, rate=0.0, clock=clock)
    policy.mark_ready("lo")
    clock.advance(10_000.0)
    policy.mark_ready("hi")
    assert policy.pop_next() == "hi"
    assert policy.starvation_bound_seconds(-10, 10) == float("inf")


def test_requeue_preserves_aging_state():
    clock = FakeClock()
    policy = _policy(priorities={"lo": -10}, rate=1.0, clock=clock)
    policy.mark_ready("lo")
    clock.advance(6.0)
    assert policy.pop_next() == "lo"  # claimed by a worker
    policy.requeue("lo")  # preempted before start; aging credit must survive
    clock.advance(1.0)
    assert policy.effective_priority("lo") == -10.0 + 7.0  # 7s total wait, not 1s


# ---------------------------------------------------------------------------
# Preemption decisions
# ---------------------------------------------------------------------------


def test_should_yield_claim_requires_strictly_higher_ready_work():
    policy = _policy(priorities={"claimed": 0, "equal": 0, "higher": 10})
    policy.mark_ready("claimed")
    assert policy.pop_next() == "claimed"
    policy.mark_ready("equal")
    assert policy.should_yield_claim("claimed") is False  # equal is not strictly higher
    policy.mark_ready("higher")
    assert policy.should_yield_claim("claimed") is True


def test_non_preemptible_claim_never_yields():
    policy = _policy(priorities={"claimed": 0, "crit": 20}, preemptible={"claimed": False})
    policy.mark_ready("claimed")
    assert policy.pop_next() == "claimed"
    policy.mark_ready("crit")
    assert policy.should_yield_claim("claimed") is False


def test_preemption_disabled_config_switch():
    policy = _policy(priorities={"claimed": 0, "crit": 20}, preemption_enabled=False)
    policy.mark_ready("claimed")
    assert policy.pop_next() == "claimed"
    policy.mark_ready("crit")
    assert policy.should_yield_claim("claimed") is False
    assert policy.decide_preemption(["claimed"]) is None


def test_decide_preemption_picks_lowest_priority_preemptible_victim():
    policy = _policy(
        priorities={"lo": -10, "mid": 0, "locked": -20, "incoming": 20},
        preemptible={"locked": False},
    )
    policy.mark_ready("incoming")
    decision = policy.decide_preemption(["mid", "lo", "locked"])
    assert decision is not None
    assert decision.victim_id == "lo"  # lowest-priority *preemptible* running task
    assert decision.incoming_id == "incoming"
    assert decision.incoming_priority > decision.victim_priority


def test_decide_preemption_none_when_not_strictly_higher_or_no_candidates():
    policy = _policy(priorities={"run_hi": 10, "incoming": 10}, preemptible={"run_hi": True})
    policy.mark_ready("incoming")
    # equal priority -> no preemption
    assert policy.decide_preemption(["run_hi"]) is None
    # no preemptible running tasks -> no preemption
    policy2 = _policy(priorities={"lo": -10, "incoming": 20}, preemptible={"lo": False})
    policy2.mark_ready("incoming")
    assert policy2.decide_preemption(["lo"]) is None
    # empty ready set -> no preemption
    policy3 = _policy(priorities={"lo": -10})
    assert policy3.decide_preemption(["lo"]) is None


# ---------------------------------------------------------------------------
# Starvation: bounded wait under sustained high-priority arrival
# ---------------------------------------------------------------------------


def test_starvation_bounded_wait_under_sustained_high_priority_arrival():
    clock = FakeClock()
    priorities = {"starved": PRIORITY_TIERS["low"]}
    for i in range(60):
        priorities[f"hi{i}"] = PRIORITY_TIERS["high"]
    policy = _policy(priorities=priorities, rate=1.0, clock=clock)

    policy.mark_ready("starved")
    bound = policy.starvation_bound_seconds(PRIORITY_TIERS["low"], PRIORITY_TIERS["high"])
    assert bound == 20.0  # (10 - -10) / 1.0

    scheduled_at = None
    # One slot frees per second; a fresh high-priority task arrives every second.
    for step in range(60):
        policy.mark_ready(f"hi{step}")
        picked = policy.pop_next()
        if picked == "starved":
            scheduled_at = step
            break
        clock.advance(1.0)

    assert scheduled_at is not None, "low-priority task starved despite aging"
    # Bounded wait: scheduled within the analytic bound (+1 step for the in-flight arrival).
    assert scheduled_at <= bound + 1


def test_starvation_bound_is_tight_for_higher_rates():
    clock = FakeClock()
    policy = _policy(priorities={"starved": -10, "fresh": 20}, rate=5.0, clock=clock)
    policy.mark_ready("starved")
    assert policy.starvation_bound_seconds(-10, 20) == 6.0
    clock.advance(6.5)
    policy.mark_ready("fresh")
    assert policy.pop_next() == "starved"


# ---------------------------------------------------------------------------
# Swarm integration: helpers
# ---------------------------------------------------------------------------


class _Planner:
    agent_id = "planner"

    def __init__(self, graph_obj):
        self.graph_obj = graph_obj

    async def run_task(self, *, task, graph, prior_results, emit_text, call_tool, cancel_event):
        return TaskResult(ok=True, output=json.dumps(self.graph_obj))


class _Reviewer:
    agent_id = "reviewer"

    async def run_task(self, *, task, graph, prior_results, emit_text, call_tool, cancel_event):
        return TaskResult(ok=True, output="final")


class _RecordingAgent:
    def __init__(self, agent_id, order):
        self.agent_id = agent_id
        self.order = order

    async def run_task(self, *, task, graph, prior_results, emit_text, call_tool, cancel_event):
        self.order.append(task.id)
        await asyncio.sleep(0)
        return TaskResult(ok=True, output=f"done {task.id}")


def _graph_obj(tasks):
    return {"version": 1, "goal": "test", "summary": "", "tasks": tasks}


def _task(tid, meta=None, agent="coder", deps=None):
    return {
        "id": tid,
        "title": tid,
        "agent": agent,
        "deps": deps or [],
        "prompt": "",
        "acceptance": [],
        "meta": meta or {},
    }


async def _run_swarm(graph_obj, subagents, config):
    orch = SwarmOrchestrator(run_id="run_qpolicy", config=config)
    events = []
    async for e in orch.astream(user_request="x", subagents=subagents):
        events.append(e)
    return orch, events


# ---------------------------------------------------------------------------
# Swarm integration: priority ordering at the real selection point
# ---------------------------------------------------------------------------


def test_swarm_executes_ready_tasks_in_priority_order():
    async def _run():
        graph_obj = _graph_obj(
            [
                _task("lowest", meta={"priority": "low"}),
                _task("plain"),  # no priority declared -> documented default
                _task("urgent", meta={"priority": "critical"}),
                _task("raised", meta={"priority": "high"}),
            ]
        )
        order = []
        subagents = {"planner": _Planner(graph_obj), "coder": _RecordingAgent("coder", order), "reviewer": _Reviewer()}
        orch, events = await _run_swarm(graph_obj, subagents, SwarmConfig(max_parallel_tasks=1))
        assert order == ["urgent", "raised", "plain", "lowest"]
        done = [e for e in events if e["type"] == "swarm_done"]
        assert done and done[0]["ok"] is True

    asyncio.run(_run())


def test_swarm_without_priorities_keeps_fifo_regression():
    async def _run():
        graph_obj = _graph_obj([_task("t1"), _task("t2"), _task("t3"), _task("t4")])
        order = []
        subagents = {"planner": _Planner(graph_obj), "coder": _RecordingAgent("coder", order), "reviewer": _Reviewer()}
        orch, events = await _run_swarm(graph_obj, subagents, SwarmConfig(max_parallel_tasks=1))
        assert order == ["t1", "t2", "t3", "t4"]
        done = [e for e in events if e["type"] == "swarm_done"]
        assert done and done[0]["ok"] is True

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Swarm integration: cooperative requeue-before-start preemption wiring
# ---------------------------------------------------------------------------


def test_swarm_claimed_task_yields_slot_to_higher_priority_ready_work():
    async def _run():
        graph_obj = _graph_obj(
            [
                _task("lowpri", meta={"priority": "low"}),
                _task("urgent", agent="helper", meta={"priority": "critical"}),
            ]
        )
        graph = TaskGraph.from_planner_json(json.dumps(graph_obj))
        orch = SwarmOrchestrator(
            run_id="run_preempt",
            config=SwarmConfig(max_parallel_tasks=2, max_parallel_per_agent={"coder": 1}),
        )
        orch.graph = graph
        policy = TaskQueuePolicy.for_graph(graph)
        orch._queue_policy = policy

        # A worker claims "lowpri" (pops it from the ready set)...
        policy.mark_ready("lowpri")
        assert policy.pop_next() == "lowpri"
        # ...but the coder agent slot is occupied by an already-running task.
        await orch._agent_sems["coder"].acquire()
        # While the claim waits, strictly-higher-priority work becomes ready.
        policy.mark_ready("urgent")

        order = []
        subagents = {"coder": _RecordingAgent("coder", order), "helper": _RecordingAgent("helper", order)}
        ran = await orch._run_one_task(task_id="lowpri", subagents=subagents)

        # The claim yielded before start: nothing executed, claim requeued with state.
        assert ran is False
        assert order == []
        assert "lowpri" in policy.ready_ids()
        # The global slot was handed back (semaphore restored to full capacity).
        assert orch._task_sem._value == 2  # noqa: SLF001 - asserting the wiring releases the slot
        # And the preemption was announced on the event stream.
        preempt_events = []
        while not orch._events.empty():
            evt = orch._events.get_nowait()
            if evt and evt.get("preempted"):
                preempt_events.append(evt)
        assert preempt_events and preempt_events[0]["task_id"] == "lowpri"
        assert preempt_events[0]["status"] == "queued"

        # The preempting task is selected ahead of the requeued claim...
        assert policy.pop_next() == "urgent"
        # ...and once the agent slot frees up, the requeued task runs normally.
        orch._agent_sems["coder"].release()
        assert policy.pop_next() == "lowpri"
        ran2 = await orch._run_one_task(task_id="lowpri", subagents=subagents)
        assert ran2 is True
        assert order == ["lowpri"]

    asyncio.run(_run())


def test_swarm_non_preemptible_claim_keeps_waiting():
    async def _run():
        graph_obj = _graph_obj(
            [
                _task("sticky", meta={"priority": "low", "preemptible": False}),
                _task("urgent", agent="helper", meta={"priority": "critical"}),
            ]
        )
        graph = TaskGraph.from_planner_json(json.dumps(graph_obj))
        orch = SwarmOrchestrator(
            run_id="run_nopreempt",
            config=SwarmConfig(max_parallel_tasks=2, max_parallel_per_agent={"coder": 1}),
        )
        orch.graph = graph
        policy = TaskQueuePolicy.for_graph(graph)
        orch._queue_policy = policy

        policy.mark_ready("sticky")
        assert policy.pop_next() == "sticky"
        await orch._agent_sems["coder"].acquire()
        policy.mark_ready("urgent")

        order = []
        subagents = {"coder": _RecordingAgent("coder", order), "helper": _RecordingAgent("helper", order)}
        run_task = asyncio.create_task(orch._run_one_task(task_id="sticky", subagents=subagents))
        # Give the claim-wait several poll cycles to (incorrectly) yield.
        await asyncio.sleep(0.2)
        assert not run_task.done(), "non-preemptible claim must keep waiting for its slot"
        assert "sticky" not in policy.ready_ids()

        orch._agent_sems["coder"].release()
        assert await run_task is True
        assert order == ["sticky"]

    asyncio.run(_run())
