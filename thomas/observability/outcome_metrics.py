"""Agent adoption/outcome metrics + counterfactual productivity dashboard (CAP-129).

Records per-agent, per-period **outcome** metrics for the work an agent does --
tasks completed, whether each was *accepted* or *rejected*, the time-to-complete,
and the number of *human edits* made *after* the agent handed the task off -- and
turns them into a **counterfactual productivity estimate**: how much time/effort
the agent saved (or cost) versus an injected *without-agent baseline* of what the
same work would have taken a human.

The whole thing is exposed as dashboard-ready data via :class:`ProductivityDashboard`:
a per-agent row (outcome summary + counterfactual), a summed *aggregate*, and the
baseline it was computed against. Every number is deterministic given the stored
outcomes and the injected baseline -- there is no wall-clock or RNG in the math.

Counterfactual formula (per agent, over the outcomes in scope)
--------------------------------------------------------------
``baseline_cost_s      = baseline.human_seconds_per_task * accepted``
``agent_active_s       = sum(time_to_complete_s over all outcomes)``
``rework_cost_s        = baseline.seconds_per_human_edit * sum(human_edits_after)``
``agent_effective_s    = agent_active_s + rework_cost_s``
``delta_s              = baseline_cost_s - agent_effective_s``

A *positive* ``delta_s`` means the agent produced the accepted work for less
effort than the human baseline would have -- i.e. net time saved. Only *accepted*
tasks earn baseline credit (rejected work delivered no value a human would have
had to reproduce), while the agent is still charged for the time it spent on both
accepted and rejected tasks plus the human rework its output required. A
zero-activity agent yields all-zero numbers and a ``delta_s`` of ``0.0``.

Persistence is SQLite so a fresh store opened on the same path sees previously
recorded outcomes. The path resolves from the explicit ``path`` argument, then the
``THOMAS_OUTCOME_METRICS_DB_PATH`` environment variable, then the Thomas data dir.

This module lives in the ``observability`` (infra) tier and only imports from
``core`` and the standard library.
"""

from __future__ import annotations

import os
import sqlite3
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from thomas.core.config import resolve_thomas_data_dir

ENV_DB_PATH = "THOMAS_OUTCOME_METRICS_DB_PATH"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_outcomes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  outcome_id TEXT NOT NULL UNIQUE,
  agent_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  period TEXT NOT NULL DEFAULT '',
  accepted INTEGER NOT NULL,
  time_to_complete_s REAL NOT NULL,
  human_edits_after INTEGER NOT NULL DEFAULT 0,
  recorded_at REAL
);

CREATE INDEX IF NOT EXISTS idx_agent_outcomes_agent ON agent_outcomes(agent_id, id);
CREATE INDEX IF NOT EXISTS idx_agent_outcomes_period ON agent_outcomes(period, id);
CREATE INDEX IF NOT EXISTS idx_agent_outcomes_agent_period
  ON agent_outcomes(agent_id, period, id);
"""


def resolve_outcome_metrics_db_path(path: str | Path | None = None) -> Path:
    """Resolve the outcome-metrics DB path from the argument, env, then data dir."""

    if path:
        return Path(path)
    env = os.getenv(ENV_DB_PATH, "").strip()
    if env:
        return Path(env)
    return resolve_thomas_data_dir() / ".thomas" / "outcome_metrics.sqlite3"


@dataclass(frozen=True)
class Baseline:
    """The injected *without-agent* cost model the counterfactual runs against.

    Parameters
    ----------
    human_seconds_per_task:
        Time a human would spend to produce the value of one *accepted* task
        without the agent. Drives the baseline credit.
    seconds_per_human_edit:
        Cost charged for each human edit made *after* the agent's handoff --
        the rework the agent's output still required. Defaults to ``0.0``.
    """

    human_seconds_per_task: float
    seconds_per_human_edit: float = 0.0


@dataclass
class AgentOutcome:
    """A single recorded outcome for one task handled by one agent.

    ``accepted`` distinguishes accepted vs rejected work; ``time_to_complete_s``
    is how long the agent took; ``human_edits_after`` counts edits a human made
    to the agent's output afterwards. ``period`` buckets the outcome (e.g.
    ``"2026-07"``); an empty string means unbucketed.
    """

    agent_id: str
    task_id: str
    accepted: bool
    time_to_complete_s: float
    human_edits_after: int = 0
    period: str = ""
    recorded_at: float | None = None
    outcome_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @classmethod
    def _from_row(cls, row: sqlite3.Row) -> AgentOutcome:
        return cls(
            agent_id=row["agent_id"],
            task_id=row["task_id"],
            accepted=bool(row["accepted"]),
            time_to_complete_s=row["time_to_complete_s"],
            human_edits_after=row["human_edits_after"],
            period=row["period"],
            recorded_at=row["recorded_at"],
            outcome_id=row["outcome_id"],
        )


@dataclass(frozen=True)
class AgentOutcomeSummary:
    """Aggregated outcome counts for one agent over the outcomes in scope."""

    agent_id: str
    tasks_completed: int
    accepted: int
    rejected: int
    total_time_to_complete_s: float
    total_human_edits_after: int
    avg_time_to_complete_s: float
    acceptance_rate: float

    @classmethod
    def empty(cls, agent_id: str) -> AgentOutcomeSummary:
        """A zero-activity summary (no recorded outcomes)."""

        return cls(
            agent_id=agent_id,
            tasks_completed=0,
            accepted=0,
            rejected=0,
            total_time_to_complete_s=0.0,
            total_human_edits_after=0,
            avg_time_to_complete_s=0.0,
            acceptance_rate=0.0,
        )

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "tasks_completed": self.tasks_completed,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "total_time_to_complete_s": self.total_time_to_complete_s,
            "total_human_edits_after": self.total_human_edits_after,
            "avg_time_to_complete_s": self.avg_time_to_complete_s,
            "acceptance_rate": self.acceptance_rate,
        }


@dataclass(frozen=True)
class CounterfactualEstimate:
    """Counterfactual productivity numbers vs the injected baseline.

    ``delta_s`` is the headline: ``baseline_cost_s - agent_effective_s``,
    positive when the agent net-saved time.
    """

    baseline_cost_s: float
    agent_active_s: float
    rework_cost_s: float
    agent_effective_s: float
    delta_s: float

    @classmethod
    def zero(cls) -> CounterfactualEstimate:
        return cls(
            baseline_cost_s=0.0,
            agent_active_s=0.0,
            rework_cost_s=0.0,
            agent_effective_s=0.0,
            delta_s=0.0,
        )

    def to_dict(self) -> dict:
        return {
            "baseline_cost_s": self.baseline_cost_s,
            "agent_active_s": self.agent_active_s,
            "rework_cost_s": self.rework_cost_s,
            "agent_effective_s": self.agent_effective_s,
            "delta_s": self.delta_s,
        }


@dataclass(frozen=True)
class AgentDashboardRow:
    """One dashboard row: an agent's outcome summary + its counterfactual."""

    summary: AgentOutcomeSummary
    counterfactual: CounterfactualEstimate

    def to_dict(self) -> dict:
        return {
            "summary": self.summary.to_dict(),
            "counterfactual": self.counterfactual.to_dict(),
        }


@dataclass(frozen=True)
class ProductivityDashboard:
    """Dashboard-ready view: per-agent rows, the baseline, and the aggregate.

    ``aggregate`` is the element-wise sum of every row's counterfactual, so
    ``aggregate.delta_s`` equals the total time saved across all agents.
    """

    period: str | None
    baseline: Baseline
    agents: tuple[AgentDashboardRow, ...]
    aggregate: CounterfactualEstimate
    total_tasks: int
    total_accepted: int
    total_rejected: int

    def row_for(self, agent_id: str) -> AgentDashboardRow | None:
        for row in self.agents:
            if row.summary.agent_id == agent_id:
                return row
        return None

    def to_dict(self) -> dict:
        return {
            "period": self.period,
            "baseline": {
                "human_seconds_per_task": self.baseline.human_seconds_per_task,
                "seconds_per_human_edit": self.baseline.seconds_per_human_edit,
            },
            "agents": [row.to_dict() for row in self.agents],
            "aggregate": self.aggregate.to_dict(),
            "total_tasks": self.total_tasks,
            "total_accepted": self.total_accepted,
            "total_rejected": self.total_rejected,
        }


def summarize_outcomes(agent_id: str, outcomes: Sequence[AgentOutcome]) -> AgentOutcomeSummary:
    """Fold a sequence of outcomes into an :class:`AgentOutcomeSummary`.

    Pure and deterministic. An empty sequence yields a zero-activity summary.
    """

    if not outcomes:
        return AgentOutcomeSummary.empty(agent_id)

    accepted = sum(1 for o in outcomes if o.accepted)
    total = len(outcomes)
    rejected = total - accepted
    total_time = sum(o.time_to_complete_s for o in outcomes)
    total_edits = sum(o.human_edits_after for o in outcomes)
    return AgentOutcomeSummary(
        agent_id=agent_id,
        tasks_completed=total,
        accepted=accepted,
        rejected=rejected,
        total_time_to_complete_s=total_time,
        total_human_edits_after=total_edits,
        avg_time_to_complete_s=total_time / total,
        acceptance_rate=accepted / total,
    )


def counterfactual_from_summary(summary: AgentOutcomeSummary, baseline: Baseline) -> CounterfactualEstimate:
    """Compute the counterfactual estimate for a summary against a baseline.

    Pure and deterministic; implements the module-level formula. A zero-activity
    summary yields :meth:`CounterfactualEstimate.zero`.
    """

    baseline_cost = baseline.human_seconds_per_task * summary.accepted
    agent_active = summary.total_time_to_complete_s
    rework_cost = baseline.seconds_per_human_edit * summary.total_human_edits_after
    agent_effective = agent_active + rework_cost
    return CounterfactualEstimate(
        baseline_cost_s=baseline_cost,
        agent_active_s=agent_active,
        rework_cost_s=rework_cost,
        agent_effective_s=agent_effective,
        delta_s=baseline_cost - agent_effective,
    )


def _sum_estimates(estimates: Iterable[CounterfactualEstimate]) -> CounterfactualEstimate:
    baseline_cost = agent_active = rework_cost = agent_effective = delta = 0.0
    for e in estimates:
        baseline_cost += e.baseline_cost_s
        agent_active += e.agent_active_s
        rework_cost += e.rework_cost_s
        agent_effective += e.agent_effective_s
        delta += e.delta_s
    return CounterfactualEstimate(
        baseline_cost_s=baseline_cost,
        agent_active_s=agent_active,
        rework_cost_s=rework_cost,
        agent_effective_s=agent_effective,
        delta_s=delta,
    )


class OutcomeMetricsStore:
    """Durable store of agent outcome metrics + counterfactual dashboard builder.

    Parameters
    ----------
    path:
        Explicit DB path. Overrides the env var and data-dir defaults.
    clock:
        ``() -> float`` seconds source used to stamp ``recorded_at`` when the
        caller does not supply one. Injectable for deterministic tests; defaults
        to :func:`time.time`.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._path = resolve_outcome_metrics_db_path(path)
        self._now: Callable[[], float] = clock or time.time
        self._ensure_schema()

    @property
    def path(self) -> Path:
        return self._path

    # -- persistence ------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(self._path))
        con.row_factory = sqlite3.Row
        return con

    def _ensure_schema(self) -> None:
        con = self._connect()
        try:
            con.executescript(_SCHEMA)
            con.commit()
        finally:
            con.close()

    # -- recording --------------------------------------------------------
    def record(self, outcome: AgentOutcome) -> str:
        """Persist ``outcome`` and return its ``outcome_id``.

        Stamps ``recorded_at`` from the injected clock when unset. Re-recording
        the same ``outcome_id`` upserts the row.
        """

        if outcome.recorded_at is None:
            outcome.recorded_at = self._now()

        con = self._connect()
        try:
            con.execute(
                """
                INSERT INTO agent_outcomes (
                    outcome_id, agent_id, task_id, period,
                    accepted, time_to_complete_s, human_edits_after, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(outcome_id) DO UPDATE SET
                    agent_id=excluded.agent_id,
                    task_id=excluded.task_id,
                    period=excluded.period,
                    accepted=excluded.accepted,
                    time_to_complete_s=excluded.time_to_complete_s,
                    human_edits_after=excluded.human_edits_after,
                    recorded_at=excluded.recorded_at
                """,
                (
                    outcome.outcome_id,
                    outcome.agent_id,
                    outcome.task_id,
                    outcome.period,
                    1 if outcome.accepted else 0,
                    float(outcome.time_to_complete_s),
                    int(outcome.human_edits_after),
                    outcome.recorded_at,
                ),
            )
            con.commit()
        finally:
            con.close()
        return outcome.outcome_id

    def record_outcome(
        self,
        *,
        agent_id: str,
        task_id: str,
        accepted: bool,
        time_to_complete_s: float,
        human_edits_after: int = 0,
        period: str = "",
        recorded_at: float | None = None,
    ) -> str:
        """Convenience wrapper around :meth:`record` for keyword construction."""

        return self.record(
            AgentOutcome(
                agent_id=agent_id,
                task_id=task_id,
                accepted=accepted,
                time_to_complete_s=time_to_complete_s,
                human_edits_after=human_edits_after,
                period=period,
                recorded_at=recorded_at,
            )
        )

    # -- queries ----------------------------------------------------------
    @staticmethod
    def _rows_to_outcomes(rows: Iterable[sqlite3.Row]) -> list[AgentOutcome]:
        return [AgentOutcome._from_row(r) for r in rows]

    def query_by_agent(self, agent_id: str, *, period: str | None = None) -> list[AgentOutcome]:
        """All outcomes for ``agent_id``, optionally filtered to ``period``."""

        con = self._connect()
        try:
            if period is None:
                rows = con.execute(
                    "SELECT * FROM agent_outcomes WHERE agent_id = ? ORDER BY id",
                    (agent_id,),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM agent_outcomes WHERE agent_id = ? AND period = ? ORDER BY id",
                    (agent_id, period),
                ).fetchall()
        finally:
            con.close()
        return self._rows_to_outcomes(rows)

    def query_by_period(self, period: str) -> list[AgentOutcome]:
        """All outcomes recorded in ``period`` across every agent."""

        con = self._connect()
        try:
            rows = con.execute(
                "SELECT * FROM agent_outcomes WHERE period = ? ORDER BY id",
                (period,),
            ).fetchall()
        finally:
            con.close()
        return self._rows_to_outcomes(rows)

    def agent_ids(self, *, period: str | None = None) -> list[str]:
        """Distinct agent ids with recorded outcomes (optionally in ``period``)."""

        con = self._connect()
        try:
            if period is None:
                rows = con.execute("SELECT DISTINCT agent_id FROM agent_outcomes ORDER BY agent_id").fetchall()
            else:
                rows = con.execute(
                    "SELECT DISTINCT agent_id FROM agent_outcomes WHERE period = ? ORDER BY agent_id",
                    (period,),
                ).fetchall()
        finally:
            con.close()
        return [r["agent_id"] for r in rows]

    def agent_summary(self, agent_id: str, *, period: str | None = None) -> AgentOutcomeSummary:
        """Outcome summary for one agent. Zero-activity agents summarise to zeros."""

        return summarize_outcomes(agent_id, self.query_by_agent(agent_id, period=period))

    # -- dashboard --------------------------------------------------------
    def build_dashboard(
        self,
        baseline: Baseline,
        *,
        period: str | None = None,
        agent_ids: Sequence[str] | None = None,
    ) -> ProductivityDashboard:
        """Build the counterfactual :class:`ProductivityDashboard`.

        Rows cover every agent with outcomes in scope, plus any explicitly named
        in ``agent_ids`` (so a *zero-activity* agent still appears, with all-zero
        numbers). The ``aggregate`` is the element-wise sum of the rows'
        counterfactual estimates. Deterministic given the stored outcomes and
        ``baseline``.
        """

        discovered = self.agent_ids(period=period)
        ids: list[str] = list(discovered)
        if agent_ids:
            for aid in agent_ids:
                if aid not in ids:
                    ids.append(aid)
        ids.sort()

        rows: list[AgentDashboardRow] = []
        total_tasks = total_accepted = total_rejected = 0
        for aid in ids:
            summary = self.agent_summary(aid, period=period)
            estimate = counterfactual_from_summary(summary, baseline)
            rows.append(AgentDashboardRow(summary=summary, counterfactual=estimate))
            total_tasks += summary.tasks_completed
            total_accepted += summary.accepted
            total_rejected += summary.rejected

        aggregate = _sum_estimates(row.counterfactual for row in rows)
        return ProductivityDashboard(
            period=period,
            baseline=baseline,
            agents=tuple(rows),
            aggregate=aggregate,
            total_tasks=total_tasks,
            total_accepted=total_accepted,
            total_rejected=total_rejected,
        )
