"""CAP-130 acceptance tests: deny-by-default egress policy + audited decisions.

Hermetic: no network, no sockets. A fixed injected clock makes every decision
deterministic, and the audit log is written to a pytest ``tmp_path``.
"""

from __future__ import annotations

import pytest

from thomas.tools.egress_policy import (
    DECISION_ALLOW,
    DECISION_DENY,
    EgressPolicyEngine,
    EgressRule,
    InvalidConnectionError,
    InvalidRuleError,
)


def _fixed_clock(value: float = 1_700_000_000.0):
    return lambda: value


def _engine(rules, tmp_path, name="audit.log"):
    return EgressPolicyEngine(
        rules,
        audit_log_path=tmp_path / name,
        clock=_fixed_clock(),
    )


# --------------------------------------------------------------------------- #
# (1) Deny-by-default: anything not explicitly allowlisted is denied.
# --------------------------------------------------------------------------- #
def test_unallowlisted_egress_is_denied_by_default(tmp_path):
    engine = _engine([], tmp_path)
    decision = engine.decide("evil.example.net", "203.0.113.7", 443)
    assert decision.decision == DECISION_DENY
    assert decision.allowed is False
    assert decision.matched_rule is None
    assert "deny-by-default" in decision.reason


def test_partial_allowlist_still_denies_others(tmp_path):
    rules = [EgressRule.allow("api", host="api.example.com", ports=443)]
    engine = _engine(rules, tmp_path)
    assert engine.decide("api.example.com", "10.0.0.1", 443).allowed is True
    # A different host is not on the allowlist -> denied.
    assert engine.decide("other.example.com", "10.0.0.1", 443).allowed is False


# --------------------------------------------------------------------------- #
# (2) Exact host + port allow permits.
# --------------------------------------------------------------------------- #
def test_exact_host_and_port_allows(tmp_path):
    rules = [EgressRule.allow("exact", host="api.example.com", ports=443)]
    engine = _engine(rules, tmp_path)
    decision = engine.decide("api.example.com", "198.51.100.5", 443)
    assert decision.decision == DECISION_ALLOW
    assert decision.matched_rule == "exact"


# --------------------------------------------------------------------------- #
# (3) Wildcard subdomain matches a subdomain but NOT the apex.
# --------------------------------------------------------------------------- #
def test_wildcard_matches_subdomain(tmp_path):
    rules = [EgressRule.allow("wild", host="*.example.com", ports=443)]
    engine = _engine(rules, tmp_path)
    assert engine.decide("cdn.example.com", "198.51.100.9", 443).allowed is True
    # Multi-label subdomains also match.
    assert engine.decide("a.b.example.com", "198.51.100.9", 443).allowed is True


def test_wildcard_does_not_match_apex(tmp_path):
    rules = [EgressRule.allow("wild", host="*.example.com", ports=443)]
    engine = _engine(rules, tmp_path)
    decision = engine.decide("example.com", "198.51.100.9", 443)
    assert decision.allowed is False
    assert decision.matched_rule is None


def test_wildcard_does_not_match_unrelated_suffix(tmp_path):
    rules = [EgressRule.allow("wild", host="*.example.com", ports=443)]
    engine = _engine(rules, tmp_path)
    # "notexample.com" must not sneak past the "." boundary check.
    assert engine.decide("evilexample.com", "198.51.100.9", 443).allowed is False


# --------------------------------------------------------------------------- #
# (4) CIDR rule matches in-range IP, rejects out-of-range.
# --------------------------------------------------------------------------- #
def test_cidr_matches_in_range_ip(tmp_path):
    rules = [EgressRule.allow("internal", cidr="10.0.0.0/8")]
    engine = _engine(rules, tmp_path)
    decision = engine.decide("db.internal", "10.4.5.6", 5432)
    assert decision.allowed is True
    assert decision.matched_rule == "internal"


def test_cidr_rejects_out_of_range_ip(tmp_path):
    rules = [EgressRule.allow("internal", cidr="10.0.0.0/8")]
    engine = _engine(rules, tmp_path)
    decision = engine.decide("db.external", "192.168.1.1", 5432)
    assert decision.allowed is False
    assert decision.matched_rule is None


def test_cidr_does_not_match_when_ip_unresolved(tmp_path):
    rules = [EgressRule.allow("internal", cidr="10.0.0.0/8")]
    engine = _engine(rules, tmp_path)
    # No ip resolved -> a cidr-only rule cannot match.
    assert engine.decide("db.internal", None, 5432).allowed is False


# --------------------------------------------------------------------------- #
# (5) A port outside an allowed range is denied even for an allowed host.
# --------------------------------------------------------------------------- #
def test_port_outside_range_denied_for_allowed_host(tmp_path):
    rules = [EgressRule.allow("web", host="api.example.com", ports=(8000, 8100))]
    engine = _engine(rules, tmp_path)
    assert engine.decide("api.example.com", "10.0.0.1", 8050).allowed is True
    # In-range boundary is inclusive.
    assert engine.decide("api.example.com", "10.0.0.1", 8100).allowed is True
    # Out of range on an otherwise-allowed host -> denied.
    denied = engine.decide("api.example.com", "10.0.0.1", 9000)
    assert denied.allowed is False
    assert denied.matched_rule is None


# --------------------------------------------------------------------------- #
# (6) Every decision is written to the audit log with the matched rule.
# --------------------------------------------------------------------------- #
def test_every_decision_is_audited_with_matched_rule(tmp_path):
    rules = [EgressRule.allow("api", host="api.example.com", ports=443)]
    engine = _engine(rules, tmp_path)
    engine.decide("api.example.com", "10.0.0.1", 443)  # allow
    engine.decide("evil.example.net", "203.0.113.7", 443)  # deny

    records = engine.read_audit_log()
    assert len(records) == 2

    allow_rec, deny_rec = records
    assert allow_rec["decision"] == DECISION_ALLOW
    assert allow_rec["matched_rule"] == "api"
    assert allow_rec["host"] == "api.example.com"
    assert allow_rec["port"] == 443

    assert deny_rec["decision"] == DECISION_DENY
    assert deny_rec["matched_rule"] is None
    assert deny_rec["host"] == "evil.example.net"


def test_audit_log_is_append_only_across_instances(tmp_path):
    path = tmp_path / "shared.log"
    rules = [EgressRule.allow("api", host="api.example.com", ports=443)]
    first = EgressPolicyEngine(rules, audit_log_path=path, clock=_fixed_clock())
    first.decide("api.example.com", "10.0.0.1", 443)
    # A brand-new engine appends rather than truncating the durable log.
    second = EgressPolicyEngine(rules, audit_log_path=path, clock=_fixed_clock())
    second.decide("evil.example.net", "203.0.113.7", 443)
    assert len(second.read_audit_log()) == 2


def test_audit_log_path_from_env(monkeypatch, tmp_path):
    log = tmp_path / "env_audit.log"
    monkeypatch.setenv("THOMAS_EGRESS_AUDIT_LOG", str(log))
    engine = EgressPolicyEngine([], clock=_fixed_clock())
    assert engine.audit_log_path == log
    engine.decide("x.example.net", "203.0.113.1", 80)
    assert len(engine.read_audit_log()) == 1


# --------------------------------------------------------------------------- #
# (7) Determinism: identical inputs => byte-identical decisions and audit lines.
# --------------------------------------------------------------------------- #
def test_determinism_of_decisions_and_audit(tmp_path):
    rules = [EgressRule.allow("api", host="api.example.com", ports=443)]
    a = _engine(rules, tmp_path, name="a.log")
    b = _engine(rules, tmp_path, name="b.log")

    da = a.decide("api.example.com", "10.0.0.1", 443)
    db = b.decide("api.example.com", "10.0.0.1", 443)
    assert da == db
    assert da.to_audit_record() == db.to_audit_record()
    # Same for a deny path.
    na = a.decide("evil.example.net", "203.0.113.7", 443)
    nb = b.decide("evil.example.net", "203.0.113.7", 443)
    assert na == nb

    assert a.read_audit_log() == b.read_audit_log()


# --------------------------------------------------------------------------- #
# Ordered evaluation + validation regressions.
# --------------------------------------------------------------------------- #
def test_first_matching_rule_wins(tmp_path):
    rules = [
        EgressRule.allow("wide", host="*.example.com", ports=(1, 65535)),
        EgressRule.allow("narrow", host="api.example.com", ports=443),
    ]
    engine = _engine(rules, tmp_path)
    decision = engine.decide("api.example.com", "10.0.0.1", 443)
    assert decision.matched_rule == "wide"  # first in order wins


def test_combined_host_cidr_port_rule(tmp_path):
    rules = [EgressRule.allow("tight", host="*.internal", cidr="10.0.0.0/8", ports="5432-5433")]
    engine = _engine(rules, tmp_path)
    assert engine.decide("db.internal", "10.1.2.3", 5432).allowed is True
    # Right host+port but ip outside the cidr -> denied.
    assert engine.decide("db.internal", "192.168.0.1", 5432).allowed is False


def test_rule_requires_host_or_cidr():
    with pytest.raises(InvalidRuleError):
        EgressRule.allow("bad", ports=443)


def test_rule_rejects_invalid_cidr():
    with pytest.raises(InvalidRuleError):
        EgressRule.allow("bad", cidr="not-a-cidr")


def test_rule_rejects_invalid_port():
    with pytest.raises(InvalidRuleError):
        EgressRule.allow("bad", host="a.example.com", ports=70000)


def test_decide_rejects_invalid_ip(tmp_path):
    engine = _engine([], tmp_path)
    with pytest.raises(InvalidConnectionError):
        engine.decide("a.example.com", "999.1.1.1", 443)


def test_decide_rejects_invalid_port(tmp_path):
    engine = _engine([], tmp_path)
    with pytest.raises(InvalidConnectionError):
        engine.decide("a.example.com", "10.0.0.1", 70000)


def test_ipv6_cidr_matching(tmp_path):
    rules = [EgressRule.allow("v6", cidr="2001:db8::/32")]
    engine = _engine(rules, tmp_path)
    assert engine.decide("v6.example.com", "2001:db8::1", 443).allowed is True
    assert engine.decide("v6.example.com", "2001:dead::1", 443).allowed is False
    # v4 ip must not match a v6 network.
    assert engine.decide("v6.example.com", "10.0.0.1", 443).allowed is False
