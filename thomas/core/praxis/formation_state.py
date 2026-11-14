"""Form combined candidates from any number of owners over versioned cycles.

Only each owner's latest submitted generation can receive a verdict. Evaluated
keys are not repeated, and a slow owner does not block others past the grace
period. The manager in ``formation.py`` rebuilds this state from obligations.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

ACCEPTED, REPAIR, STOP = "accepted", "repair", "stop"
ABSENT = "absent"
FORMATIONS = ("all_waiting", "latest_submitted")
OWNER_END_RULES = ("stop_waiting_peers", "continue")


@dataclass(frozen=True)
class Cycle:
    cycle_id: int
    requirements_version: str
    acceptance_version: str


@dataclass(frozen=True)
class Rules:
    formation: str = "all_waiting"
    formation_grace_s: float = 0.0
    max_rounds: int = 3
    on_owner_end: str = "stop_waiting_peers"


N1_RULES = Rules()
STAGE2_RULES = Rules(formation="latest_submitted", formation_grace_s=120.0, max_rounds=3, on_owner_end="continue")


class FormationState:
    def __init__(
        self,
        owners: Sequence[str],
        cycles: Sequence[Cycle],
        rules: Rules = N1_RULES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not owners or len(set(owners)) != len(owners):
            raise ValueError("owners must be distinct and non-empty")
        if not cycles or len({cycle.cycle_id for cycle in cycles}) != len(cycles):
            raise ValueError("cycles must be distinct and non-empty")
        if rules.formation not in FORMATIONS or rules.on_owner_end not in OWNER_END_RULES or rules.max_rounds < 1:
            raise ValueError(f"unknown rules: {rules}")
        self.owners = tuple(owners)
        self.cycles = tuple(cycles)
        self.rules = rules
        self._clock = clock
        self._lock = threading.RLock()
        self.cycle_index = 0
        self.latest: dict[str, dict[str, Any]] = {}
        self.waiting: set[str] = set()
        self.ended: set[str] = set()
        self.rounds: dict[tuple[int, str], int] = {}
        self.round_floor: dict[tuple[int, str], int] = {}
        self.evaluated: list[tuple] = []
        self.pending: tuple | None = None
        self.accepted: list[dict[str, Any]] = []
        self.finished: str | None = None
        self.events: list[dict[str, Any]] = []

    @property
    def cycle(self) -> Cycle:
        return self.cycles[self.cycle_index]

    def _event(self, event: str, **fields: Any) -> None:
        self.events.append({"event": event, "cycle_id": self.cycle.cycle_id, **fields})

    def round_of(self, owner: str) -> int:
        return self.rounds.get((self.cycle.cycle_id, owner), 1)

    def replace_owner(self, owner: str, *, first_generation: int) -> None:
        with self._lock:
            key = (self.cycle.cycle_id, owner)
            self.rounds[key] = 1
            self.round_floor[key] = int(first_generation)
            self.waiting.discard(owner)
            self._event("owner_replaced", owner=owner, first_generation=int(first_generation))

    def submit(
        self,
        *,
        owner: str,
        generation: Any,
        candidate_hash: str,
        requirements_version: str,
        acceptance_version: str,
        now: float | None = None,
    ) -> str | None:
        """Record a submission; returns the refusal reason, or None when it was accepted as the owner's latest."""
        with self._lock:
            now = self._clock() if now is None else now
            cycle = self.cycle
            if owner not in self.owners:
                reason = "owner_not_registered"
            elif owner in self.ended:
                reason = "owner_ended"
            elif self.finished is not None:
                reason = "formation_finished"
            elif (requirements_version, acceptance_version) != (cycle.requirements_version, cycle.acceptance_version):
                reason = "version_mismatch"
            elif isinstance(generation, bool) or not isinstance(generation, int):
                reason = "generation_not_int"
            elif owner in self.latest and generation <= self.latest[owner]["generation"]:
                reason = "generation_not_newer"
            else:
                reason = None
            if reason is not None:
                self._event("submission_refused", owner=owner, generation=generation, reason=reason)
                return reason
            self.latest[owner] = {"generation": generation, "candidate_hash": candidate_hash, "submitted_at": now}
            self.waiting.add(owner)
            self._event("submission", owner=owner, generation=generation, round=self.round_of(owner))
            return None

    def formation_key(self, now: float | None = None) -> tuple | None:
        with self._lock:
            if self.finished is not None or self.pending is not None or not self.waiting:
                return None
            now = self._clock() if now is None else now
            if self.rules.formation == "all_waiting":
                if any(owner not in self.waiting for owner in self.owners):
                    return None
            else:
                missing = [owner for owner in self.owners if owner not in self.latest and owner not in self.ended]
                oldest = min(self.latest[owner]["submitted_at"] for owner in self.waiting)
                if missing and now - oldest < self.rules.formation_grace_s:
                    return None
            key = tuple(
                (owner, self.latest[owner]["candidate_hash"], self.latest[owner]["generation"])
                if owner in self.latest
                else (owner, ABSENT, 0)
                for owner in self.owners
            )
            if key in self.evaluated:
                return None
            return key

    def open_evaluation(self, key: tuple) -> None:
        with self._lock:
            if self.pending is not None:
                raise RuntimeError("an evaluation is already pending")
            self.pending = key
            self.evaluated.append(key)
            self._event("evaluation_opened", key=[list(part) for part in key])

    def record_outcomes(self, key: tuple, outcomes: dict[str, str]) -> list[dict[str, Any]]:
        with self._lock:
            if key != self.pending:
                raise RuntimeError("outcomes for an evaluation that is not pending")
            cycle = self.cycle
            deliveries: list[dict[str, Any]] = []
            for owner, candidate_hash, generation in key:
                outcome = outcomes.get(owner)
                if (
                    outcome is None
                    or owner not in self.waiting
                    or (self.latest.get(owner) or {}).get("generation") != generation
                ):
                    continue
                if outcome == REPAIR:
                    if self.round_of(owner) >= self.rules.max_rounds:
                        outcome = STOP
                    else:
                        self.rounds[(cycle.cycle_id, owner)] = self.round_of(owner) + 1
                deliveries.append(
                    {
                        "owner": owner,
                        "generation": generation,
                        "candidate_hash": candidate_hash,
                        "outcome": outcome,
                        "classification": "repairs_exhausted"
                        if outcome == STOP and outcomes.get(owner) == REPAIR
                        else outcome,
                        "cycle_id": cycle.cycle_id,
                        "round_after": self.round_of(owner),
                        "requirements_version": cycle.requirements_version,
                        "acceptance_version": cycle.acceptance_version,
                    }
                )
                self.waiting.discard(owner)
            self.pending = None
            accepted = all(
                outcomes.get(owner) == ACCEPTED and candidate_hash != ABSENT for owner, candidate_hash, _ in key
            )
            self._event(
                "evaluation_closed",
                key=[list(part) for part in key],
                outcomes=dict(outcomes),
                delivered=[row["owner"] for row in deliveries],
                accepted=accepted,
            )
            if accepted:
                self.accepted.append({"cycle_id": cycle.cycle_id, "key": [list(part) for part in key]})
                if self.cycle_index + 1 < len(self.cycles):
                    self.cycle_index += 1
                    self.latest.clear()
                    self.waiting.clear()
                    self.evaluated.clear()
                    self._event(
                        "cycle_opened",
                        requirements_version=self.cycle.requirements_version,
                        acceptance_version=self.cycle.acceptance_version,
                    )
                else:
                    self.finished = "all_cycles_accepted"
            return deliveries

    def owner_ended(self, owner: str) -> list[dict[str, Any]]:
        with self._lock:
            if owner not in self.owners or owner in self.ended:
                return []
            self.ended.add(owner)
            was_waiting = owner in self.waiting
            self.waiting.discard(owner)
            cycle = self.cycle
            stops: list[dict[str, Any]] = []
            if self.rules.on_owner_end == "stop_waiting_peers" and self.pending is None:
                for peer in sorted(self.waiting):
                    latest = self.latest[peer]
                    stops.append(
                        {
                            "owner": peer,
                            "generation": latest["generation"],
                            "candidate_hash": latest["candidate_hash"],
                            "outcome": STOP,
                            "classification": "peer_ended",
                            "cycle_id": cycle.cycle_id,
                            "round_after": self.round_of(peer),
                            "requirements_version": cycle.requirements_version,
                            "acceptance_version": cycle.acceptance_version,
                        }
                    )
                self.waiting.clear()
            if self.ended == set(self.owners) and self.finished is None:
                self.finished = "stopped:all_owners_ended"
            self._event(
                "owner_ended", owner=owner, was_waiting=was_waiting, stopped_peers=[row["owner"] for row in stops]
            )
            return stops

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "cycle_index": self.cycle_index,
                "cycle_id": self.cycle.cycle_id,
                "latest": {
                    owner: {"generation": entry["generation"], "candidate_hash": entry["candidate_hash"]}
                    for owner, entry in sorted(self.latest.items())
                },
                "waiting": sorted(self.waiting),
                "ended": sorted(self.ended),
                "rounds": {f"{cycle_id}:{owner}": value for (cycle_id, owner), value in sorted(self.rounds.items())},
                "finished": self.finished,
                "accepted_cycles": [row["cycle_id"] for row in self.accepted],
            }


__all__ = ["ABSENT", "ACCEPTED", "N1_RULES", "REPAIR", "STAGE2_RULES", "STOP", "Cycle", "FormationState", "Rules"]
