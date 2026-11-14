"""Where a gate's history lives, and the run boundary that reads it.

``propose_from_lane`` decides from ``gate.checked_count`` and ``fired_count``, but
a lane is rebuilt on every run, so those counters died with the run that produced
them and no proposal could ever reach its threshold. This is the memory that makes
the evolution loop possible at all.

Counters are deliberately NOT kept in the lane definition. ``LaneStore.save_lane``
pushes a new version and a history entry on every save, so writing counters there
would mean a new lane version per run and a version number that no longer means
"someone changed the gates".

The boundary is also deliberately quiet. ``close_run`` is bookkeeping that happens
after a job has already finished, so it must never be able to fail the run it is
closing: it swallows its own errors and reports nothing rather than raising into a
completed job.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.core.owned_root import freedom_transit_dir

from .model import Lane
from .proposals import GateProposal, GateProposalStore, propose_from_lane
from .store import lane_data_dir

log = logging.getLogger(__name__)


def default_store_path() -> Path:
    """Resolved when asked, so a Thomas with its own data folder keeps lane data there."""
    return freedom_transit_dir() / "work_lane_stats.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class GateHistory:
    checked: int = 0
    fired: int = 0
    waived: int = 0


class GateStatsStore:
    """Cumulative per-gate counters, keyed by job kind and gate id."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else default_store_path()

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"stats": {}}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"gate stats store is not an object: {self.path}")
        data.setdefault("stats", {})
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)

    def history(self, job_kind: str, gate_id: str) -> GateHistory:
        row = self._read()["stats"].get(job_kind, {}).get(gate_id)
        if not isinstance(row, dict):
            return GateHistory()
        return GateHistory(
            checked=int(row.get("checked") or 0),
            fired=int(row.get("fired") or 0),
            waived=int(row.get("waived") or 0),
        )

    def record(self, lane: Lane, *, waived_gate_ids: list[str]) -> None:
        """Fold one run's counters into the cumulative history."""

        data = self._read()
        kinds = data["stats"].setdefault(lane.job_kind, {})
        for step in lane.steps:
            for gate in step.gates:
                waived = sum(1 for gate_id in waived_gate_ids if gate_id == gate.id)
                if not (gate.checked_count or gate.fired_count or waived):
                    # A run that exercised nothing must not invent history, or a
                    # gate would age toward retirement without being asked anything.
                    continue
                row = kinds.setdefault(gate.id, {"checked": 0, "fired": 0, "waived": 0, "first_seen": _now()})
                row["checked"] = int(row.get("checked") or 0) + int(gate.checked_count)
                row["fired"] = int(row.get("fired") or 0) + int(gate.fired_count)
                row["waived"] = int(row.get("waived") or 0) + waived
                row["last_seen"] = _now()
        self._write(data)

    def hydrate(self, lane: Lane) -> Lane:
        """Put the accumulated history back onto the lane's gates."""

        for step in lane.steps:
            for gate in step.gates:
                seen = self.history(lane.job_kind, gate.id)
                gate.checked_count = seen.checked
                gate.fired_count = seen.fired
        return lane

    def waived_gate_ids(self, lane: Lane) -> list[str]:
        """The cumulative waivers, in the repeated-id shape proposals expects."""

        ids: list[str] = []
        for step in lane.steps:
            for gate in step.gates:
                ids.extend([gate.id] * self.history(lane.job_kind, gate.id).waived)
        return ids


def close_run(
    lane: Lane,
    *,
    waived_gate_ids: list[str],
    stats_store: GateStatsStore,
    proposal_store: GateProposalStore,
) -> list[GateProposal]:
    """Record what this run showed, then ask about anything it revealed.

    Returns only the proposals newly queued. Bookkeeping that can fail a completed
    run would be a worse defect than a missed proposal, so the failures this can
    actually meet -- an unwritable or corrupt store -- are logged and swallowed.

    They are named rather than caught broadly on purpose. A `TypeError` or an
    `AttributeError` here is a bug in this module, not a storage problem, and
    swallowing it would hide the defect behind a silently missing proposal.
    """

    try:
        stats_store.record(lane, waived_gate_ids=waived_gate_ids)
        hydrated = stats_store.hydrate(lane)
        cumulative = stats_store.waived_gate_ids(hydrated)
        return proposal_store.queue(propose_from_lane(hydrated, waived_gate_ids=cumulative))
    except (OSError, ValueError, KeyError):
        log.warning("closing a work lane run could not record its history", exc_info=True)
        return []
