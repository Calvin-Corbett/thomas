"""Manager-facing formation coordinator over durable obligation records."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from typing import Any

from thomas.core.praxis.formation_state import (
    ABSENT,
    ACCEPTED,
    REPAIR,
    STOP,
    Cycle,
    FormationState,
    Rules,
)

log = logging.getLogger(__name__)


class NOwnerCoordinator:
    """A manager for coordinator_proxy.CoordinatorProxy (or any handle with issue_verdict(obligation_id, verdict))."""

    def __init__(
        self, *, state: FormationState, handle: Any, evaluate: Callable[[tuple, Cycle], dict[str, str]]
    ) -> None:
        self.state = state
        self.handle = handle
        self.evaluate = evaluate
        self.obligation_by_owner: dict[str, str] = {}
        self.issued: list[dict[str, Any]] = []

    @classmethod
    def from_records(
        cls,
        records_state: dict[str, Any],
        handle: Any,
        *,
        owners: Sequence[str],
        cycles: Sequence[Cycle],
        rules: Rules,
        evaluate: Callable[[tuple, Cycle], dict[str, str]],
        clock: Callable[[], float] = time.monotonic,
        replacement_floors: dict[tuple[int, str], int] | None = None,
    ) -> NOwnerCoordinator:
        state = FormationState(owners, cycles, rules, clock)
        index_by_versions = {
            (cycle.requirements_version, cycle.acceptance_version): index for index, cycle in enumerate(state.cycles)
        }
        obligations = sorted(records_state["obligations"].values(), key=lambda row: row["opened_seq"])
        known = [
            (row, index_by_versions.get((row["requirements_version"], row["acceptance_version"])))
            for row in obligations
        ]
        known = [(row, index) for row, index in known if index is not None and row["owner"] in state.owners]
        state.cycle_index = max((index for _row, index in known), default=0)
        coordinator = cls(state=state, handle=handle, evaluate=evaluate)
        floors = {
            (int(cycle_id), str(owner)): int(generation)
            for (cycle_id, owner), generation in (replacement_floors or {}).items()
        }
        state.round_floor.update(floors)
        for row, index in known:
            key = (state.cycles[index].cycle_id, row["owner"])
            counted = int(row["generation"]) >= floors.get(key, 0)
            repairs = sum(1 for verdict in row["verdicts"] if verdict["outcome"] == REPAIR) if counted else 0
            if repairs:
                state.rounds[key] = min(rules.max_rounds, state.rounds.get(key, 1) + repairs)
            if index != state.cycle_index:
                continue
            state.latest[row["owner"]] = {
                "generation": row["generation"],
                "candidate_hash": row["candidate_hash"],
                "submitted_at": clock(),
            }
            if row["status"] == "open":
                state.waiting.add(row["owner"])
                coordinator.obligation_by_owner[row["owner"]] = row["obligation_id"]
            else:
                state.waiting.discard(row["owner"])
                coordinator.obligation_by_owner.pop(row["owner"], None)
        state._event("rebuilt_from_records", records=records_state["records"], epoch=records_state["epoch"])
        return coordinator

    def on_submission(self, obligation_id: str, candidate: dict[str, Any]) -> None:
        owner = str(candidate.get("owner") or "")
        refusal = self.state.submit(
            owner=owner,
            generation=candidate.get("generation"),
            candidate_hash=str(candidate.get("candidate_hash") or ""),
            requirements_version=str(candidate.get("requirements_version") or ""),
            acceptance_version=str(candidate.get("acceptance_version") or ""),
        )
        if refusal is not None:
            verdict = {
                "outcome": STOP,
                "classification": f"submission_refused:{refusal}",
                "owner": owner,
                "generation": candidate.get("generation"),
                "revision_vector": {owner: candidate.get("candidate_hash")},
                "requirements_version": candidate.get("requirements_version"),
                "acceptance_version": candidate.get("acceptance_version"),
            }
            delivered = self.handle.issue_verdict(obligation_id, verdict)
            self.issued.append({**verdict, "obligation_id": obligation_id, "delivered": delivered})
            return
        self.obligation_by_owner[owner] = obligation_id

    def owner_replaced(self, owner: str, *, cycle_id: int, first_generation: int) -> bool:
        """The bridge bound a censored owner's replacement: fresh repair rounds in the current cycle (false for another cycle)."""
        with self.state._lock:
            if self.state.cycle.cycle_id != cycle_id:
                return False
            self.state.replace_owner(owner, first_generation=first_generation)
            self.obligation_by_owner.pop(owner, None)
            return True

    def current_revision(self) -> dict[str, Any]:
        cycle = self.state.cycle
        return {
            "revision_vector": {owner: entry["candidate_hash"] for owner, entry in self.state.latest.items()},
            "requirements_version": cycle.requirements_version,
            "acceptance_version": cycle.acceptance_version,
        }

    def _issue(self, deliveries: list[dict[str, Any]], vector: dict[str, str]) -> list[dict[str, Any]]:
        for row in deliveries:
            obligation_id = self.obligation_by_owner.pop(row["owner"], None)
            verdict = {**row, "revision_vector": dict(vector)}
            delivered = self.handle.issue_verdict(obligation_id, verdict) if obligation_id is not None else False
            self.issued.append({**verdict, "obligation_id": obligation_id, "delivered": delivered})
        return deliveries

    def step(self, now: float | None = None) -> list[dict[str, Any]]:
        key = self.state.formation_key(now)
        if key is None:
            return []
        self.state.open_evaluation(key)
        cycle = self.state.cycle
        try:
            outcomes = dict(self.evaluate(key, cycle))
        except Exception:
            log.exception("Praxis formation evaluation failed; pending formation remains unaccepted")
            self.state.record_outcomes(key, {})
            raise
        deliveries = self.state.record_outcomes(key, outcomes)
        return self._issue(
            deliveries, {owner: candidate_hash for owner, candidate_hash, _ in key if candidate_hash != ABSENT}
        )

    def owner_ended(self, owner: str) -> list[dict[str, Any]]:
        vector = self.current_revision()["revision_vector"]
        stops = self.state.owner_ended(owner)
        return self._issue(stops, vector)


__all__ = ["NOwnerCoordinator"]
