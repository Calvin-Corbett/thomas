"""Tests for CAP-110 team / org shared knowledge.

Proves the exact Level-2 acceptance line: org-scoped knowledge with
different-user sharing and a reviewed promotion gate.

Every test is hermetic: a temp-dir JSON path and an injected deterministic
clock -- no network, no live model, no wall-clock reliance.
"""

from __future__ import annotations

import itertools

import pytest

from thomas.memory.org_knowledge import (
    SCOPE_ORG,
    SCOPE_PERSONAL,
    ItemNotFoundError,
    NotAuthorizedError,
    OrgKnowledgeStore,
    PromotionProposal,
    PromotionStateError,
    ProposalNotFoundError,
)

ORG = "acme"
OUTSIDER_ORG = "globex"


@pytest.fixture
def clock():
    counter = itertools.count(1)
    return lambda: float(next(counter))


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "org_knowledge.json"


@pytest.fixture
def store(store_path, clock):
    return OrgKnowledgeStore(path=store_path, clock=clock)


# -- org scoping: member sees, outsider does not ---------------------------


def test_org_scoped_item_visible_to_member_not_outsider(store):
    # alice authors and shares an item to org ACME; bob is a member of ACME;
    # carol is not a member of ACME (she's only in a different org).
    store.add_member(ORG, "bob")
    store.add_member(OUTSIDER_ORG, "carol")

    item = store.add_personal(ORG, "alice", "deploy runbook v2")
    shared = store.share_to_org(item.item_id, "alice")
    assert shared.scope == SCOPE_ORG

    # bob (same org) sees it
    bob_view = store.visible_items(ORG, "bob")
    assert [i.item_id for i in bob_view] == [item.item_id]
    assert store.can_see("bob", shared) is True

    # carol (outside ACME) does NOT see it
    assert store.can_see("carol", shared) is False
    assert store.visible_items(ORG, "carol") == []


# -- different-user sharing: A shares, different user B sees ----------------


def test_user_shares_item_and_a_different_user_sees_it(store):
    store.add_member(ORG, "bob")
    item = store.add_personal(ORG, "alice", "on-call escalation contacts")

    # before sharing: only the author alice sees it; bob does not
    assert store.can_see("alice", item) is True
    assert store.can_see("bob", item) is False
    assert store.visible_items(ORG, "bob") == []

    # alice shares her own item to the org
    store.share_to_org(item.item_id, "alice")

    # a DIFFERENT user, bob, now sees alice's item
    bob_view = store.visible_items(ORG, "bob")
    assert [i.item_id for i in bob_view] == [item.item_id]
    assert bob_view[0].author_user_id == "alice"


def test_only_author_may_share_their_item(store):
    store.add_member(ORG, "bob")
    item = store.add_personal(ORG, "alice", "secret note")
    with pytest.raises(NotAuthorizedError):
        store.share_to_org(item.item_id, "bob")
    # unchanged: still personal, still author-only
    assert store.get_item(item.item_id).scope == SCOPE_PERSONAL
    assert store.visible_items(ORG, "bob") == []


# -- reviewed promotion gate: pending until approved, then org-visible ------


def test_promotion_proposal_pending_until_approved_then_org_visible(store):
    store.add_member(ORG, "bob")
    store.add_reviewer(ORG, "review-lead")
    item = store.add_personal(ORG, "alice", "postmortem template")

    proposal = store.propose_promotion(item.item_id, "alice", reason="reusable across teams")
    assert isinstance(proposal, PromotionProposal)
    assert proposal.is_pending

    # while pending: item stays personal, other users cannot see it
    assert store.get_item(item.item_id).scope == SCOPE_PERSONAL
    assert store.can_see("bob", store.get_item(item.item_id)) is False
    assert store.visible_items(ORG, "bob") == []
    assert [p.proposal_id for p in store.pending_proposals(ORG)] == [proposal.proposal_id]

    # authorized reviewer approves
    decided = store.approve_promotion(proposal.proposal_id, "review-lead")
    assert decided.is_approved
    assert decided.reviewer_user_id == "review-lead"

    # now org-visible to a different member
    promoted = store.get_item(item.item_id)
    assert promoted.scope == SCOPE_ORG
    assert store.can_see("bob", promoted) is True
    assert [i.item_id for i in store.visible_items(ORG, "bob")] == [item.item_id]
    # proposal no longer pending
    assert store.pending_proposals(ORG) == []


def test_non_reviewer_cannot_approve_promotion(store):
    store.add_member(ORG, "bob")
    store.add_reviewer(ORG, "review-lead")
    item = store.add_personal(ORG, "alice", "template")
    proposal = store.propose_promotion(item.item_id, "alice")

    # bob is a plain member, not a reviewer
    with pytest.raises(NotAuthorizedError):
        store.approve_promotion(proposal.proposal_id, "bob")
    # unchanged: still pending, still personal
    assert store.get_proposal(proposal.proposal_id).is_pending
    assert store.get_item(item.item_id).scope == SCOPE_PERSONAL


# -- reviewed promotion gate: rejected proposal stays personal -------------


def test_rejected_proposal_stays_personal(store):
    store.add_member(ORG, "bob")
    store.add_reviewer(ORG, "review-lead")
    item = store.add_personal(ORG, "alice", "draft not ready")

    proposal = store.propose_promotion(item.item_id, "alice")
    decided = store.reject_promotion(proposal.proposal_id, "review-lead", reason="too specific")
    assert decided.is_rejected
    assert decided.reason == "too specific"

    # item stays personal and invisible to other members
    still = store.get_item(item.item_id)
    assert still.scope == SCOPE_PERSONAL
    assert still.origin == "personal"
    assert store.can_see("bob", still) is False
    assert store.visible_items(ORG, "bob") == []
    assert store.org_items(ORG) == []


def test_cannot_decide_already_decided_proposal(store):
    store.add_reviewer(ORG, "review-lead")
    item = store.add_personal(ORG, "alice", "x")
    proposal = store.propose_promotion(item.item_id, "alice")
    store.reject_promotion(proposal.proposal_id, "review-lead")
    with pytest.raises(PromotionStateError):
        store.approve_promotion(proposal.proposal_id, "review-lead")


def test_cannot_propose_for_already_org_item(store):
    item = store.add_personal(ORG, "alice", "x")
    store.share_to_org(item.item_id, "alice")
    with pytest.raises(PromotionStateError):
        store.propose_promotion(item.item_id, "alice")


def test_rejected_item_can_be_reproposed_and_approved(store):
    store.add_reviewer(ORG, "review-lead")
    store.add_member(ORG, "bob")
    item = store.add_personal(ORG, "alice", "iterating")
    first = store.propose_promotion(item.item_id, "alice")
    store.reject_promotion(first.proposal_id, "review-lead")

    # a new proposal may now be opened for the same (still personal) item
    second = store.propose_promotion(item.item_id, "alice")
    store.approve_promotion(second.proposal_id, "review-lead")
    assert store.get_item(item.item_id).scope == SCOPE_ORG
    assert store.can_see("bob", store.get_item(item.item_id)) is True


# -- durable round-trip -----------------------------------------------------


def test_round_trip_reload_from_disk(store_path, clock):
    store = OrgKnowledgeStore(path=store_path, clock=clock)
    store.add_member(ORG, "bob")
    store.add_reviewer(ORG, "review-lead")

    shared_item = store.add_personal(ORG, "alice", "shared runbook")
    store.share_to_org(shared_item.item_id, "alice")

    promoted_item = store.add_personal(ORG, "alice", "promoted template")
    promo = store.propose_promotion(promoted_item.item_id, "alice", reason="reuse")
    store.approve_promotion(promo.proposal_id, "review-lead")

    rejected_item = store.add_personal(ORG, "dan", "rejected draft")
    rej = store.propose_promotion(rejected_item.item_id, "dan")
    store.reject_promotion(rej.proposal_id, "review-lead", reason="no")

    # reload a fresh store from the same path
    reloaded = OrgKnowledgeStore(path=store_path, clock=clock)

    # membership survives
    assert reloaded.members(ORG) == store.members(ORG)
    assert reloaded.reviewers(ORG) == ["review-lead"]

    # items survive with exact scope/origin/content
    assert reloaded.get_item(shared_item.item_id).to_payload() == shared_item_payload(store, shared_item.item_id)
    assert reloaded.get_item(shared_item.item_id).scope == SCOPE_ORG
    assert reloaded.get_item(promoted_item.item_id).scope == SCOPE_ORG
    assert reloaded.get_item(promoted_item.item_id).origin == "promoted"

    # rejected item still personal after reload
    assert reloaded.get_item(rejected_item.item_id).scope == SCOPE_PERSONAL

    # proposals survive with decisions intact
    assert reloaded.get_proposal(promo.proposal_id).is_approved
    assert reloaded.get_proposal(rej.proposal_id).is_rejected
    assert reloaded.get_proposal(rej.proposal_id).reason == "no"

    # visibility is identical across the reload
    assert [i.item_id for i in reloaded.visible_items(ORG, "bob")] == [
        i.item_id for i in store.visible_items(ORG, "bob")
    ]


def shared_item_payload(store: OrgKnowledgeStore, item_id: str) -> dict:
    return store.get_item(item_id).to_payload()


# -- misc error surfaces ----------------------------------------------------


def test_unknown_item_and_proposal_raise(store):
    with pytest.raises(ItemNotFoundError):
        store.get_item("item-999")
    with pytest.raises(ProposalNotFoundError):
        store.get_proposal("proposal-999")
