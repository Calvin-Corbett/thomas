"""Bind a Build run's real child lifecycle to Praxis formation and obligations.

The server, not child prose, submits a candidate after collecting its artifact
identity. A terminal ``done`` event alone is never evidence of acceptance.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from thomas.core.praxis.escalation import EscalationHold
from thomas.core.praxis.feedback import feedback_text
from thomas.core.praxis.formation import NOwnerCoordinator
from thomas.core.praxis.formation_state import ACCEPTED, REPAIR, STAGE2_RULES, STOP, Cycle, Rules
from thomas.core.praxis.manager_proxy import CoordinatorProxy, ReplacementController
from thomas.core.praxis.obligations import ObligationLog

Evaluation = Callable[[tuple, Cycle], dict[str, str | dict[str, Any]]]
Delivery = Callable[[dict[str, Any]], None]
log = logging.getLogger(__name__)


class PraxisBuildCoordinator:
    """One Build run's durable manager with explicit candidate and verdict flow.

    ``evaluate`` must inspect actual combined artifacts/check results. It may
    return an outcome string or ``{"outcome": ..., "evidence": ...}`` per owner.
    The caller retains the proxy across manager replacements and calls ``tick``
    while the run is alive so grace periods and held escalations can progress.
    """

    def __init__(
        self,
        *,
        run_id: str,
        owners: Sequence[str],
        cycles: Sequence[Cycle],
        log_path: Path,
        evaluate: Evaluation,
        manager_id: str,
        rules: Rules = STAGE2_RULES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.run_id = run_id
        self.owners = tuple(owners)
        self.cycles = tuple(cycles)
        self.rules = rules
        self.clock = clock
        self.evaluate = evaluate
        self.escalation = EscalationHold(clock=clock)
        self._evidence: dict[str, dict[str, Any]] = {}
        self._owned_paths: dict[str, str] = {}
        self._deliveries: list[dict[str, Any]] = []
        self.log = ObligationLog(log_path)
        self.proxy = CoordinatorProxy(
            coordinator_id=run_id,
            log=self.log,
            manager_id=manager_id,
            factory=self._manager_factory,
        )
        self.replacement = ReplacementController(self.proxy)

    def _manager_factory(self, records: dict[str, Any], handle: Any) -> NOwnerCoordinator:
        def evaluated(key: tuple, cycle: Cycle) -> dict[str, str]:
            raw = self.evaluate(key, cycle)
            outcomes: dict[str, str] = {}
            for owner, value in raw.items():
                if isinstance(value, dict):
                    outcomes[owner] = str(value.get("outcome") or "")
                    self._evidence[owner] = dict(value.get("evidence") or {})
                else:
                    outcomes[owner] = str(value)
                if outcomes[owner] not in {ACCEPTED, REPAIR, STOP}:
                    raise ValueError(f"invalid evaluator outcome for {owner}")
            return outcomes

        return NOwnerCoordinator.from_records(
            records,
            handle,
            owners=self.owners,
            cycles=self.cycles,
            rules=self.rules,
            evaluate=evaluated,
            clock=self.clock,
        )

    def child_queued(self, child_id: str) -> None:
        self.escalation.builder_queued(child_id)

    def child_admitted(self, child_id: str) -> None:
        self.escalation.builder_admitted(child_id)

    def child_ended(self, child_id: str) -> list[dict[str, Any]]:
        self.escalation.builder_admitted(child_id)
        self.escalation.verdict_delivered(child_id)
        return self.proxy.manager.owner_ended(child_id)

    def child_state(self, child_id: str, state: str) -> None:
        """Observe a real RunChannel transition; completion does not accept work."""
        if state == "starting":
            self.child_queued(child_id)
        elif state == "running":
            self.child_admitted(child_id)
        elif state in {"failed", "stopped"}:
            self.child_ended(child_id)
        elif state in {"completed", "retrying", "quota_wait"}:
            self.escalation.builder_admitted(child_id)

    def submit_candidate(
        self,
        *,
        owner: str,
        generation: int,
        candidate_hash: str,
        role: str,
        owned_path: str,
        deliver: Delivery,
    ) -> str:
        """Record a server-verified artifact identity and hold its verdict.

        The caller must derive ``candidate_hash`` from actual candidate bytes or
        an immutable revision, never from the child's claimed success text.
        """
        if owner not in self.owners or not candidate_hash or not owned_path:
            raise ValueError("candidate needs a registered owner, artifact hash, and owned path")
        cycle = self.proxy.manager.state.cycle
        candidate = {
            "owner": owner,
            "role": role,
            "generation": generation,
            "candidate_hash": candidate_hash,
            "requirements_version": cycle.requirements_version,
            "acceptance_version": cycle.acceptance_version,
        }
        self._owned_paths[owner] = owned_path
        self.escalation.builder_waiting_for_verdict(owner)

        def delivered(verdict: dict[str, Any]) -> None:
            self.escalation.verdict_delivered(owner)
            payload = dict(verdict)
            if payload.get("outcome") == "repair":
                payload["feedback"] = feedback_text(owned_path, self._evidence.get(owner))
                payload["repair_offer"] = self.escalation.request("repair_offer", owner)
            self._deliveries.append(payload)
            deliver(payload)

        try:
            obligation_id = self.proxy.submit(candidate, delivered)
        except Exception:
            self.escalation.verdict_delivered(owner)
            log.exception("Praxis candidate obligation submission failed for %s", owner)
            raise
        self.tick()
        return obligation_id

    def submit_file(self, *, owner: str, generation: int, path: Path, role: str, deliver: Delivery) -> str:
        """Hash actual on-disk bytes before opening a candidate obligation."""
        path = path.resolve(strict=True)
        if not path.is_file():
            raise ValueError("candidate artifact must be a regular file")
        return self.submit_candidate(
            owner=owner,
            generation=generation,
            candidate_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
            role=role,
            owned_path=str(path),
            deliver=deliver,
        )

    def tick(self) -> dict[str, Any]:
        """Evaluate a formed revision and release held escalation in order."""
        verdicts = self.proxy.manager.step()
        released = self.escalation.poll()
        return {"verdicts": verdicts, "released": released}

    def request_effort(self, owner: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.escalation.request("effort_escalation", owner, detail=detail)

    def replace_manager(self, manager_id: str) -> dict[str, Any]:
        return self.replacement.replace(manager_id=manager_id, factory=self._manager_factory)

    def report(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "formation": self.proxy.manager.state.snapshot(),
            "obligations": self.log.state(),
            "escalation": self.escalation.report(),
            "deliveries": list(self._deliveries),
        }


__all__ = ["PraxisBuildCoordinator"]
