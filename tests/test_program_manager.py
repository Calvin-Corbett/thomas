"""CAP-144 acceptance: two-week program plan with automatic midpoint risk/phase reports.

Covers the exact acceptance line -- "Automate a two-week program plan with
midpoint risk/phase reports":
  * a 14-day plan is built with phases + milestones respecting dependencies,
  * the midpoint (day 7) report enumerates phase status + at-risk items,
  * a slipping milestone is flagged as a risk,
  * a phase-boundary report fires at the transition,
  * determinism (same inputs -> identical plan and reports).

Everything is hermetic and clock-free: the "current day" is always injected.
"""

import pytest

from thomas.agent.program_manager import (
    DEFAULT_HORIZON_DAYS,
    MilestoneSpec,
    PhaseStatus,
    ProgramManager,
    ProgramPlanError,
    RiskKind,
    TaskSpec,
    TaskState,
)


def _tasks() -> list[TaskSpec]:
    return [
        TaskSpec("interviews", "User interviews", "discovery", effort_days=3),
        TaskSpec("prototype", "Build prototype", "build", effort_days=4, deps=("interviews",)),
        TaskSpec("integrate", "Integrate systems", "build", effort_days=3, deps=("prototype",)),
        TaskSpec("launch_prep", "Launch prep", "launch", effort_days=2, deps=("integrate",)),
        TaskSpec("launch", "Go live", "launch", effort_days=2, deps=("launch_prep",)),
    ]


def _milestones() -> list[MilestoneSpec]:
    return [
        MilestoneSpec("m_signoff", "Design signoff", due_day=2, requires=("interviews",), phase="discovery"),
        MilestoneSpec("m_proto", "Prototype ready", due_day=7, requires=("prototype",), phase="build"),
        MilestoneSpec("m_ga", "General availability", due_day=14, requires=("launch",), phase="launch"),
    ]


def _manager() -> ProgramManager:
    return ProgramManager("Ship v2", _tasks(), _milestones(), horizon_days=14)


# ---------------------------------------------------------------------------
# Plan construction: 14-day horizon, phases + milestones, deps respected
# ---------------------------------------------------------------------------


def test_default_horizon_is_two_weeks():
    assert DEFAULT_HORIZON_DAYS == 14
    mgr = ProgramManager("g", _tasks())
    assert mgr.horizon_days == 14
    assert mgr.midpoint_day == 7


def test_plan_schedules_respecting_dependencies():
    plan = _manager().plan
    # Forward pass: each task starts exactly when its dependency ends.
    assert plan.task("interviews").start_day == 0
    assert plan.task("interviews").end_day == 3
    assert plan.task("prototype").start_day == plan.task("interviews").end_day == 3
    assert plan.task("prototype").end_day == 7
    assert plan.task("integrate").start_day == plan.task("prototype").end_day == 7
    assert plan.task("launch_prep").start_day == plan.task("integrate").end_day == 10
    assert plan.task("launch").start_day == plan.task("launch_prep").end_day == 12
    assert plan.task("launch").end_day == 14
    # No task ever begins before any dependency finishes.
    for task in plan.tasks:
        for dep in task.deps:
            assert task.start_day >= plan.task(dep).end_day
    # The whole program fits the two-week horizon.
    assert plan.span_days == 14
    assert plan.overflows_horizon is False


def test_plan_derives_phase_windows_and_milestones():
    plan = _manager().plan
    phases = {p.name: p for p in plan.phases}
    assert [p.name for p in plan.phases] == ["discovery", "build", "launch"]
    assert (phases["discovery"].start_day, phases["discovery"].end_day) == (0, 3)
    assert (phases["build"].start_day, phases["build"].end_day) == (3, 10)
    assert (phases["launch"].start_day, phases["launch"].end_day) == (10, 14)
    assert phases["build"].task_ids == ("prototype", "integrate")
    # Milestones carry a projected completion derived from their required tasks.
    proto = next(m for m in plan.milestones if m.id == "m_proto")
    assert proto.projected_day == 7
    assert proto.slipping is False


def test_unknown_dependency_and_cycle_are_rejected():
    with pytest.raises(ProgramPlanError):
        ProgramManager("g", [TaskSpec("a", "A", "p", deps=("ghost",))])
    with pytest.raises(ProgramPlanError):
        ProgramManager(
            "g",
            [
                TaskSpec("a", "A", "p", deps=("b",)),
                TaskSpec("b", "B", "p", deps=("a",)),
            ],
        )
    with pytest.raises(ProgramPlanError):
        ProgramManager("g", [TaskSpec("a", "A", "p"), TaskSpec("a", "dup", "p")])
    with pytest.raises(ProgramPlanError):
        ProgramManager("g", [TaskSpec("a", "A", "p", effort_days=0)])


# ---------------------------------------------------------------------------
# Midpoint report: phase status + at-risk items at day 7
# ---------------------------------------------------------------------------


def test_midpoint_report_enumerates_phase_status():
    report = _manager().midpoint_report()
    assert report.day == 7
    assert report.is_midpoint is True
    status = {line.name: line.status for line in report.phase_status}
    # At day 7 discovery is done, build is running, launch has not begun.
    assert status["discovery"] == PhaseStatus.DONE
    assert status["build"] == PhaseStatus.IN_PROGRESS
    assert status["launch"] == PhaseStatus.NOT_STARTED
    # Every phase is enumerated exactly once.
    assert len(report.phase_status) == 3


def test_midpoint_report_flags_slipping_milestone_as_risk():
    report = _manager().midpoint_report()
    slip_risks = report.risks_of(RiskKind.SLIPPING_MILESTONE)
    ref_ids = {r.ref_id for r in slip_risks}
    # Design signoff is due day 2 but its work finishes day 3 -> slipping.
    assert "m_signoff" in ref_ids
    # On-schedule milestones are NOT flagged.
    assert "m_proto" not in ref_ids
    assert "m_ga" not in ref_ids
    assert "m_signoff" in report.at_risk_ref_ids


def test_midpoint_report_flags_blocked_and_overdue_tasks_from_progress():
    mgr = _manager()
    # At day 7: prototype reported blocked; interviews should have finished
    # (end day 3) but is still in progress -> overdue.
    progress = {"prototype": TaskState.BLOCKED, "interviews": "in_progress"}
    report = mgr.midpoint_report(progress=progress)
    blocked = {r.ref_id for r in report.risks_of(RiskKind.BLOCKED_TASK)}
    overdue = {r.ref_id for r in report.risks_of(RiskKind.OVERDUE_TASK)}
    assert blocked == {"prototype"}
    assert overdue == {"interviews"}


def test_status_report_without_progress_reports_only_schedule_risks():
    report = _manager().status_report(7)
    assert report.risks_of(RiskKind.BLOCKED_TASK) == ()
    assert report.risks_of(RiskKind.OVERDUE_TASK) == ()
    # The schedule-inherent slipping milestone is still surfaced.
    assert {r.ref_id for r in report.risks_of(RiskKind.SLIPPING_MILESTONE)} == {"m_signoff"}


# ---------------------------------------------------------------------------
# Phase-transition reports at boundaries
# ---------------------------------------------------------------------------


def test_phase_transition_fires_at_boundary():
    mgr = _manager()
    # Day 3: discovery ends and build begins.
    at3 = mgr.phase_transition_report(3)
    assert at3 is not None
    assert at3.ending == ("discovery",)
    assert at3.starting == ("build",)
    # Day 10: build ends and launch begins.
    at10 = mgr.phase_transition_report(10)
    assert at10 is not None
    assert at10.ending == ("build",)
    assert at10.starting == ("launch",)


def test_no_transition_report_on_a_non_boundary_day():
    mgr = _manager()
    # Day 5 sits inside the build phase -- no phase starts or ends.
    assert mgr.phase_transition_report(5) is None
    # The midpoint (day 7) is a milestone day, not a phase boundary.
    assert mgr.phase_transition_report(7) is None


def test_phase_transitions_enumerates_all_boundaries_in_order():
    reports = _manager().phase_transitions()
    assert [r.day for r in reports] == [0, 3, 10, 14]
    first, last = reports[0], reports[-1]
    assert first.starting == ("discovery",) and first.ending == ()
    assert last.ending == ("launch",) and last.starting == ()


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_plan_and_reports_are_deterministic():
    plan_a = ProgramManager("Ship v2", _tasks(), _milestones(), horizon_days=14).plan
    plan_b = ProgramManager("Ship v2", _tasks(), _milestones(), horizon_days=14).plan
    assert plan_a.to_dict() == plan_b.to_dict()

    mgr = _manager()
    progress = {"prototype": "blocked", "interviews": "in_progress"}
    assert mgr.midpoint_report(progress).to_dict() == mgr.midpoint_report(progress).to_dict()
    assert _manager().phase_transition_report(3).to_dict() == _manager().phase_transition_report(3).to_dict()
    # Rendered text is stable too (safe to persist / diff).
    assert mgr.midpoint_report().render() == _manager().midpoint_report().render()
