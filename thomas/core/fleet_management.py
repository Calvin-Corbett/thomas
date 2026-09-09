"""Programmatic fleet management: CRUD registry for agents, automations,
schedules, and policies.

This module is the *management / registry* layer for an agent fleet -- not the
executor. It exposes durable, validated CRUD over four resource kinds through a
single :class:`FleetManager`:

- ``agents``      -- required fields ``id``, ``name``
- ``automations`` -- required fields ``id``, ``trigger``, ``action``
- ``schedules``   -- required fields ``id``, ``cron``, ``target``
- ``policies``    -- required fields ``id``, ``rules``

Each kind supports the full lifecycle: :meth:`~FleetManager.create`,
:meth:`~FleetManager.get`, :meth:`~FleetManager.list`,
:meth:`~FleetManager.update`, :meth:`~FleetManager.delete`.

Guarantees:

- **Validated.** ``create`` rejects a missing required field
  (:class:`FleetValidationError`) and a duplicate id
  (:class:`FleetConflictError`). ``get`` / ``update`` / ``delete`` of an
  unknown id raise :class:`FleetNotFoundError` with a clear message.
- **Consistent.** A created resource is immediately gettable and listable; an
  updated one reflects the change on the next read; a deleted one is gone.
- **Durable.** State persists to a JSON file (atomic replace). The store path is
  overridable via the ``THOMAS_FLEET_STORE`` environment variable; otherwise it
  defaults under the resolved Thomas data dir. A fresh manager pointed at the
  same store observes all prior state.
- **Isolated.** The four kinds live in separate namespaces, so an ``agents``
  record and a ``policies`` record may share an id without colliding.
- **Deterministic.** No live processes, no network, no clock reads baked in --
  the timestamp source is an injectable ``clock`` callable.

Every mutating/reading operation returns a structured :class:`FleetRecord`
(``create`` / ``get`` / ``update``), a list of them (``list``), or a
:class:`FleetDeletion` receipt (``delete``).

Core-clean: stdlib only, plus :mod:`thomas.core.config` for default-path
resolution (same package).
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from thomas.core.config import resolve_thomas_data_dir

__all__ = [
    "FLEET_KINDS",
    "FleetConflictError",
    "FleetDeletion",
    "FleetError",
    "FleetManager",
    "FleetNotFoundError",
    "FleetRecord",
    "FleetValidationError",
    "resolve_fleet_store_path",
]

# ---------------------------------------------------------------------------
# Kind specifications -- required fields per resource kind. The id field is
# always required and is the primary key within a kind's namespace.
# ---------------------------------------------------------------------------

ID_FIELD = "id"

FLEET_KINDS: dict[str, tuple[str, ...]] = {
    "agents": ("id", "name"),
    "automations": ("id", "trigger", "action"),
    "schedules": ("id", "cron", "target"),
    "policies": ("id", "rules"),
}

_STORE_ENV_VAR = "THOMAS_FLEET_STORE"
_DEFAULT_STORE_NAME = "fleet_management.json"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FleetError(Exception):
    """Base class for all fleet-management errors."""


class FleetValidationError(FleetError):
    """A resource failed validation (unknown kind, missing/blank required field)."""


class FleetConflictError(FleetError):
    """A create was attempted for an id that already exists in the kind."""


class FleetNotFoundError(FleetError):
    """A get/update/delete referenced an id that does not exist in the kind."""


# ---------------------------------------------------------------------------
# Structured results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FleetRecord:
    """A single fleet resource plus its registry metadata.

    ``data`` holds the caller-supplied fields (including ``id``). ``created_at``
    and ``updated_at`` come from the injected clock. ``revision`` starts at 1 on
    create and increments on every successful update.
    """

    kind: str
    id: str
    data: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    updated_at: float = 0.0
    revision: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable copy of this record."""
        return {
            "kind": self.kind,
            "id": self.id,
            "data": copy.deepcopy(self.data),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> FleetRecord:
        """Reconstruct a record from its :meth:`to_dict` form."""
        return cls(
            kind=str(payload["kind"]),
            id=str(payload["id"]),
            data=copy.deepcopy(dict(payload.get("data") or {})),
            created_at=float(payload.get("created_at") or 0.0),
            updated_at=float(payload.get("updated_at") or 0.0),
            revision=int(payload.get("revision") or 1),
        )


@dataclass(frozen=True)
class FleetDeletion:
    """Structured receipt returned by :meth:`FleetManager.delete`."""

    kind: str
    id: str
    deleted: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "id": self.id, "deleted": self.deleted}


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def resolve_fleet_store_path(
    store_path: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the JSON store path.

    Precedence: explicit ``store_path`` argument, then the
    ``THOMAS_FLEET_STORE`` environment variable, then a default file under the
    resolved Thomas data dir.
    """
    env_map = env if env is not None else os.environ

    raw = str(store_path or "").strip()
    if not raw:
        raw = str(env_map.get(_STORE_ENV_VAR) or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()

    base = resolve_thomas_data_dir(env=env_map)
    return (base / "fleet" / _DEFAULT_STORE_NAME).resolve()


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class FleetManager:
    """Durable, validated CRUD over agents, automations, schedules, policies.

    Parameters
    ----------
    store_path:
        Explicit JSON store path. When omitted, resolved via
        :func:`resolve_fleet_store_path` (env-overridable).
    env:
        Environment mapping used for path resolution (defaults to
        ``os.environ``). Injectable for hermetic tests.
    clock:
        Zero-arg callable returning a float timestamp, used for
        ``created_at`` / ``updated_at``. Injectable for determinism.
    """

    def __init__(
        self,
        store_path: str | Path | None = None,
        *,
        env: Mapping[str, str] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._path = resolve_fleet_store_path(store_path, env=env)
        self._clock: Callable[[], float] = clock or time.time
        # namespace -> {id -> record dict}
        self._store: dict[str, dict[str, dict[str, Any]]] = {kind: {} for kind in FLEET_KINDS}
        self._load()

    # -- public API --------------------------------------------------------

    @property
    def store_path(self) -> Path:
        """The resolved JSON store path backing this manager."""
        return self._path

    def kinds(self) -> tuple[str, ...]:
        """The supported resource kinds."""
        return tuple(FLEET_KINDS)

    def create(self, kind: str, resource: Mapping[str, Any]) -> FleetRecord:
        """Create a new resource. Rejects missing required fields and dup ids."""
        required = self._require_kind(kind)
        if not isinstance(resource, Mapping):
            raise FleetValidationError(f"{kind} resource must be a mapping, got {type(resource).__name__}")

        data = copy.deepcopy(dict(resource))
        rid = self._extract_id(kind, data)
        self._check_required(kind, data, required)

        namespace = self._store[kind]
        if rid in namespace:
            raise FleetConflictError(f"{kind} id {rid!r} already exists")

        now = float(self._clock())
        record = FleetRecord(kind=kind, id=rid, data=data, created_at=now, updated_at=now, revision=1)
        namespace[rid] = record.to_dict()
        self._save()
        return record

    def get(self, kind: str, resource_id: str) -> FleetRecord:
        """Return the record for ``resource_id``; raise if it does not exist."""
        self._require_kind(kind)
        namespace = self._store[kind]
        stored = namespace.get(str(resource_id))
        if stored is None:
            raise FleetNotFoundError(f"{kind} id {str(resource_id)!r} not found")
        return FleetRecord.from_dict(stored)

    def exists(self, kind: str, resource_id: str) -> bool:
        """Whether a resource with ``resource_id`` exists in ``kind``."""
        self._require_kind(kind)
        return str(resource_id) in self._store[kind]

    def list(
        self,
        kind: str,
        filters: Mapping[str, Any] | None = None,
    ) -> list[FleetRecord]:
        """List records for ``kind``, optionally filtered.

        A filter matches when, for every ``key: value`` pair, the record's
        field equals ``value`` -- or, when the stored field is a list, when
        ``value`` is a member of it (enabling tag-style filters). Results are
        ordered deterministically by ``created_at`` then ``id``.
        """
        self._require_kind(kind)
        records = [FleetRecord.from_dict(stored) for stored in self._store[kind].values()]
        records.sort(key=lambda r: (r.created_at, r.id))
        if not filters:
            return records
        return [r for r in records if self._matches(r, filters)]

    def update(self, kind: str, resource_id: str, changes: Mapping[str, Any]) -> FleetRecord:
        """Merge ``changes`` into an existing record; raise if it does not exist.

        The ``id`` is immutable: a change that would alter it is rejected. The
        merged result is re-validated against the kind's required fields, so an
        update cannot blank a required field. ``revision`` increments and
        ``updated_at`` is refreshed from the clock.
        """
        required = self._require_kind(kind)
        rid = str(resource_id)
        namespace = self._store[kind]
        stored = namespace.get(rid)
        if stored is None:
            raise FleetNotFoundError(f"{kind} id {rid!r} not found")
        if not isinstance(changes, Mapping):
            raise FleetValidationError(f"{kind} changes must be a mapping, got {type(changes).__name__}")

        if ID_FIELD in changes and str(changes[ID_FIELD]) != rid:
            raise FleetValidationError(f"{kind} id is immutable: cannot change {rid!r} to {str(changes[ID_FIELD])!r}")

        merged = copy.deepcopy(dict(stored["data"]))
        merged.update(copy.deepcopy(dict(changes)))
        merged[ID_FIELD] = rid
        self._check_required(kind, merged, required)

        now = float(self._clock())
        record = FleetRecord(
            kind=kind,
            id=rid,
            data=merged,
            created_at=float(stored.get("created_at") or now),
            updated_at=now,
            revision=int(stored.get("revision") or 1) + 1,
        )
        namespace[rid] = record.to_dict()
        self._save()
        return record

    def delete(self, kind: str, resource_id: str) -> FleetDeletion:
        """Delete a resource; raise if it does not exist."""
        self._require_kind(kind)
        rid = str(resource_id)
        namespace = self._store[kind]
        if rid not in namespace:
            raise FleetNotFoundError(f"{kind} id {rid!r} not found")
        del namespace[rid]
        self._save()
        return FleetDeletion(kind=kind, id=rid, deleted=True)

    # -- internals ---------------------------------------------------------

    def _require_kind(self, kind: str) -> tuple[str, ...]:
        required = FLEET_KINDS.get(kind)
        if required is None:
            known = ", ".join(sorted(FLEET_KINDS))
            raise FleetValidationError(f"unknown fleet kind {kind!r}; expected one of: {known}")
        return required

    def _extract_id(self, kind: str, data: Mapping[str, Any]) -> str:
        if ID_FIELD not in data or data[ID_FIELD] is None:
            raise FleetValidationError(f"{kind} resource missing required field {ID_FIELD!r}")
        rid = str(data[ID_FIELD]).strip()
        if not rid:
            raise FleetValidationError(f"{kind} resource has a blank {ID_FIELD!r}")
        return rid

    def _check_required(self, kind: str, data: Mapping[str, Any], required: tuple[str, ...]) -> None:
        missing = [f for f in required if data.get(f) is None]
        if missing:
            raise FleetValidationError(f"{kind} resource missing required field(s): {', '.join(sorted(missing))}")

    @staticmethod
    def _matches(record: FleetRecord, filters: Mapping[str, Any]) -> bool:
        for key, want in filters.items():
            have = record.data.get(key)
            if isinstance(have, list):
                if want not in have:
                    return False
            elif have != want:
                return False
        return True

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            raise FleetError(f"failed to read fleet store {self._path}: {exc}") from exc
        if not raw.strip():
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FleetError(f"fleet store {self._path} is not valid JSON: {exc}") from exc

        kinds_payload = payload.get("kinds") if isinstance(payload, Mapping) else None
        if not isinstance(kinds_payload, Mapping):
            raise FleetError(f"fleet store {self._path} has an unexpected shape")

        for kind in FLEET_KINDS:
            entries = kinds_payload.get(kind) or {}
            if not isinstance(entries, Mapping):
                raise FleetError(f"fleet store {self._path} kind {kind!r} is malformed")
            namespace: dict[str, dict[str, Any]] = {}
            for rid, stored in entries.items():
                if not isinstance(stored, Mapping):
                    raise FleetError(f"fleet store {self._path} record {kind}/{rid} is malformed")
                namespace[str(rid)] = FleetRecord.from_dict(stored).to_dict()
            self._store[kind] = namespace

    def _save(self) -> None:
        payload = {
            "version": 1,
            "kinds": {kind: dict(namespace) for kind, namespace in self._store.items()},
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self._path.name}.",
            suffix=".tmp",
            dir=str(self._path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.replace(tmp_name, self._path)
        except OSError as exc:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise FleetError(f"failed to write fleet store {self._path}: {exc}") from exc
