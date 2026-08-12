"""Spend metering with per-agent attribution, projection, budgets, and downshift.

This is a core-clean module (no imports from ``thomas.agent`` / ``thomas.server``
/ ``thomas.tools``). It gives Thomas *policy-driven* cost control rather than
mere reporting:

1. **Per-agent attribution** -- :meth:`MeteringEngine.record_spend` accumulates
   tokens and USD cost keyed by ``agent_id``; agents are isolated from each
   other and roll up into a global aggregate.

2. **Spend projection** -- :meth:`MeteringEngine.project` extrapolates
   end-of-period spend from the run-rate observed so far using a documented
   linear model:

       ``projected = actual / elapsed_fraction``

   where ``elapsed_fraction`` is the fraction of the billing period that has
   elapsed according to an *injected clock* (``now = clock()``). The fraction is
   clamped to ``(EPSILON, 1.0]`` so the projection is defined at the very start
   of a period and never *under*-projects once the period is over.

3. **Budgets + alerts** -- per-agent and global budgets carry alert thresholds
   (default 80% warning, 100% breach). When *actual or projected* spend crosses
   a threshold a structured :class:`Alert` is emitted. Alerts fire once per
   (scope, threshold, basis) and are deduplicated durably.

4. **Policy-driven downshift** -- when an agent is over budget (or projected to
   be), :meth:`MeteringEngine.downshift_decision` recommends a cheaper tier via
   an ordered tier ladder, returning a :class:`DownshiftDecision` carrying the
   reason. Spend is thereby controlled by policy, not only reported.

State persists durably as JSON at ``THOMAS_METERING_PATH`` (env-overridable).
All time comes from the injected clock, so behaviour is fully deterministic.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1

#: Smallest elapsed fraction used when projecting, so a projection is defined at
#: the instant a period opens (avoids division by zero / runaway extrapolation).
EPSILON = 1e-9

#: Default billing-period length (30 days) when none is supplied.
DEFAULT_PERIOD = timedelta(days=30)

#: Default alert thresholds as fractions of budget: 80% warning, 100% breach.
DEFAULT_THRESHOLDS: tuple[float, ...] = (0.8, 1.0)

#: Default tier ladder, most expensive first. Downshift walks toward the tail.
DEFAULT_TIERS: tuple[str, ...] = ("premium", "standard", "economy")

#: Sentinel agent id used for the global (all-agents) aggregate scope.
GLOBAL_SCOPE = "__global__"

#: A threshold at/above this fraction is a "breach"; below it is a "warning".
BREACH_AT = 1.0


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Alert:
    """A structured budget alert emitted when spend crosses a threshold."""

    scope: str  # "agent" | "global"
    agent_id: str  # concrete agent id, or GLOBAL_SCOPE for the global scope
    kind: str  # "warning" | "breach"
    basis: str  # "actual" | "projected"
    threshold: float  # fraction of budget crossed (e.g. 0.8, 1.0)
    budget: float
    spend: float
    ratio: float  # spend / budget
    ts: str  # ISO-8601 timestamp from the injected clock

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "agent_id": self.agent_id,
            "kind": self.kind,
            "basis": self.basis,
            "threshold": self.threshold,
            "budget": self.budget,
            "spend": self.spend,
            "ratio": self.ratio,
            "ts": self.ts,
        }


@dataclass(frozen=True)
class Projection:
    """Linear end-of-period spend projection for a scope."""

    scope: str
    agent_id: str
    actual_spend: float
    elapsed_fraction: float
    projected_spend: float
    period_start: str
    period_end: str


@dataclass(frozen=True)
class DownshiftDecision:
    """Policy recommendation to keep an agent's spend under control."""

    agent_id: str
    downshift: bool
    current_tier: str
    recommended_tier: str
    reason: str
    basis: str  # "actual" | "projected" | "" when no downshift
    ratio: float


@dataclass
class _AgentState:
    cost: float = 0.0
    tokens: int = 0
    tier: str = ""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


@dataclass
class _Config:
    period_start: datetime
    period_length: timedelta
    thresholds: tuple[float, ...]
    tiers: tuple[str, ...]
    downshift_ratio: float
    global_budget: float | None
    budgets: dict[str, float] = field(default_factory=dict)


class MeteringEngine:
    """Meter spend per agent with projection, budgets, alerts, and downshift.

    Parameters
    ----------
    path:
        JSON persistence file. Defaults to ``THOMAS_METERING_PATH`` or
        ``<repo>/thomas_metering.json``.
    clock:
        Zero-arg callable returning the current :class:`datetime`. Injected for
        determinism; defaults to :func:`datetime.now`.
    period_start / period_length:
        Define the billing period used for projection. ``period_start`` defaults
        to ``clock()`` at construction; ``period_length`` defaults to 30 days.
    thresholds:
        Alert thresholds as budget fractions (default ``(0.8, 1.0)``).
    tiers:
        Ordered tier ladder, most expensive first (default premium/standard/economy).
    downshift_ratio:
        Spend/budget ratio at or above which an agent is downshifted (default 1.0).
    """

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        period_start: datetime | None = None,
        period_length: timedelta | None = None,
        thresholds: tuple[float, ...] | None = None,
        tiers: tuple[str, ...] | None = None,
        downshift_ratio: float = BREACH_AT,
        global_budget: float | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._clock: Callable[[], datetime] = clock or datetime.now

        repo_root = Path(__file__).resolve().parents[2]
        self._path = Path(
            path
            if path is not None
            else os.environ.get("THOMAS_METERING_PATH", str(repo_root / "thomas_metering.json"))
        )

        thresholds = tuple(sorted(float(t) for t in (thresholds or DEFAULT_THRESHOLDS)))
        tiers = tuple(tiers or DEFAULT_TIERS)
        if not tiers:
            raise ValueError("tiers must be non-empty")

        start = period_start or self._clock()
        self._cfg = _Config(
            period_start=start,
            period_length=period_length or DEFAULT_PERIOD,
            thresholds=thresholds,
            tiers=tiers,
            downshift_ratio=float(downshift_ratio),
            global_budget=(float(global_budget) if global_budget is not None else None),
        )

        self._agents: dict[str, _AgentState] = {}
        # Fired-alert keys: (scope, agent_id, basis, threshold) -> dedup.
        self._fired: set[tuple[str, str, str, float]] = set()

        self._load()

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_budget(self, agent_id: str, amount: float) -> None:
        """Set (or clear, with ``amount<=0``) an agent's spend budget in USD."""
        with self._lock:
            aid = self._norm_agent(agent_id)
            if amount is None or float(amount) <= 0:
                self._cfg.budgets.pop(aid, None)
            else:
                self._cfg.budgets[aid] = float(amount)
            self._save()

    def set_global_budget(self, amount: float | None) -> None:
        """Set (or clear with ``None``/``<=0``) the aggregate global budget."""
        with self._lock:
            self._cfg.global_budget = float(amount) if amount and float(amount) > 0 else None
            self._save()

    def set_tier(self, agent_id: str, tier: str) -> None:
        """Pin an agent's current tier (must be a member of the tier ladder)."""
        with self._lock:
            if tier not in self._cfg.tiers:
                raise ValueError(f"unknown tier {tier!r}; known: {self._cfg.tiers}")
            st = self._agent(agent_id)
            st.tier = tier
            self._save()

    # ------------------------------------------------------------------
    # Metering
    # ------------------------------------------------------------------

    def record_spend(self, agent_id: str, tokens: int, cost: float) -> list[Alert]:
        """Attribute ``tokens``/``cost`` to ``agent_id`` and return new alerts.

        Negative inputs are clamped to zero. Alerts newly crossed by this record
        (across every scope, threshold, and basis) are returned in a stable
        order (agent scope before global; warning before breach); previously
        fired alerts are not repeated.
        """
        with self._lock:
            st = self._agent(agent_id)
            st.cost += max(0.0, float(cost or 0.0))
            st.tokens += max(0, int(tokens or 0))
            alerts = self._evaluate_alerts()
            self._save()
            return alerts

    def agent_spend(self, agent_id: str) -> float:
        with self._lock:
            st = self._agents.get(self._norm_agent(agent_id))
            return float(st.cost) if st else 0.0

    def agent_tokens(self, agent_id: str) -> int:
        with self._lock:
            st = self._agents.get(self._norm_agent(agent_id))
            return int(st.tokens) if st else 0

    def global_spend(self) -> float:
        """Aggregate spend across all attributed agents."""
        with self._lock:
            return float(sum(s.cost for s in self._agents.values()))

    def global_tokens(self) -> int:
        with self._lock:
            return int(sum(s.tokens for s in self._agents.values()))

    def agent_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._agents.keys())

    # ------------------------------------------------------------------
    # Projection
    # ------------------------------------------------------------------

    def elapsed_fraction(self) -> float:
        """Fraction of the billing period elapsed, clamped to ``(EPSILON, 1.0]``."""
        now = self._clock()
        elapsed = (now - self._cfg.period_start).total_seconds()
        length = self._cfg.period_length.total_seconds()
        if length <= 0:
            return 1.0
        frac = elapsed / length
        if frac < EPSILON:
            return EPSILON
        if frac > 1.0:
            return 1.0
        return frac

    def project(self, agent_id: str | None = None) -> Projection:
        """Linear end-of-period projection for an agent (or the global scope).

        ``projected = actual / elapsed_fraction``. With ``agent_id=None`` the
        projection is for the aggregated global spend.
        """
        with self._lock:
            frac = self.elapsed_fraction()
            if agent_id is None:
                scope, aid, actual = "global", GLOBAL_SCOPE, self.global_spend()
            else:
                scope, aid, actual = "agent", self._norm_agent(agent_id), self.agent_spend(agent_id)
            projected = actual / frac
            end = self._cfg.period_start + self._cfg.period_length
            return Projection(
                scope=scope,
                agent_id=aid,
                actual_spend=float(actual),
                elapsed_fraction=float(frac),
                projected_spend=float(projected),
                period_start=self._cfg.period_start.isoformat(),
                period_end=end.isoformat(),
            )

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    def active_alerts(self) -> list[Alert]:
        """Return every threshold currently crossed (idempotent; no dedup mutation)."""
        with self._lock:
            return self._compute_alerts()

    def _evaluate_alerts(self) -> list[Alert]:
        """Compute crossings and return only those not previously fired."""
        new: list[Alert] = []
        for alert in self._compute_alerts():
            key = (alert.scope, alert.agent_id, alert.basis, alert.threshold)
            if key not in self._fired:
                self._fired.add(key)
                new.append(alert)
        return new

    def _compute_alerts(self) -> list[Alert]:
        ts = self._clock().isoformat()
        frac = self.elapsed_fraction()
        out: list[Alert] = []

        # Per-agent scopes first (sorted for determinism), then global.
        for aid in sorted(self._cfg.budgets.keys()):
            budget = self._cfg.budgets[aid]
            if budget <= 0:
                continue
            actual = self.agent_spend(aid)
            out.extend(self._alerts_for("agent", aid, budget, actual, actual / frac, ts))

        if self._cfg.global_budget and self._cfg.global_budget > 0:
            actual = self.global_spend()
            out.extend(self._alerts_for("global", GLOBAL_SCOPE, self._cfg.global_budget, actual, actual / frac, ts))
        return out

    def _alerts_for(
        self,
        scope: str,
        agent_id: str,
        budget: float,
        actual: float,
        projected: float,
        ts: str,
    ) -> list[Alert]:
        out: list[Alert] = []
        for basis, spend in (("actual", actual), ("projected", projected)):
            ratio = spend / budget if budget > 0 else 0.0
            for threshold in self._cfg.thresholds:
                if ratio + EPSILON >= threshold:
                    out.append(
                        Alert(
                            scope=scope,
                            agent_id=agent_id,
                            kind="breach" if threshold >= BREACH_AT else "warning",
                            basis=basis,
                            threshold=float(threshold),
                            budget=float(budget),
                            spend=float(spend),
                            ratio=float(ratio),
                            ts=ts,
                        )
                    )
        return out

    # ------------------------------------------------------------------
    # Downshift policy
    # ------------------------------------------------------------------

    def downshift_decision(self, agent_id: str) -> DownshiftDecision:
        """Recommend a cheaper tier when an agent is over (or projected over) budget.

        An agent is downshifted when either actual or projected spend reaches
        ``downshift_ratio`` (default 1.0) of its budget. Actual overage takes
        precedence over a projected overage in the stated reason.
        """
        with self._lock:
            aid = self._norm_agent(agent_id)
            current = self._current_tier(aid)
            budget = self._cfg.budgets.get(aid)
            if not budget or budget <= 0:
                return DownshiftDecision(aid, False, current, current, "no budget configured", "", 0.0)

            actual = self.agent_spend(aid)
            frac = self.elapsed_fraction()
            projected = actual / frac
            actual_ratio = actual / budget
            projected_ratio = projected / budget
            limit = self._cfg.downshift_ratio

            if actual_ratio + EPSILON >= limit:
                basis, ratio = "actual", actual_ratio
            elif projected_ratio + EPSILON >= limit:
                basis, ratio = "projected", projected_ratio
            else:
                return DownshiftDecision(aid, False, current, current, "within budget", "", float(actual_ratio))

            recommended = self._cheaper_tier(current)
            reason = (
                f"{basis} spend {ratio * 100:.1f}% of budget "
                f"(limit {limit * 100:.0f}%); downshift {current} -> {recommended}"
            )
            return DownshiftDecision(aid, True, current, recommended, reason, basis, float(ratio))

    def _current_tier(self, agent_id: str) -> str:
        st = self._agents.get(agent_id)
        if st and st.tier:
            return st.tier
        return self._cfg.tiers[0]

    def _cheaper_tier(self, tier: str) -> str:
        tiers = self._cfg.tiers
        try:
            idx = tiers.index(tier)
        except ValueError:
            return tiers[-1]
        return tiers[min(idx + 1, len(tiers) - 1)]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _snapshot(self) -> dict[str, Any]:
        return {
            "version": SCHEMA_VERSION,
            "period_start": self._cfg.period_start.isoformat(),
            "period_seconds": self._cfg.period_length.total_seconds(),
            "thresholds": list(self._cfg.thresholds),
            "tiers": list(self._cfg.tiers),
            "downshift_ratio": self._cfg.downshift_ratio,
            "global_budget": self._cfg.global_budget,
            "budgets": dict(self._cfg.budgets),
            "agents": {
                aid: {"cost": st.cost, "tokens": st.tokens, "tier": st.tier} for aid, st in sorted(self._agents.items())
            },
            "fired": sorted([list(k) for k in self._fired]),
        }

    def _save(self) -> None:
        payload = json.dumps(self._snapshot(), ensure_ascii=False, indent=2, sort_keys=True)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self._path)

    def _load(self) -> None:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        data = json.loads(raw)

        ps = data.get("period_start")
        if isinstance(ps, str):
            self._cfg.period_start = datetime.fromisoformat(ps)
        secs = data.get("period_seconds")
        if isinstance(secs, (int, float)) and secs > 0:
            self._cfg.period_length = timedelta(seconds=float(secs))
        thresholds = data.get("thresholds")
        if isinstance(thresholds, list) and thresholds:
            self._cfg.thresholds = tuple(sorted(float(t) for t in thresholds))
        tiers = data.get("tiers")
        if isinstance(tiers, list) and tiers:
            self._cfg.tiers = tuple(str(t) for t in tiers)
        dr = data.get("downshift_ratio")
        if isinstance(dr, (int, float)):
            self._cfg.downshift_ratio = float(dr)
        gb = data.get("global_budget")
        self._cfg.global_budget = float(gb) if isinstance(gb, (int, float)) else None

        budgets = data.get("budgets")
        if isinstance(budgets, dict):
            self._cfg.budgets = {str(k): float(v) for k, v in budgets.items()}

        agents = data.get("agents")
        if isinstance(agents, dict):
            for aid, row in agents.items():
                if not isinstance(row, dict):
                    continue
                self._agents[str(aid)] = _AgentState(
                    cost=float(row.get("cost", 0.0) or 0.0),
                    tokens=int(row.get("tokens", 0) or 0),
                    tier=str(row.get("tier", "") or ""),
                )

        fired = data.get("fired")
        if isinstance(fired, list):
            for item in fired:
                if isinstance(item, list) and len(item) == 4:
                    self._fired.add((str(item[0]), str(item[1]), str(item[2]), float(item[3])))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _norm_agent(agent_id: str) -> str:
        aid = (agent_id or "").strip()
        if not aid:
            raise ValueError("agent_id must be a non-empty string")
        return aid

    def _agent(self, agent_id: str) -> _AgentState:
        aid = self._norm_agent(agent_id)
        st = self._agents.get(aid)
        if st is None:
            st = _AgentState(tier=self._cfg.tiers[0])
            self._agents[aid] = st
        return st


__all__ = [
    "Alert",
    "DownshiftDecision",
    "MeteringEngine",
    "Projection",
    "DEFAULT_THRESHOLDS",
    "DEFAULT_TIERS",
    "GLOBAL_SCOPE",
]
