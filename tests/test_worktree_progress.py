"""Tests for the subagent/worktree progress aggregation core (CAP-139).

Acceptance line: "Per-worktree status plus task-graph timing and cost."

Covered here:
  * per-worktree status (active/idle/done, current node, elapsed) reflects the
    ingested started/finished events;
  * task-graph timing computes per-node durations and the critical-path total
    across the dependency DAG;
  * cost rolls up per-node -> per-worktree -> total (tokens too);
  * a still-running node reports elapsed-so-far without a finish event;
  * the whole snapshot is deterministic given the injected clock.
"""

from __future__ import annotations

from thomas.observability.worktree_progress import (
    STATE_ACTIVE,
    STATE_DONE,
    STATE_IDLE,
    ProgressAggregator,
)


class FixedClock:
    """Deterministic, injectable clock returning preset float timestamps."""

    def __init__(self, values: list[float]) -> None:
        self._values = list(values)
        self._i = 0

    def __call__(self) -> float:
        if self._i < len(self._values):
            v = self._values[self._i]
            self._i += 1
        else:
            v = self._values[-1]
        return v


# ---------------------------------------------------------------------------
# Per-worktree status
# ---------------------------------------------------------------------------
def test_worktree_status_reflects_ingested_events() -> None:
    agg = ProgressAggregator(clock=FixedClock([1000.0]))

    # wt1 runs n1 (started at 100, finished at 130) then n2 (started 130, running).
    agg.node_started(worktree_id="wt1", node_id="n1", at=100.0)
    agg.node_finished(node_id="n1", at=130.0, tokens=50, cost=0.5)
    agg.node_started(worktree_id="wt1", node_id="n2", at=130.0)

    # wt2 runs n3 to completion.
    agg.node_started(worktree_id="wt2", node_id="n3", at=110.0)
    agg.node_finished(node_id="n3", at=140.0, tokens=20, cost=0.2)

    # wt3 is registered but has started nothing -> idle.
    agg.register_worktree("wt3")

    # wt1 has a running node -> active, current is that node, elapsed-so-far.
    s1 = agg.worktree_status("wt1", now=200.0)
    assert s1.state == STATE_ACTIVE
    assert s1.current_node == "n2"
    assert s1.elapsed_s == 70.0  # 200 - 130
    assert s1.running_nodes == ("n2",)

    # wt2 finished every node -> done; elapsed spans first-start..last-finish.
    s2 = agg.worktree_status("wt2", now=200.0)
    assert s2.state == STATE_DONE
    assert s2.current_node == "n3"
    assert s2.elapsed_s == 30.0  # 140 - 110
    assert s2.running_nodes == ()

    # wt3 has no nodes -> idle.
    s3 = agg.worktree_status("wt3", now=200.0)
    assert s3.state == STATE_IDLE
    assert s3.current_node is None
    assert s3.elapsed_s == 0.0


def test_still_running_node_reports_elapsed_without_finish() -> None:
    agg = ProgressAggregator(clock=FixedClock([500.0]))
    agg.node_started(worktree_id="wt1", node_id="n1", at=100.0)

    # No finish event: duration/elapsed comes from the injected clock.
    timing = agg.node_timings(now=175.0)[0]
    assert timing.running is True
    assert timing.finished_at is None
    assert timing.duration_s == 75.0  # 175 - 100

    status = agg.worktree_status("wt1", now=175.0)
    assert status.state == STATE_ACTIVE
    assert status.elapsed_s == 75.0

    # Advancing the clock advances elapsed-so-far, still with no finish.
    assert agg.node_timings(now=260.0)[0].duration_s == 160.0


# ---------------------------------------------------------------------------
# Task-graph timing + critical path
# ---------------------------------------------------------------------------
def test_task_graph_timing_and_critical_path() -> None:
    agg = ProgressAggregator(clock=FixedClock([9999.0]))

    # Diamond DAG:
    #   a (10) -> b (30) -> d (5)
    #   a (10) -> c (2)  -> d (5)
    # Critical path a->b->d = 10 + 30 + 5 = 45; the a->c->d path is 17.
    agg.node_started(worktree_id="wt1", node_id="a", at=0.0)
    agg.node_finished(node_id="a", at=10.0)
    agg.node_started(worktree_id="wt1", node_id="b", depends_on=["a"], at=10.0)
    agg.node_finished(node_id="b", at=40.0)
    agg.node_started(worktree_id="wt2", node_id="c", depends_on=["a"], at=10.0)
    agg.node_finished(node_id="c", at=12.0)
    agg.node_started(worktree_id="wt1", node_id="d", depends_on=["b", "c"], at=40.0)
    agg.node_finished(node_id="d", at=45.0)

    timings = {t.node_id: t.duration_s for t in agg.node_timings()}
    assert timings == {"a": 10.0, "b": 30.0, "c": 2.0, "d": 5.0}

    cp = agg.critical_path()
    assert cp.nodes == ("a", "b", "d")
    assert cp.duration_s == 45.0


def test_critical_path_includes_running_node_elapsed() -> None:
    agg = ProgressAggregator(clock=FixedClock([1000.0]))
    agg.node_started(worktree_id="wt1", node_id="a", at=0.0)
    agg.node_finished(node_id="a", at=10.0)
    # b depends on a and is still running: elapsed-so-far feeds the critical path.
    agg.node_started(worktree_id="wt1", node_id="b", depends_on=["a"], at=10.0)

    cp = agg.critical_path(now=50.0)
    assert cp.nodes == ("a", "b")
    assert cp.duration_s == 50.0  # a: 10, b elapsed-so-far: 40


def test_critical_path_detects_cycle() -> None:
    agg = ProgressAggregator(clock=FixedClock([0.0]))
    agg.node_started(worktree_id="wt1", node_id="x", depends_on=["y"], at=0.0)
    agg.node_started(worktree_id="wt1", node_id="y", depends_on=["x"], at=0.0)
    try:
        agg.critical_path(now=1.0)
    except ValueError as exc:
        assert "cycle" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected a cycle to be detected")


# ---------------------------------------------------------------------------
# Cost rollup
# ---------------------------------------------------------------------------
def test_cost_rolls_up_per_node_worktree_and_total() -> None:
    agg = ProgressAggregator(clock=FixedClock([0.0]))

    agg.node_started(worktree_id="wt1", node_id="n1", at=0.0)
    agg.node_finished(node_id="n1", at=1.0, tokens=100, cost=1.25)
    agg.node_started(worktree_id="wt1", node_id="n2", at=1.0)
    agg.node_finished(node_id="n2", at=2.0, tokens=200, cost=2.75)
    agg.node_started(worktree_id="wt2", node_id="n3", at=0.0)
    agg.node_finished(node_id="n3", at=3.0, tokens=50, cost=0.5)
    # Idle worktree still appears in the rollup with zero cost.
    agg.register_worktree("wt3")

    roll = agg.cost_rollup()
    assert roll.per_node == {"n1": 1.25, "n2": 2.75, "n3": 0.5}
    assert roll.per_worktree == {"wt1": 4.0, "wt2": 0.5, "wt3": 0.0}
    assert roll.total == 4.5

    assert roll.tokens_per_node == {"n1": 100, "n2": 200, "n3": 50}
    assert roll.tokens_per_worktree == {"wt1": 300, "wt2": 50, "wt3": 0}
    assert roll.tokens_total == 350


# ---------------------------------------------------------------------------
# Determinism + snapshot
# ---------------------------------------------------------------------------
def test_snapshot_is_deterministic_for_same_clock_value() -> None:
    def build() -> ProgressAggregator:
        agg = ProgressAggregator(clock=FixedClock([0.0]))
        agg.node_started(worktree_id="wt1", node_id="a", at=0.0)
        agg.node_finished(node_id="a", at=10.0, tokens=10, cost=0.1)
        agg.node_started(worktree_id="wt1", node_id="b", depends_on=["a"], at=10.0)
        agg.node_started(worktree_id="wt2", node_id="c", at=5.0)
        agg.node_finished(node_id="c", at=8.0, tokens=3, cost=0.03)
        return agg

    snap_a = build().snapshot(now=100.0)
    snap_b = build().snapshot(now=100.0)
    assert snap_a.to_dict() == snap_b.to_dict()

    # The snapshot records the clock value it was computed against.
    assert snap_a.at == 100.0
    # Running node "b" contributes elapsed-so-far in the snapshot's timings.
    assert snap_a.timing("b").duration_s == 90.0  # 100 - 10
    assert snap_a.worktree("wt1").state == STATE_ACTIVE
    assert snap_a.worktree("wt2").state == STATE_DONE


def test_snapshot_default_clock_uses_injected_source() -> None:
    # Snapshot without an explicit `now` reads the injected clock, not wall time.
    agg = ProgressAggregator(clock=FixedClock([321.0]))
    agg.node_started(worktree_id="wt1", node_id="n1", at=1.0)
    snap = agg.snapshot()
    assert snap.at == 321.0
    assert snap.timing("n1").duration_s == 320.0
