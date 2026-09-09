"""Tests for CAP-026 governed team/org distribution with approval + revocation.

Hermetic: injected fake item registry, in-memory directory + approver policy,
injected clock, temp-dir JSON store. No network.
"""

from __future__ import annotations

import itertools

import pytest

from thomas.marketplace.governed_distribution import (
    ACTION_APPROVE,
    ACTION_DISTRIBUTE,
    ACTION_REVOKE,
    STATUS_ACTIVE,
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_REVOKED,
    DistributionRecord,
    FakeItemRegistry,
    GovernedDistribution,
    GovernedDistributionStore,
    InMemoryApproverPolicy,
    InMemoryDirectory,
    NotAuthorizedError,
)


def _clock():
    counter = itertools.count(1000)

    def _tick() -> float:
        return float(next(counter))

    return _tick


def _build(tmp_path):
    store = GovernedDistributionStore(path=tmp_path / "gd.json")
    registry = FakeItemRegistry(["acme.linter", "acme.formatter"])
    directory = InMemoryDirectory()
    # Team t1: alice, bob.  Org o1: dave.  carol is an outsider.
    directory.add_member("team", "t1", "alice")
    directory.add_member("team", "t1", "bob")
    directory.add_member("org", "o1", "dave")
    approvers = InMemoryApproverPolicy()
    approvers.add_approver("mgr", "team", "t1")
    approvers.add_approver("mgr", "org", "o1")
    gd = GovernedDistribution(
        store=store,
        membership=directory,
        registry=registry,
        approvers=approvers,
        clock=_clock(),
    )
    return gd, store, registry, directory, approvers


def test_approved_team_distribution_reaches_member_not_outsider(tmp_path):
    gd, *_ = _build(tmp_path)
    rec = gd.request_distribution(item_id="acme.linter", scope_type="team", scope_id="t1", requested_by="admin")
    assert rec.status == STATUS_PENDING
    # Pending: nobody receives it yet.
    assert gd.is_received("alice", "acme.linter") is False

    gd.approve(rec.distribution_id, "mgr")
    # Member receives it; outsider does not.
    assert gd.is_received("alice", "acme.linter") is True
    assert gd.is_received("bob", "acme.linter") is True
    assert gd.is_received("carol", "acme.linter") is False
    assert gd.received_items("alice") == ["acme.linter"]
    assert gd.received_items("carol") == []


def test_org_scope_distribution(tmp_path):
    gd, *_ = _build(tmp_path)
    rec = gd.request_distribution(item_id="acme.formatter", scope_type="org", scope_id="o1", requested_by="admin")
    gd.approve(rec.distribution_id, "mgr")
    assert gd.is_received("dave", "acme.formatter") is True
    assert gd.is_received("carol", "acme.formatter") is False


def test_pending_is_not_distributed_until_approved(tmp_path):
    gd, *_ = _build(tmp_path)
    rec = gd.request_distribution(item_id="acme.linter", scope_type="team", scope_id="t1", requested_by="admin")
    assert gd.get(rec.distribution_id).status == STATUS_PENDING
    assert gd.is_received("alice", "acme.linter") is False
    assert gd.can_install("alice", "acme.linter") is False
    # After approval the same distribution becomes active and is received.
    gd.approve(rec.distribution_id, "mgr")
    assert gd.get(rec.distribution_id).status == STATUS_ACTIVE
    assert gd.is_received("alice", "acme.linter") is True


def test_rejected_item_is_never_distributed(tmp_path):
    gd, *_ = _build(tmp_path)
    rec = gd.request_distribution(item_id="acme.linter", scope_type="team", scope_id="t1", requested_by="admin")
    gd.reject(rec.distribution_id, "mgr", reason="not vetted")
    assert gd.get(rec.distribution_id).status == STATUS_REJECTED
    assert gd.is_received("alice", "acme.linter") is False
    assert gd.can_install("alice", "acme.linter") is False


def test_unauthorized_approver_cannot_approve(tmp_path):
    gd, *_ = _build(tmp_path)
    rec = gd.request_distribution(item_id="acme.linter", scope_type="team", scope_id="t1", requested_by="admin")
    with pytest.raises(NotAuthorizedError):
        gd.approve(rec.distribution_id, "random_person")
    # Still pending, still not distributed.
    assert gd.get(rec.distribution_id).status == STATUS_PENDING
    assert gd.is_received("alice", "acme.linter") is False


def test_revoked_item_is_withdrawn_and_future_installs_blocked(tmp_path):
    gd, *_ = _build(tmp_path)
    rec = gd.request_distribution(item_id="acme.linter", scope_type="team", scope_id="t1", requested_by="admin")
    gd.approve(rec.distribution_id, "mgr")
    assert gd.is_received("alice", "acme.linter") is True

    gd.revoke(rec.distribution_id, "admin", reason="license expired")
    assert gd.get(rec.distribution_id).status == STATUS_REVOKED
    # Withdrawn from members; future installs blocked.
    assert gd.is_received("alice", "acme.linter") is False
    assert gd.is_received("bob", "acme.linter") is False
    assert gd.can_install("alice", "acme.linter") is False
    assert gd.received_items("alice") == []


def test_audit_trail_records_approve_distribute_revoke_in_order(tmp_path):
    gd, *_ = _build(tmp_path)
    rec = gd.request_distribution(item_id="acme.linter", scope_type="team", scope_id="t1", requested_by="admin")
    gd.approve(rec.distribution_id, "mgr")
    gd.revoke(rec.distribution_id, "admin")

    trail = gd.audit_trail(distribution_id=rec.distribution_id)
    # Sequence numbers strictly increase in append order.
    assert [e.seq for e in trail] == sorted(e.seq for e in trail)
    governance = [e.action for e in trail if e.action in {ACTION_APPROVE, ACTION_DISTRIBUTE, ACTION_REVOKE}]
    assert governance == [ACTION_APPROVE, ACTION_DISTRIBUTE, ACTION_REVOKE]


def test_round_trip_persistence(tmp_path):
    gd, store, registry, directory, approvers = _build(tmp_path)
    rec = gd.request_distribution(item_id="acme.linter", scope_type="team", scope_id="t1", requested_by="admin")
    gd.approve(rec.distribution_id, "mgr")

    # Rebuild everything from the persisted JSON store on disk.
    store2 = GovernedDistributionStore(path=store.path())
    gd2 = GovernedDistribution(
        store=store2,
        membership=directory,
        registry=registry,
        approvers=approvers,
        clock=_clock(),
    )
    reloaded = gd2.get(rec.distribution_id)
    assert isinstance(reloaded, DistributionRecord)
    assert reloaded.status == STATUS_ACTIVE
    assert reloaded.item_id == "acme.linter"
    assert gd2.is_received("alice", "acme.linter") is True
    # Audit survived the round-trip.
    actions = [e.action for e in gd2.audit_trail(distribution_id=rec.distribution_id)]
    assert ACTION_APPROVE in actions and ACTION_DISTRIBUTE in actions


def test_unknown_item_and_bad_scope_rejected(tmp_path):
    from thomas.marketplace.governed_distribution import InvalidScopeError, UnknownItemError

    gd, *_ = _build(tmp_path)
    with pytest.raises(UnknownItemError):
        gd.request_distribution(item_id="ghost", scope_type="team", scope_id="t1", requested_by="admin")
    with pytest.raises(InvalidScopeError):
        gd.request_distribution(item_id="acme.linter", scope_type="galaxy", scope_id="t1", requested_by="admin")
