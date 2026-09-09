"""Long-horizon program management (CAP-144, stdlib-only, deterministic).

This module turns a *goal* plus a flat list of *tasks* into a bounded
multi-week **program plan** and then generates the status/risk reports a
program lead needs to run it: an automatic **midpoint report** at the middle
of the horizon (day 7 of a 14-day program) and a **phase-transition report**
at every phase boundary.

Everything here is a pure function of its inputs. There is no wall clock: the
"current day" is always injected (:meth:`ProgramManager.status_report` takes a
``today`` argument, and the midpoint day is derived from the horizon). Building
the same plan twice, or generating a report for the same day twice, yields
byte-identical output -- see the determinism test.

Model
-----
Scheduling
    Each :class:`TaskSpec` declares an integer ``effort_days`` (>= 1) and a
    tuple of dependency task ids. Tasks are scheduled on a half-open day axis:
    a task occupying ``effort_days`` days starting on ``start_day`` ends on
    ``end_day = start_day + effort_days`` (it works days ``start_day`` ..
    ``end_day - 1`` inclusive). A task's ``start_day`` is the max ``end_day``
    of its dependencies (0 when it has none), so the schedule is the classic
    earliest-start critical-path forward pass. The dependency graph is walked
    in a deterministic topological order (input order breaks ties); a cycle or
    an unknown dependency is a :class:`ProgramPlanError`.

Phases
    Tasks carry a ``phase`` label. Phases are ordered by first appearance in
    the input task list. A phase's window is ``[min(task start), max(task
    end))`` over its tasks. Phase status at ``today`` is ``NOT_STARTED`` when
    ``today < start``, ``DONE`` when ``today >= end``, else ``IN_PROGRESS``.

Milestones
    A :class:`MilestoneSpec` has a ``due_day`` and the set of task ids that
    must be complete for it to be met. Its *projected* completion day is the
    max ``end_day`` of those tasks. A milestone **slips** when its projected
    day exceeds its due day -- a static property of the baseline plan, so a
    slipping milestone is flagged as a risk even before any execution signal
    arrives. Optional runtime ``progress`` (a task id -> :class:`TaskState`
    mapping) adds two more risk sources: a task reported ``BLOCKED``, and a
    task whose planned ``end_day`` has passed (``end_day <= today``) but which
    is not yet ``DONE`` (overdue).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from enum import Enum

DEFAULT_HORIZON_DAYS = 14


class ProgramPlanError(ValueError):
    """Raised for structurally invalid program inputs (bad deps, cycles, etc.)."""


class PhaseStatus(Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class TaskState(Enum):
    """Runtime execution state supplied via a ``progress`` mapping (optional)."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"


class RiskKind(Enum):
    SLIPPING_MILESTONE = "slipping_milestone"
    BLOCKED_TASK = "blocked_task"
    OVERDUE_TASK = "overdue_task"


def _normalize_state(value: object) -> TaskState:
    """Coerce a progress value to a :class:`TaskState` (unknown -> NOT_STARTED)."""
    if isinstance(value, TaskState):
        return value
    if isinstance(value, str):
        key = value.strip().lower()
        for state in TaskState:
            if state.value == key:
                return state
    return TaskState.NOT_STARTED


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class TaskSpec:
    """One unit of program work. ``deps`` are ids of tasks that must finish first."""

    id: str
    title: str
    phase: str
    effort_days: int = 1
    deps: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class MilestoneSpec:
    """A checkpoint due on ``due_day`` requiring ``requires`` tasks to be complete."""

    id: str
    title: str
    due_day: int
    requires: tuple[str, ...] = ()
    phase: str | None = None


# ---------------------------------------------------------------------------
# Built plan
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ScheduledTask:
    id: str
    title: str
    phase: str
    start_day: int
    end_day: int
    deps: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "phase": self.phase,
            "start_day": self.start_day,
            "end_day": self.end_day,
            "deps": list(self.deps),
        }


@dataclasses.dataclass(frozen=True)
class PhaseWindow:
    name: str
    order: int
    start_day: int
    end_day: int
    task_ids: tuple[str, ...]

    def status_at(self, today: int) -> PhaseStatus:
        if today < self.start_day:
            return PhaseStatus.NOT_STARTED
        if today >= self.end_day:
            return PhaseStatus.DONE
        return PhaseStatus.IN_PROGRESS

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "order": self.order,
            "start_day": self.start_day,
            "end_day": self.end_day,
            "task_ids": list(self.task_ids),
        }


@dataclasses.dataclass(frozen=True)
class Milestone:
    id: str
    title: str
    due_day: int
    projected_day: int
    requires: tuple[str, ...]
    phase: str | None

    @property
    def slipping(self) -> bool:
        """True when required work is projected to finish after the due day."""
        return self.projected_day > self.due_day

    @property
    def slip_days(self) -> int:
        return max(0, self.projected_day - self.due_day)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "due_day": self.due_day,
            "projected_day": self.projected_day,
            "requires": list(self.requires),
            "phase": self.phase,
            "slipping": self.slipping,
            "slip_days": self.slip_days,
        }


@dataclasses.dataclass(frozen=True)
class ProgramPlan:
    goal: str
    horizon_days: int
    tasks: tuple[ScheduledTask, ...]
    phases: tuple[PhaseWindow, ...]
    milestones: tuple[Milestone, ...]

    def task(self, task_id: str) -> ScheduledTask:
        for t in self.tasks:
            if t.id == task_id:
                return t
        raise KeyError(task_id)

    @property
    def span_days(self) -> int:
        """Last scheduled day across all tasks (0 for an empty plan)."""
        return max((t.end_day for t in self.tasks), default=0)

    @property
    def overflows_horizon(self) -> bool:
        return self.span_days > self.horizon_days

    def to_dict(self) -> dict[str, object]:
        return {
            "goal": self.goal,
            "horizon_days": self.horizon_days,
            "span_days": self.span_days,
            "overflows_horizon": self.overflows_horizon,
            "tasks": [t.to_dict() for t in self.tasks],
            "phases": [p.to_dict() for p in self.phases],
            "milestones": [m.to_dict() for m in self.milestones],
        }


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class PhaseStatusLine:
    name: str
    status: PhaseStatus
    start_day: int
    end_day: int

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status.value,
            "start_day": self.start_day,
            "end_day": self.end_day,
        }


@dataclasses.dataclass(frozen=True)
class RiskItem:
    kind: RiskKind
    ref_id: str
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind.value, "ref_id": self.ref_id, "detail": self.detail}


@dataclasses.dataclass(frozen=True)
class StatusReport:
    """Risk + phase-status snapshot for a single day (the midpoint report is one)."""

    day: int
    horizon_days: int
    is_midpoint: bool
    phase_status: tuple[PhaseStatusLine, ...]
    risks: tuple[RiskItem, ...]

    @property
    def at_risk_ref_ids(self) -> tuple[str, ...]:
        return tuple(r.ref_id for r in self.risks)

    def risks_of(self, kind: RiskKind) -> tuple[RiskItem, ...]:
        return tuple(r for r in self.risks if r.kind == kind)

    def to_dict(self) -> dict[str, object]:
        return {
            "day": self.day,
            "horizon_days": self.horizon_days,
            "is_midpoint": self.is_midpoint,
            "phase_status": [line.to_dict() for line in self.phase_status],
            "risks": [r.to_dict() for r in self.risks],
        }

    def render(self) -> str:
        label = "MIDPOINT" if self.is_midpoint else "STATUS"
        lines = [f"{label} REPORT -- day {self.day}/{self.horizon_days}", "", "Phase status:"]
        for line in self.phase_status:
            lines.append(f"  [{line.status.value:>11}] {line.name} (days {line.start_day}-{line.end_day})")
        lines.append("")
        if self.risks:
            lines.append(f"Risks ({len(self.risks)}):")
            for r in self.risks:
                lines.append(f"  ({r.kind.value}) {r.ref_id}: {r.detail}")
        else:
            lines.append("Risks: none")
        return "\n".join(lines)


@dataclasses.dataclass(frozen=True)
class PhaseTransitionReport:
    """Fires on a boundary day where one or more phases end and/or begin."""

    day: int
    ending: tuple[str, ...]
    starting: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"day": self.day, "ending": list(self.ending), "starting": list(self.starting)}

    def render(self) -> str:
        parts = [f"PHASE TRANSITION -- day {self.day}"]
        if self.ending:
            parts.append("  completed: " + ", ".join(self.ending))
        if self.starting:
            parts.append("  starting:  " + ", ".join(self.starting))
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class ProgramManager:
    """Builds a bounded program plan from a goal + tasks and reports on it.

    The plan is built eagerly in the constructor and exposed as
    :attr:`plan`. Report methods take an injected ``today`` (or derive the
    midpoint from the horizon) so the whole surface is clock-free and
    deterministic.
    """

    def __init__(
        self,
        goal: str,
        tasks: Sequence[TaskSpec],
        milestones: Sequence[MilestoneSpec] = (),
        *,
        horizon_days: int = DEFAULT_HORIZON_DAYS,
    ) -> None:
        if horizon_days < 1:
            raise ProgramPlanError("horizon_days must be >= 1")
        self.goal = goal
        self.horizon_days = horizon_days
        self.plan = self._build_plan(tasks, milestones)

    # -- construction --------------------------------------------------------

    def _build_plan(self, tasks: Sequence[TaskSpec], milestones: Sequence[MilestoneSpec]) -> ProgramPlan:
        specs = list(tasks)
        by_id: dict[str, TaskSpec] = {}
        for spec in specs:
            if spec.id in by_id:
                raise ProgramPlanError(f"duplicate task id: {spec.id!r}")
            if spec.effort_days < 1:
                raise ProgramPlanError(f"task {spec.id!r} effort_days must be >= 1")
            by_id[spec.id] = spec
        for spec in specs:
            for dep in spec.deps:
                if dep not in by_id:
                    raise ProgramPlanError(f"task {spec.id!r} depends on unknown task {dep!r}")

        order = self._topological_order(specs, by_id)
        scheduled = self._schedule(order, by_id)

        phases = self._build_phases(specs, scheduled)
        built_milestones = self._build_milestones(milestones, scheduled)
        return ProgramPlan(
            goal=self.goal,
            horizon_days=self.horizon_days,
            tasks=tuple(scheduled[spec.id] for spec in specs),
            phases=phases,
            milestones=built_milestones,
        )

    @staticmethod
    def _topological_order(specs: Sequence[TaskSpec], by_id: Mapping[str, TaskSpec]) -> list[str]:
        """Kahn's algorithm with input-order tie-breaking; raises on cycles."""
        index = {spec.id: i for i, spec in enumerate(specs)}
        indegree = {spec.id: len(set(spec.deps)) for spec in specs}
        dependents: dict[str, list[str]] = {spec.id: [] for spec in specs}
        for spec in specs:
            for dep in set(spec.deps):
                dependents[dep].append(spec.id)

        ready = sorted((tid for tid, d in indegree.items() if d == 0), key=lambda t: index[t])
        result: list[str] = []
        while ready:
            current = ready.pop(0)
            result.append(current)
            newly_ready: list[str] = []
            for child in dependents[current]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    newly_ready.append(child)
            if newly_ready:
                ready.extend(newly_ready)
                ready.sort(key=lambda t: index[t])

        if len(result) != len(specs):
            remaining = sorted(set(index) - set(result), key=lambda t: index[t])
            raise ProgramPlanError(f"dependency cycle among tasks: {remaining}")
        return result

    @staticmethod
    def _schedule(order: Sequence[str], by_id: Mapping[str, TaskSpec]) -> dict[str, ScheduledTask]:
        scheduled: dict[str, ScheduledTask] = {}
        for tid in order:
            spec = by_id[tid]
            start = max((scheduled[dep].end_day for dep in spec.deps), default=0)
            scheduled[tid] = ScheduledTask(
                id=spec.id,
                title=spec.title,
                phase=spec.phase,
                start_day=start,
                end_day=start + spec.effort_days,
                deps=tuple(spec.deps),
            )
        return scheduled

    @staticmethod
    def _build_phases(specs: Sequence[TaskSpec], scheduled: Mapping[str, ScheduledTask]) -> tuple[PhaseWindow, ...]:
        order: list[str] = []
        members: dict[str, list[str]] = {}
        for spec in specs:
            if spec.phase not in members:
                members[spec.phase] = []
                order.append(spec.phase)
            members[spec.phase].append(spec.id)

        windows: list[PhaseWindow] = []
        for i, name in enumerate(order):
            task_ids = members[name]
            start = min(scheduled[t].start_day for t in task_ids)
            end = max(scheduled[t].end_day for t in task_ids)
            windows.append(PhaseWindow(name=name, order=i, start_day=start, end_day=end, task_ids=tuple(task_ids)))
        return tuple(windows)

    @staticmethod
    def _build_milestones(
        milestones: Sequence[MilestoneSpec], scheduled: Mapping[str, ScheduledTask]
    ) -> tuple[Milestone, ...]:
        built: list[Milestone] = []
        for spec in milestones:
            for req in spec.requires:
                if req not in scheduled:
                    raise ProgramPlanError(f"milestone {spec.id!r} requires unknown task {req!r}")
            projected = max((scheduled[req].end_day for req in spec.requires), default=spec.due_day)
            built.append(
                Milestone(
                    id=spec.id,
                    title=spec.title,
                    due_day=spec.due_day,
                    projected_day=projected,
                    requires=tuple(spec.requires),
                    phase=spec.phase,
                )
            )
        return tuple(built)

    # -- reporting -----------------------------------------------------------

    @property
    def midpoint_day(self) -> int:
        return self.horizon_days // 2

    def status_report(
        self,
        today: int,
        progress: Mapping[str, object] | None = None,
    ) -> StatusReport:
        """Phase-status + risk snapshot for ``today`` (an injected day index)."""
        states = {tid: _normalize_state(val) for tid, val in (progress or {}).items()}
        phase_status = tuple(
            PhaseStatusLine(
                name=p.name,
                status=p.status_at(today),
                start_day=p.start_day,
                end_day=p.end_day,
            )
            for p in self.plan.phases
        )
        risks = self._collect_risks(today, states)
        return StatusReport(
            day=today,
            horizon_days=self.horizon_days,
            is_midpoint=(today == self.midpoint_day),
            phase_status=phase_status,
            risks=risks,
        )

    def midpoint_report(self, progress: Mapping[str, object] | None = None) -> StatusReport:
        """Automatic midpoint (day ``horizon // 2``) risk/phase report."""
        return self.status_report(self.midpoint_day, progress=progress)

    def _collect_risks(self, today: int, states: Mapping[str, TaskState]) -> tuple[RiskItem, ...]:
        risks: list[RiskItem] = []
        # Slipping milestones -- static (baseline schedule) plus runtime slip.
        for m in self.plan.milestones:
            reasons: list[str] = []
            if m.slipping:
                reasons.append(f"projected day {m.projected_day} > due day {m.due_day}")
            runtime_blockers = [
                req
                for req in m.requires
                if states.get(req) == TaskState.BLOCKED
                or (self.plan.task(req).end_day <= today and states.get(req) not in (TaskState.DONE, None))
            ]
            if runtime_blockers and not m.slipping:
                reasons.append("required tasks behind: " + ", ".join(runtime_blockers))
            if reasons:
                risks.append(
                    RiskItem(
                        kind=RiskKind.SLIPPING_MILESTONE,
                        ref_id=m.id,
                        detail=f"{m.title}: " + "; ".join(reasons),
                    )
                )
        # Runtime task risks (only meaningful when progress is supplied).
        for task in self.plan.tasks:
            state = states.get(task.id)
            if state == TaskState.BLOCKED:
                risks.append(
                    RiskItem(
                        kind=RiskKind.BLOCKED_TASK,
                        ref_id=task.id,
                        detail=f"{task.title}: reported blocked",
                    )
                )
            elif state is not None and state != TaskState.DONE and task.end_day <= today:
                risks.append(
                    RiskItem(
                        kind=RiskKind.OVERDUE_TASK,
                        ref_id=task.id,
                        detail=(f"{task.title}: planned end day {task.end_day} passed, still {state.value}"),
                    )
                )
        return tuple(risks)

    def phase_transition_report(self, today: int) -> PhaseTransitionReport | None:
        """Report for ``today`` iff a phase ends and/or begins on that day."""
        ending = tuple(p.name for p in self.plan.phases if p.end_day == today)
        starting = tuple(p.name for p in self.plan.phases if p.start_day == today)
        if not ending and not starting:
            return None
        return PhaseTransitionReport(day=today, ending=ending, starting=starting)

    def phase_transitions(self) -> tuple[PhaseTransitionReport, ...]:
        """Every phase-boundary report across the plan, in day order."""
        boundary_days = sorted({p.start_day for p in self.plan.phases} | {p.end_day for p in self.plan.phases})
        reports: list[PhaseTransitionReport] = []
        for day in boundary_days:
            report = self.phase_transition_report(day)
            if report is not None:
                reports.append(report)
        return tuple(reports)
