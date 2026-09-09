"""Ownership-scoped auth provisioning for generated (app-builder) apps.

What this provides
------------------
Given the *resource model* of an app the app-builder just generated, this
module:

1. **Generates an ownership-scoped access policy.** Every resource has an
   ``owner`` (an account id). The generated :class:`OwnershipPolicy` permits an
   actor to act on a resource only when the actor *owns* it or has been *granted*
   an explicit permission for it. Everything else is **default-deny** --
   including any resource, actor, or action the policy has never heard of.

2. **Auto-emits cross-account denial tests.** From the resource model alone it
   derives runnable, structured :class:`DenialTestSpec` cases asserting that
   account *B* is denied access to account *A*'s resources (and vice versa) for
   every action -- the classic cross-tenant/IDOR guard. The specs are plain data
   (JSON-serializable) *and* runnable (``spec.run(policy)``).

3. **Validates the policy by running those tests against it.** :func:`run_denial_tests`
   executes every emitted spec and returns a structured :class:`DenialTestReport`.
   A correct ownership policy passes them all; a deliberately permissive/broken
   build fails them -- proving the tests have teeth.

Design notes
------------
* **Deterministic.** Resources, actors, actions, and emitted specs are all
  sorted, so identical inputs produce byte-identical output and stable test ids.
* **The policy is the injectable seam.** :class:`Policy` is a ``Protocol``. The
  real default is :class:`OwnershipPolicy`; :class:`PermissivePolicy` is the
  hermetic "broken build" used in tests to prove the denial suite actually
  fails when ownership isn't enforced. A generated app can swap in its own
  ``Policy`` implementation and re-run the same emitted specs.
* **No external edges.** Pure in-process logic -- no network, no filesystem, no
  clock. Nothing to fake beyond the policy itself.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Default CRUD-ish action verbs an app-builder app exposes on its resources.
# Kept explicit so the emitted denial suite covers every mutating/reading verb.
DEFAULT_ACTIONS: tuple[str, ...] = ("read", "write", "delete", "list")


# ---------------------------------------------------------------------------
# Resource model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Resource:
    """A single ownership-scoped resource in a generated app.

    ``owner`` is the account id that owns the resource. ``grants`` maps an
    actor (account id) to the set of actions that actor has been *explicitly*
    granted on this resource (beyond ownership).
    """

    resource_id: str
    resource_type: str
    owner: str
    grants: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def granted_actions(self, actor: str) -> frozenset[str]:
        actions = self.grants.get(actor)
        return actions if actions else frozenset()

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "owner": self.owner,
            "grants": {actor: sorted(actions) for actor, actions in self.grants.items()},
        }


def make_resource(
    resource_id: str,
    resource_type: str,
    owner: str,
    grants: Mapping[str, Iterable[str]] | None = None,
) -> Resource:
    """Build a :class:`Resource`, normalizing ``grants`` to frozensets."""
    normalized: dict[str, frozenset[str]] = {}
    if grants:
        for actor, actions in grants.items():
            action_set = frozenset(str(a) for a in actions)
            if action_set:
                normalized[str(actor)] = action_set
    return Resource(
        resource_id=str(resource_id),
        resource_type=str(resource_type),
        owner=str(owner),
        grants=normalized,
    )


@dataclass(frozen=True)
class ResourceModel:
    """The full ownership model for a generated app."""

    resources: tuple[Resource, ...]
    actions: tuple[str, ...] = DEFAULT_ACTIONS

    @classmethod
    def build(
        cls,
        resources: Sequence[Resource],
        actions: Sequence[str] | None = None,
    ) -> ResourceModel:
        # Deterministic: sort resources by id, dedupe/sort actions preserving
        # a stable order.
        ordered_resources = tuple(sorted(resources, key=lambda r: r.resource_id))
        if actions is None:
            ordered_actions = DEFAULT_ACTIONS
        else:
            seen: dict[str, None] = {}
            for a in actions:
                seen.setdefault(str(a), None)
            ordered_actions = tuple(sorted(seen))
        return cls(resources=ordered_resources, actions=ordered_actions)

    def resource_ids(self) -> tuple[str, ...]:
        return tuple(r.resource_id for r in self.resources)

    def owners(self) -> tuple[str, ...]:
        return tuple(sorted({r.owner for r in self.resources}))

    def get(self, resource_id: str) -> Resource | None:
        for r in self.resources:
            if r.resource_id == resource_id:
                return r
        return None


# ---------------------------------------------------------------------------
# Access decision + policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AccessDecision:
    """Result of an authorization check."""

    allowed: bool
    reason: str
    actor: str
    resource_id: str
    action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "actor": self.actor,
            "resource_id": self.resource_id,
            "action": self.action,
        }


def _resource_id_of(resource: Resource | str) -> str:
    return resource.resource_id if isinstance(resource, Resource) else str(resource)


@runtime_checkable
class Policy(Protocol):
    """Injectable authorization policy.

    The correct default is :class:`OwnershipPolicy`. Tests inject
    :class:`PermissivePolicy` to prove the emitted denial suite has teeth.
    """

    def check_access(self, actor: str, resource: Resource | str, action: str) -> AccessDecision: ...


class OwnershipPolicy:
    """Ownership-scoped, default-deny authorization policy.

    Allows ``actor`` on ``resource`` for ``action`` iff:

    * the actor **owns** the resource, or
    * the actor has an explicit **grant** covering that action.

    Any unknown resource, unknown action, or non-owner-without-grant is
    **denied**. Deny is the default and the only fallthrough.
    """

    def __init__(self, model: ResourceModel) -> None:
        self._model = model
        self._by_id: dict[str, Resource] = {r.resource_id: r for r in model.resources}
        self._actions: frozenset[str] = frozenset(model.actions)

    @property
    def model(self) -> ResourceModel:
        return self._model

    def check_access(self, actor: str, resource: Resource | str, action: str) -> AccessDecision:
        actor = str(actor)
        action = str(action)
        resource_id = _resource_id_of(resource)

        res = self._by_id.get(resource_id)
        if res is None:
            return AccessDecision(False, "default-deny: unknown resource", actor, resource_id, action)
        if action not in self._actions:
            return AccessDecision(False, "default-deny: unknown action", actor, resource_id, action)
        if not actor:
            return AccessDecision(False, "default-deny: anonymous actor", actor, resource_id, action)

        if res.owner == actor:
            return AccessDecision(True, "allowed: actor owns resource", actor, resource_id, action)
        if action in res.granted_actions(actor):
            return AccessDecision(True, "allowed: explicit grant", actor, resource_id, action)
        return AccessDecision(
            False,
            "default-deny: actor is not owner and has no grant",
            actor,
            resource_id,
            action,
        )


class PermissivePolicy:
    """A deliberately broken, allow-everything policy.

    Represents a generated app that *forgot* to scope access by ownership (or
    whose ownership check regressed). It exists so the auto-emitted denial
    suite can be shown to **fail** against it -- proving the suite is not
    vacuous.
    """

    def check_access(self, actor: str, resource: Resource | str, action: str) -> AccessDecision:
        resource_id = _resource_id_of(resource)
        return AccessDecision(True, "permissive: allow-all (broken build)", str(actor), resource_id, str(action))


def generate_ownership_policy(model: ResourceModel) -> OwnershipPolicy:
    """Generate the ownership-scoped, default-deny policy for ``model``."""
    policy = OwnershipPolicy(model)
    logger.info(
        "auth.policy.generated resources=%d owners=%d actions=%d",
        len(model.resources),
        len(model.owners()),
        len(model.actions),
    )
    return policy


# ---------------------------------------------------------------------------
# Auto-emitted cross-account denial tests
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DenialTestSpec:
    """A runnable, structured cross-account denial assertion.

    Asserts that ``actor`` (an account that does *not* own ``resource_id``) is
    **denied** ``action`` on it. Runnable via :meth:`run`; serializable via
    :meth:`to_dict`.
    """

    test_id: str
    actor: str
    resource_id: str
    action: str
    resource_owner: str
    expected_effect: str = "deny"

    def run(self, policy: Policy) -> DenialTestResult:
        decision = policy.check_access(self.actor, self.resource_id, self.action)
        # The spec asserts denial: it PASSES when access is denied.
        passed = not decision.allowed
        return DenialTestResult(spec=self, passed=passed, decision=decision)

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_id": self.test_id,
            "actor": self.actor,
            "resource_id": self.resource_id,
            "action": self.action,
            "resource_owner": self.resource_owner,
            "expected_effect": self.expected_effect,
        }


@dataclass(frozen=True)
class DenialTestResult:
    """Outcome of running one :class:`DenialTestSpec` against a policy."""

    spec: DenialTestSpec
    passed: bool
    decision: AccessDecision

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_id": self.spec.test_id,
            "passed": self.passed,
            "spec": self.spec.to_dict(),
            "decision": self.decision.to_dict(),
        }


@dataclass(frozen=True)
class DenialTestReport:
    """Aggregate result of running a denial suite against a policy."""

    total: int
    passed: int
    failed: int
    results: tuple[DenialTestResult, ...]

    @property
    def all_passed(self) -> bool:
        return self.total > 0 and self.failed == 0

    def failures(self) -> tuple[DenialTestResult, ...]:
        return tuple(r for r in self.results if not r.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "all_passed": self.all_passed,
            "results": [r.to_dict() for r in self.results],
        }


def emit_cross_account_denial_tests(model: ResourceModel) -> tuple[DenialTestSpec, ...]:
    """Auto-generate cross-account denial specs from the resource model.

    For every resource owned by account *A* and every *other* account *B* in
    the model, emit one spec per action asserting *B* is denied on *A*'s
    resource. This is symmetric across all account pairs (A denied on B's, and
    B denied on A's), giving full cross-account coverage. Deterministic order.
    """
    owners = model.owners()
    specs: list[DenialTestSpec] = []
    for res in model.resources:  # already sorted by resource_id
        for actor in owners:  # sorted
            if actor == res.owner:
                continue  # same-account access is not a cross-account denial case
            for action in model.actions:  # sorted
                # Skip actions the app explicitly granted to this actor: those
                # are legitimately allowed and are covered by grant tests, not
                # cross-account denial tests.
                if action in res.granted_actions(actor):
                    continue
                test_id = f"denial::{actor}::{res.resource_id}::{action}"
                specs.append(
                    DenialTestSpec(
                        test_id=test_id,
                        actor=actor,
                        resource_id=res.resource_id,
                        action=action,
                        resource_owner=res.owner,
                    )
                )
    logger.info("auth.denial_tests.emitted count=%d", len(specs))
    return tuple(specs)


def run_denial_tests(specs: Sequence[DenialTestSpec], policy: Policy) -> DenialTestReport:
    """Run every denial spec against ``policy`` and aggregate the outcome."""
    results = tuple(spec.run(policy) for spec in specs)
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    report = DenialTestReport(total=len(results), passed=passed, failed=failed, results=results)
    logger.info(
        "auth.denial_tests.ran total=%d passed=%d failed=%d",
        report.total,
        report.passed,
        report.failed,
    )
    return report


# ---------------------------------------------------------------------------
# One-shot provisioning
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthProvisioning:
    """Bundle of everything produced for a generated app's auth layer."""

    model: ResourceModel
    policy: OwnershipPolicy
    denial_tests: tuple[DenialTestSpec, ...]
    report: DenialTestReport

    @property
    def validated(self) -> bool:
        """True iff the emitted denial suite passes against the generated policy."""
        return self.report.all_passed

    def check_access(self, actor: str, resource: Resource | str, action: str) -> AccessDecision:
        return self.policy.check_access(actor, resource, action)


def provision_auth(model: ResourceModel) -> AuthProvisioning:
    """Generate policy + denial tests and validate the policy against them.

    This is the end-to-end app-builder entry point: give it the app's resource
    model, get back the ownership-scoped policy, the auto-emitted cross-account
    denial suite, and the report proving the policy passes that suite.
    """
    policy = generate_ownership_policy(model)
    denial_tests = emit_cross_account_denial_tests(model)
    report = run_denial_tests(denial_tests, policy)
    if not report.all_passed:
        # A correct ownership policy MUST pass its own denial suite. Surfacing
        # this loudly turns a silent auth regression into a provisioning error.
        logger.error(
            "auth.provisioning.invalid app policy failed %d/%d denial tests",
            report.failed,
            report.total,
        )
    return AuthProvisioning(model=model, policy=policy, denial_tests=denial_tests, report=report)
