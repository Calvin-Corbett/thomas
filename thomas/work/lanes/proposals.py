"""Thomas may notice a better gate. It may not change its own gates quietly.

Gates start imperfect, so evolution is the point -- but a system that rewrites
its own checks without asking has no checks. Every change is a proposal: it
carries the evidence that produced it, it waits, and applying it needs a real
human authorization passed in by the caller.

Two kinds, both evidence-backed:

* ``retire`` -- a gate that has never fired in a meaningful number of checks, or
  one the user keeps waiving. Evolution that can only add ends in a lane that
  spends its whole budget on ceremony, so subtraction is first-class.
* ``add`` -- a gate proposed from an observed run, carried on the proposal. This
  is the seam through which :class:`~thomas.work.lanes.observation.LaneProposal`
  (a whole lane observed from run one) reaches the same queue.

Rejections are remembered against the evidence that prompted them. Without that
the same suggestion returns every run until it is approved out of fatigue, which
is consent by attrition rather than agreement.

Named ``GateProposal`` rather than ``Proposal`` because
``thomas.core.aliveness_permissions.Proposal`` already holds that name for a
different domain -- notification permission levels -- with the same philosophy
and different fields.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.core.owned_root import freedom_transit_dir

from .model import Gate, Lane, validate_lane
from .proving import prove_lane
from .store import LaneStore, lane_data_dir

PROPOSAL_KINDS = ("add", "retire")

#: A gate needs a real history before silence means anything. One quiet run is
#: not evidence, and retiring on it would delete working gates.
MIN_CHECKS_BEFORE_RETIREMENT = 20

#: A gate the user overrides this often is a wrong gate, not a disobedient user.
MIN_WAIVERS_BEFORE_RETIREMENT = 3


def default_store_path() -> Path:
    """Resolved when asked, so a Thomas with its own data folder keeps lane data there."""
    return freedom_transit_dir() / "work_lane_proposals.json"


#: How much louder the evidence must get before a refused idea may return.
REPROPOSE_EVIDENCE_FACTOR = 2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class GateProposal:
    """A suggested change to one gate, and the evidence that produced it."""

    id: str
    job_kind: str
    kind: str
    gate_id: str
    rationale: str
    evidence: dict[str, Any] = field(default_factory=dict)
    gate: Gate | None = None
    status: str = "pending"
    created_at: str = field(default_factory=_now)
    decided_at: str = ""
    decided_reason: str = ""
    decided_by: str = ""

    @property
    def strength(self) -> int:
        """How loud the evidence is, for deciding whether a refused idea returns."""

        return int(self.evidence.get("checked_count", 0)) + int(self.evidence.get("waived_count", 0))

    def to_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["gate"] = asdict(self.gate) if self.gate else None
        return data

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> GateProposal:
        row = dict(payload)
        gate = row.pop("gate", None)
        return cls(**row, gate=Gate(**gate) if isinstance(gate, dict) else None)


def _dedupe_key(proposal: GateProposal) -> str:
    return f"{proposal.job_kind}:{proposal.kind}:{proposal.gate_id}"


# -- noticing -----------------------------------------------------------------


def propose_from_lane(lane: Lane, *, waived_gate_ids: list[str]) -> list[GateProposal]:
    """Read the lane's own counters and say what should change, with evidence."""

    proposals: list[GateProposal] = []
    for step in lane.steps:
        for gate in step.gates:
            waived = sum(1 for gate_id in waived_gate_ids if gate_id == gate.id)
            if waived >= MIN_WAIVERS_BEFORE_RETIREMENT:
                proposals.append(
                    GateProposal(
                        id=f"{lane.job_kind}-retire-{gate.id}",
                        job_kind=lane.job_kind,
                        kind="retire",
                        gate_id=gate.id,
                        rationale=(
                            f"You waived this {waived} times. A gate you keep overriding is one that is "
                            "asking the wrong question."
                        ),
                        evidence={
                            "checked_count": gate.checked_count,
                            "fired_count": gate.fired_count,
                            "waived_count": waived,
                        },
                    )
                )
                continue
            if gate.checked_count >= MIN_CHECKS_BEFORE_RETIREMENT and gate.fired_count == 0:
                proposals.append(
                    GateProposal(
                        id=f"{lane.job_kind}-retire-{gate.id}",
                        job_kind=lane.job_kind,
                        kind="retire",
                        gate_id=gate.id,
                        rationale=(
                            f"Checked {gate.checked_count} times and never once stopped anything. It is "
                            "either asking something that cannot fail here, or asking nothing."
                        ),
                        evidence={"checked_count": gate.checked_count, "fired_count": 0, "waived_count": 0},
                    )
                )
    return proposals


# -- the queue ----------------------------------------------------------------


class GateProposalStore:
    """Pending and decided proposals, with memory of what was already refused."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else default_store_path()

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"proposals": []}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"proposal store is not an object: {self.path}")
        data.setdefault("proposals", [])
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)

    def _all(self) -> list[GateProposal]:
        return [GateProposal.from_payload(row) for row in self._read()["proposals"]]

    def _save(self, rows: list[GateProposal]) -> None:
        self._write({"proposals": [row.to_payload() for row in rows]})

    def queue(self, proposals: list[GateProposal]) -> list[GateProposal]:
        """Add what is genuinely new. Returns only the ones actually queued."""

        rows = self._all()
        by_key = {_dedupe_key(row): row for row in rows}
        added: list[GateProposal] = []
        for proposal in proposals:
            seen = by_key.get(_dedupe_key(proposal))
            if seen is not None and not self._may_return(seen, proposal):
                continue
            if seen is not None:
                rows = [row for row in rows if row.id != seen.id]
            rows.append(proposal)
            by_key[_dedupe_key(proposal)] = proposal
            added.append(proposal)
        if added:
            self._save(rows)
        return added

    def _may_return(self, seen: GateProposal, incoming: GateProposal) -> bool:
        """A pending idea never duplicates; a refused one waits for louder evidence."""

        if seen.status in {"pending", "approved"}:
            return False
        return incoming.strength >= max(1, seen.strength) * REPROPOSE_EVIDENCE_FACTOR

    def pending(self, job_kind: str = "") -> list[GateProposal]:
        return [row for row in self._all() if row.status == "pending" and (not job_kind or row.job_kind == job_kind)]

    def decided(self, job_kind: str = "") -> list[GateProposal]:
        return [row for row in self._all() if row.status != "pending" and (not job_kind or row.job_kind == job_kind)]

    def get(self, proposal_id: str) -> GateProposal | None:
        return next((row for row in self._all() if row.id == proposal_id), None)

    def _decide(self, proposal_id: str, *, status: str, reason: str, by: str) -> GateProposal:
        rows = self._all()
        target = next((row for row in rows if row.id == proposal_id), None)
        if target is None:
            raise KeyError(f"no such proposal: {proposal_id}")
        target.status = status
        target.decided_at = _now()
        target.decided_reason = reason
        target.decided_by = by
        self._save(rows)
        return target

    def approve(self, proposal_id: str, *, approved_by: str = "", reason: str = "") -> GateProposal:
        return self._decide(proposal_id, status="approved", reason=reason, by=approved_by)

    def reject(self, proposal_id: str, *, reason: str = "", rejected_by: str = "") -> GateProposal:
        return self._decide(proposal_id, status="rejected", reason=reason, by=rejected_by)


# -- applying one -------------------------------------------------------------

#: Returns ``(ok, message)``. Injected so this package never imports the
#: breakglass scripts, and so a test can refuse without a Windows prompt.
Authorizer = Callable[..., tuple[bool, str]]


def apply_proposal(proposal: GateProposal, lane_store: LaneStore, *, authorize: Authorizer) -> Lane:
    """Change the lane, but only behind a real human authorization.

    Approval exempts the result from nothing: the new lane is validated and every
    gate re-proven, so an approved change that empties a lane or adds a gate that
    cannot fail is still refused.
    """

    ok, message = authorize(
        purpose="work-lane-gate-change",
        reason=f"{proposal.kind} gate {proposal.gate_id!r} on lane {proposal.job_kind!r}: {proposal.rationale}",
    )
    if not ok:
        raise PermissionError(message or "human authorization was not granted")

    lane = lane_store.load_lane(proposal.job_kind)
    if lane is None:
        raise KeyError(f"no lane stored for {proposal.job_kind}")

    if proposal.kind == "retire":
        for step in lane.steps:
            step.gates = [gate for gate in step.gates if gate.id != proposal.gate_id]
    elif proposal.kind == "add":
        if proposal.gate is None:
            raise ValueError("an add proposal must carry the gate it adds")
        lane.steps[0].gates.append(proposal.gate)
    else:
        raise ValueError(f"unknown proposal kind: {proposal.kind}")

    prove_lane(validate_lane(lane))
    return lane_store.save_lane(lane, approved_by=proposal.decided_by or "human")
