"""Tests for CAP-127: agent identity, scoped policy, signed attestation.

Every test is hermetic: a temp store path, an injected clock, injected nonces,
no network and no live model.
"""

from __future__ import annotations

import itertools
import json

import pytest

from thomas.security.agent_identity import (
    REDACTED,
    Attestation,
    IdentityStore,
    ManagedIdentity,
    ScopedPolicy,
    attest,
    canonical_action_payload,
    check_policy,
    mint_identity,
    verify_attestation,
)


class FixedClock:
    """Deterministic clock yielding a fixed sequence of ISO timestamps."""

    def __init__(self, *stamps: str) -> None:
        self._stamps = list(stamps) or ["2026-07-21T00:00:00Z"]
        self._it = itertools.cycle(self._stamps)

    def __call__(self) -> str:
        return next(self._it)


@pytest.fixture()
def store_path(tmp_path):
    return tmp_path / "identities" / "agent_identities.json"


@pytest.fixture()
def identity():
    return mint_identity(
        "Planner Agent",
        nonce="nonce-abc",
        clock=FixedClock("2026-07-21T12:00:00Z"),
    )


# ---------------------------------------------------------------------------
# Managed identity: durability + secret never leaks
# ---------------------------------------------------------------------------


def test_minting_is_durable_and_roundtrips(store_path):
    store = IdentityStore(store_path)
    minted = store.mint("Planner Agent", nonce="seed-1", clock=FixedClock("2026-07-21T09:00:00Z"))
    assert store_path.exists()

    # A fresh store instance over the same path recovers the identity intact.
    reloaded = IdentityStore(store_path).get(minted.agent_id)
    assert reloaded is not None
    assert reloaded == minted
    assert reloaded.secret == minted.secret
    assert reloaded.display_name == "Planner Agent"
    assert reloaded.created_at == "2026-07-21T09:00:00Z"
    assert IdentityStore(store_path).list_ids() == [minted.agent_id]


def test_secret_absent_from_repr_and_attestation(identity):
    # repr / str never reveal the secret.
    assert identity.secret not in repr(identity)
    assert identity.secret not in str(identity)
    assert REDACTED in repr(identity)

    # public_dict omits the secret entirely.
    assert "secret" not in identity.public_dict()
    assert identity.secret not in json.dumps(identity.public_dict())

    # The attestation carries no secret in any field or its serialisation.
    attestation = attest(
        identity,
        {"action": "read", "resource": "doc-1"},
        clock=FixedClock("2026-07-21T12:30:00Z"),
        nonce="att-nonce-1",
    )
    serialised = json.dumps(attestation.to_dict())
    assert identity.secret not in serialised
    for value in attestation.to_dict().values():
        assert identity.secret != value


def test_secret_absent_from_store_public_surface(store_path, identity):
    # The persisted store file necessarily holds the secret (server-side), but
    # the public_dict surface handed to callers/logs must not.
    store = IdentityStore(store_path)
    store.save(identity)
    assert "secret" not in identity.public_dict()


# ---------------------------------------------------------------------------
# Scoped policy: default-deny
# ---------------------------------------------------------------------------


def test_policy_allows_in_scope_and_denies_out_of_scope(identity):
    policy = ScopedPolicy.create(
        identity.agent_id,
        {"read": {"doc-1", "doc-2"}, "write": {"doc-1"}},
    )

    # In-scope: explicit action + resource grant.
    allowed = check_policy(policy, identity, "read", "doc-1")
    assert allowed.allowed is True
    assert bool(allowed) is True

    # Out-of-scope resource -> deny.
    assert check_policy(policy, identity, "read", "doc-99").allowed is False
    # Out-of-scope action -> deny.
    assert check_policy(policy, identity, "delete", "doc-1").allowed is False
    # Write is only granted for doc-1.
    assert check_policy(policy, identity, "write", "doc-1").allowed is True
    assert check_policy(policy, identity, "write", "doc-2").allowed is False


def test_policy_default_deny_when_no_grants(identity):
    empty = ScopedPolicy.create(identity.agent_id, {})
    decision = check_policy(empty, identity, "read", "doc-1")
    assert decision.allowed is False
    assert "default-deny" in decision.reason


def test_policy_wildcards(identity):
    # Wildcard resource for an action.
    any_read = ScopedPolicy.create(identity.agent_id, {"read": {"*"}})
    assert check_policy(any_read, identity, "read", "anything").allowed is True
    assert check_policy(any_read, identity, "write", "anything").allowed is False

    # Wildcard action.
    god = ScopedPolicy.create(identity.agent_id, {"*": {"*"}})
    assert check_policy(god, identity, "delete", "whatever").allowed is True


def test_policy_for_other_agent_is_denied(identity):
    other = mint_identity("Other Agent", nonce="nonce-xyz", clock=FixedClock("2026-07-21T12:00:00Z"))
    assert other.agent_id != identity.agent_id
    policy = ScopedPolicy.create(other.agent_id, {"read": {"doc-1"}})
    # Same grant, wrong identity -> deny.
    assert check_policy(policy, identity, "read", "doc-1").allowed is False


def test_policy_roundtrips_through_store(store_path, identity):
    store = IdentityStore(store_path)
    store.save(identity)
    policy = ScopedPolicy.create(identity.agent_id, {"read": {"doc-1", "doc-2"}})
    store.attach_policy(policy)

    reloaded = IdentityStore(store_path).get_policy(identity.agent_id)
    assert reloaded is not None
    assert reloaded == policy
    assert check_policy(reloaded, identity, "read", "doc-2").allowed is True


# ---------------------------------------------------------------------------
# Signed attestation: verifies true, tamper fails, forgery fails
# ---------------------------------------------------------------------------


def test_attestation_verifies_for_original_action(identity):
    action = {"action": "write", "resource": "doc-1", "bytes": 42}
    attestation = attest(identity, action, clock=FixedClock("2026-07-21T13:00:00Z"), nonce="n1")
    assert verify_attestation(attestation, action, identity) is True


def test_tampering_action_payload_fails_verification(identity):
    action = {"action": "write", "resource": "doc-1", "bytes": 42}
    attestation = attest(identity, action, clock=FixedClock("2026-07-21T13:00:00Z"), nonce="n1")

    tampered = dict(action)
    tampered["bytes"] = 43
    assert verify_attestation(attestation, tampered, identity) is False

    tampered2 = dict(action)
    tampered2["resource"] = "doc-2"
    assert verify_attestation(attestation, tampered2, identity) is False


def test_tampering_identity_fails_verification(identity):
    action = {"action": "write", "resource": "doc-1"}
    attestation = attest(identity, action, clock=FixedClock("2026-07-21T13:00:00Z"), nonce="n1")

    # A different identity (different agent_id AND secret) must not verify.
    other = mint_identity("Other Agent", nonce="other-seed", clock=FixedClock("2026-07-21T13:00:00Z"))
    assert verify_attestation(attestation, action, other) is False

    # Same agent_id but a different secret (swapped-key attack) also fails.
    forged_secret = ManagedIdentity(
        agent_id=identity.agent_id,
        display_name=identity.display_name,
        created_at=identity.created_at,
        secret="0" * 64,
    )
    assert verify_attestation(attestation, action, forged_secret) is False


def test_forged_attestation_with_wrong_secret_fails(identity):
    action = {"action": "write", "resource": "doc-1"}
    # Attacker signs with the WRONG secret but claims the victim's agent_id.
    attacker = ManagedIdentity(
        agent_id=identity.agent_id,
        display_name=identity.display_name,
        created_at=identity.created_at,
        secret="deadbeef" * 8,
    )
    forged = attest(attacker, action, clock=FixedClock("2026-07-21T13:00:00Z"), nonce="n1")
    # Verifying against the real identity's secret must fail.
    assert verify_attestation(forged, action, identity) is False


def test_tampering_signed_fields_fails(identity):
    action = {"action": "write", "resource": "doc-1"}
    attestation = attest(identity, action, clock=FixedClock("2026-07-21T13:00:00Z"), nonce="n1")
    # Flip the nonce and issued_at that the signature commits to.
    mutated = Attestation(
        agent_id=attestation.agent_id,
        action_digest=attestation.action_digest,
        issued_at="2099-01-01T00:00:00Z",
        nonce=attestation.nonce,
        signature=attestation.signature,
    )
    assert verify_attestation(mutated, action, identity) is False

    mutated_nonce = Attestation(
        agent_id=attestation.agent_id,
        action_digest=attestation.action_digest,
        issued_at=attestation.issued_at,
        nonce="different-nonce",
        signature=attestation.signature,
    )
    assert verify_attestation(mutated_nonce, action, identity) is False


def test_attestation_is_deterministic(identity):
    action = {"b": 2, "a": 1}
    kwargs = {"clock": FixedClock("2026-07-21T13:00:00Z"), "nonce": "n1"}
    a1 = attest(identity, action, **kwargs)
    a2 = attest(identity, action, **kwargs)
    assert a1 == a2
    # Key order in the action dict must not change the digest.
    reordered = {"a": 1, "b": 2}
    a3 = attest(identity, reordered, **kwargs)
    assert a3.action_digest == a1.action_digest


def test_canonical_payload_is_key_order_independent():
    assert canonical_action_payload({"a": 1, "b": 2}) == canonical_action_payload({"b": 2, "a": 1})


def test_store_env_override(tmp_path, monkeypatch):
    target = tmp_path / "custom" / "ids.json"
    monkeypatch.setenv("THOMAS_AGENT_IDENTITY_STORE_PATH", str(target))
    store = IdentityStore()
    assert store.path == target
    store.mint("Env Agent", nonce="e1", clock=FixedClock("2026-07-21T00:00:00Z"))
    assert target.exists()
