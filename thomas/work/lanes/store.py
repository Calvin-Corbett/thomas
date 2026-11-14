"""Durable, versioned lane definitions -- user data, never repo data.

Lanes are what Thomas has learned about how a job is really done, so they belong
with the rest of Work's durable data (beside ``work_apps.json``) rather than in
``runtime/``, which is gitignored and disposable. Nothing here touches
``plans/thomas/``: the dev workboard and a user's job lanes are different things
and mixing them would put business-job runs into repo engineering records.

Every save keeps the previous version, so a gate change that turns out to be
wrong can be rolled back rather than argued with.

**Proof is re-earned on load, not trusted from disk.** ``load_lane`` runs each
gate against its counterexample again, so a stored gate that has been edited into
one that always passes is refused at load rather than discovered in production.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.core.owned_root import freedom_transit_dir

from .model import Gate, Lane, Step, validate_lane
from .proving import prove_lane

STORE_VERSION = 1


#: Beside work_apps.json: the same backup story as the rest of Work.
def default_store_path() -> Path:
    """Resolved when asked, so a Thomas with its own data folder keeps lane data there."""
    return freedom_transit_dir() / "work_lanes.json"


#: Kept for the test that asserts we never write into the dev workboard.
FORBIDDEN_PREFIXES = ("plans/",)


def lane_data_dir(work_root: str | Path) -> Path:
    """Where a WorkStore's lane data lives: beside its own ``state.json``.

    ``.thomas/`` is gitignored, so this never lands in the repo, and it is derived
    from the work store rather than fixed at ``$HOME`` so a store pointed at a
    temporary root -- every test -- keeps its lane data there too. A default that
    resolves to the real user directory turns any test that creates a job into a
    write against live data.
    """

    return Path(work_root).expanduser().resolve() / ".thomas" / "work"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def lane_to_payload(lane: Lane) -> dict[str, Any]:
    return asdict(lane)


def lane_from_payload(payload: dict[str, Any]) -> Lane:
    return Lane(
        id=str(payload.get("id") or ""),
        job_kind=str(payload.get("job_kind") or ""),
        version=int(payload.get("version") or 1),
        steps=[
            Step(
                id=str(step.get("id") or ""),
                name=str(step.get("name") or ""),
                gates=[Gate(**gate) for gate in (step.get("gates") or [])],
            )
            for step in (payload.get("steps") or [])
        ],
    )


class LaneStore:
    """Lane definitions keyed by job kind, with a rollback history."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else default_store_path()
        text = str(self.path).replace("\\", "/")
        if any(f"/{prefix}" in f"/{text}" for prefix in FORBIDDEN_PREFIXES):
            raise ValueError(f"lane store must not live under {FORBIDDEN_PREFIXES}: {self.path}")

    # ── disk ──────────────────────────────────────────────────────────────────

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": STORE_VERSION, "lanes": {}, "history": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # A corrupt store must not silently look like an empty one: an empty
            # store means "no gates yet", which would wave every run through.
            raise
        if not isinstance(data, dict):
            raise ValueError(f"lane store is not an object: {self.path}")
        data.setdefault("lanes", {})
        data.setdefault("history", {})
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)

    # ── api ───────────────────────────────────────────────────────────────────

    def save_lane(self, lane: Lane, *, approved_by: str = "") -> Lane:
        """Validate, prove, and store as the next version for its job kind."""

        prove_lane(validate_lane(lane))
        data = self._read()
        previous = data["lanes"].get(lane.job_kind)
        if isinstance(previous, dict):
            data["history"].setdefault(lane.job_kind, []).append(previous)
            lane.version = int(previous.get("version") or 0) + 1
        payload = lane_to_payload(lane)
        payload["saved_at"] = _now()
        payload["approved_by"] = approved_by
        data["lanes"][lane.job_kind] = payload
        self._write(data)
        return lane

    def load_lane(self, job_kind: str) -> Lane | None:
        payload = self._read()["lanes"].get(job_kind)
        if not isinstance(payload, dict):
            return None
        return prove_lane(validate_lane(lane_from_payload(payload)))

    def history(self, job_kind: str) -> list[dict[str, Any]]:
        rows = self._read()["history"].get(job_kind)
        return list(rows) if isinstance(rows, list) else []

    def rollback(self, job_kind: str) -> Lane | None:
        """Restore the previous version of a lane and drop the current one."""

        data = self._read()
        rows = data["history"].get(job_kind)
        if not isinstance(rows, list) or not rows:
            return None
        restored = rows.pop()
        data["lanes"][job_kind] = restored
        self._write(data)
        return prove_lane(validate_lane(lane_from_payload(restored)))
