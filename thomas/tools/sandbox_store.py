"""Persistent server-side sandbox registry with a startup reconciler.

Server-side sandboxes (containers / micro-VMs) must survive a server restart:
the process that created them dies and restarts, but the underlying provider
resources (Docker containers, Firecracker VMs, ...) keep running. This module
provides the durable half of that story.

Two pieces:

* :class:`SandboxStore` — a durable SQLite-backed registry recording every
  sandbox: id, spec, provider ref, state, ``created_at``, teardown policy, and
  process/volume metadata. The path is env-overridable
  (``THOMAS_SANDBOX_STORE_PATH``). It follows the same WAL + ``NORMAL`` sync
  conventions as ``thomas/memory/store.py`` (MetaDB), but is self-contained so
  the ``tools`` tier does not reach up into ``memory``.

* A **startup reconciler** (:meth:`SandboxStore.reconcile`) that, on server
  (re)start, reconciles the durable store against *provider truth* obtained
  from an injectable :class:`SandboxProvider`. Still-alive sandboxes are adopted
  (their state synced from the provider), vanished ones are marked ``gone``, and
  a sandbox that is present in the provider but new to the store is adopted as a
  fresh record. A sandbox that was already marked ``gone`` is never resurrected.

The real default provider (:class:`SubprocessContainerProvider`) shells out to a
container lister (``docker ps`` by default) using only stdlib. Tests inject
:class:`FakeProvider` for a fully hermetic run — no network, no daemon, injected
clock.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

_ENV_PATH = "THOMAS_SANDBOX_STORE_PATH"


# ---------------------------------------------------------------------------
# States and policies
# ---------------------------------------------------------------------------


class SandboxState(str, Enum):
    """Lifecycle state of a sandbox as recorded in the store."""

    PENDING = "pending"
    RUNNING = "running"
    STOPPED = "stopped"
    GONE = "gone"


class TeardownPolicy(str, Enum):
    """Durability policy applied when a sandbox is torn down.

    ``KEEP_VOLUME`` retains the sandbox's volume metadata (a durable disk that
    outlives the container); ``REMOVE_VOLUME`` clears it (ephemeral scratch).
    """

    KEEP_VOLUME = "keep_volume"
    REMOVE_VOLUME = "remove_volume"


# Provider-reported state string -> SandboxState. Unknown-but-alive states fall
# back to RUNNING; explicitly dead states map to GONE.
_PROVIDER_STATE_MAP: dict[str, SandboxState] = {
    "running": SandboxState.RUNNING,
    "up": SandboxState.RUNNING,
    "restarting": SandboxState.RUNNING,
    "created": SandboxState.PENDING,
    "pending": SandboxState.PENDING,
    "paused": SandboxState.STOPPED,
    "stopped": SandboxState.STOPPED,
    "exited": SandboxState.STOPPED,
    "dead": SandboxState.GONE,
    "removing": SandboxState.GONE,
}


def _map_provider_state(raw: str) -> SandboxState:
    """Map a provider-reported state string to a :class:`SandboxState`."""
    return _PROVIDER_STATE_MAP.get(raw.strip().lower(), SandboxState.RUNNING)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SandboxRecord:
    """A single durable sandbox entry."""

    id: str
    spec: dict[str, Any]
    provider_ref: str
    state: SandboxState
    created_at: int
    teardown_policy: TeardownPolicy = TeardownPolicy.KEEP_VOLUME
    process_metadata: dict[str, Any] = field(default_factory=dict)
    volume_metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: int = 0

    def to_row(self) -> tuple[Any, ...]:
        return (
            self.id,
            json.dumps(self.spec, ensure_ascii=False),
            self.provider_ref,
            self.state.value,
            int(self.created_at),
            self.teardown_policy.value,
            json.dumps(self.process_metadata, ensure_ascii=False),
            json.dumps(self.volume_metadata, ensure_ascii=False),
            int(self.updated_at),
        )

    @staticmethod
    def from_row(row: tuple[Any, ...]) -> SandboxRecord:
        return SandboxRecord(
            id=row[0],
            spec=json.loads(row[1]),
            provider_ref=row[2],
            state=SandboxState(row[3]),
            created_at=int(row[4]),
            teardown_policy=TeardownPolicy(row[5]),
            process_metadata=json.loads(row[6]),
            volume_metadata=json.loads(row[7]),
            updated_at=int(row[8]),
        )


@dataclass(frozen=True)
class ProviderSandbox:
    """Provider truth for a single live sandbox (a container / VM lister row)."""

    ref: str
    state: str
    spec: dict[str, Any] = field(default_factory=dict)
    process_metadata: dict[str, Any] = field(default_factory=dict)
    volume_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReconcileReport:
    """Outcome of a reconcile pass."""

    adopted: list[str] = field(default_factory=list)  # existing, still alive
    marked_gone: list[str] = field(default_factory=list)  # vanished from provider
    newly_adopted: list[str] = field(default_factory=list)  # new to the store
    skipped_dead: list[str] = field(default_factory=list)  # already gone, not resurrected


# ---------------------------------------------------------------------------
# Provider interface + real default
# ---------------------------------------------------------------------------


@runtime_checkable
class SandboxProvider(Protocol):
    """Source of provider truth. Injectable so tests can supply a fake."""

    def list_live(self) -> list[ProviderSandbox]:
        """Return every sandbox the provider currently knows about."""
        ...


class ProviderUnavailable(RuntimeError):
    """Raised when the real provider cannot be queried.

    Reconcile propagates this rather than treating an unreachable provider as
    "everything vanished" — a transient daemon outage must not nuke the store.
    """


class SubprocessContainerProvider:
    """Real default provider: lists containers via a subprocess (``docker ps``).

    Uses only stdlib (:mod:`subprocess`). The lister command is injectable and
    env-overridable so this works with docker, podman, nerdctl, etc. Output is
    expected to be one JSON object per line (``docker ps --format '{{json .}}'``).

    This lane is real-system-gated: it requires a container runtime to be
    installed and reachable. It is exercised live only when such a runtime
    exists; the hermetic core is proven against :class:`FakeProvider`.
    """

    _FAULTS = (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError)

    def __init__(
        self,
        list_command: list[str] | None = None,
        *,
        runner: Callable[[list[str]], str] | None = None,
        timeout_s: float = 15.0,
    ) -> None:
        env_cmd = os.environ.get("THOMAS_SANDBOX_LIST_COMMAND")
        if list_command is not None:
            self._cmd = list(list_command)
        elif env_cmd:
            self._cmd = env_cmd.split()
        else:
            self._cmd = ["docker", "ps", "--all", "--no-trunc", "--format", "{{json .}}"]
        self._runner = runner
        self._timeout_s = timeout_s

    def _run(self) -> str:
        if self._runner is not None:
            return self._runner(self._cmd)
        completed = subprocess.run(  # noqa: S603 - command is caller/env-controlled, not shell
            self._cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=self._timeout_s,
        )
        return completed.stdout

    def list_live(self) -> list[ProviderSandbox]:
        try:
            raw = self._run()
        except self._FAULTS as exc:
            logger.warning("sandbox provider lister failed (%s): %s", type(exc).__name__, exc)
            raise ProviderUnavailable(str(exc)) from exc
        out: list[ProviderSandbox] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("skipping unparsable lister row: %s", exc)
                continue
            ref = str(obj.get("ID") or obj.get("Id") or obj.get("Names") or "").strip()
            if not ref:
                continue
            out.append(
                ProviderSandbox(
                    ref=ref,
                    state=str(obj.get("State") or obj.get("Status") or "running"),
                    spec={"image": obj.get("Image"), "names": obj.get("Names")},
                    process_metadata={"status": obj.get("Status")},
                )
            )
        return out


# ---------------------------------------------------------------------------
# Durable store
# ---------------------------------------------------------------------------


def _default_clock() -> int:
    return int(time.time())


def resolve_store_path(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the store path: explicit arg > env var > default under cwd."""
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get(_ENV_PATH)
    if env:
        return Path(env)
    return Path("data") / "sandbox_store.db"


class SandboxStore:
    """Durable registry of server-side sandboxes with a startup reconciler."""

    def __init__(
        self,
        db_path: str | os.PathLike[str] | None = None,
        *,
        clock: Callable[[], int] = _default_clock,
    ) -> None:
        self._path = resolve_store_path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sandboxes (
                id TEXT PRIMARY KEY,
                spec_json TEXT NOT NULL DEFAULT '{}',
                provider_ref TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                teardown_policy TEXT NOT NULL DEFAULT 'keep_volume',
                process_metadata_json TEXT NOT NULL DEFAULT '{}',
                volume_metadata_json TEXT NOT NULL DEFAULT '{}',
                updated_at INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_sandbox_ref ON sandboxes(provider_ref)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_sandbox_state ON sandboxes(state)")
        self._conn.commit()

    # --- CRUD -------------------------------------------------------------

    def record(
        self,
        sandbox_id: str,
        spec: dict[str, Any],
        provider_ref: str,
        state: SandboxState = SandboxState.PENDING,
        *,
        teardown_policy: TeardownPolicy = TeardownPolicy.KEEP_VOLUME,
        process_metadata: dict[str, Any] | None = None,
        volume_metadata: dict[str, Any] | None = None,
    ) -> SandboxRecord:
        """Insert or replace a sandbox record. Returns the persisted record."""
        now = self._clock()
        existing = self.get(sandbox_id)
        created = existing.created_at if existing else now
        rec = SandboxRecord(
            id=sandbox_id,
            spec=dict(spec),
            provider_ref=provider_ref,
            state=state,
            created_at=created,
            teardown_policy=teardown_policy,
            process_metadata=dict(process_metadata or {}),
            volume_metadata=dict(volume_metadata or {}),
            updated_at=now,
        )
        self._upsert(rec)
        return rec

    def _upsert(self, rec: SandboxRecord) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO sandboxes "
            "(id, spec_json, provider_ref, state, created_at, teardown_policy, "
            " process_metadata_json, volume_metadata_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rec.to_row(),
        )
        self._conn.commit()

    def get(self, sandbox_id: str) -> SandboxRecord | None:
        row = self._conn.execute(
            "SELECT id, spec_json, provider_ref, state, created_at, teardown_policy, "
            "process_metadata_json, volume_metadata_json, updated_at "
            "FROM sandboxes WHERE id = ?",
            (sandbox_id,),
        ).fetchone()
        return SandboxRecord.from_row(row) if row else None

    def list_all(self, *, include_gone: bool = True) -> list[SandboxRecord]:
        if include_gone:
            rows = self._conn.execute(
                "SELECT id, spec_json, provider_ref, state, created_at, teardown_policy, "
                "process_metadata_json, volume_metadata_json, updated_at "
                "FROM sandboxes ORDER BY created_at, id"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, spec_json, provider_ref, state, created_at, teardown_policy, "
                "process_metadata_json, volume_metadata_json, updated_at "
                "FROM sandboxes WHERE state != ? ORDER BY created_at, id",
                (SandboxState.GONE.value,),
            ).fetchall()
        return [SandboxRecord.from_row(r) for r in rows]

    def _set_state(self, sandbox_id: str, state: SandboxState) -> None:
        self._conn.execute(
            "UPDATE sandboxes SET state = ?, updated_at = ? WHERE id = ?",
            (state.value, self._clock(), sandbox_id),
        )
        self._conn.commit()

    # --- Teardown ---------------------------------------------------------

    def teardown(self, sandbox_id: str) -> SandboxRecord | None:
        """Mark a sandbox gone, applying its teardown policy to the volume.

        ``KEEP_VOLUME`` retains ``volume_metadata`` (durable disk survives);
        ``REMOVE_VOLUME`` clears it (ephemeral scratch discarded).
        """
        rec = self.get(sandbox_id)
        if rec is None:
            return None
        keep = rec.teardown_policy is TeardownPolicy.KEEP_VOLUME
        new_volume = dict(rec.volume_metadata) if keep else {}
        updated = replace(
            rec,
            state=SandboxState.GONE,
            volume_metadata=new_volume,
            updated_at=self._clock(),
        )
        self._upsert(updated)
        return updated

    # --- Reconciler -------------------------------------------------------

    def reconcile(self, provider: SandboxProvider) -> ReconcileReport:
        """Reconcile the durable store against provider truth on (re)start.

        * A stored sandbox still present in the provider is **adopted** and its
          state synced from provider truth.
        * A stored sandbox absent from the provider is **marked gone**.
        * A provider sandbox new to the store is **adopted** as a fresh record.
        * A sandbox already marked ``gone`` is **never resurrected**, even if the
          provider still lists its ref.

        Raises :class:`ProviderUnavailable` (propagated from the provider) if the
        provider cannot be queried, so a transient outage never mass-marks gone.
        """
        truth: dict[str, ProviderSandbox] = {p.ref: p for p in provider.list_live()}
        report = ReconcileReport()
        seen_refs: set[str] = set()

        for rec in self.list_all(include_gone=True):
            if rec.state is SandboxState.GONE:
                # Dead stays dead. Claim its ref so we do not re-adopt as new.
                seen_refs.add(rec.provider_ref)
                report.skipped_dead.append(rec.id)
                continue
            live = truth.get(rec.provider_ref)
            if live is not None:
                seen_refs.add(rec.provider_ref)
                new_state = _map_provider_state(live.state)
                updated = replace(
                    rec,
                    state=new_state,
                    process_metadata=dict(live.process_metadata) or rec.process_metadata,
                    updated_at=self._clock(),
                )
                self._upsert(updated)
                report.adopted.append(rec.id)
            else:
                self._set_state(rec.id, SandboxState.GONE)
                report.marked_gone.append(rec.id)

        # Provider sandboxes new to the store are adopted.
        for ref, live in truth.items():
            if ref in seen_refs:
                continue
            new_id = f"adopted-{ref}"
            self.record(
                new_id,
                spec=dict(live.spec),
                provider_ref=ref,
                state=_map_provider_state(live.state),
                process_metadata=dict(live.process_metadata),
                volume_metadata=dict(live.volume_metadata),
            )
            report.newly_adopted.append(new_id)

        return report

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()

    def __enter__(self) -> SandboxStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Hermetic fake provider (for tests and offline reconcile dry-runs)
# ---------------------------------------------------------------------------


class FakeProvider:
    """In-memory :class:`SandboxProvider` for hermetic tests."""

    def __init__(self, live: Iterable[ProviderSandbox] = ()) -> None:
        self._live: list[ProviderSandbox] = list(live)

    def set_live(self, live: Iterable[ProviderSandbox]) -> None:
        self._live = list(live)

    def list_live(self) -> list[ProviderSandbox]:
        return list(self._live)


__all__ = [
    "FakeProvider",
    "ProviderSandbox",
    "ProviderUnavailable",
    "ReconcileReport",
    "SandboxProvider",
    "SandboxRecord",
    "SandboxState",
    "SandboxStore",
    "SubprocessContainerProvider",
    "TeardownPolicy",
    "resolve_store_path",
]
