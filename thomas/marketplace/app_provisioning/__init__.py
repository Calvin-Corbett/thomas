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
- :func:`provision_auth` -- generates an ownership-scoped, default-deny access
  policy for a generated app plus an auto-emitted cross-account denial suite,
  and validates the policy by running that suite against it.
"""

from thomas.marketplace.app_provisioning.auth import (
    DEFAULT_ACTIONS,
    AccessDecision,
    AuthProvisioning,
    DenialTestReport,
    DenialTestResult,
    DenialTestSpec,
    OwnershipPolicy,
    PermissivePolicy,
    Policy,
    Resource,
    ResourceModel,
    emit_cross_account_denial_tests,
    generate_ownership_policy,
    make_resource,
    provision_auth,
    run_denial_tests,
)
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
    "DEFAULT_ACTIONS",
    "AccessDecision",
    "AuthProvisioning",
    "DenialTestReport",
    "DenialTestResult",
    "DenialTestSpec",
    "OwnershipPolicy",
    "PermissivePolicy",
    "Policy",
    "Resource",
    "ResourceModel",
    "emit_cross_account_denial_tests",
    "generate_ownership_policy",
    "make_resource",
    "provision_auth",
    "run_denial_tests",
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
