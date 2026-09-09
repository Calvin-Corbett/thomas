"""Tests for the evolve autonomy gate -- the leash on a self-modifying Thomas."""

from __future__ import annotations

from thomas.forge.anvil.evolve_autonomy import (
    ACTION_APPROVE,
    ACTION_PROMOTE,
    ACTION_REJECT,
    EvolvePosture,
    auto_promotable,
    decide_for_session,
    decide_promotion,
    parse_posture,
    summarize_session_outcome,
)


def _clean(**over):
    base = dict(verification_ok=True, changed_count=3, policy_violation=False, agent_failed=False)
    base.update(over)
    return base


def test_parse_posture_aliases_and_default():
    assert parse_posture("propose") is EvolvePosture.PROPOSE
    assert parse_posture("manual") is EvolvePosture.PROPOSE
    assert parse_posture("auto-safe") is EvolvePosture.AUTO_SAFE
    assert parse_posture("balanced") is EvolvePosture.AUTO_SAFE
    assert parse_posture("autonomous") is EvolvePosture.AUTONOMOUS
    assert parse_posture("yolo") is EvolvePosture.AUTONOMOUS
    assert parse_posture("") is EvolvePosture.AUTO_SAFE  # default
    assert parse_posture("nonsense") is EvolvePosture.AUTO_SAFE


def test_hard_stops_reject_regardless_of_posture():
    for posture in ("propose", "auto_safe", "autonomous"):
        # agent crashed
        assert decide_promotion(posture=posture, risk_tier="low", **_clean(agent_failed=True)).action == ACTION_REJECT
        # produced nothing
        assert decide_promotion(posture=posture, risk_tier="low", **_clean(changed_count=0)).action == ACTION_REJECT
        # failed verification
        assert (
            decide_promotion(posture=posture, risk_tier="low", **_clean(verification_ok=False)).action == ACTION_REJECT
        )


def test_policy_violation_rejects_whole_session():
    d = decide_promotion(posture="auto_safe", risk_tier="low", **_clean(policy_violation=True))
    assert d.action == ACTION_REJECT
    assert "protected path tamper" in d.reason

    held = decide_promotion(posture="auto_safe", risk_tier="high", **_clean(policy_violation=True))
    assert held.action == ACTION_REJECT


def test_propose_always_holds_clean_changes():
    for tier in ("low", "medium", "high"):
        d = decide_promotion(posture="propose", risk_tier=tier, **_clean())
        assert d.action == ACTION_APPROVE
        assert d.needs_approval


def test_autonomous_promotes_any_verified_change():
    for tier in ("low", "medium", "high"):
        d = decide_promotion(posture="autonomous", risk_tier=tier, **_clean())
        assert d.action == ACTION_PROMOTE
        assert d.promote


def test_auto_safe_promotes_low_medium_holds_high():
    assert decide_promotion(posture="auto_safe", risk_tier="low", **_clean()).action == ACTION_PROMOTE
    assert decide_promotion(posture="auto_safe", risk_tier="medium", **_clean()).action == ACTION_PROMOTE
    assert decide_promotion(posture="auto_safe", risk_tier="high", **_clean()).action == ACTION_APPROVE


def test_auto_promotable_preview_matrix():
    assert auto_promotable("autonomous", "high") is True
    assert auto_promotable("auto_safe", "low") is True
    assert auto_promotable("auto_safe", "medium") is True
    assert auto_promotable("auto_safe", "high") is False
    assert auto_promotable("propose", "low") is False


def test_summarize_session_outcome_reads_engine_session():
    session = {
        "status": "ready",
        "delta": {"changed_count": 4, "changed_files": ["a.py", "b.py"]},
        "policy_violations": [],
        "verification": [{"command": "pytest", "returncode": 0}],
    }
    outcome = summarize_session_outcome(session)
    assert outcome.verification_ok is True
    assert outcome.verification_ran is True
    assert outcome.changed_count == 4
    assert outcome.policy_violation is False
    assert outcome.agent_failed is False
    assert outcome.session_rejected is False
    assert outcome.verification_floor_failed is False


def test_missing_verification_holds_for_approval_instead_of_promoting():
    session = {
        "status": "ready",
        "delta": {"changed_count": 1, "changed_files": ["thomas/server/web/js/runtime/example.js"]},
        "policy_violations": [],
        "verification": [],
    }
    outcome = summarize_session_outcome(session)
    assert outcome.verification_ok is True
    assert outcome.verification_ran is False

    for posture in ("auto_safe", "autonomous"):
        decision = decide_for_session(posture, session, "low")
        assert decision.action == ACTION_APPROVE
        assert "no verification ran" in decision.reason


def test_summarize_flags_failed_verification_and_policy_violation():
    session = {
        "status": "verification_failed",
        "delta": {"changed_count": 2},
        "policy_violations": ["agent_safety.toml"],
        "verification": [{"command": "pytest", "returncode": 1}],
    }
    outcome = summarize_session_outcome(session)
    assert outcome.verification_ok is False
    assert outcome.verification_ran is True
    assert outcome.policy_violation is True


def test_summarize_flags_session_rejection_and_verification_floor_failure():
    session = {
        "status": "verification_failed",
        "delta": {"changed_count": 1},
        "policy_violations": [],
        "session_rejections": ["test infrastructure changed: tests/conftest.py"],
        "verification_floor_failures": ["no blast-radius tests selected for changed Python files: thomas/core/x.py"],
        "verification": [{"command": "python -m py_compile thomas/core/x.py", "returncode": 0}],
    }
    outcome = summarize_session_outcome(session)
    assert outcome.verification_ran is True
    assert outcome.verification_ok is False
    assert outcome.session_rejected is True
    assert outcome.verification_floor_failed is True

    rejected = decide_for_session("autonomous", session, "low")
    assert rejected.action == ACTION_REJECT
    assert "session rejected" in rejected.reason

    floor_only = dict(session)
    floor_only["session_rejections"] = []
    floor_rejected = decide_for_session("autonomous", floor_only, "low")
    assert floor_rejected.action == ACTION_REJECT
    assert "verification floor" in floor_rejected.reason


def test_decide_promotion_unverified_flag_holds_before_autopromote():
    held = decide_promotion(posture="autonomous", risk_tier="low", **_clean(verification_ran=False))
    assert held.action == ACTION_APPROVE
    assert "no verification ran" in held.reason

    failed = decide_promotion(posture="autonomous", risk_tier="low", **_clean(verification_ok=False))
    assert failed.action == ACTION_REJECT


def test_decide_for_session_end_to_end():
    promotable_low_risk = {
        "status": "ready",
        "delta": {"changed_count": 2},
        "policy_violations": [],
        "verification": [{"command": "pytest", "returncode": 0}],
    }
    assert decide_for_session("auto_safe", promotable_low_risk, "low").action == ACTION_PROMOTE
    assert decide_for_session("auto_safe", promotable_low_risk, "high").action == ACTION_APPROVE
    assert decide_for_session("propose", promotable_low_risk, "low").action == ACTION_APPROVE
