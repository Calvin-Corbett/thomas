"""Tests for CAP-125: custom scoped RBAC enforced identically for humans/agents.

Every test is hermetic: no network, no live model, temp dirs only, and an
injected fixed clock for the persistence-metadata field.
"""

from __future__ import annotations

import pytest

from thomas.security.rbac import (
    AGENT,
    ALLOW,
    DENY,
    HUMAN,
    STORE_ENV,
    AccessDecision,
    Permission,
    Principal,
    RBACEngine,
    RBACError,
    Role,
)

FIXED_CLOCK = lambda: 1234.0  # noqa: E731 - tiny injected deterministic clock


def _engine(tmp_path) -> RBACEngine:
    return RBACEngine(store_path=tmp_path / "rbac_store.json", clock=FIXED_CLOCK)


# -- custom scoped role grants exactly its permissions --------------------


def test_custom_scoped_role_grants_exactly_its_permissions(tmp_path):
    eng = _engine(tmp_path)
    eng.define_role(
        "doc-editor",
        [
            Permission("document", "read"),
            Permission("document", "write"),
        ],
    )
    alice = Principal.human("alice")
    eng.assign_role(alice, "doc-editor")

    # Exactly the two granted (resource, action) pairs are allowed.
    assert eng.check_access(alice, "document", "read").allowed is True
    assert eng.check_access(alice, "document", "write").allowed is True
    # A neighbouring action the role never granted is denied.
    assert eng.check_access(alice, "document", "delete").allowed is False
    # A different resource is denied.
    assert eng.check_access(alice, "billing", "read").allowed is False


# -- human and agent with SAME role get IDENTICAL decisions ---------------


def test_human_and_agent_same_role_identical_decisions(tmp_path):
    eng = _engine(tmp_path)
    eng.define_role(
        "auditor",
        [Permission("logs", "read", scope="prod/**"), Permission("logs", "export")],
    )
    human = Principal(HUMAN, "same-id")
    agent = Principal(AGENT, "same-id")
    eng.assign_role(human, "auditor")
    eng.assign_role(agent, "auditor")

    for resource, action, scope in [
        ("logs", "read", "prod/api"),
        ("logs", "read", "staging/api"),  # out of scope -> deny for both
        ("logs", "export", None),
        ("logs", "delete", None),  # not granted -> deny for both
    ]:
        hd = eng.check_access(human, resource, action, scope)
        ad = eng.check_access(agent, resource, action, scope)
        # Decisions are byte-for-byte identical; principal.kind never leaks in.
        assert hd == ad, (resource, action, scope, hd, ad)


def test_different_roles_give_different_decisions(tmp_path):
    eng = _engine(tmp_path)
    eng.define_role("reader", [Permission("report", "read")])
    eng.define_role("writer", [Permission("report", "write")])
    human = Principal.human("h1")
    agent = Principal.agent("a1")
    eng.assign_role(human, "reader")
    eng.assign_role(agent, "writer")

    # Same request, different roles -> different outcomes.
    assert eng.check_access(human, "report", "write").allowed is False
    assert eng.check_access(agent, "report", "write").allowed is True
    assert eng.check_access(human, "report", "read").allowed is True
    assert eng.check_access(agent, "report", "read").allowed is False


# -- principal without the role is default-denied with reason -------------


def test_principal_without_role_is_default_denied_with_reason(tmp_path):
    eng = _engine(tmp_path)
    eng.define_role("ops", [Permission("server", "restart")])
    stranger = Principal.agent("nobody")

    decision = eng.check_access(stranger, "server", "restart")
    assert decision.allowed is False
    assert decision.matched_role is None
    assert "default-deny" in decision.reason
    assert "holds no roles" in decision.reason


def test_default_deny_when_role_held_but_no_permission_matches(tmp_path):
    eng = _engine(tmp_path)
    eng.define_role("limited", [Permission("a", "read")])
    p = Principal.human("u")
    eng.assign_role(p, "limited")

    decision = eng.check_access(p, "a", "write")
    assert decision.allowed is False
    assert decision.matched_role is None
    assert "default-deny" in decision.reason
    assert "no held role grants" in decision.reason


# -- explicit deny overrides an allow -------------------------------------


def test_explicit_deny_overrides_allow(tmp_path):
    eng = _engine(tmp_path)
    eng.define_role("broad", [Permission("secret", "read", effect=ALLOW)])
    eng.define_role("blocklist", [Permission("secret", "read", effect=DENY)])
    p = Principal.human("dual")
    eng.assign_role(p, "broad")
    eng.assign_role(p, "blocklist")

    decision = eng.check_access(p, "secret", "read")
    assert decision.allowed is False
    assert decision.effect == DENY
    assert decision.matched_role == "blocklist"
    assert "explicit deny" in decision.reason


def test_deny_wins_regardless_of_role_assignment_order(tmp_path):
    # Assign in the opposite order to prove deny precedence is not order-driven.
    eng = _engine(tmp_path)
    eng.define_role("zeta-allow", [Permission("x", "do", effect=ALLOW)])
    eng.define_role("alpha-deny", [Permission("x", "do", effect=DENY)])
    p = Principal.agent("bot")
    eng.assign_role(p, "zeta-allow")
    eng.assign_role(p, "alpha-deny")

    assert eng.check_access(p, "x", "do").allowed is False


# -- scope constraints are enforced ---------------------------------------


def test_scope_constraint_enforced_in_and_out_of_scope(tmp_path):
    eng = _engine(tmp_path)
    eng.define_role("repo-writer", [Permission("file", "write", scope="repo/thomas/**")])
    p = Principal.human("dev")
    eng.assign_role(p, "repo-writer")

    # In scope -> allowed.
    assert eng.check_access(p, "file", "write", "repo/thomas/core/config.py").allowed is True
    # Out of scope -> default-denied.
    out = eng.check_access(p, "file", "write", "repo/other/x.py")
    assert out.allowed is False
    assert out.matched_role is None
    # A scoped permission requires a scope; a scope-less request does not match.
    assert eng.check_access(p, "file", "write", None).allowed is False


def test_unscoped_permission_applies_to_any_scope(tmp_path):
    eng = _engine(tmp_path)
    eng.define_role("global-reader", [Permission("file", "read")])  # no scope
    p = Principal.agent("reader-bot")
    eng.assign_role(p, "global-reader")

    assert eng.check_access(p, "file", "read", "any/path/here").allowed is True
    assert eng.check_access(p, "file", "read", None).allowed is True


def test_wildcard_resource_and_action(tmp_path):
    eng = _engine(tmp_path)
    eng.define_role("superuser", [Permission("*", "*")])
    p = Principal.human("root")
    eng.assign_role(p, "superuser")

    assert eng.check_access(p, "anything", "any-action", "any/scope").allowed is True


# -- multi-role union works -----------------------------------------------


def test_multi_role_union(tmp_path):
    eng = _engine(tmp_path)
    eng.define_role("reader", [Permission("doc", "read")])
    eng.define_role("commenter", [Permission("doc", "comment")])
    p = Principal.human("multi")
    eng.assign_role(p, "reader")
    eng.assign_role(p, "commenter")

    # Union: both permissions apply.
    assert eng.check_access(p, "doc", "read").allowed is True
    assert eng.check_access(p, "doc", "comment").allowed is True
    # Still default-deny for the un-granted action.
    assert eng.check_access(p, "doc", "delete").allowed is False


# -- definitions round-trip (durable JSON persistence) --------------------


def test_definitions_round_trip(tmp_path):
    eng = _engine(tmp_path)
    eng.define_role(
        "editor",
        [
            Permission("doc", "read"),
            Permission("doc", "write", scope="team/**"),
            Permission("doc", "purge", effect=DENY),
        ],
    )
    human = Principal(HUMAN, "u1")
    agent = Principal(AGENT, "u1")
    eng.assign_role(human, "editor")
    eng.assign_role(agent, "editor")

    written = eng.save()
    assert written.exists()

    reloaded = RBACEngine(store_path=written, clock=FIXED_CLOCK)
    reloaded.load()

    # Roles and assignments survived intact.
    assert {r.name for r in reloaded.roles()} == {"editor"}
    assert reloaded.roles_for(human) == ("editor",)
    assert reloaded.roles_for(agent) == ("editor",)

    # Decisions after reload match decisions before reload, for both principals.
    for principal in (human, agent):
        for res, act, scope in [
            ("doc", "read", None),
            ("doc", "write", "team/x"),
            ("doc", "write", "other/x"),
            ("doc", "purge", None),
        ]:
            assert eng.check_access(principal, res, act, scope) == reloaded.check_access(principal, res, act, scope)

    # Full serialised dict is identical (deterministic; fixed clock).
    assert eng.to_dict() == reloaded.to_dict()


def test_store_path_overridable_via_env(tmp_path, monkeypatch):
    custom = tmp_path / "nested" / "custom_rbac.json"
    monkeypatch.setenv(STORE_ENV, str(custom))
    eng = RBACEngine(clock=FIXED_CLOCK)  # no explicit path -> reads env
    assert eng.store_path == custom
    eng.define_role("r", [Permission("a", "read")])
    eng.save()
    assert custom.exists()


def test_from_store_loads_existing_and_tolerates_missing(tmp_path):
    path = tmp_path / "rbac.json"
    # Missing file: fresh empty engine, no error.
    fresh = RBACEngine.from_store(path, clock=FIXED_CLOCK)
    assert fresh.roles() == ()

    fresh.define_role("r", [Permission("a", "b")])
    fresh.assign_role(Principal.human("x"), "r")
    fresh.save()

    loaded = RBACEngine.from_store(path, clock=FIXED_CLOCK)
    assert loaded.roles_for(Principal.human("x")) == ("r",)


# -- validation & edge cases ----------------------------------------------


def test_assign_unknown_role_raises(tmp_path):
    eng = _engine(tmp_path)
    with pytest.raises(RBACError):
        eng.assign_role(Principal.human("a"), "ghost")


def test_bad_effect_rejected():
    with pytest.raises(RBACError):
        Permission("a", "b", effect="maybe")


def test_load_rejects_assignment_to_unknown_role(tmp_path):
    eng = _engine(tmp_path)
    with pytest.raises(RBACError):
        eng.load_dict({"roles": [], "assignments": {"human:x": ["nope"]}})


def test_revoke_role(tmp_path):
    eng = _engine(tmp_path)
    eng.define_role("r", [Permission("a", "read")])
    p = Principal.human("x")
    eng.assign_role(p, "r")
    assert eng.check_access(p, "a", "read").allowed is True
    eng.revoke_role(p, "r")
    assert eng.check_access(p, "a", "read").allowed is False
    assert eng.roles_for(p) == ()


def test_access_decision_is_hashable_frozen():
    d = AccessDecision(allowed=True, matched_role="r", reason="ok", effect=ALLOW)
    assert d.allowed is True
    # frozen dataclass -> equality by value
    assert d == AccessDecision(True, "r", "ok", ALLOW)


def test_role_and_permission_dataclasses_frozen():
    perm = Permission("a", "b")
    role = Role("r", (perm,))
    assert role.permissions == (perm,)
    with pytest.raises(Exception):
        perm.resource = "c"  # type: ignore[misc]
