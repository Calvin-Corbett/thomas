"""Tests for the orchestration scale benchmark (CAP-032).

Proves the L2 acceptance line: a 20-25 concurrent-agent run reaches the target
peak concurrency (barrier-verified real concurrency), the merge-quality oracle
computes clean-merge/conflict/gate-pass rates, a deliberately-conflicting pair
yields a non-zero conflict rate, the report carries all fields, and the run is
deterministic.
"""

from __future__ import annotations

import asyncio

import pytest

from thomas.agent.scale_benchmark import (
    AgentChange,
    AgentOutcome,
    BenchTask,
    GitMergeChecker,
    GitResult,
    InProcessMergeChecker,
    ScaleBenchmark,
    ScaleReport,
    build_tasks,
    deterministic_worker,
    git_available,
)


class _FakeClock:
    """Deterministic monotonic clock: advances a fixed step per read."""

    def __init__(self, step: float = 0.5) -> None:
        self._t = 0.0
        self._step = step

    def __call__(self) -> float:
        now = self._t
        self._t += self._step
        return now


def _barrier_worker(barrier: asyncio.Barrier):
    """A fake worker that parks every agent at a shared barrier.

    All N workers must arrive before any proceeds, so if the run completes the
    peak in-flight count provably reached N -- real concurrency, not interleaved
    single-stepping.
    """

    async def worker(task: BenchTask) -> AgentChange:
        await barrier.wait()
        return await deterministic_worker(task)

    return worker


# ---------------------------------------------------------------------------
# Concurrency: peak reaches the 20-25 target, barrier-verified
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [20, 22, 25])
def test_peak_concurrency_reaches_target_with_barrier(n: int) -> None:
    async def _run() -> ScaleReport:
        barrier = asyncio.Barrier(n)
        tasks = build_tasks(n)
        bench = ScaleBenchmark(clock=_FakeClock())
        # No timeout wrapper: if concurrency were faked (< n workers overlapping)
        # the barrier could never release and the test would hang -- so passing
        # is itself proof that n workers ran simultaneously.
        return await asyncio.wait_for(
            bench.run(tasks=tasks, worker=_barrier_worker(barrier)),
            timeout=10.0,
        )

    report = asyncio.run(_run())
    assert report.n_agents == n
    assert report.peak_concurrency >= 20
    assert report.peak_concurrency == n
    assert report.target_concurrency == n


def test_capped_concurrency_limits_peak() -> None:
    """With max_concurrency below N, peak is bounded by the cap (no barrier)."""

    async def _run() -> ScaleReport:
        tasks = build_tasks(25)
        bench = ScaleBenchmark(clock=_FakeClock())
        return await bench.run(tasks=tasks, max_concurrency=4)

    report = asyncio.run(_run())
    assert report.n_agents == 25
    assert report.target_concurrency == 4
    assert 1 <= report.peak_concurrency <= 4


# ---------------------------------------------------------------------------
# Merge-quality oracle: clean-merge / conflict / gate-pass rates
# ---------------------------------------------------------------------------


def test_all_independent_tasks_merge_clean() -> None:
    async def _run() -> ScaleReport:
        tasks = build_tasks(22)
        bench = ScaleBenchmark(clock=_FakeClock())
        return await bench.run(tasks=tasks)

    report = asyncio.run(_run())
    assert report.clean_merge_pct == 100.0
    assert report.conflict_pct == 0.0
    assert report.gate_pass_pct == 100.0
    assert report.clean_merge_count == 22
    assert report.conflict_count == 0


def test_deliberately_conflicting_pair_yields_nonzero_conflict_rate() -> None:
    async def _run() -> ScaleReport:
        # Agents 5 and 6 both target region-5 but with different content.
        tasks = build_tasks(
            20,
            contents={5: "alpha", 6: "beta"},
            conflicting_pairs=[(5, 6)],
        )
        bench = ScaleBenchmark(clock=_FakeClock())
        return await bench.run(tasks=tasks)

    report = asyncio.run(_run())
    assert report.conflict_count == 1
    assert report.conflict_pct > 0.0
    assert report.clean_merge_count == 19
    conflicted = [o for o in report.per_agent if o.conflict]
    assert conflicted[0].agent_id == "agent-006"
    assert "conflict" in conflicted[0].detail


def test_gate_failure_lowers_gate_pass_rate() -> None:
    """A change that fails its gate merges cleanly but does not pass gates."""
    changes = [
        AgentChange(agent_id="a0", task_id="T0", target="r0", content="x", gate_ok=True),
        AgentChange(agent_id="a1", task_id="T1", target="r1", content="y", gate_ok=False),
    ]
    checker = InProcessMergeChecker()
    outcomes = checker.check(changes)
    assert outcomes[0].clean_merge and outcomes[0].gate_pass
    assert outcomes[1].clean_merge and not outcomes[1].gate_pass


def test_identical_rewrite_is_clean_not_conflict() -> None:
    """Two agents writing identical content to one region is a no-op merge."""
    changes = [
        AgentChange(agent_id="a0", task_id="T0", target="r0", content="same"),
        AgentChange(agent_id="a1", task_id="T1", target="r0", content="same"),
    ]
    outcomes = InProcessMergeChecker().check(changes)
    assert all(o.clean_merge and not o.conflict for o in outcomes)


# ---------------------------------------------------------------------------
# Report shape: all fields present
# ---------------------------------------------------------------------------


def test_report_has_all_fields() -> None:
    async def _run() -> ScaleReport:
        tasks = build_tasks(20, conflicting_pairs=[(0, 1)], contents={0: "p", 1: "q"})
        bench = ScaleBenchmark(clock=_FakeClock(step=0.25))
        return await bench.run(tasks=tasks)

    report = asyncio.run(_run())
    d = report.to_dict()
    for field in (
        "n_agents",
        "peak_concurrency",
        "target_concurrency",
        "clean_merge_pct",
        "conflict_pct",
        "gate_pass_pct",
        "clean_merge_count",
        "conflict_count",
        "gate_pass_count",
        "duration_s",
        "per_agent",
    ):
        assert field in d, f"missing report field: {field}"
    assert len(d["per_agent"]) == 20
    assert d["duration_s"] >= 0.0
    for row in d["per_agent"]:
        assert set(row) == {"agent_id", "task_id", "clean_merge", "conflict", "gate_pass", "detail"}


def test_percentages_are_consistent() -> None:
    outcomes = [
        AgentOutcome("a0", "T0", clean_merge=True, conflict=False, gate_pass=True),
        AgentOutcome("a1", "T1", clean_merge=True, conflict=False, gate_pass=False),
        AgentOutcome("a2", "T2", clean_merge=False, conflict=True, gate_pass=False),
        AgentOutcome("a3", "T3", clean_merge=False, conflict=True, gate_pass=False),
    ]
    from thomas.agent.scale_benchmark import _build_report

    report = _build_report(n=4, peak=4, target=4, outcomes=outcomes, duration=1.0)
    assert report.clean_merge_pct == 50.0
    assert report.conflict_pct == 50.0
    assert report.gate_pass_pct == 25.0


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_run_is_deterministic() -> None:
    async def _once() -> ScaleReport:
        tasks = build_tasks(21, conflicting_pairs=[(3, 4)], contents={3: "u", 4: "v"})
        bench = ScaleBenchmark(clock=_FakeClock())
        return await bench.run(tasks=tasks)

    r1 = asyncio.run(_once())
    r2 = asyncio.run(_once())
    assert r1.to_dict() == r2.to_dict()


# ---------------------------------------------------------------------------
# GitMergeChecker: hermetic (fake git runner) + optional live lane
# ---------------------------------------------------------------------------


def test_git_merge_checker_with_fake_runner_detects_conflict() -> None:
    """Drive GitMergeChecker with a fake git layer -- no real git, fully hermetic.

    The fake returns non-zero for a merge that targets an already-merged file,
    mirroring how real git signals a conflict via exit code.
    """
    merged_files: set[str] = set()

    def fake_git(args, cwd) -> GitResult:
        args = list(args)
        if args and args[0] == "merge" and args[0] != "--abort":
            # args like ["merge", "--no-edit", "change_2"] -- we cannot see the
            # file here, so encode conflict via a side table keyed by branch.
            branch = args[-1]
            fname = _branch_files.get(branch)
            if fname in merged_files:
                return GitResult(returncode=1, stderr="CONFLICT")
            if fname is not None:
                merged_files.add(fname)
            return GitResult(returncode=0)
        return GitResult(returncode=0)

    # Track which file each change branch writes by intercepting nothing fancy;
    # instead precompute from the changes below.
    changes = [
        AgentChange("a0", "T0", target="r0", content="x"),
        AgentChange("a1", "T1", target="r1", content="y"),
        AgentChange("a2", "T2", target="r0", content="z"),  # collides with a0
    ]
    checker = GitMergeChecker(git_runner=fake_git)
    _branch_files.clear()
    for idx, ch in enumerate(changes):
        _branch_files[f"change_{idx}"] = checker._file_for(ch.target)

    outcomes = checker.check(changes)
    assert outcomes[0].clean_merge
    assert outcomes[1].clean_merge
    assert outcomes[2].conflict and not outcomes[2].clean_merge
    assert sum(1 for o in outcomes if o.conflict) == 1


_branch_files: dict[str, str] = {}


@pytest.mark.skipif(not git_available(), reason="git binary not on PATH (live lane)")
def test_git_merge_checker_live_git_detects_conflict(tmp_path) -> None:
    """Live lane: exercise the REAL git binary in a temp repo (no network)."""
    changes = [
        AgentChange("a0", "T0", target="shared", content="from-a0"),
        AgentChange("a1", "T1", target="solo", content="from-a1"),
        AgentChange("a2", "T2", target="shared", content="from-a2"),  # conflicts with a0
    ]
    checker = GitMergeChecker(work_root=str(tmp_path))
    outcomes = checker.check(changes)
    assert outcomes[0].clean_merge
    assert outcomes[1].clean_merge
    assert outcomes[2].conflict
    assert sum(1 for o in outcomes if o.conflict) == 1
