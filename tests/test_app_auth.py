"""CAP-118 Auth provisioning: ownership-scoped access for a generated app with
auto-emitted cross-account denial tests.

Hermetic + deterministic: pure in-process logic, no network, no filesystem, no
clock. The "broken build" is the injected :class:`PermissivePolicy`, used to
prove the auto-emitted denial suite actually fails when ownership is not
enforced (the tests have teeth).
"""

from __future__ import annotations

from thomas.marketplace.app_provisioning.auth import (
    DEFAULT_ACTIONS,
    OwnershipPolicy,
    PermissivePolicy,
    ResourceModel,
    emit_cross_account_denial_tests,
    generate_ownership_policy,
    make_resource,
    provision_auth,
    run_denial_tests,
)

# Two accounts (A and B) each owning one resource, plus a resource A owns but
# has granted B a single "read" on (to prove grants are honored and excluded
# from the cross-account denial suite).
DOC_A = make_resource("doc_a", "document", owner="acct_A")
DOC_B = make_resource("doc_b", "document", owner="acct_B")
SHARED = make_resource("doc_shared", "document", owner="acct_A", grants={"acct_B": ["read"]})


def _model() -> ResourceModel:
    return ResourceModel.build([DOC_A, DOC_B, SHARED])


# ---------------------------------------------------------------------------
# (1) ownership-scoped access: owner allowed, non-owner denied (default-deny)
# ---------------------------------------------------------------------------


def test_owner_allowed_and_non_owner_denied_default_deny():
    policy = generate_ownership_policy(_model())

    # Owner is allowed on their own resource for every action.
    for action in DEFAULT_ACTIONS:
        owner_dec = policy.check_access("acct_A", "doc_a", action)
        assert owner_dec.allowed is True
        assert "owns" in owner_dec.reason

    # A non-owner is denied on someone else's resource -- default-deny.
    non_owner_dec = policy.check_access("acct_B", "doc_a", "read")
    assert non_owner_dec.allowed is False
    assert "default-deny" in non_owner_dec.reason

    # Default-deny also covers unknown resources and unknown actions.
    assert policy.check_access("acct_A", "does_not_exist", "read").allowed is False
    assert policy.check_access("acct_A", "doc_a", "sudo").allowed is False
    assert policy.check_access("", "doc_a", "read").allowed is False

    # An explicit grant is honored (B may READ the shared doc A owns)...
    assert policy.check_access("acct_B", "doc_shared", "read").allowed is True
    # ...but only for the granted action; write is still denied.
    assert policy.check_access("acct_B", "doc_shared", "write").allowed is False


# ---------------------------------------------------------------------------
# (2) auto-emit cross-account denial tests for the resource model
# ---------------------------------------------------------------------------


def test_cross_account_denial_tests_are_auto_emitted():
    model = _model()
    specs = emit_cross_account_denial_tests(model)

    # Non-empty, every spec asserts denial, and no spec targets the resource's
    # own owner (those aren't cross-account cases).
    assert len(specs) > 0
    for spec in specs:
        assert spec.expected_effect == "deny"
        owner = model.get(spec.resource_id).owner
        assert spec.actor != owner

    # Symmetric coverage: B is tested against A's resource AND A against B's.
    pairs = {(s.actor, s.resource_id) for s in specs}
    assert ("acct_B", "doc_a") in pairs  # B denied on A's resource
    assert ("acct_A", "doc_b") in pairs  # A denied on B's resource

    # The granted (acct_B, doc_shared, "read") case is EXCLUDED from the denial
    # suite (it is legitimately allowed), while write/delete/list remain.
    shared_b = {s.action for s in specs if s.actor == "acct_B" and s.resource_id == "doc_shared"}
    assert "read" not in shared_b
    assert {"write", "delete", "list"} <= shared_b

    # Deterministic: identical input -> identical specs (ids and order).
    specs_again = emit_cross_account_denial_tests(_model())
    assert [s.test_id for s in specs] == [s.test_id for s in specs_again]


# ---------------------------------------------------------------------------
# (3a) running the suite against the CORRECT policy PASSES
# ---------------------------------------------------------------------------


def test_denial_suite_passes_against_correct_policy():
    model = _model()
    policy = generate_ownership_policy(model)
    specs = emit_cross_account_denial_tests(model)

    report = run_denial_tests(specs, policy)

    assert report.total == len(specs)
    assert report.all_passed is True
    assert report.failed == 0
    assert report.passed == report.total
    assert report.failures() == ()


# ---------------------------------------------------------------------------
# (3b) running the suite against a BROKEN (permissive) policy FAILS
#      -- proves the auto-emitted tests have teeth
# ---------------------------------------------------------------------------


def test_denial_suite_fails_against_broken_permissive_policy():
    model = _model()
    specs = emit_cross_account_denial_tests(model)

    broken = PermissivePolicy()  # allow-all: forgot to scope by ownership
    report = run_denial_tests(specs, broken)

    assert report.total == len(specs)
    assert report.all_passed is False
    # A permissive build allows every cross-account access, so EVERY denial
    # assertion fails -- the suite is not vacuous.
    assert report.failed == report.total
    assert report.passed == 0
    assert len(report.failures()) == report.total


# ---------------------------------------------------------------------------
# round-trip: provision_auth wires generate -> emit -> validate end to end
# ---------------------------------------------------------------------------


def test_provision_auth_round_trip():
    prov = provision_auth(_model())

    # The generated policy is the ownership policy and it self-validates.
    assert isinstance(prov.policy, OwnershipPolicy)
    assert prov.validated is True
    assert prov.report.all_passed is True
    assert len(prov.denial_tests) == prov.report.total

    # Access still enforced through the bundle's convenience method.
    assert prov.check_access("acct_A", "doc_a", "write").allowed is True
    assert prov.check_access("acct_B", "doc_a", "write").allowed is False

    # The exact same emitted suite fails against a broken build -> teeth proven
    # within the round-trip too.
    broken_report = run_denial_tests(prov.denial_tests, PermissivePolicy())
    assert broken_report.all_passed is False
    assert broken_report.failed == broken_report.total

    # Structured/serializable output for downstream tooling.
    payload = prov.report.to_dict()
    assert payload["all_passed"] is True
    assert payload["total"] == len(prov.denial_tests)
    assert prov.denial_tests[0].to_dict()["expected_effect"] == "deny"
