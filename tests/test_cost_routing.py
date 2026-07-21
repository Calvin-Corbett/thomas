"""Tests for the auditable cost-tiered internal router (CAP-094).

Proves the exact acceptance line: an auditable classifier routes low-risk
summaries and status work to a cheap profile, while risky/complex work does
not fall into the cheap tier, and every decision is auditable and serializable.
"""

from __future__ import annotations

import json

import pytest

from thomas.core.cost_routing import (
    DEFAULT_PROFILE_MAP,
    CostTier,
    CostTierRouter,
    RiskLevel,
    RoutingDecision,
    WorkItem,
)


def test_status_summary_routes_to_cheap_with_named_rule():
    router = CostTierRouter()
    work = WorkItem(kind="status_summary", summary="Summarize today's status update for the dashboard")

    decision = router.classify(work)

    assert decision.tier is CostTier.CHEAP
    assert decision.profile_id == DEFAULT_PROFILE_MAP[CostTier.CHEAP]
    # The audit record names the deciding rule and cites the signal.
    assert decision.rule == "low_risk_summary"
    assert decision.signal  # non-empty citation
    assert decision.signal == "kind:status_summary"
    # And it is recorded in the audit trail.
    assert router.audit_trail == (decision,)


def test_free_text_summary_keyword_routes_cheap():
    router = CostTierRouter()
    work = WorkItem(summary="Please summarize the latest changes in one paragraph")

    decision = router.classify(work)

    assert decision.tier is CostTier.CHEAP
    assert decision.rule == "low_risk_summary"
    assert decision.signal.startswith("keyword:")


def test_code_modification_routes_standard_not_cheap():
    router = CostTierRouter()
    work = WorkItem(kind="code_edit", summary="Refactor the auth handler", modifies_code=True)

    decision = router.classify(work)

    assert decision.tier is not CostTier.CHEAP
    assert decision.tier is CostTier.STANDARD
    assert decision.profile_id == DEFAULT_PROFILE_MAP[CostTier.STANDARD]
    assert decision.rule == "code_change_flag"
    assert decision.signal == "flag:modifies_code=True"
    assert decision.risk is RiskLevel.ELEVATED


def test_destructive_action_routes_premium_not_cheap():
    router = CostTierRouter()
    work = WorkItem(summary="Delete the production database and drop table users", destructive=True)

    decision = router.classify(work)

    assert decision.tier is CostTier.PREMIUM
    assert decision.tier is not CostTier.CHEAP
    assert decision.risk is RiskLevel.HIGH
    assert decision.rule == "destructive_flag"


def test_destructive_keyword_beats_summary_wording():
    # A work item that reads like a summary but also proposes a destructive
    # action must NOT be routed cheap: risk-first ordering wins.
    router = CostTierRouter()
    work = WorkItem(summary="Summarize the plan, then rm -rf the build dir")

    decision = router.classify(work)

    assert decision.tier is CostTier.PREMIUM
    assert decision.rule == "destructive_signal"
    assert "rm -rf" in decision.signal


def test_long_reasoning_is_not_cheap():
    router = CostTierRouter()
    work = WorkItem(summary="Deep architectural analysis", est_reasoning_tokens=8000)

    decision = router.classify(work)

    assert decision.tier is CostTier.STANDARD
    assert decision.rule == "long_reasoning"
    assert "est_reasoning_tokens" in decision.signal


def test_ambiguous_item_falls_back_to_documented_default_not_cheap():
    router = CostTierRouter()
    work = WorkItem(summary="Handle the widget for the thing")  # no classifying signal

    decision = router.classify(work)

    assert decision.tier is CostTier.STANDARD
    assert decision.tier is not CostTier.CHEAP
    assert decision.rule == "ambiguous_default"
    assert decision.risk is RiskLevel.UNKNOWN
    assert decision.signal == "no_signal_matched"
    assert "default" in decision.rationale.lower()


def test_every_decision_audit_record_present_serializable_and_cites_signal():
    router = CostTierRouter()
    items = [
        WorkItem(kind="status_summary", summary="daily status"),
        WorkItem(summary="Refactor module", modifies_code=True),
        WorkItem(summary="delete everything", destructive=True),
        WorkItem(summary="totally ambiguous request"),
    ]
    for item in items:
        router.classify(item)

    log = router.audit_log()
    assert len(log) == len(items)

    # Serializable end to end.
    encoded = json.dumps(log)
    assert encoded

    for i, record in enumerate(log):
        assert record["sequence"] == i
        # Every decision cites the deciding signal and names its rule.
        assert record["signal"], f"record {i} missing signal citation"
        assert record["rule"], f"record {i} missing rule"
        assert record["rationale"]
        assert record["tier"] in {t.value for t in CostTier}
        assert record["risk"] in {r.value for r in RiskLevel}


def test_routing_decision_to_dict_is_json_serializable():
    router = CostTierRouter()
    decision = router.classify(WorkItem(kind="status", summary="status"))
    d = decision.to_dict()
    assert json.loads(json.dumps(d)) == d
    assert set(d) >= {"tier", "profile_id", "rule", "risk", "signal", "rationale"}


def test_configurable_profile_mapping_is_honored():
    custom = {
        CostTier.CHEAP: "haiku-nano",
        CostTier.STANDARD: "sonnet-4",
        CostTier.PREMIUM: "opus-4",
    }
    router = CostTierRouter(profile_map=custom)

    cheap = router.classify(WorkItem(kind="status_summary", summary="status"))
    standard = router.classify(WorkItem(summary="implement feature", modifies_code=True))

    assert cheap.profile_id == "haiku-nano"
    assert standard.profile_id == "sonnet-4"
    assert router.profile_for(CostTier.PREMIUM) == "opus-4"


def test_partial_profile_override_falls_back_to_defaults():
    router = CostTierRouter(profile_map={CostTier.CHEAP: "my-cheap"})
    assert router.profile_for(CostTier.CHEAP) == "my-cheap"
    # Un-overridden tiers keep safe defaults.
    assert router.profile_for(CostTier.STANDARD) == DEFAULT_PROFILE_MAP[CostTier.STANDARD]
    assert router.profile_for(CostTier.PREMIUM) == DEFAULT_PROFILE_MAP[CostTier.PREMIUM]


def test_determinism_same_input_same_decision():
    work = WorkItem(kind="status_summary", summary="Summarize the release status")
    r1 = CostTierRouter()
    r2 = CostTierRouter()

    d1 = r1.preview(work)
    d2 = r2.preview(work)

    assert d1 == d2
    assert d1.to_dict() == d2.to_dict()

    # Repeated classification of equal items yields equal decisions.
    many = [r1.preview(work) for _ in range(5)]
    assert all(d == d1 for d in many)


def test_preview_does_not_record_but_classify_does():
    router = CostTierRouter()
    router.preview(WorkItem(kind="status", summary="s"))
    assert router.audit_trail == ()

    router.classify(WorkItem(kind="status", summary="s"))
    assert len(router.audit_trail) == 1


def test_route_returns_profile_id_and_records():
    router = CostTierRouter()
    profile = router.route(WorkItem(kind="status_summary", summary="status"))
    assert profile == DEFAULT_PROFILE_MAP[CostTier.CHEAP]
    assert len(router.audit_trail) == 1


def test_injected_clock_stamps_audit_without_affecting_decision():
    ticks = iter([10.0, 20.0, 30.0])
    router = CostTierRouter(clock=lambda: next(ticks))
    d = router.classify(WorkItem(kind="status", summary="s"))

    # Decision itself carries no timestamp (stays deterministic).
    assert "decided_at" not in d.to_dict()
    # Audit entry does.
    log = router.audit_log()
    assert log[0]["decided_at"] == 10.0


def test_clear_audit():
    router = CostTierRouter()
    router.classify(WorkItem(kind="status", summary="s"))
    assert router.audit_trail
    router.clear_audit()
    assert router.audit_trail == ()


def test_returned_decision_is_immutable():
    router = CostTierRouter()
    decision = router.classify(WorkItem(kind="status", summary="s"))
    with pytest.raises((AttributeError, TypeError)):
        decision.tier = CostTier.PREMIUM  # type: ignore[misc]


def test_classification_and_extraction_categories_route_cheap():
    router = CostTierRouter()
    for kind in ("classification", "formatting", "extraction"):
        decision = router.preview(WorkItem(kind=kind, summary=f"{kind} task"))
        assert decision.tier is CostTier.CHEAP, kind
        assert isinstance(decision, RoutingDecision)
