"""Durable manager replacement with epoch-fenced verdict delivery.

The proxy owns callbacks while managers see only obligation IDs. Replacement
rebuilds state from the hash-chained log and fences verdicts from an old epoch.
The server run channel must retain the proxy across manager replacements.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from thomas.core.praxis import obligations as obligation_records

IDENTITY = obligation_records.IDENTITY_FIELDS


def obligation_id_for(candidate: dict[str, Any]) -> str:
    return (
        f"{candidate.get('owner')}:{str(candidate.get('requirements_version'))[:16]}:{str(candidate.get('acceptance_version'))[:16]}"
        f":g{candidate.get('generation')}:{str(candidate.get('candidate_hash'))[:16]}"
    )


class ManagerHandle:
    """A manager's only channel to builders, bound to the epoch the manager was built under."""

    def __init__(self, proxy: CoordinatorProxy, epoch: int) -> None:
        self._proxy = proxy
        self.epoch = epoch

    def issue_verdict(self, obligation_id: str, verdict: dict[str, Any]) -> bool:
        return self._proxy.issue_verdict(epoch=self.epoch, obligation_id=obligation_id, verdict=verdict)


class CoordinatorProxy:
    def __init__(
        self,
        *,
        coordinator_id: str,
        log: obligation_records.ObligationLog,
        manager_id: str,
        factory: Callable[[dict[str, Any], ManagerHandle], Any],
    ) -> None:
        self.coordinator_id = str(coordinator_id)
        self.log = log
        self._lock = threading.RLock()
        self.epoch = log.open_epoch(manager_id)
        self.manager_id = manager_id
        self._delivers: dict[str, Callable[[dict[str, Any]], None]] = {}
        self._submitted: dict[str, dict[str, Any]] = {}
        self.stale_actions: list[dict[str, Any]] = []
        self._manager = factory(obligation_records.rebuild(log.path), ManagerHandle(self, self.epoch))

    @property
    def manager(self) -> Any:
        with self._lock:
            return self._manager

    def register(self, register: Callable[[str, Any], None]) -> None:
        """Register THIS proxy under the coordinator id (for Thomas: integration_hold.register_coordinator)."""
        register(self.coordinator_id, self)

    # ---- the Thomas hold protocol ----
    def submit(self, candidate: dict[str, Any], deliver: Callable[[dict[str, Any]], None]) -> str:
        payload = dict(candidate)
        identity = {name: payload.get(name) for name in IDENTITY}
        with self._lock:
            epoch, manager = self.epoch, self._manager
            obligation_id = obligation_id_for(payload)
            self.log.open_obligation(epoch=epoch, obligation_id=obligation_id, owed="verdict", **identity)
            self._delivers[obligation_id] = deliver
            self._submitted[obligation_id] = {
                "obligation_id": obligation_id,
                **identity,
                "owed": "verdict",
                "status": "open",
            }
            # Manager replacement takes this same lock. Do not leave a window
            # where a newly opened obligation reaches an already fenced manager.
            manager.on_submission(obligation_id, payload)
        return obligation_id

    def current_revision(self) -> dict[str, Any]:
        with self._lock:
            manager = self._manager
        return manager.current_revision()

    # ---- the manager side ----
    def issue_verdict(self, *, epoch: int, obligation_id: str, verdict: dict[str, Any]) -> bool:
        outcome = str(verdict.get("outcome") or "")
        with self._lock:
            if epoch != self.epoch:
                self.stale_actions.append(
                    {
                        "action": "issue_verdict",
                        "obligation_id": obligation_id,
                        "stale_epoch": epoch,
                        "current_epoch": self.epoch,
                        "outcome": outcome,
                    }
                )
                self.log.record_refusal(
                    epoch=self.epoch,
                    refused_epoch=epoch,
                    action="issue_verdict",
                    obligation_id=obligation_id,
                    detail={"outcome": outcome},
                )
                return False
            deliver = self._delivers.get(obligation_id)
            if deliver is None:
                self.stale_actions.append(
                    {
                        "action": "issue_verdict_without_held_obligation",
                        "obligation_id": obligation_id,
                        "stale_epoch": epoch,
                        "current_epoch": self.epoch,
                        "outcome": outcome,
                    }
                )
                self.log.record_refusal(
                    epoch=self.epoch,
                    refused_epoch=epoch,
                    action="issue_verdict_without_held_obligation",
                    obligation_id=obligation_id,
                    detail={"outcome": outcome},
                )
                return False
            self.log.issue_verdict(epoch=epoch, obligation_id=obligation_id, outcome=outcome)
            self.log.discharge(epoch=epoch, obligation_id=obligation_id, how=f"verdict_delivered:{outcome}")
            del self._delivers[obligation_id]
        deliver(dict(verdict))
        return True

    def memory_state(self) -> dict[str, Any]:
        """The proxy's in-memory submission history. NOT a recovery source: replacement rebuilds from the records only."""
        with self._lock:
            return {
                "epoch": self.epoch,
                "manager_id": self.manager_id,
                "records": len(self._submitted),
                "open": {key: dict(value) for key, value in self._submitted.items()},
            }


class ReplacementController:
    def __init__(self, proxy: CoordinatorProxy) -> None:
        self.proxy = proxy
        self.replacements: list[dict[str, Any]] = []

    def replace(self, *, manager_id: str, factory: Callable[[dict[str, Any], ManagerHandle], Any]) -> dict[str, Any]:
        proxy = self.proxy
        with proxy._lock:
            old_epoch, old_manager_id = proxy.epoch, proxy.manager_id
            new_epoch = proxy.log.open_epoch(manager_id)
            proxy.epoch = new_epoch
            state = obligation_records.rebuild(proxy.log.path)
            manager = factory(state, ManagerHandle(proxy, new_epoch))
            proxy._manager, proxy.manager_id = manager, manager_id
            report = {
                "old_epoch": old_epoch,
                "new_epoch": new_epoch,
                "old_manager_id": old_manager_id,
                "new_manager_id": manager_id,
                "open_obligations": sorted(state["open"]),
                "records": state["records"],
            }
            self.replacements.append(report)
        return report


__all__ = ["CoordinatorProxy", "ManagerHandle", "ReplacementController", "obligation_id_for"]
