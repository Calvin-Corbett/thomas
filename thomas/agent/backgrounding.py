"""CAP-059: one-command backgrounding for inflight agent runs (stdlib-only).

An inflight run can be *backgrounded* with a single call
(:meth:`BackgroundRunRegistry.background`) and later *reattached*
(:meth:`BackgroundRunRegistry.reattach`). Between those two points a status
surface can enumerate backgrounded runs (:meth:`list_background`) and query
any run's live state, progress, and a deterministic ETA
(:meth:`status`).

Design
------
Durable store
    Records live in a single JSON file so that a backgrounded run survives a
    process restart (a CLI that backgrounds a run in one invocation and
    reattaches in another must see it). The path is taken from the
    ``store_path`` argument, else the ``THOMAS_BACKGROUNDING_STORE`` environment
    variable, else a per-user default under the home directory. Writes are
    atomic (temp file + ``os.replace``) so a crash mid-write cannot corrupt an
    existing store.

State machine
    ``RUNNING -> BACKGROUNDED`` via :meth:`background`;
    ``BACKGROUNDED -> RUNNING`` (foregrounded) via a successful
    :meth:`reattach`; and either may transition to the terminal ``DONE`` /
    ``FAILED`` via :meth:`mark_done` / :meth:`mark_failed`. Terminal runs are
    immutable and cannot be reattached. A ``status`` query for a run the store
    has never seen returns the sentinel ``UNKNOWN`` state rather than raising,
    so a status surface never crashes on a stale id.

ETA estimator (deterministic — see :func:`estimate_eta_seconds`)
    The ETA is derived from an *elapsed-rate* projection against an
    *estimated-total* step count. Given a progress snapshot with ``steps_done``
    completed at wall-clock ``now`` for a run started at ``started_at``::

        elapsed = now - started_at
        rate    = steps_done / elapsed          # steps completed per second
        remaining = estimated_total - steps_done
        eta_seconds = remaining / rate = remaining * elapsed / steps_done

    The estimate is intentionally ``None`` (unknown) when it cannot be computed
    honestly: no ``estimated_total`` was supplied, no progress has been made
    (``steps_done <= 0``), or no time has elapsed (``elapsed <= 0``) — in each
    case there is no defensible rate to project. When ``steps_done`` already
    meets or exceeds ``estimated_total`` the ETA is ``0.0``. Because the
    projection is a pure function of the snapshot and the injected ``now``, the
    same inputs always yield the same ETA, which keeps tests hermetic.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

ENV_STORE_PATH = "THOMAS_BACKGROUNDING_STORE"


class BackgroundStoreError(RuntimeError):
    """Raised when the durable store exists but cannot be parsed."""


class RunState(str, enum.Enum):
    """Lifecycle state of a run tracked by the registry.

    ``UNKNOWN`` is a non-canonical sentinel returned by :meth:`status` for a
    run id the store has never recorded; it is never persisted.
    """

    RUNNING = "running"
    BACKGROUNDED = "backgrounded"
    DONE = "done"
    FAILED = "failed"
    UNKNOWN = "unknown"


TERMINAL_STATES: frozenset[RunState] = frozenset({RunState.DONE, RunState.FAILED})


@dataclasses.dataclass(frozen=True)
class ProgressSnapshot:
    """A point-in-time view of a run's progress.

    steps_done: completed unit-of-work count.
    phase: human-readable phase label ("planning", "executing", ...).
    started_at: wall-clock epoch seconds when the run began (ETA anchor).
    estimated_total: best-known total step count, or ``None`` if unknown.
    cursor: position in the run's event/stream from which a reattach resumes
        (e.g. an event index or byte offset). Defaults to ``steps_done`` when
        not supplied so a naive caller still gets a sensible resume point.
    """

    steps_done: int = 0
    phase: str = ""
    started_at: float = 0.0
    estimated_total: int | None = None
    cursor: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps_done": self.steps_done,
            "phase": self.phase,
            "started_at": self.started_at,
            "estimated_total": self.estimated_total,
            "cursor": self.cursor,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProgressSnapshot:
        return cls(
            steps_done=int(data.get("steps_done", 0)),
            phase=str(data.get("phase", "")),
            started_at=float(data.get("started_at", 0.0)),
            estimated_total=(None if data.get("estimated_total") is None else int(data["estimated_total"])),
            cursor=int(data.get("cursor", 0)),
        )


@dataclasses.dataclass(frozen=True)
class RunStatus:
    """Structured status returned by :meth:`BackgroundRunRegistry.status`.

    eta_seconds: projected seconds until completion, or ``None`` when it cannot
        be estimated (see :func:`estimate_eta_seconds`).
    eta_at: absolute epoch seconds at which completion is projected
        (``now + eta_seconds``), or ``None`` when ``eta_seconds`` is ``None``.
    """

    run_id: str
    state: RunState
    progress: ProgressSnapshot
    eta_seconds: float | None
    eta_at: float | None

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES


@dataclasses.dataclass(frozen=True)
class ReattachHandle:
    """Result of :meth:`BackgroundRunRegistry.reattach`.

    ``ok`` is ``True`` only when a backgrounded (or running) run was found and
    foregrounded; ``cursor`` and ``progress`` then carry enough state to resume
    streaming from where the background snapshot left off. When ``ok`` is
    ``False`` (unknown id or a terminal run), ``reason`` explains why and no
    state transition occurred — callers get a clear signal, not an exception.
    """

    run_id: str
    ok: bool
    state: RunState
    cursor: int = 0
    progress: ProgressSnapshot | None = None
    reason: str = ""


def estimate_eta_seconds(
    *,
    steps_done: int,
    estimated_total: int | None,
    started_at: float,
    now: float,
) -> float | None:
    """Project seconds-to-completion via elapsed-rate against an estimated total.

    Returns ``None`` when no honest estimate exists (no ``estimated_total``, no
    progress, or no elapsed time), ``0.0`` when the run has met/exceeded its
    estimated total, and otherwise ``remaining * elapsed / steps_done``. See
    the module docstring for the full derivation.
    """
    if estimated_total is None:
        return None
    if steps_done >= estimated_total:
        return 0.0
    if steps_done <= 0:
        return None
    elapsed = now - started_at
    if elapsed <= 0:
        return None
    remaining = estimated_total - steps_done
    return remaining * elapsed / steps_done


def _default_store_path() -> Path:
    """Resolve the store path: env override, else a per-user default."""
    env = os.environ.get(ENV_STORE_PATH)
    if env:
        return Path(env)
    return Path.home() / ".thomas" / "backgrounding" / "runs.json"


class BackgroundRunRegistry:
    """Durable registry of backgrounded runs with status, ETA, and reattach.

    All mutations write through to the JSON store atomically. A single
    ``threading.Lock`` guards the in-memory record map so concurrent status
    surfaces and the run's own worker do not race. The ``clock`` is injectable
    to keep ETA computation and tests deterministic.
    """

    def __init__(
        self,
        store_path: str | os.PathLike[str] | None = None,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._path = Path(store_path) if store_path is not None else _default_store_path()
        self._clock: Callable[[], float] = clock or time.time
        self._lock = threading.Lock()
        self._records: dict[str, dict[str, Any]] = self._load()

    # -- persistence ---------------------------------------------------------

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BackgroundStoreError(f"corrupt backgrounding store at {self._path}: {exc}") from exc
        runs = data.get("runs", {}) if isinstance(data, dict) else {}
        return {str(k): dict(v) for k, v in runs.items()} if isinstance(runs, dict) else {}

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": 1, "runs": self._records}, indent=2, sort_keys=True)
        tmp = self._path.with_name(f"{self._path.name}.{os.getpid()}.tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self._path)

    def _record(self, run_id: str, state: RunState, snapshot: ProgressSnapshot) -> dict[str, Any]:
        now = self._clock()
        existing = self._records.get(run_id, {})
        rec = {
            "run_id": run_id,
            "state": state.value,
            "snapshot": snapshot.to_dict(),
            "backgrounded_at": existing.get("backgrounded_at"),
            "updated_at": now,
        }
        if state is RunState.BACKGROUNDED:
            rec["backgrounded_at"] = now
        return rec

    # -- public API ----------------------------------------------------------

    def background(self, run_id: str, snapshot: ProgressSnapshot) -> RunStatus:
        """Background an inflight run with one call, recording its snapshot.

        Idempotent: backgrounding an already-backgrounded run refreshes its
        snapshot. Refuses to background a terminal (done/failed) run.
        """
        with self._lock:
            existing = self._records.get(run_id)
            if existing is not None and RunState(existing["state"]) in TERMINAL_STATES:
                raise ValueError(f"run {run_id!r} is already {existing['state']} and cannot be backgrounded")
            self._records[run_id] = self._record(run_id, RunState.BACKGROUNDED, snapshot)
            self._flush()
        return self.status(run_id)

    def update_progress(self, run_id: str, snapshot: ProgressSnapshot) -> None:
        """Refresh the progress snapshot of a known, non-terminal run in place."""
        with self._lock:
            existing = self._records.get(run_id)
            if existing is None:
                raise KeyError(run_id)
            state = RunState(existing["state"])
            if state in TERMINAL_STATES:
                raise ValueError(f"run {run_id!r} is {state.value} and cannot be updated")
            self._records[run_id] = self._record(run_id, state, snapshot)
            self._flush()

    def mark_done(self, run_id: str, snapshot: ProgressSnapshot | None = None) -> None:
        """Mark a run finished successfully (terminal)."""
        self._finish(run_id, RunState.DONE, snapshot)

    def mark_failed(self, run_id: str, snapshot: ProgressSnapshot | None = None) -> None:
        """Mark a run finished with failure (terminal)."""
        self._finish(run_id, RunState.FAILED, snapshot)

    def _finish(self, run_id: str, state: RunState, snapshot: ProgressSnapshot | None) -> None:
        with self._lock:
            existing = self._records.get(run_id)
            snap = snapshot
            if snap is None:
                snap = ProgressSnapshot.from_dict(existing["snapshot"]) if existing else ProgressSnapshot()
            self._records[run_id] = self._record(run_id, state, snap)
            self._flush()

    def status(self, run_id: str, *, now: float | None = None) -> RunStatus:
        """Return structured state, progress, and an ETA for ``run_id``.

        An unknown run yields ``RunState.UNKNOWN`` with an empty snapshot and no
        ETA, so a status surface never crashes on a stale id.
        """
        with self._lock:
            rec = self._records.get(run_id)
        if rec is None:
            return RunStatus(
                run_id=run_id,
                state=RunState.UNKNOWN,
                progress=ProgressSnapshot(),
                eta_seconds=None,
                eta_at=None,
            )
        snapshot = ProgressSnapshot.from_dict(rec["snapshot"])
        state = RunState(rec["state"])
        clock_now = self._clock() if now is None else now
        if state in TERMINAL_STATES:
            eta_seconds: float | None = 0.0 if state is RunState.DONE else None
        else:
            eta_seconds = estimate_eta_seconds(
                steps_done=snapshot.steps_done,
                estimated_total=snapshot.estimated_total,
                started_at=snapshot.started_at,
                now=clock_now,
            )
        eta_at = None if eta_seconds is None else clock_now + eta_seconds
        return RunStatus(
            run_id=run_id,
            state=state,
            progress=snapshot,
            eta_seconds=eta_seconds,
            eta_at=eta_at,
        )

    def reattach(self, run_id: str) -> ReattachHandle:
        """Reattach to a backgrounded run and foreground it.

        On success the run transitions ``BACKGROUNDED -> RUNNING`` and the
        handle carries the last progress cursor and snapshot needed to resume
        streaming. Unknown ids and terminal runs return ``ok=False`` with a
        reason and leave state untouched.
        """
        with self._lock:
            rec = self._records.get(run_id)
            if rec is None:
                return ReattachHandle(
                    run_id=run_id,
                    ok=False,
                    state=RunState.UNKNOWN,
                    reason="unknown run",
                )
            state = RunState(rec["state"])
            snapshot = ProgressSnapshot.from_dict(rec["snapshot"])
            if state in TERMINAL_STATES:
                return ReattachHandle(
                    run_id=run_id,
                    ok=False,
                    state=state,
                    cursor=snapshot.cursor,
                    progress=snapshot,
                    reason=f"run already {state.value}",
                )
            # Foreground it.
            self._records[run_id] = self._record(run_id, RunState.RUNNING, snapshot)
            self._flush()
        return ReattachHandle(
            run_id=run_id,
            ok=True,
            state=RunState.RUNNING,
            cursor=snapshot.cursor,
            progress=snapshot,
            reason="",
        )

    def list_background(self, *, now: float | None = None) -> list[RunStatus]:
        """Enumerate currently-backgrounded runs for a status surface.

        Ordered by most-recently backgrounded first.
        """
        with self._lock:
            backgrounded = [
                (rec.get("backgrounded_at") or 0.0, run_id)
                for run_id, rec in self._records.items()
                if RunState(rec["state"]) is RunState.BACKGROUNDED
            ]
        backgrounded.sort(key=lambda item: item[0], reverse=True)
        return [self.status(run_id, now=now) for _, run_id in backgrounded]
