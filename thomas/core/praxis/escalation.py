"""Escalation hold on starvation or verification backlog (stage-2 slice 7). No Thomas import; nothing here sends.

LIVE-PLAN-02-DRAFT section 4: no new effort escalation and no new repair offer while any condition holds:
- starvation: a builder has waited for a verdict longer than verdict_wait_s (600 s), or has been queued in the scheduler with
  no admission longer than scheduler_queue_s (300 s);
- verification backlog: more than pending_evaluations_max (2) combined evaluations are pending, or the oldest pending
  evaluation is older than oldest_pending_evaluation_s (600 s).
Every threshold is strict: a value equal to its threshold does not hold.

Nothing is silently skipped. request() records every request as granted (no condition active and nothing already held)
or held (with the conditions active at that moment). A request made while earlier ones are held is held behind them, so
release keeps request order. poll() releases every held request, in order, once no condition is active, and records the
release with how long each was held and the hold period. report() accounts for every request:
requested = granted + released + still_held, and lists the hold periods and anything still held.

Callers (slice 8 wires the coordinator and the seam) apply a granted or released escalation, and never apply a held one.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

KINDS = ("effort_escalation", "repair_offer")


@dataclass(frozen=True)
class Thresholds:
    verdict_wait_s: float = 600.0
    scheduler_queue_s: float = 300.0
    pending_evaluations_max: int = 2
    oldest_pending_evaluation_s: float = 600.0


class EscalationHold:
    def __init__(self, thresholds: Thresholds = Thresholds(), *, clock: Callable[[], float] = time.monotonic) -> None:
        self.thresholds = thresholds
        self._clock = clock
        self._lock = threading.RLock()
        self._waiting_verdict: dict[str, float] = {}
        self._queued: dict[str, float] = {}
        self._pending_evaluations: dict[str, float] = {}
        self._held: list[dict[str, Any]] = []
        self._hold_started: float | None = None
        self._hold_conditions: list[dict[str, Any]] = []
        self._counts = {"requested": 0, "granted": 0, "held": 0, "released": 0}
        self._seq = 0
        self.events: list[dict[str, Any]] = []
        self.hold_periods: list[dict[str, Any]] = []

    def _now(self, now: float | None) -> float:
        return float(self._clock() if now is None else now)

    def _event(self, event: str, now: float, **fields: Any) -> dict[str, Any]:
        self._seq += 1
        row = {"seq": self._seq, "event": event, "at": now, **fields}
        self.events.append(row)
        return row

    # ---- observations ----
    def builder_waiting_for_verdict(self, builder: str, *, now: float | None = None) -> None:
        with self._lock:
            self._waiting_verdict.setdefault(builder, self._now(now))

    def verdict_delivered(self, builder: str) -> None:
        with self._lock:
            self._waiting_verdict.pop(builder, None)

    def builder_queued(self, builder: str, *, now: float | None = None) -> None:
        with self._lock:
            self._queued.setdefault(builder, self._now(now))

    def builder_admitted(self, builder: str) -> None:
        with self._lock:
            self._queued.pop(builder, None)

    def evaluation_pending(self, evaluation_id: str, *, now: float | None = None) -> None:
        with self._lock:
            self._pending_evaluations.setdefault(evaluation_id, self._now(now))

    def evaluation_finished(self, evaluation_id: str) -> None:
        with self._lock:
            self._pending_evaluations.pop(evaluation_id, None)

    # ---- the rule ----
    def conditions(self, now: float | None = None) -> list[dict[str, Any]]:
        with self._lock:
            now = self._now(now)
            t = self.thresholds
            found: list[dict[str, Any]] = []
            for builder, since in sorted(self._waiting_verdict.items()):
                if now - since > t.verdict_wait_s:
                    found.append(
                        {
                            "condition": "starvation_verdict_wait",
                            "subject": builder,
                            "value_s": round(now - since, 6),
                            "threshold_s": t.verdict_wait_s,
                        }
                    )
            for builder, since in sorted(self._queued.items()):
                if now - since > t.scheduler_queue_s:
                    found.append(
                        {
                            "condition": "starvation_scheduler_queue",
                            "subject": builder,
                            "value_s": round(now - since, 6),
                            "threshold_s": t.scheduler_queue_s,
                        }
                    )
            if len(self._pending_evaluations) > t.pending_evaluations_max:
                found.append(
                    {
                        "condition": "backlog_pending_evaluations",
                        "subject": None,
                        "value": len(self._pending_evaluations),
                        "threshold": t.pending_evaluations_max,
                    }
                )
            if self._pending_evaluations:
                oldest, since = min(self._pending_evaluations.items(), key=lambda item: (item[1], item[0]))
                if now - since > t.oldest_pending_evaluation_s:
                    found.append(
                        {
                            "condition": "backlog_oldest_pending_evaluation",
                            "subject": oldest,
                            "value_s": round(now - since, 6),
                            "threshold_s": t.oldest_pending_evaluation_s,
                        }
                    )
            return found

    def request(
        self, kind: str, builder: str, *, detail: dict[str, Any] | None = None, now: float | None = None
    ) -> dict[str, Any]:
        """Record one escalation or repair-offer request; returns the granted or held event."""
        if kind not in KINDS:
            raise ValueError(f"unknown escalation kind {kind!r}")
        with self._lock:
            now = self._now(now)
            self._counts["requested"] += 1
            active = self.conditions(now)
            if not active and not self._held:
                self._counts["granted"] += 1
                return self._event("escalation_granted", now, kind=kind, builder=builder, detail=dict(detail or {}))
            if self._hold_started is None:
                self._hold_started = now
                self._hold_conditions = active
                self._event("hold_started", now, conditions=active)
            row = self._event(
                "escalation_held",
                now,
                kind=kind,
                builder=builder,
                detail=dict(detail or {}),
                conditions=active,
                behind=len(self._held),
            )
            self._held.append(row)
            self._counts["held"] += 1
            return row

    def poll(self, now: float | None = None) -> list[dict[str, Any]]:
        """Release every held request, in request order, once no condition is active. Returns the release events."""
        with self._lock:
            now = self._now(now)
            active = self.conditions(now)
            if active:
                return []
            if self._hold_started is not None:
                period = {
                    "started_at": self._hold_started,
                    "cleared_at": now,
                    "held_for_s": round(now - self._hold_started, 6),
                    "requests_held": len(self._held),
                    "conditions": self._hold_conditions,
                }
                self.hold_periods.append(period)
                self._event("hold_cleared", now, **period)
                self._hold_started = None
                self._hold_conditions = []
            released = []
            for row in self._held:
                released.append(
                    self._event(
                        "escalation_released",
                        now,
                        kind=row["kind"],
                        builder=row["builder"],
                        detail=row["detail"],
                        held_seq=row["seq"],
                        held_for_s=round(now - row["at"], 6),
                    )
                )
                self._counts["released"] += 1
            self._held = []
            return released

    def report(self, now: float | None = None) -> dict[str, Any]:
        with self._lock:
            counts = {**self._counts, "still_held": len(self._held)}
            return {
                "thresholds": asdict(self.thresholds),
                "counts": counts,
                "accounted": counts["requested"] == counts["granted"] + counts["released"] + counts["still_held"],
                "still_held": [dict(row) for row in self._held],
                "hold_periods": [dict(period) for period in self.hold_periods],
                "in_hold": self._hold_started is not None,
                "active_conditions": self.conditions(now),
                "events": [dict(event) for event in self.events],
            }


__all__ = ["KINDS", "EscalationHold", "Thresholds"]
