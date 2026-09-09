"""Tests for CAP-134 org inventory over governed team/org distribution.

Hermetic: reuses the CAP-026 hermetic fakes (FakeItemRegistry, InMemoryDirectory,
InMemoryApproverPolicy), an injected monotonic clock, and temp-dir JSON stores.
No network.
"""

from __future__ import annotations

import itertools

import pytest

from thomas.marketplace.governed_distribution import (
    STATUS_ACTIVE,
    STATUS_PENDING,
    STATUS_REVOKED,
    FakeItemRegistry,
    GovernedDistribution,
    GovernedDistributionStore,
    InMemoryApproverPolicy,
    InMemoryDirectory,
)
from thomas.marketplace.org_inventory import (
    FLAG_OVER_SEAT,
    FLAG_UNAPPROVED_INSTALL,
    INSTALL_AVAILABLE,
    INSTALL_INSTALLED,
    INSTALL_NONE,
    INSTALL_REVOKED,
    InvalidSeatCountError,
    InvalidVersionError,
    InventoryLine,
    NotEntitledError,
    OrgInventory,
    OrgInventoryStore,
)


def _clock():
    counter = itertools.count(1000)

    def _tick() -> float:
        return float(next(counter))

    return _tick


def _build(tmp_path):
    gd_store = GovernedDistributionStore(path=tmp_path / "gd.json")
    inv_store = OrgInventoryStore(path=tmp_path / "inv.json")
    registry = FakeItemRegistry(["acme.linter", "acme.formatter"])
    directory = InMemoryDirectory()
    # Org o1: alice, bob, dave.  Team t1: erin.  carol is an outsider.
    directory.add_member("org", "o1", "alice")
    directory.add_member("org", "o1", "bob")
    directory.add_member("org", "o1", "dave")
    directory.add_member("team", "t1", "erin")
    approvers = InMemoryApproverPolicy()
    approvers.add_approver("mgr", "org", "o1")
    approvers.add_approver("mgr", "team", "t1")
    gd = GovernedDistribution(
        store=gd_store,
        membership=directory,
        registry=registry,
        approvers=approvers,
        clock=_clock(),
    )
    inv = OrgInventory(governed=gd, store=inv_store, membership=directory, clock=_clock())
    return inv, gd, inv_store, registry, directory, approvers


def test_approved_org_distribution_appears_in_inventory_with_version_and_seats(tmp_path):
    inv, *_ = _build(tmp_path)
    line = inv.distribute(
        item_id="acme.linter",
        scope_type="org",
        scope_id="o1",
        version="1.2.0",
        seats=2,
        requested_by="admin",
    )
    assert line.status == STATUS_PENDING
    # Pending: not yet in the *active* inventory, and nobody entitled.
    assert inv.member_status(line.distribution_id, "alice") == INSTALL_NONE

    inv.approve(line.distribution_id, "mgr")
    org_lines = inv.org_inventory("o1")
    assert len(org_lines) == 1
    got = org_lines[0]
    assert got.item_id == "acme.linter"
    assert got.version == "1.2.0"
    assert got.seats == 2
    assert got.status == STATUS_ACTIVE
    # Entitled but not installed -> available.
    assert inv.member_status(got.distribution_id, "alice") == INSTALL_AVAILABLE
    assert inv.member_status(got.distribution_id, "carol") == INSTALL_NONE


def test_member_install_shows_in_inventory(tmp_path):
    inv, *_ = _build(tmp_path)
    line = inv.distribute(
        item_id="acme.linter", scope_type="org", scope_id="o1", version="1.0.0", seats=3, requested_by="admin"
    )
    inv.approve(line.distribution_id, "mgr")

    inv.install(line.distribution_id, "alice")
    assert inv.member_status(line.distribution_id, "alice") == INSTALL_INSTALLED
    assert inv.installers("acme.linter") == ["alice"]
    assert inv.get_line(line.distribution_id).installed_members == ["alice"]

    inv.install(line.distribution_id, "bob")
    assert inv.installers("acme.linter", scope_type="org", scope_id="o1") == ["alice", "bob"]


def test_install_requires_entitlement(tmp_path):
    inv, *_ = _build(tmp_path)
    line = inv.distribute(
        item_id="acme.linter", scope_type="org", scope_id="o1", version="1.0.0", seats=3, requested_by="admin"
    )
    # Not yet approved -> not entitled.
    with pytest.raises(NotEntitledError):
        inv.install(line.distribution_id, "alice")
    inv.approve(line.distribution_id, "mgr")
    # Outsider is not in scope -> not entitled.
    with pytest.raises(NotEntitledError):
        inv.install(line.distribution_id, "carol")


def test_exceeding_seat_count_is_flagged(tmp_path):
    inv, *_ = _build(tmp_path)
    # Only 1 seat licensed, but two members install.
    line = inv.distribute(
        item_id="acme.linter", scope_type="org", scope_id="o1", version="1.0.0", seats=1, requested_by="admin"
    )
    inv.approve(line.distribution_id, "mgr")
    inv.install(line.distribution_id, "alice")
    usage = inv.seat_usage(line.distribution_id)
    assert usage.seats == 1 and usage.used == 1 and usage.available == 0 and usage.over_seat is False

    inv.install(line.distribution_id, "bob")
    usage = inv.seat_usage(line.distribution_id)
    assert usage.used == 2 and usage.available == -1 and usage.over_seat is True

    flags = inv.compliance(scope_type="org", scope_id="o1")
    over = [f for f in flags if f.kind == FLAG_OVER_SEAT]
    assert len(over) == 1
    assert over[0].item_id == "acme.linter"


def test_revoked_item_marked_revoked_and_installs_withdrawn(tmp_path):
    inv, *_ = _build(tmp_path)
    line = inv.distribute(
        item_id="acme.linter", scope_type="org", scope_id="o1", version="1.0.0", seats=3, requested_by="admin"
    )
    inv.approve(line.distribution_id, "mgr")
    inv.install(line.distribution_id, "alice")
    inv.install(line.distribution_id, "bob")
    assert inv.installers("acme.linter") == ["alice", "bob"]

    inv.revoke(line.distribution_id, "admin", reason="license expired")
    reloaded = inv.get_line(line.distribution_id)
    assert reloaded.status == STATUS_REVOKED
    # Installs withdrawn: installed -> revoked, none remain installed.
    assert reloaded.installed_members == []
    assert inv.member_status(line.distribution_id, "alice") == INSTALL_REVOKED
    assert inv.installers("acme.linter") == []
    # Seat usage drops to zero.
    assert inv.seat_usage(line.distribution_id).used == 0


def test_unapproved_install_flagged_in_compliance(tmp_path):
    inv, gd, *_ = _build(tmp_path)
    line = inv.distribute(
        item_id="acme.linter", scope_type="org", scope_id="o1", version="1.0.0", seats=2, requested_by="admin"
    )
    inv.approve(line.distribution_id, "mgr")
    inv.install(line.distribution_id, "alice")
    # Revoke after install: the line becomes non-active but had installs. The
    # revoke path withdraws them, so no unapproved-install flag should remain.
    inv.revoke(line.distribution_id, "admin")
    flags = inv.compliance(scope_type="org", scope_id="o1")
    assert flags == []

    # An install lingering on a non-active line is the unapproved-install
    # breach. Install on an active line, then drive the line back to pending
    # (representing a lost/rolled-back approval) with the install still present.
    line2 = inv.distribute(
        item_id="acme.formatter", scope_type="org", scope_id="o1", version="2.0.0", seats=2, requested_by="admin"
    )
    inv.approve(line2.distribution_id, "mgr")
    inv.install(line2.distribution_id, "bob")
    # Force the inventory line into a pending state with an install still present
    # to represent an unapproved-install compliance breach.
    with inv.store.transaction() as state:
        raw = state["lines"][line2.distribution_id]
        raw["status"] = STATUS_PENDING
    flags = inv.compliance(scope_type="org", scope_id="o1")
    unapproved = [f for f in flags if f.kind == FLAG_UNAPPROVED_INSTALL]
    assert len(unapproved) == 1
    assert unapproved[0].item_id == "acme.formatter"


def test_inventory_queries_by_org_by_item_and_seats(tmp_path):
    inv, *_ = _build(tmp_path)
    a = inv.distribute(
        item_id="acme.linter", scope_type="org", scope_id="o1", version="1.0.0", seats=5, requested_by="admin"
    )
    b = inv.distribute(
        item_id="acme.formatter", scope_type="team", scope_id="t1", version="3.1.0", seats=1, requested_by="admin"
    )
    inv.approve(a.distribution_id, "mgr")
    inv.approve(b.distribution_id, "mgr")
    inv.install(a.distribution_id, "alice")
    inv.install(b.distribution_id, "erin")

    # By org.
    org_items = [ln.item_id for ln in inv.org_inventory("o1")]
    assert org_items == ["acme.linter"]
    # By item (across scopes).
    assert [ln.scope_id for ln in inv.inventory(item_id="acme.formatter")] == ["t1"]
    # Who has the formatter installed.
    assert inv.installers("acme.formatter") == ["erin"]
    # Seats.
    assert inv.seat_usage(a.distribution_id).available == 4
    assert inv.seat_usage(b.distribution_id).available == 0


def test_round_trip_persistence(tmp_path):
    inv, gd, inv_store, registry, directory, approvers = _build(tmp_path)
    line = inv.distribute(
        item_id="acme.linter", scope_type="org", scope_id="o1", version="4.2.0", seats=2, requested_by="admin"
    )
    inv.approve(line.distribution_id, "mgr")
    inv.install(line.distribution_id, "alice")

    # Rebuild everything from the persisted JSON stores on disk.
    gd_store2 = GovernedDistributionStore(path=gd.store.path())
    gd2 = GovernedDistribution(
        store=gd_store2, membership=directory, registry=registry, approvers=approvers, clock=_clock()
    )
    inv_store2 = OrgInventoryStore(path=inv_store.path())
    inv2 = OrgInventory(governed=gd2, store=inv_store2, membership=directory, clock=_clock())

    reloaded = inv2.get_line(line.distribution_id)
    assert isinstance(reloaded, InventoryLine)
    assert reloaded.status == STATUS_ACTIVE
    assert reloaded.item_id == "acme.linter"
    assert reloaded.version == "4.2.0"
    assert reloaded.seats == 2
    assert reloaded.installed_members == ["alice"]
    assert inv2.member_status(line.distribution_id, "alice") == INSTALL_INSTALLED
    assert inv2.seat_usage(line.distribution_id).used == 1


def test_invalid_seats_and_version_rejected(tmp_path):
    inv, *_ = _build(tmp_path)
    with pytest.raises(InvalidSeatCountError):
        inv.distribute(
            item_id="acme.linter", scope_type="org", scope_id="o1", version="1.0.0", seats=-1, requested_by="admin"
        )
    with pytest.raises(InvalidVersionError):
        inv.distribute(
            item_id="acme.linter", scope_type="org", scope_id="o1", version="  ", seats=1, requested_by="admin"
        )
