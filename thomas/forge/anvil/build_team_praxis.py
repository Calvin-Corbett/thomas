"""Durable Praxis obligations for files actually integrated by ``task.team``."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from thomas.core.praxis.acceptance import evaluate_acceptance
from thomas.core.praxis.build_coordinator import PraxisBuildCoordinator
from thomas.core.praxis.formation_state import STOP, Cycle
from thomas.core.praxis.routing import route

from .build_agent_workspace import current_fingerprint
from .build_team_ledger import TeamLedger


class TeamPraxisBridge:
    """Track integration truth separately from project acceptance truth."""

    def __init__(self, project: Path, ledger: TeamLedger) -> None:
        self.project = project
        self.ledger = ledger
        children = ledger.data["children"]
        self.owners = tuple(str(child["path"]) for child in children)
        self.paths = {owner: project / owner for owner in self.owners}
        self._routing: dict[str, Any] = {}
        requirements = hashlib.sha256(
            json.dumps(
                [{key: child.get(key) for key in ("title", "instructions", "path")} for child in children],
                sort_keys=True,
            ).encode()
        ).hexdigest()

        def evaluate(key: tuple, _cycle: Cycle) -> dict[str, dict[str, Any]]:
            evidence: dict[str, dict[str, Any]] = {}
            problems: list[str] = []
            for owner, candidate_hash, _generation in key:
                path = self.paths[owner]
                actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
                if actual != candidate_hash:
                    evidence[owner] = {
                        "isolation_failed_checks": [f"{owner}: integrated bytes changed before evaluation"]
                    }
                    problems.append(f"candidate_changed:{owner}")
                    continue
                # No engine-owned independent check receipt exists on this tool
                # path yet. A child report, even a successful one, cannot fill it.
                check = {"id": f"accept:{owner}", "kind": "file_exists", "text": f"Verify {owner}", "cites": owner}
                verdict = evaluate_acceptance([check], [], instructions=owner, require_child_reports=False)
                evidence[owner] = {
                    "candidate_sha256": actual,
                    "acceptance_state": verdict["state"],
                    "isolation_failed_checks": [f"{owner}: independent acceptance check pending"],
                }
                problems.append(f"missing_verifier_receipt:{owner}")
            self._routing = route(
                self.owners,
                dependencies={},
                isolation={},
                combined={},
                child_problems=problems,
            )
            return {
                owner: {"outcome": self._routing["outcomes"].get(owner, STOP), "evidence": evidence.get(owner, {})}
                for owner in self.owners
            }

        self.coordinator = PraxisBuildCoordinator(
            run_id=str(ledger.data["team_id"]),
            owners=self.owners,
            cycles=[Cycle(1, requirements, "independent_acceptance_v1")],
            log_path=ledger.folder / "praxis_obligations.jsonl",
            evaluate=evaluate,
            manager_id="build-team-manager",
        )
        existing = self.coordinator.log.state()["obligations"]
        self.submitted = {(str(row["owner"]), str(row["candidate_hash"])) for row in existing.values()}

    def integrated(self, index: int) -> None:
        child = self.ledger.data["children"][index]
        owner = str(child["path"])
        path = self.paths[owner]
        expected = child.get("integrated_file")
        if not expected or current_fingerprint(self.project, owner) != expected:
            raise ValueError(f"integrated bytes changed before Praxis receipt: {owner}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if (owner, digest) in self.submitted:
            return
        self.coordinator.submit_file(
            owner=owner,
            generation=int(child.get("attempts", 0)) + 1,
            path=path,
            role="builder",
            deliver=lambda _verdict: None,
        )
        self.submitted.add((owner, digest))

    def report(self) -> dict[str, Any]:
        self.coordinator.tick()
        return {"acceptance_state": "completed_unverified", "routing": self._routing, **self.coordinator.report()}
