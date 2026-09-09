"""Org inventory over governed team/org marketplace distribution.

CAP-134 -- "Marketplace with org distribution" (Level 2:
"Add team/org distribution, approval, inventory, and revocation.")

This module adds the **inventory** dimension on top of the CAP-026 governed
distribution layer (:mod:`thomas.marketplace.governed_distribution`). It does not
re-implement the team/org distribution + approval + revocation state machine --
it *composes* :class:`~thomas.marketplace.governed_distribution.GovernedDistribution`
so the approval gate and revocation semantics remain the single source of truth
for who is entitled to an item. On top of that it tracks, durably and
deterministically:

1. **Org inventory** -- per scope (org / team), which marketplace items are
   distributed, at what ``version``, with how many licensed ``seats``, and the
   install status of each member (``installed`` / ``available`` / ``revoked``).
2. **Distribution lifecycle** -- ``distribute`` -> ``approve`` / ``reject`` ->
   ``revoke``, delegated to the composed :class:`GovernedDistribution`. A member
   ``install`` is only recorded once an entitlement exists; a ``revoke``
   withdraws every install on the line.
3. **Inventory queries** -- what a scope has (:meth:`OrgInventory.inventory`),
   who has an item installed (:meth:`OrgInventory.installers`), seats used vs
   allowed (:meth:`OrgInventory.seat_usage`), and a compliance view
   (:meth:`OrgInventory.compliance`) that flags over-seat lines and unapproved
   installs.

Injectable edges (real default + hermetic fake)
-----------------------------------------------
* **Governed distribution** -- a :class:`GovernedDistribution` is injected; in
  tests it is wired with the hermetic ``FakeItemRegistry`` / ``InMemoryDirectory``
  / ``InMemoryApproverPolicy`` from CAP-026.
* **Membership** -- the same
  :class:`~thomas.marketplace.governed_distribution.MembershipProvider` used by
  the governed layer, so entitlement checks agree with distribution.
* **Clock** -- injected ``Callable[[], float]`` for deterministic timestamps.

Persistence is JSON, env-overridable via ``THOMAS_ORG_INVENTORY_FILE``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from thomas.marketplace.governed_distribution import (
    STATUS_ACTIVE,
    STATUS_PENDING,
    STATUS_REVOKED,
    DistributionRecord,
    GovernedDistribution,
    MembershipProvider,
    _require_scope,
)

logger = logging.getLogger(__name__)

Clock = Callable[[], float]

# Per-member install status inside an inventory line.
INSTALL_INSTALLED = "installed"
INSTALL_AVAILABLE = "available"
INSTALL_REVOKED = "revoked"
INSTALL_NONE = "none"

# Compliance flag kinds.
FLAG_OVER_SEAT = "over_seat"
FLAG_UNAPPROVED_INSTALL = "unapproved_install"

_STATE_VERSION = 1


def _default_clock() -> float:
    import time

    return time.time()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OrgInventoryError(Exception):
    """Base error for the org inventory layer."""


class InvalidSeatCountError(OrgInventoryError):
    """Seat count is not a non-negative integer."""


class InvalidVersionError(OrgInventoryError):
    """Version string is empty."""


class InventoryLineNotFoundError(OrgInventoryError):
    """No inventory line exists for the given distribution id."""


class NotEntitledError(OrgInventoryError):
    """The member is not entitled to install the item (no active distribution)."""


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InventoryLine:
    """One distributed item within a scope's inventory.

    ``installs`` maps ``member_id`` -> install status
    (``installed`` / ``revoked``). Members entitled but not yet installed are
    reported as ``available`` by :meth:`OrgInventory.member_status`; they are not
    stored here until they act.
    """

    distribution_id: str
    item_id: str
    scope_type: str
    scope_id: str
    version: str
    seats: int
    status: str
    created_at: float
    updated_at: float
    installs: dict[str, str] = field(default_factory=dict)

    @property
    def installed_members(self) -> list[str]:
        return sorted(m for m, s in self.installs.items() if s == INSTALL_INSTALLED)

    @property
    def seats_used(self) -> int:
        return len(self.installed_members)

    def to_dict(self) -> dict[str, Any]:
        return {
            "distribution_id": self.distribution_id,
            "item_id": self.item_id,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "version": self.version,
            "seats": self.seats,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "installs": dict(self.installs),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> InventoryLine:
        raw_installs = data.get("installs")
        installs: dict[str, str] = {}
        if isinstance(raw_installs, Mapping):
            for member, status in raw_installs.items():
                installs[str(member)] = str(status)
        return cls(
            distribution_id=str(data.get("distribution_id", "")),
            item_id=str(data.get("item_id", "")),
            scope_type=str(data.get("scope_type", "")),
            scope_id=str(data.get("scope_id", "")),
            version=str(data.get("version", "")),
            seats=int(data.get("seats", 0)),
            status=str(data.get("status", STATUS_PENDING)),
            created_at=float(data.get("created_at", 0.0)),
            updated_at=float(data.get("updated_at", 0.0)),
            installs=installs,
        )


@dataclass(frozen=True)
class SeatUsage:
    """Seats used vs allowed for one inventory line."""

    distribution_id: str
    item_id: str
    scope_type: str
    scope_id: str
    seats: int
    used: int

    @property
    def available(self) -> int:
        return self.seats - self.used

    @property
    def over_seat(self) -> bool:
        return self.used > self.seats

    def to_dict(self) -> dict[str, Any]:
        return {
            "distribution_id": self.distribution_id,
            "item_id": self.item_id,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "seats": self.seats,
            "used": self.used,
            "available": self.available,
            "over_seat": self.over_seat,
        }


@dataclass(frozen=True)
class ComplianceFlag:
    """One compliance issue on an inventory line."""

    kind: str
    distribution_id: str
    item_id: str
    scope_type: str
    scope_id: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "distribution_id": self.distribution_id,
            "item_id": self.item_id,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _empty_state() -> dict[str, Any]:
    return {"version": _STATE_VERSION, "lines": {}}


def _default_store_path() -> Path:
    env = os.getenv("THOMAS_ORG_INVENTORY_FILE")
    if env:
        return Path(env).expanduser().resolve()
    try:
        from thomas.core.config import resolve_thomas_data_dir

        return (resolve_thomas_data_dir() / "json" / "thomas_org_inventory.json").resolve()
    except ImportError:
        return (Path.home() / ".thomas" / "thomas_org_inventory.json").resolve()


class OrgInventoryStore:
    """JSON-backed, env-overridable, lock-guarded inventory store.

    File shape::

        {"version": 1, "lines": {"<distribution_id>": {InventoryLine...}}}
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
            logger.warning("org_inventory.store.unreadable path=%s -- starting empty", p)
            return _empty_state()
        if not isinstance(data, dict) or not isinstance(data.get("lines"), dict):
            return _empty_state()
        data.setdefault("version", _STATE_VERSION)
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
# Org inventory orchestrator
# ---------------------------------------------------------------------------


def _require_seats(seats: int) -> int:
    if isinstance(seats, bool) or not isinstance(seats, int) or seats < 0:
        raise InvalidSeatCountError(f"seats must be a non-negative integer, got {seats!r}")
    return seats


def _require_version(version: str) -> str:
    if not str(version).strip():
        raise InvalidVersionError("version must be a non-empty string")
    return str(version)


class OrgInventory:
    """Org inventory composed over governed team/org distribution."""

    def __init__(
        self,
        *,
        governed: GovernedDistribution,
        store: OrgInventoryStore,
        membership: MembershipProvider,
        clock: Clock | None = None,
    ) -> None:
        self._gd = governed
        self._store = store
        self._membership = membership
        self._clock = clock or _default_clock

    @property
    def store(self) -> OrgInventoryStore:
        return self._store

    @property
    def governed(self) -> GovernedDistribution:
        return self._gd

    # -- internal helpers ---------------------------------------------------

    def _get_line(self, state: Mapping[str, Any], distribution_id: str) -> InventoryLine:
        raw = state["lines"].get(distribution_id)
        if not isinstance(raw, dict):
            raise InventoryLineNotFoundError(f"no inventory line for distribution {distribution_id!r}")
        return InventoryLine.from_dict(raw)

    def _put_line(self, state: dict[str, Any], line: InventoryLine) -> None:
        state["lines"][line.distribution_id] = line.to_dict()

    # -- distribution lifecycle --------------------------------------------

    def distribute(
        self,
        *,
        item_id: str,
        scope_type: str,
        scope_id: str,
        version: str,
        seats: int,
        requested_by: str,
        reason: str = "",
    ) -> InventoryLine:
        """Request a governed distribution and open a pending inventory line.

        The item is not entitled to anyone until :meth:`approve` is called -- the
        approval gate is enforced by the composed governed distribution layer.
        """
        _require_scope(scope_type, scope_id)
        version = _require_version(version)
        seats = _require_seats(seats)
        # The governed layer validates the item against the registry and creates
        # the pending distribution (approval gate lives there).
        record = self._gd.request_distribution(
            item_id=item_id,
            scope_type=scope_type,
            scope_id=scope_id,
            requested_by=requested_by,
            reason=reason,
        )
        now = float(self._clock())
        with self._store.transaction() as state:
            line = InventoryLine(
                distribution_id=record.distribution_id,
                item_id=record.item_id,
                scope_type=record.scope_type,
                scope_id=record.scope_id,
                version=version,
                seats=seats,
                status=STATUS_PENDING,
                created_at=now,
                updated_at=now,
                installs={},
            )
            self._put_line(state, line)
        logger.info(
            "org_inventory.distributed id=%s item=%s scope=%s/%s version=%s seats=%d",
            record.distribution_id,
            record.item_id,
            record.scope_type,
            record.scope_id,
            version,
            seats,
        )
        return line

    def _sync_status(self, distribution_id: str, record: DistributionRecord) -> InventoryLine:
        now = float(self._clock())
        with self._store.transaction() as state:
            line = self._get_line(state, distribution_id)
            installs = dict(line.installs)
            if record.status == STATUS_REVOKED:
                # Withdraw every install: installed members become revoked.
                installs = {m: (INSTALL_REVOKED if s == INSTALL_INSTALLED else s) for m, s in installs.items()}
            updated = InventoryLine(
                distribution_id=line.distribution_id,
                item_id=line.item_id,
                scope_type=line.scope_type,
                scope_id=line.scope_id,
                version=line.version,
                seats=line.seats,
                status=record.status,
                created_at=line.created_at,
                updated_at=now,
                installs=installs,
            )
            self._put_line(state, updated)
            return updated

    def approve(self, distribution_id: str, approver_id: str, *, reason: str = "") -> InventoryLine:
        """Approve the distribution (governed gate) and mark the line active."""
        record = self._gd.approve(distribution_id, approver_id, reason=reason)
        return self._sync_status(distribution_id, record)

    def reject(self, distribution_id: str, approver_id: str, *, reason: str = "") -> InventoryLine:
        """Reject the distribution (governed gate) and mark the line rejected."""
        record = self._gd.reject(distribution_id, approver_id, reason=reason)
        return self._sync_status(distribution_id, record)

    def revoke(self, distribution_id: str, admin_id: str, *, reason: str = "") -> InventoryLine:
        """Revoke the distribution and withdraw every install on the line."""
        record = self._gd.revoke(distribution_id, admin_id, reason=reason)
        line = self._sync_status(distribution_id, record)
        logger.info(
            "org_inventory.revoked id=%s item=%s scope=%s/%s withdrew=%d",
            distribution_id,
            line.item_id,
            line.scope_type,
            line.scope_id,
            sum(1 for s in line.installs.values() if s == INSTALL_REVOKED),
        )
        return line

    def install(self, distribution_id: str, member_id: str) -> InventoryLine:
        """Record a member installing an entitled item.

        Requires an *active* distribution covering the member (governed
        entitlement). The install is recorded even when it pushes usage past the
        seat count -- that overage surfaces in :meth:`compliance` rather than
        being silently dropped, so operators can see and remediate it.
        """
        record = self._gd.get(distribution_id)
        if record is None:
            raise InventoryLineNotFoundError(f"no distribution {distribution_id!r}")
        if record.status != STATUS_ACTIVE:
            raise NotEntitledError(
                f"distribution {distribution_id!r} is {record.status!r}; member {member_id!r} cannot install"
            )
        if not self._membership.is_member(record.scope_type, record.scope_id, member_id):
            raise NotEntitledError(f"member {member_id!r} is not in scope {record.scope_type}/{record.scope_id}")
        now = float(self._clock())
        with self._store.transaction() as state:
            line = self._get_line(state, distribution_id)
            installs = dict(line.installs)
            installs[str(member_id)] = INSTALL_INSTALLED
            updated = InventoryLine(
                distribution_id=line.distribution_id,
                item_id=line.item_id,
                scope_type=line.scope_type,
                scope_id=line.scope_id,
                version=line.version,
                seats=line.seats,
                status=line.status,
                created_at=line.created_at,
                updated_at=now,
                installs=installs,
            )
            self._put_line(state, updated)
        logger.info(
            "org_inventory.installed id=%s item=%s member=%s used=%d/%d",
            distribution_id,
            updated.item_id,
            member_id,
            updated.seats_used,
            updated.seats,
        )
        return updated

    def uninstall(self, distribution_id: str, member_id: str) -> InventoryLine:
        """Remove a member's install record (member-initiated uninstall)."""
        now = float(self._clock())
        with self._store.transaction() as state:
            line = self._get_line(state, distribution_id)
            installs = dict(line.installs)
            installs.pop(str(member_id), None)
            updated = InventoryLine(
                distribution_id=line.distribution_id,
                item_id=line.item_id,
                scope_type=line.scope_type,
                scope_id=line.scope_id,
                version=line.version,
                seats=line.seats,
                status=line.status,
                created_at=line.created_at,
                updated_at=now,
                installs=installs,
            )
            self._put_line(state, updated)
            return updated

    # -- queries ------------------------------------------------------------

    def get_line(self, distribution_id: str) -> InventoryLine | None:
        state = self._store.snapshot()
        raw = state["lines"].get(distribution_id)
        if not isinstance(raw, dict):
            return None
        return InventoryLine.from_dict(raw)

    def _all_lines(self, state: Mapping[str, Any]) -> list[InventoryLine]:
        lines: list[InventoryLine] = []
        for raw in state["lines"].values():
            if isinstance(raw, dict):
                lines.append(InventoryLine.from_dict(raw))
        lines.sort(key=lambda ln: (ln.scope_type, ln.scope_id, ln.item_id, ln.distribution_id))
        return lines

    def inventory(
        self,
        *,
        scope_type: str | None = None,
        scope_id: str | None = None,
        item_id: str | None = None,
        status: str | None = None,
    ) -> list[InventoryLine]:
        """What does a scope have -- filter inventory lines deterministically."""
        state = self._store.snapshot()
        out: list[InventoryLine] = []
        for line in self._all_lines(state):
            if scope_type is not None and line.scope_type != scope_type:
                continue
            if scope_id is not None and line.scope_id != scope_id:
                continue
            if item_id is not None and line.item_id != item_id:
                continue
            if status is not None and line.status != status:
                continue
            out.append(line)
        return out

    def org_inventory(self, org_id: str) -> list[InventoryLine]:
        """Convenience: everything distributed to org ``org_id``."""
        return self.inventory(scope_type="org", scope_id=org_id)

    def installers(
        self,
        item_id: str,
        *,
        scope_type: str | None = None,
        scope_id: str | None = None,
    ) -> list[str]:
        """Who has item ``item_id`` installed -- sorted unique member ids."""
        members: set[str] = set()
        for line in self.inventory(scope_type=scope_type, scope_id=scope_id, item_id=item_id):
            members.update(line.installed_members)
        return sorted(members)

    def member_status(self, distribution_id: str, member_id: str) -> str:
        """Install status of ``member_id`` on a line.

        ``installed`` / ``revoked`` come straight from the recorded installs;
        ``available`` means the member is entitled (line active + in scope) but
        has not installed; ``none`` means no entitlement.
        """
        line = self.get_line(distribution_id)
        if line is None:
            return INSTALL_NONE
        recorded = line.installs.get(str(member_id))
        if recorded is not None:
            return recorded
        if line.status == STATUS_ACTIVE and self._membership.is_member(line.scope_type, line.scope_id, member_id):
            return INSTALL_AVAILABLE
        return INSTALL_NONE

    def seat_usage(self, distribution_id: str) -> SeatUsage:
        """Seats used vs allowed for one line."""
        state = self._store.snapshot()
        line = self._get_line(state, distribution_id)
        return SeatUsage(
            distribution_id=line.distribution_id,
            item_id=line.item_id,
            scope_type=line.scope_type,
            scope_id=line.scope_id,
            seats=line.seats,
            used=line.seats_used,
        )

    def compliance(
        self,
        *,
        scope_type: str | None = None,
        scope_id: str | None = None,
    ) -> list[ComplianceFlag]:
        """Compliance view: flag over-seat lines and unapproved installs.

        * ``over_seat`` -- an active line whose installed count exceeds its
          licensed seat count.
        * ``unapproved_install`` -- a line carrying installs while it is not
          active (e.g. installs recorded before approval, or a line whose
          approval was never completed).
        """
        flags: list[ComplianceFlag] = []
        for line in self.inventory(scope_type=scope_type, scope_id=scope_id):
            used = line.seats_used
            if used > line.seats:
                flags.append(
                    ComplianceFlag(
                        kind=FLAG_OVER_SEAT,
                        distribution_id=line.distribution_id,
                        item_id=line.item_id,
                        scope_type=line.scope_type,
                        scope_id=line.scope_id,
                        detail=f"{used} installs exceed {line.seats} seats",
                    )
                )
            if line.status != STATUS_ACTIVE and used > 0:
                flags.append(
                    ComplianceFlag(
                        kind=FLAG_UNAPPROVED_INSTALL,
                        distribution_id=line.distribution_id,
                        item_id=line.item_id,
                        scope_type=line.scope_type,
                        scope_id=line.scope_id,
                        detail=f"{used} install(s) on a {line.status!r} line",
                    )
                )
        flags.sort(key=lambda f: (f.scope_type, f.scope_id, f.item_id, f.kind))
        return flags


__all__ = [
    "FLAG_OVER_SEAT",
    "FLAG_UNAPPROVED_INSTALL",
    "INSTALL_AVAILABLE",
    "INSTALL_INSTALLED",
    "INSTALL_NONE",
    "INSTALL_REVOKED",
    "ComplianceFlag",
    "InvalidSeatCountError",
    "InvalidVersionError",
    "InventoryLine",
    "InventoryLineNotFoundError",
    "NotEntitledError",
    "OrgInventory",
    "OrgInventoryError",
    "OrgInventoryStore",
    "SeatUsage",
]
