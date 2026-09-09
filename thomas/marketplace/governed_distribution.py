"""Governed team/organization distribution for marketplace items.

CAP-026 -- "Plugins/extensions + marketplace" (Level 2:
"Add governed team and organization distribution with approval and revocation.")

A :class:`GovernedDistribution` layer sits *over* an existing item registry
(plugins / extensions / skills) and answers one question durably and
deterministically: **which members of a team or organization are entitled to
receive a given marketplace item, right now?**

Governance model
----------------
1. **Distribution to a scope.** An admin *requests* distribution of an item to a
   ``team`` or ``org`` scope. The request starts life ``pending`` -- it grants
   nothing until it is approved.
2. **Approval gate.** Only an *authorized approver* for that scope may approve
   (or reject). A ``rejected`` request is never distributed; a ``pending``
   request is not distributed until approved. Approval effectuates the
   distribution (status ``active``) so members of the scope receive the item.
3. **Revocation.** An admin revokes an active distribution: it is withdrawn from
   the scope's members immediately, and future installs are blocked. Every
   approve / distribute / revoke transition is appended to a durable audit trail.

Injectable edges (real default + hermetic fake)
-----------------------------------------------
* **Item registry** -- :class:`ItemRegistry`. The real default
  :class:`PluginItemRegistry` reuses the repo's plugin registry
  (``thomas.plugins``) with no new deps. :class:`FakeItemRegistry` is a
  hermetic in-memory set for tests / offline use.
* **Membership** -- :class:`MembershipProvider`. Who belongs to a team / org is
  external directory data; :class:`InMemoryDirectory` is a deterministic default
  usable in tests and small deployments.
* **Approver authority** -- :class:`ApproverPolicy`. :class:`InMemoryApproverPolicy`
  maps scopes (and a global tier) to authorized approver ids.
* **Clock** -- injected ``Callable[[], float]`` so timestamps are deterministic.

Persistence is JSON, env-overridable via ``THOMAS_GOVERNED_DISTRIBUTION_FILE``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

Clock = Callable[[], float]

ScopeType = Literal["team", "org"]
_SCOPE_TYPES: frozenset[str] = frozenset({"team", "org"})

# Distribution lifecycle.
STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_REJECTED = "rejected"
STATUS_REVOKED = "revoked"

# Audit actions.
ACTION_REQUEST = "request"
ACTION_APPROVE = "approve"
ACTION_DISTRIBUTE = "distribute"
ACTION_REJECT = "reject"
ACTION_REVOKE = "revoke"

_STATE_VERSION = 1


def _default_clock() -> float:
    import time

    return time.time()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class GovernedDistributionError(Exception):
    """Base error for the governed distribution layer."""


class InvalidScopeError(GovernedDistributionError):
    """The scope type is not ``team`` or ``org``, or an id is empty."""


class UnknownItemError(GovernedDistributionError):
    """The item is not present in the backing item registry."""


class DistributionNotFoundError(GovernedDistributionError):
    """No distribution exists for the given id."""


class NotAuthorizedError(GovernedDistributionError):
    """The actor is not authorized to approve / reject for the scope."""


class InvalidStateError(GovernedDistributionError):
    """The distribution is not in a state that allows the requested transition."""


# ---------------------------------------------------------------------------
# Injectable edges
# ---------------------------------------------------------------------------


@runtime_checkable
class ItemRegistry(Protocol):
    """Backing registry of distributable items (plugins / extensions / skills)."""

    def has_item(self, item_id: str) -> bool: ...


@runtime_checkable
class MembershipProvider(Protocol):
    """Resolves whether a member belongs to a team / org scope."""

    def is_member(self, scope_type: str, scope_id: str, member_id: str) -> bool: ...


@runtime_checkable
class ApproverPolicy(Protocol):
    """Resolves whether an actor may approve / reject for a scope."""

    def can_approve(self, approver_id: str, scope_type: str, scope_id: str) -> bool: ...


class FakeItemRegistry:
    """Hermetic in-memory item registry (default-usable, test-friendly)."""

    def __init__(self, items: object = None) -> None:
        self._items: set[str] = set()
        if items is not None:
            for item in items:  # type: ignore[union-attr]
                self._items.add(str(item))

    def add(self, item_id: str) -> None:
        self._items.add(str(item_id))

    def remove(self, item_id: str) -> None:
        self._items.discard(str(item_id))

    def has_item(self, item_id: str) -> bool:
        return str(item_id) in self._items


class PluginItemRegistry:
    """Real default: resolves item existence against the repo plugin registry.

    Reuses :func:`thomas.plugins.p105_plugin_registry_core_model.build_plugin_registry_core_model`
    (marketplace -> plugins is an allowed dependency edge). Imported lazily so
    constructing this class never pulls the plugin stack until first use. An
    item id matches either a plugin ``name`` or its module path.
    """

    def __init__(self, loader: Callable[[], object] | None = None) -> None:
        self._loader = loader
        self._cache: set[str] | None = None

    def _load_ids(self) -> set[str]:
        if self._cache is not None:
            return self._cache
        if self._loader is not None:
            model = self._loader()
        else:
            from thomas.plugins.p105_plugin_registry_core_model import (
                PluginRegistryError,
                build_plugin_registry_core_model,
            )

            try:
                model = build_plugin_registry_core_model()
            except (PluginRegistryError, ImportError, ModuleNotFoundError) as exc:
                # A malformed/absent plugin module must not crash governance:
                # degrade to "no items known" (the safe posture -- unknown items
                # cannot be distributed). Concrete catch, so the gate is honored.
                logger.warning("governed_distribution.plugin_registry.unavailable error=%s", type(exc).__name__)
                self._cache = set()
                return self._cache
        ids: set[str] = set()
        plugins = getattr(model, "plugins", None) or []
        for plugin in plugins:
            name = getattr(plugin, "name", None)
            module = getattr(plugin, "module", None)
            if name:
                ids.add(str(name))
            if module:
                ids.add(str(module))
        self._cache = ids
        return ids

    def has_item(self, item_id: str) -> bool:
        return str(item_id) in self._load_ids()


class InMemoryDirectory:
    """Deterministic team/org membership directory (default + test)."""

    def __init__(self) -> None:
        self._members: dict[tuple[str, str], set[str]] = {}

    def add_member(self, scope_type: str, scope_id: str, member_id: str) -> None:
        key = (str(scope_type), str(scope_id))
        self._members.setdefault(key, set()).add(str(member_id))

    def remove_member(self, scope_type: str, scope_id: str, member_id: str) -> None:
        self._members.get((str(scope_type), str(scope_id)), set()).discard(str(member_id))

    def members(self, scope_type: str, scope_id: str) -> list[str]:
        return sorted(self._members.get((str(scope_type), str(scope_id)), set()))

    def is_member(self, scope_type: str, scope_id: str, member_id: str) -> bool:
        return str(member_id) in self._members.get((str(scope_type), str(scope_id)), set())


class InMemoryApproverPolicy:
    """Maps scopes (and a global tier) to authorized approver ids."""

    def __init__(self) -> None:
        self._scoped: dict[tuple[str, str], set[str]] = {}
        self._global: set[str] = set()

    def add_approver(self, approver_id: str, scope_type: str, scope_id: str) -> None:
        self._scoped.setdefault((str(scope_type), str(scope_id)), set()).add(str(approver_id))

    def add_global_approver(self, approver_id: str) -> None:
        self._global.add(str(approver_id))

    def can_approve(self, approver_id: str, scope_type: str, scope_id: str) -> bool:
        approver_id = str(approver_id)
        if approver_id in self._global:
            return True
        return approver_id in self._scoped.get((str(scope_type), str(scope_id)), set())


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DistributionRecord:
    """A governed distribution of one item to one scope."""

    distribution_id: str
    item_id: str
    scope_type: str
    scope_id: str
    status: str
    requested_by: str
    created_at: float
    updated_at: float
    approver_id: str | None = None
    decided_at: float | None = None
    reason: str = ""

    @property
    def is_active(self) -> bool:
        return self.status == STATUS_ACTIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "distribution_id": self.distribution_id,
            "item_id": self.item_id,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "status": self.status,
            "requested_by": self.requested_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "approver_id": self.approver_id,
            "decided_at": self.decided_at,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DistributionRecord:
        approver = data.get("approver_id")
        decided = data.get("decided_at")
        return cls(
            distribution_id=str(data.get("distribution_id", "")),
            item_id=str(data.get("item_id", "")),
            scope_type=str(data.get("scope_type", "")),
            scope_id=str(data.get("scope_id", "")),
            status=str(data.get("status", STATUS_PENDING)),
            requested_by=str(data.get("requested_by", "")),
            created_at=float(data.get("created_at", 0.0)),
            updated_at=float(data.get("updated_at", 0.0)),
            approver_id=str(approver) if approver is not None else None,
            decided_at=float(decided) if decided is not None else None,
            reason=str(data.get("reason", "")),
        )


@dataclass(frozen=True)
class AuditEntry:
    """One immutable audit-trail line."""

    seq: int
    action: str
    distribution_id: str
    item_id: str
    scope_type: str
    scope_id: str
    actor: str
    timestamp: float
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "action": self.action,
            "distribution_id": self.distribution_id,
            "item_id": self.item_id,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "actor": self.actor,
            "timestamp": self.timestamp,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AuditEntry:
        return cls(
            seq=int(data.get("seq", 0)),
            action=str(data.get("action", "")),
            distribution_id=str(data.get("distribution_id", "")),
            item_id=str(data.get("item_id", "")),
            scope_type=str(data.get("scope_type", "")),
            scope_id=str(data.get("scope_id", "")),
            actor=str(data.get("actor", "")),
            timestamp=float(data.get("timestamp", 0.0)),
            detail=str(data.get("detail", "")),
        )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _empty_state() -> dict[str, Any]:
    return {"version": _STATE_VERSION, "dist_seq": 0, "audit_seq": 0, "distributions": {}, "audit": []}


def _default_store_path() -> Path:
    env = os.getenv("THOMAS_GOVERNED_DISTRIBUTION_FILE")
    if env:
        return Path(env).expanduser().resolve()
    try:
        from thomas.core.config import resolve_thomas_data_dir

        return (resolve_thomas_data_dir() / "json" / "thomas_governed_distribution.json").resolve()
    except ImportError:
        return (Path.home() / ".thomas" / "thomas_governed_distribution.json").resolve()


class GovernedDistributionStore:
    """JSON-backed, env-overridable, lock-guarded distribution + audit store.

    File shape::

        {"version": 1, "dist_seq": N, "audit_seq": M,
         "distributions": {"<id>": {...}}, "audit": [ {...}, ... ]}
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self._path_override = Path(path).expanduser().resolve() if path else None
        self._resolved_path: Path | None = None
        self._lock = threading.RLock()

    def path(self) -> Path:
        if self._path_override is not None:
            return self._path_override
        if self._resolved_path is None:
            self._resolved_path = _default_store_path()
        return self._resolved_path

    def _load(self) -> dict[str, Any]:
        p = self.path()
        if not p.exists():
            return _empty_state()
        try:
            raw = p.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else _empty_state()
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("governed_distribution.store.unreadable path=%s -- starting empty", p)
            return _empty_state()
        if not isinstance(data, dict) or not isinstance(data.get("distributions"), dict):
            return _empty_state()
        data.setdefault("version", _STATE_VERSION)
        data.setdefault("dist_seq", 0)
        data.setdefault("audit_seq", 0)
        if not isinstance(data.get("audit"), list):
            data["audit"] = []
        return data

    def _save(self, data: Mapping[str, Any]) -> None:
        p = self.path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        tmp.replace(p)

    @contextmanager
    def transaction(self) -> Iterator[dict[str, Any]]:
        """Load state, yield it mutable, persist on clean exit."""
        with self._lock:
            state = self._load()
            yield state
            self._save(state)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._load()


# ---------------------------------------------------------------------------
# Governed distribution orchestrator
# ---------------------------------------------------------------------------


def _require_scope(scope_type: str, scope_id: str) -> None:
    if scope_type not in _SCOPE_TYPES:
        raise InvalidScopeError(f"scope_type must be one of {sorted(_SCOPE_TYPES)}, got {scope_type!r}")
    if not str(scope_id).strip():
        raise InvalidScopeError("scope_id must be a non-empty string")


class GovernedDistribution:
    """Governed team/org distribution with an approval gate and revocation."""

    def __init__(
        self,
        *,
        store: GovernedDistributionStore,
        membership: MembershipProvider,
        registry: ItemRegistry | None = None,
        approvers: ApproverPolicy,
        clock: Clock | None = None,
    ) -> None:
        self._store = store
        self._membership = membership
        self._registry: ItemRegistry = registry if registry is not None else PluginItemRegistry()
        self._approvers = approvers
        self._clock = clock or _default_clock

    @property
    def store(self) -> GovernedDistributionStore:
        return self._store

    # -- internal helpers ---------------------------------------------------

    def _next_distribution_id(self, state: dict[str, Any], item_id: str, scope_type: str, scope_id: str) -> str:
        seq = int(state.get("dist_seq", 0))
        state["dist_seq"] = seq + 1
        digest = hashlib.sha256(f"{item_id}:{scope_type}:{scope_id}:{seq}".encode()).hexdigest()
        return "dist_" + digest[:16]

    def _append_audit(
        self,
        state: dict[str, Any],
        *,
        action: str,
        record: DistributionRecord,
        actor: str,
        timestamp: float,
        detail: str = "",
    ) -> None:
        seq = int(state.get("audit_seq", 0))
        state["audit_seq"] = seq + 1
        entry = AuditEntry(
            seq=seq,
            action=action,
            distribution_id=record.distribution_id,
            item_id=record.item_id,
            scope_type=record.scope_type,
            scope_id=record.scope_id,
            actor=actor,
            timestamp=timestamp,
            detail=detail,
        )
        state["audit"].append(entry.to_dict())

    def _get_record(self, state: Mapping[str, Any], distribution_id: str) -> DistributionRecord:
        raw = state["distributions"].get(distribution_id)
        if not isinstance(raw, dict):
            raise DistributionNotFoundError(f"no distribution with id {distribution_id!r}")
        return DistributionRecord.from_dict(raw)

    # -- distribution lifecycle --------------------------------------------

    def request_distribution(
        self,
        *,
        item_id: str,
        scope_type: str,
        scope_id: str,
        requested_by: str,
        reason: str = "",
    ) -> DistributionRecord:
        """Create a ``pending`` distribution of ``item_id`` to a scope."""
        _require_scope(scope_type, scope_id)
        if not self._registry.has_item(item_id):
            raise UnknownItemError(f"item {item_id!r} is not in the item registry")
        now = float(self._clock())
        with self._store.transaction() as state:
            distribution_id = self._next_distribution_id(state, item_id, scope_type, scope_id)
            record = DistributionRecord(
                distribution_id=distribution_id,
                item_id=str(item_id),
                scope_type=str(scope_type),
                scope_id=str(scope_id),
                status=STATUS_PENDING,
                requested_by=str(requested_by),
                created_at=now,
                updated_at=now,
                reason=reason,
            )
            state["distributions"][distribution_id] = record.to_dict()
            self._append_audit(
                state, action=ACTION_REQUEST, record=record, actor=str(requested_by), timestamp=now, detail=reason
            )
        logger.info(
            "governed_distribution.requested id=%s item=%s scope=%s/%s by=%s",
            distribution_id,
            item_id,
            scope_type,
            scope_id,
            requested_by,
        )
        return record

    def approve(self, distribution_id: str, approver_id: str, *, reason: str = "") -> DistributionRecord:
        """Authorize and effectuate a pending distribution (-> ``active``)."""
        now = float(self._clock())
        with self._store.transaction() as state:
            record = self._get_record(state, distribution_id)
            if record.status != STATUS_PENDING:
                raise InvalidStateError(
                    f"distribution {distribution_id!r} is {record.status!r}, cannot approve (must be pending)"
                )
            if not self._approvers.can_approve(approver_id, record.scope_type, record.scope_id):
                raise NotAuthorizedError(
                    f"approver {approver_id!r} is not authorized for scope {record.scope_type}/{record.scope_id}"
                )
            approved = DistributionRecord(
                distribution_id=record.distribution_id,
                item_id=record.item_id,
                scope_type=record.scope_type,
                scope_id=record.scope_id,
                status=STATUS_ACTIVE,
                requested_by=record.requested_by,
                created_at=record.created_at,
                updated_at=now,
                approver_id=str(approver_id),
                decided_at=now,
                reason=reason or record.reason,
            )
            state["distributions"][distribution_id] = approved.to_dict()
            # Approval emits the governance decision, then the effectuation.
            self._append_audit(
                state, action=ACTION_APPROVE, record=approved, actor=str(approver_id), timestamp=now, detail=reason
            )
            self._append_audit(state, action=ACTION_DISTRIBUTE, record=approved, actor=str(approver_id), timestamp=now)
        logger.info(
            "governed_distribution.approved id=%s item=%s scope=%s/%s approver=%s",
            distribution_id,
            approved.item_id,
            approved.scope_type,
            approved.scope_id,
            approver_id,
        )
        return approved

    def reject(self, distribution_id: str, approver_id: str, *, reason: str = "") -> DistributionRecord:
        """Authorize and reject a pending distribution (never distributed)."""
        now = float(self._clock())
        with self._store.transaction() as state:
            record = self._get_record(state, distribution_id)
            if record.status != STATUS_PENDING:
                raise InvalidStateError(
                    f"distribution {distribution_id!r} is {record.status!r}, cannot reject (must be pending)"
                )
            if not self._approvers.can_approve(approver_id, record.scope_type, record.scope_id):
                raise NotAuthorizedError(
                    f"approver {approver_id!r} is not authorized for scope {record.scope_type}/{record.scope_id}"
                )
            rejected = DistributionRecord(
                distribution_id=record.distribution_id,
                item_id=record.item_id,
                scope_type=record.scope_type,
                scope_id=record.scope_id,
                status=STATUS_REJECTED,
                requested_by=record.requested_by,
                created_at=record.created_at,
                updated_at=now,
                approver_id=str(approver_id),
                decided_at=now,
                reason=reason or record.reason,
            )
            state["distributions"][distribution_id] = rejected.to_dict()
            self._append_audit(
                state, action=ACTION_REJECT, record=rejected, actor=str(approver_id), timestamp=now, detail=reason
            )
        logger.info(
            "governed_distribution.rejected id=%s item=%s scope=%s/%s approver=%s",
            distribution_id,
            rejected.item_id,
            rejected.scope_type,
            rejected.scope_id,
            approver_id,
        )
        return rejected

    def revoke(self, distribution_id: str, admin_id: str, *, reason: str = "") -> DistributionRecord:
        """Withdraw an active distribution and block future installs."""
        now = float(self._clock())
        with self._store.transaction() as state:
            record = self._get_record(state, distribution_id)
            if record.status != STATUS_ACTIVE:
                raise InvalidStateError(
                    f"distribution {distribution_id!r} is {record.status!r}, cannot revoke (must be active)"
                )
            revoked = DistributionRecord(
                distribution_id=record.distribution_id,
                item_id=record.item_id,
                scope_type=record.scope_type,
                scope_id=record.scope_id,
                status=STATUS_REVOKED,
                requested_by=record.requested_by,
                created_at=record.created_at,
                updated_at=now,
                approver_id=record.approver_id,
                decided_at=record.decided_at,
                reason=reason or record.reason,
            )
            state["distributions"][distribution_id] = revoked.to_dict()
            self._append_audit(
                state, action=ACTION_REVOKE, record=revoked, actor=str(admin_id), timestamp=now, detail=reason
            )
        logger.info(
            "governed_distribution.revoked id=%s item=%s scope=%s/%s admin=%s",
            distribution_id,
            revoked.item_id,
            revoked.scope_type,
            revoked.scope_id,
            admin_id,
        )
        return revoked

    # -- queries ------------------------------------------------------------

    def get(self, distribution_id: str) -> DistributionRecord | None:
        state = self._store.snapshot()
        raw = state["distributions"].get(distribution_id)
        if not isinstance(raw, dict):
            return None
        return DistributionRecord.from_dict(raw)

    def list_distributions(
        self,
        *,
        item_id: str | None = None,
        scope_type: str | None = None,
        scope_id: str | None = None,
        status: str | None = None,
    ) -> list[DistributionRecord]:
        state = self._store.snapshot()
        out: list[DistributionRecord] = []
        for raw in state["distributions"].values():
            if not isinstance(raw, dict):
                continue
            record = DistributionRecord.from_dict(raw)
            if item_id is not None and record.item_id != item_id:
                continue
            if scope_type is not None and record.scope_type != scope_type:
                continue
            if scope_id is not None and record.scope_id != scope_id:
                continue
            if status is not None and record.status != status:
                continue
            out.append(record)
        out.sort(key=lambda r: (r.item_id, r.scope_type, r.scope_id, r.distribution_id))
        return out

    def _active_records(self, state: Mapping[str, Any]) -> list[DistributionRecord]:
        records: list[DistributionRecord] = []
        for raw in state["distributions"].values():
            if isinstance(raw, dict) and raw.get("status") == STATUS_ACTIVE:
                records.append(DistributionRecord.from_dict(raw))
        return records

    def is_received(self, member_id: str, item_id: str) -> bool:
        """True iff an *active* distribution to a scope the member belongs to grants ``item_id``."""
        state = self._store.snapshot()
        for record in self._active_records(state):
            if record.item_id != item_id:
                continue
            if self._membership.is_member(record.scope_type, record.scope_id, member_id):
                return True
        return False

    def received_items(self, member_id: str) -> list[str]:
        """Deterministic sorted list of item ids the member currently receives."""
        state = self._store.snapshot()
        items: set[str] = set()
        for record in self._active_records(state):
            if self._membership.is_member(record.scope_type, record.scope_id, member_id):
                items.add(record.item_id)
        return sorted(items)

    def can_install(self, member_id: str, item_id: str) -> bool:
        """Future-install gate: allowed only while an active distribution covers the member."""
        return self.is_received(member_id, item_id)

    def audit_trail(self, *, distribution_id: str | None = None) -> list[AuditEntry]:
        """Return the audit trail in append (sequence) order."""
        state = self._store.snapshot()
        entries = [AuditEntry.from_dict(e) for e in state.get("audit", []) if isinstance(e, dict)]
        entries.sort(key=lambda e: e.seq)
        if distribution_id is not None:
            entries = [e for e in entries if e.distribution_id == distribution_id]
        return entries


__all__ = [
    "ACTION_APPROVE",
    "ACTION_DISTRIBUTE",
    "ACTION_REJECT",
    "ACTION_REQUEST",
    "ACTION_REVOKE",
    "STATUS_ACTIVE",
    "STATUS_PENDING",
    "STATUS_REJECTED",
    "STATUS_REVOKED",
    "ApproverPolicy",
    "AuditEntry",
    "DistributionNotFoundError",
    "DistributionRecord",
    "FakeItemRegistry",
    "GovernedDistribution",
    "GovernedDistributionError",
    "GovernedDistributionStore",
    "InMemoryApproverPolicy",
    "InMemoryDirectory",
    "InvalidScopeError",
    "InvalidStateError",
    "ItemRegistry",
    "MembershipProvider",
    "NotAuthorizedError",
    "PluginItemRegistry",
    "UnknownItemError",
]
