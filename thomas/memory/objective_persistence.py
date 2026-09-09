"""Long-horizon objective persistence (CAP-010).

A first-class primitive for surviving process restarts across long-horizon
work. Three guarantees, each independently testable:

1. **Objective snapshots** -- a structured objective (goal text, constraints,
   acceptance criteria, progress markers, ``created_at``, and a monotonically
   increasing ``revision``) is persisted to a durable append-only SQLite file.
   Every snapshot is a new revision; prior revisions are never mutated or
   deleted, so the full history is always recoverable.

2. **Drift audit** -- :meth:`ObjectiveStore.audit_drift` compares a current
   work-state against a persisted snapshot using deterministic, rule-based
   checks (no model required) and returns a :class:`DriftReport` with specific
   pointers into the offending constraint / acceptance-criterion.

3. **Exact resume** -- :meth:`ObjectiveStore.resume` reloads the latest
   snapshot for an objective and returns a :class:`ResumeState` that is
   byte-for-byte equal to what was persisted, so a freshly started process
   continues from the exact objective + progress.

This module lives in the ``memory`` tier and depends only on the standard
library (allowed to import ``core``/``library`` but needs neither).

Storage path resolution order:
    1. explicit ``path=`` argument to :class:`ObjectiveStore`
    2. ``THOMAS_OBJECTIVE_STORE_PATH`` environment variable (used by tests)
    3. ``~/.thomas/objectives.sqlite3``
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "ObjectiveSnapshot",
    "ResumeState",
    "DriftFinding",
    "DriftReport",
    "ObjectiveStore",
    "ObjectiveNotFoundError",
]

_ENV_PATH_VAR = "THOMAS_OBJECTIVE_STORE_PATH"


class ObjectiveNotFoundError(KeyError):
    """Raised when an operation targets an objective that has no snapshots."""


def _canonical_json(payload: dict[str, Any]) -> str:
    """Deterministic JSON serialization used both for storage and comparison.

    Sorted keys + tight separators guarantee that re-serializing a reloaded
    snapshot reproduces the exact bytes that were originally persisted.
    """

    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class ObjectiveSnapshot:
    """An immutable, revisioned snapshot of a long-horizon objective."""

    objective_id: str
    revision: int
    goal: str
    constraints: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    progress: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0

    def to_payload(self) -> dict[str, Any]:
        """Serialize to a plain dict with deterministic ordering of fields."""

        return {
            "acceptance_criteria": list(self.acceptance_criteria),
            "constraints": list(self.constraints),
            "created_at": self.created_at,
            "goal": self.goal,
            "objective_id": self.objective_id,
            "progress": self.progress,
            "revision": self.revision,
        }

    @property
    def canonical_json(self) -> str:
        """Byte-for-byte canonical serialization of this snapshot."""

        return _canonical_json(self.to_payload())

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ObjectiveSnapshot:
        return cls(
            objective_id=str(payload["objective_id"]),
            revision=int(payload["revision"]),
            goal=str(payload["goal"]),
            constraints=tuple(payload.get("constraints") or ()),
            acceptance_criteria=tuple(payload.get("acceptance_criteria") or ()),
            progress=dict(payload.get("progress") or {}),
            created_at=float(payload.get("created_at") or 0.0),
        )


@dataclass(frozen=True)
class ResumeState:
    """The exact state a restarted process resumes from."""

    snapshot: ObjectiveSnapshot
    stored_json: str

    @property
    def objective_id(self) -> str:
        return self.snapshot.objective_id

    @property
    def revision(self) -> int:
        return self.snapshot.revision

    @property
    def progress(self) -> dict[str, Any]:
        return self.snapshot.progress

    def is_exact(self) -> bool:
        """True when the reloaded snapshot re-serializes to the stored bytes."""

        return self.snapshot.canonical_json == self.stored_json


@dataclass(frozen=True)
class DriftFinding:
    """A single deterministic divergence from a persisted objective."""

    kind: str  # "constraint_violated" | "criterion_unaddressed"
    pointer: str  # e.g. "constraints[1]" / "acceptance_criteria[0]"
    detail: str


@dataclass(frozen=True)
class DriftReport:
    """Outcome of a drift audit against a snapshot."""

    objective_id: str
    revision: int
    findings: tuple[DriftFinding, ...] = ()

    @property
    def drifted(self) -> bool:
        return bool(self.findings)

    @property
    def violated_constraints(self) -> tuple[DriftFinding, ...]:
        return tuple(f for f in self.findings if f.kind == "constraint_violated")

    @property
    def unaddressed_criteria(self) -> tuple[DriftFinding, ...]:
        return tuple(f for f in self.findings if f.kind == "criterion_unaddressed")


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


class ObjectiveStore:
    """Append-only, restart-safe store for long-horizon objectives."""

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self._path = self._resolve_path(path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    @staticmethod
    def _resolve_path(path: str | os.PathLike[str] | None) -> str:
        if path is not None:
            return os.fspath(path)
        env = os.environ.get(_ENV_PATH_VAR)
        if env:
            return env
        return str(Path.home() / ".thomas" / "objectives.sqlite3")

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS objective_snapshots (
                    objective_id TEXT NOT NULL,
                    revision     INTEGER NOT NULL,
                    created_at   REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (objective_id, revision)
                )
                """
            )

    # -- persistence --------------------------------------------------------

    def snapshot(
        self,
        objective_id: str,
        goal: str,
        *,
        constraints: list[str] | tuple[str, ...] | None = None,
        acceptance_criteria: list[str] | tuple[str, ...] | None = None,
        progress: dict[str, Any] | None = None,
        created_at: float | None = None,
    ) -> ObjectiveSnapshot:
        """Persist a new, monotonically-revisioned snapshot (append-only)."""

        if not objective_id:
            raise ValueError("objective_id must be a non-empty string")
        revision = self._next_revision(objective_id)
        snap = ObjectiveSnapshot(
            objective_id=objective_id,
            revision=revision,
            goal=goal,
            constraints=tuple(constraints or ()),
            acceptance_criteria=tuple(acceptance_criteria or ()),
            progress=dict(progress or {}),
            created_at=time.time() if created_at is None else float(created_at),
        )
        payload_json = snap.canonical_json
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO objective_snapshots "
                    "(objective_id, revision, created_at, payload_json) "
                    "VALUES (?, ?, ?, ?)",
                    (objective_id, revision, snap.created_at, payload_json),
                )
        except sqlite3.IntegrityError as exc:  # concurrent writer took this rev
            raise RuntimeError(f"revision {revision} for {objective_id!r} already exists") from exc
        return snap

    def _next_revision(self, objective_id: str) -> int:
        row = self._conn.execute(
            "SELECT MAX(revision) AS m FROM objective_snapshots WHERE objective_id = ?",
            (objective_id,),
        ).fetchone()
        current = row["m"] if row is not None else None
        return 1 if current is None else int(current) + 1

    # -- retrieval ----------------------------------------------------------

    def latest(self, objective_id: str) -> ObjectiveSnapshot | None:
        row = self._conn.execute(
            "SELECT payload_json FROM objective_snapshots WHERE objective_id = ? ORDER BY revision DESC LIMIT 1",
            (objective_id,),
        ).fetchone()
        if row is None:
            return None
        return ObjectiveSnapshot.from_payload(json.loads(row["payload_json"]))

    def history(self, objective_id: str) -> list[ObjectiveSnapshot]:
        """Every revision for an objective, oldest first (append-only log)."""

        rows = self._conn.execute(
            "SELECT payload_json FROM objective_snapshots WHERE objective_id = ? ORDER BY revision ASC",
            (objective_id,),
        ).fetchall()
        return [ObjectiveSnapshot.from_payload(json.loads(r["payload_json"])) for r in rows]

    def objective_ids(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT objective_id FROM objective_snapshots ORDER BY objective_id"
        ).fetchall()
        return [str(r["objective_id"]) for r in rows]

    # -- exact resume -------------------------------------------------------

    def resume(self, objective_id: str) -> ResumeState:
        """Reload the latest snapshot exactly as persisted.

        The returned :class:`ResumeState` wraps both the reconstructed snapshot
        and the exact JSON bytes read from disk; ``is_exact()`` proves the
        round-trip is byte-for-byte faithful.
        """

        row = self._conn.execute(
            "SELECT payload_json FROM objective_snapshots WHERE objective_id = ? ORDER BY revision DESC LIMIT 1",
            (objective_id,),
        ).fetchone()
        if row is None:
            raise ObjectiveNotFoundError(objective_id)
        stored_json = row["payload_json"]
        snap = ObjectiveSnapshot.from_payload(json.loads(stored_json))
        return ResumeState(snapshot=snap, stored_json=stored_json)

    # -- drift audit --------------------------------------------------------

    def audit_drift(
        self,
        current_state: dict[str, Any],
        snapshot: ObjectiveSnapshot,
    ) -> DriftReport:
        """Deterministically flag divergence of ``current_state`` from a snapshot.

        ``current_state`` is a plain mapping describing the current work:

            {
                "violated_constraints": [<constraint text>, ...],
                "addressed_criteria":   [<acceptance criterion text>, ...],
            }

        Rules (all deterministic, no model):

        * every persisted constraint whose text appears in
          ``violated_constraints`` yields a ``constraint_violated`` finding;
        * every persisted acceptance criterion NOT present in
          ``addressed_criteria`` yields a ``criterion_unaddressed`` finding.

        A compliant state (no violated constraints, all criteria addressed)
        produces an empty, non-drifted report.
        """

        violated = {_normalize(str(c)) for c in current_state.get("violated_constraints") or ()}
        addressed = {_normalize(str(c)) for c in current_state.get("addressed_criteria") or ()}

        findings: list[DriftFinding] = []
        for idx, constraint in enumerate(snapshot.constraints):
            if _normalize(constraint) in violated:
                findings.append(
                    DriftFinding(
                        kind="constraint_violated",
                        pointer=f"constraints[{idx}]",
                        detail=constraint,
                    )
                )
        for idx, criterion in enumerate(snapshot.acceptance_criteria):
            if _normalize(criterion) not in addressed:
                findings.append(
                    DriftFinding(
                        kind="criterion_unaddressed",
                        pointer=f"acceptance_criteria[{idx}]",
                        detail=criterion,
                    )
                )
        return DriftReport(
            objective_id=snapshot.objective_id,
            revision=snapshot.revision,
            findings=tuple(findings),
        )

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> ObjectiveStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
