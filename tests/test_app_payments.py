"""CAP-119 Payments wiring: verified webhooks grant entitlements; nothing
is granted without a verified event.

Hermetic: injected clock, temp entitlement store, no network, no real secret.
The valid/forged signature paths are proven against the REAL default verifier
(which reuses the repo's SDK-free Stripe verifier) *and* the hermetic fake.
"""

from __future__ import annotations

import json
import logging
import time

import pytest

from thomas.marketplace.app_provisioning.payments import (
    CheckoutIntent,
    EntitlementStore,
    FakePaymentProvider,
    FakeSignatureVerifier,
    PaymentWiring,
    StripePaymentProvider,
    StripeSignatureVerifier,
    build_stripe_signature_header,
)

SECRET = "whsec_hermetic_test_secret"
FROZEN_TS = 1_700_000_000


def _now_ts() -> int:
    # The REAL repo verifier checks the signature timestamp against wall-clock
    # tolerance, so real-verifier tests sign at "now". Still fully offline.
    return int(time.time())


@pytest.fixture
def clock():
    return lambda: float(FROZEN_TS)


@pytest.fixture
def store(tmp_path, clock):
    return EntitlementStore(tmp_path / "entitlements.json", clock=clock)


def _event_body(event_type: str, account_id: str, entitlement: str = "pro", event_id: str = "evt_1") -> bytes:
    payload = {
        "id": event_id,
        "type": event_type,
        "data": {
            "object": {
                "client_reference_id": account_id,
                "metadata": {"account_id": account_id, "entitlement": entitlement},
            }
        },
    }
    return json.dumps(payload).encode("utf-8")


def _real_wiring(store) -> PaymentWiring:
    # Default verifier reuses the repo's SDK-free Stripe signature verifier.
    return PaymentWiring(
        app_id="app_demo",
        signing_secrets=SECRET,
        store=store,
        provider=FakePaymentProvider(),
        verifier=StripeSignatureVerifier(),
    )


# ---------------------------------------------------------------------------
# ACCEPTANCE: a valid signed webhook grants the entitlement
# ---------------------------------------------------------------------------


def test_valid_signed_webhook_grants_entitlement_real_verifier(store):
    wiring = _real_wiring(store)
    body = _event_body("checkout.session.completed", "acct_42")
    header = build_stripe_signature_header(SECRET, body, _now_ts())

    # Precondition: no entitlement yet.
    assert wiring.is_entitled("acct_42", "pro") is False

    decision = wiring.handle_webhook(body=body, signature_header=header)

    assert decision.accepted is True
    assert decision.action == "grant"
    assert decision.account_id == "acct_42"
    assert decision.entitlement == "pro"
    # check() reflects current state -> now entitled
    assert wiring.is_entitled("acct_42", "pro") is True
    assert store.check("acct_42", "pro") is True


# ---------------------------------------------------------------------------
# ACCEPTANCE: a forged / invalid signature grants nothing (rejected + reason)
# ---------------------------------------------------------------------------


def test_forged_signature_grants_nothing_real_verifier(store):
    wiring = _real_wiring(store)
    body = _event_body("checkout.session.completed", "acct_bad")
    forged = f"t={_now_ts()},v1=deadbeefdeadbeef"

    decision = wiring.handle_webhook(body=body, signature_header=forged)

    assert decision.accepted is False
    assert decision.action == "rejected"
    assert decision.reason  # non-empty machine-readable reason
    # Nothing granted, store untouched.
    assert wiring.is_entitled("acct_bad", "pro") is False
    assert store.get("acct_bad", "pro") is None


def test_wrong_secret_signature_grants_nothing_real_verifier(store):
    wiring = _real_wiring(store)
    body = _event_body("checkout.session.completed", "acct_x")
    header = build_stripe_signature_header("whsec_attacker_key", body, _now_ts())

    decision = wiring.handle_webhook(body=body, signature_header=header)

    assert decision.accepted is False
    assert decision.action == "rejected"
    assert store.check("acct_x", "pro") is False


def test_missing_signature_header_grants_nothing(store):
    wiring = _real_wiring(store)
    body = _event_body("checkout.session.completed", "acct_y")

    decision = wiring.handle_webhook(body=body, signature_header=None)

    assert decision.accepted is False
    assert decision.action == "rejected"
    assert "missing signature" in decision.reason
    assert store.check("acct_y", "pro") is False


def test_tampered_body_after_signing_grants_nothing(store):
    wiring = _real_wiring(store)
    body = _event_body("checkout.session.completed", "acct_orig")
    header = build_stripe_signature_header(SECRET, body, _now_ts())
    tampered = _event_body("checkout.session.completed", "acct_attacker")

    decision = wiring.handle_webhook(body=tampered, signature_header=header)

    assert decision.accepted is False
    assert store.check("acct_attacker", "pro") is False
    assert store.check("acct_orig", "pro") is False


# ---------------------------------------------------------------------------
# ACCEPTANCE: revoke on a cancellation event; check reflects current state
# ---------------------------------------------------------------------------


def test_revoke_on_cancellation_event(store):
    # Use the hermetic fake verifier with the injected clock for determinism.
    verifier = FakeSignatureVerifier(clock=lambda: float(FROZEN_TS))
    wiring = PaymentWiring(
        app_id="app_demo",
        signing_secrets=SECRET,
        store=store,
        verifier=verifier,
    )

    grant_body = _event_body("customer.subscription.created", "acct_sub", event_id="evt_grant")
    grant_header = build_stripe_signature_header(SECRET, grant_body, FROZEN_TS)
    assert wiring.handle_webhook(body=grant_body, signature_header=grant_header).action == "grant"
    assert wiring.is_entitled("acct_sub", "pro") is True

    cancel_body = _event_body("customer.subscription.deleted", "acct_sub", event_id="evt_cancel")
    cancel_header = build_stripe_signature_header(SECRET, cancel_body, FROZEN_TS)
    decision = wiring.handle_webhook(body=cancel_body, signature_header=cancel_header)

    assert decision.action == "revoke"
    assert decision.accepted is True
    # check() reflects current state -> no longer entitled
    assert wiring.is_entitled("acct_sub", "pro") is False
    rec = store.get("acct_sub", "pro")
    assert rec is not None and rec.status == "revoked"


def test_unhandled_event_type_is_ignored_no_state_change(store):
    verifier = FakeSignatureVerifier(clock=lambda: float(FROZEN_TS))
    wiring = PaymentWiring(app_id="a", signing_secrets=SECRET, store=store, verifier=verifier)
    body = _event_body("charge.updated", "acct_ignored")
    header = build_stripe_signature_header(SECRET, body, FROZEN_TS)

    decision = wiring.handle_webhook(body=body, signature_header=header)

    assert decision.accepted is True
    assert decision.action == "ignored"
    assert store.get("acct_ignored", "pro") is None


# ---------------------------------------------------------------------------
# ACCEPTANCE: secrets never logged
# ---------------------------------------------------------------------------


def test_secret_never_logged(store, caplog):
    wiring = _real_wiring(store)
    body = _event_body("checkout.session.completed", "acct_log")
    header = build_stripe_signature_header(SECRET, body, _now_ts())

    with caplog.at_level(logging.DEBUG):
        wiring.handle_webhook(body=body, signature_header=header)
        # also a rejection path
        wiring.handle_webhook(body=body, signature_header="t=1,v1=bad")

    combined = "\n".join(r.getMessage() for r in caplog.records)
    assert SECRET not in combined


def test_api_key_never_logged_on_checkout(caplog):
    provider = StripePaymentProvider("sk_test_super_secret_key", clock=lambda: float(FROZEN_TS))
    intent = CheckoutIntent(
        account_id="acct_c",
        entitlement="pro",
        price_id="price_123",
        success_url="https://app/success",
        cancel_url="https://app/cancel",
    )
    with caplog.at_level(logging.DEBUG):
        session = provider.create_checkout(intent)

    combined = "\n".join(r.getMessage() for r in caplog.records)
    assert "sk_test_super_secret_key" not in combined
    # The key is still present in the (unlogged) prepared request headers.
    assert session.prepared_request is not None
    assert session.prepared_request.headers["Authorization"] == "Bearer sk_test_super_secret_key"


# ---------------------------------------------------------------------------
# Checkout wiring: real provider builds the request, no live call
# ---------------------------------------------------------------------------


def test_stripe_provider_builds_request_without_live_call():
    provider = StripePaymentProvider("sk_test_x", clock=lambda: float(FROZEN_TS))
    intent = CheckoutIntent(
        account_id="acct_z",
        entitlement="pro",
        price_id="price_abc",
        mode="subscription",
        success_url="https://app/ok",
        cancel_url="https://app/no",
    )
    session = provider.create_checkout(intent)

    assert session.live_call_made is False
    req = session.prepared_request
    assert req is not None
    assert req.method == "POST"
    assert req.url == "https://api.stripe.com/v1/checkout/sessions"
    assert "mode=subscription" in req.body
    assert "line_items%5B0%5D%5Bprice%5D=price_abc" in req.body
    assert "client_reference_id=acct_z" in req.body
    assert "metadata%5Bentitlement%5D=pro" in req.body
    assert req.headers["Idempotency-Key"]


def test_wire_checkout_through_wiring_fake_provider(store):
    provider = FakePaymentProvider()
    wiring = PaymentWiring(app_id="app", signing_secrets=SECRET, store=store, provider=provider)
    intent = CheckoutIntent(account_id="acct_w", entitlement="pro", price_id="price_1")

    session = wiring.wire_checkout(intent)

    assert session.checkout_url and session.checkout_url.startswith("https://fake.checkout.local/")
    assert provider.calls == [intent]


def test_wire_checkout_without_provider_raises(store):
    wiring = PaymentWiring(app_id="app", signing_secrets=SECRET, store=store)
    with pytest.raises(ValueError, match="no payment provider"):
        wiring.wire_checkout(CheckoutIntent(account_id="a", entitlement="pro", price_id="p"))


# ---------------------------------------------------------------------------
# Store round-trip + persistence
# ---------------------------------------------------------------------------


def test_entitlement_store_roundtrip_persists(tmp_path, clock):
    path = tmp_path / "ent.json"
    store_a = EntitlementStore(path, clock=clock)
    store_a.grant("acct_rt", "pro", event_id="evt_rt", reason="checkout.session.completed")

    # Fresh instance reading the same file reflects the grant.
    store_b = EntitlementStore(path, clock=clock)
    assert store_b.check("acct_rt", "pro") is True
    rec = store_b.get("acct_rt", "pro")
    assert rec is not None
    assert rec.active is True
    assert rec.source_event_id == "evt_rt"
    assert rec.granted_at == float(FROZEN_TS)

    listed = store_b.list_for("acct_rt")
    assert [r.entitlement for r in listed] == ["pro"]


def test_env_override_store_path(monkeypatch, tmp_path, clock):
    target = tmp_path / "env_entitlements.json"
    monkeypatch.setenv("THOMAS_ENTITLEMENTS_FILE", str(target))
    store = EntitlementStore(clock=clock)
    store.grant("acct_env", "team", event_id="evt_env")
    assert target.exists()
    assert store.check("acct_env", "team") is True


def test_grant_preserves_original_granted_at_on_regrant(store):
    first = store.grant("acct_re", "pro", event_id="evt1")
    again = store.grant("acct_re", "pro", event_id="evt2")
    assert again.granted_at == first.granted_at
    assert again.source_event_id == "evt2"
