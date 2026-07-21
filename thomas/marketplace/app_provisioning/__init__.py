"""App provisioning: payment/entitlement wiring for generated apps.

Public surface:

- :class:`PaymentWiring` -- wires a checkout/subscription intent through an
  injectable payment provider and grants/revokes entitlements strictly on
  *verified* webhook events.
- :class:`EntitlementStore` -- JSON-backed account -> entitlements store with
  grant/revoke/check.
- :class:`StripePaymentProvider` -- real (SDK-free) default that *builds* the
  Stripe Checkout Session request without making a live call.
- :class:`FakePaymentProvider` -- hermetic provider for tests.
- :class:`StripeSignatureVerifier` -- default verifier reusing the repo's
  SDK-free Stripe signature verifier.
"""

from thomas.marketplace.app_provisioning.payments import (
    CheckoutIntent,
    CheckoutSession,
    EntitlementDecision,
    EntitlementRecord,
    EntitlementStore,
    FakePaymentProvider,
    FakeSignatureVerifier,
    PaymentProvider,
    PaymentWiring,
    PreparedRequest,
    SignatureVerifier,
    StripePaymentProvider,
    StripeSignatureVerifier,
    VerificationResult,
    build_stripe_signature_header,
)

__all__ = [
    "CheckoutIntent",
    "CheckoutSession",
    "EntitlementDecision",
    "EntitlementRecord",
    "EntitlementStore",
    "FakePaymentProvider",
    "FakeSignatureVerifier",
    "PaymentProvider",
    "PaymentWiring",
    "PreparedRequest",
    "SignatureVerifier",
    "StripePaymentProvider",
    "StripeSignatureVerifier",
    "VerificationResult",
    "build_stripe_signature_header",
]
