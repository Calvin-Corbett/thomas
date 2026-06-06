"""Evolve autonomy posture -- the leash on a self-modifying Thomas.

All evolve work happens in the green mirror regardless of posture.  The posture
decides only one thing: what gets *promoted* to live Thomas without a human tap.

    propose      every change waits for explicit human approval (safest)
    auto_safe    low/medium-risk changes that fully verify promote on their own;
                 high-risk changes (security/hardening, anything the planner
                 tagged 'high') wait for approval (the recommended default)
    autonomous   anything that verifies promotes; only hard failures stop it

The decision is a pure function of the finished session + the goal's risk tier,
so it is trivially unit tested and cannot be fooled by a posture string alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class EvolvePosture(str, Enum):
    PROPOSE = "propose"
    AUTO_SAFE = "auto_safe"
    AUTONOMOUS = "autonomous"


DEFAULT_POSTURE = EvolvePosture.AUTO_SAFE

# Human-facing one-liners for the dashboard/chat.
POSTURE_LABELS: dict[str, str] = {
    EvolvePosture.PROPOSE.value: "Propose only -- you approve every change",
    EvolvePosture.AUTO_SAFE.value: "Auto-promote safe, hold risky for you",
    EvolvePosture.AUTONOMOUS.value: "Fully autonomous -- promote anything that verifies",
}

# Actions a promotion decision can take.
ACTION_PROMOTE = "promote"
ACTION_APPROVE = "approve"  # hold in the pending-approval queue for a human
ACTION_REJECT = "reject"  # do not promote; record and move on


def parse_posture(value: str | EvolvePosture | None) -> EvolvePosture:
    """Coerce a string/enum into a posture, defaulting to auto_safe."""
    if isinstance(value, EvolvePosture):
        return value
    key = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "propose": EvolvePosture.PROPOSE,
        "propose_only": EvolvePosture.PROPOSE,
        "manual": EvolvePosture.PROPOSE,
        "review": EvolvePosture.PROPOSE,
        "auto_safe": EvolvePosture.AUTO_SAFE,
        "safe": EvolvePosture.AUTO_SAFE,
        "balanced": EvolvePosture.AUTO_SAFE,
        "auto": EvolvePosture.AUTO_SAFE,
        "autonomous": EvolvePosture.AUTONOMOUS,
        "full": EvolvePosture.AUTONOMOUS,
        "full_send": EvolvePosture.AUTONOMOUS,
        "yolo": EvolvePosture.AUTONOMOUS,
    }
    return aliases.get(key, DEFAULT_POSTURE)


@dataclass(frozen=True)
class PromotionDecision:
    action: str  # ACTION_PROMOTE | ACTION_APPROVE | ACTION_REJECT
    reason: str
    posture: str
    risk_tier: str

    @property
    def promote(self) -> bool:
        return self.action == ACTION_PROMOTE

    @property
    def needs_approval(self) -> bool:
        return self.action == ACTION_APPROVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "posture": self.posture,
            "risk_tier": self.risk_tier,
        }


@dataclass(frozen=True)
class SessionOutcome:
    """The few facts about a finished evolve session the gate cares about."""

    verification_ok: bool
    changed_count: int
    policy_violation: bool
    agent_failed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "verification_ok": self.verification_ok,
            "changed_count": self.changed_count,
            "policy_violation": self.policy_violation,
            "agent_failed": self.agent_failed,
        }


def summarize_session_outcome(session: dict[str, Any]) -> SessionOutcome:
    """Reduce a `run_evolve_session` session dict to the gate's inputs."""
    session = dict(session or {})
    delta = dict(session.get("delta") or {})
    changed_count = int(delta.get("changed_count") or len(session.get("changed_files") or []))
    policy_violation = bool(session.get("policy_violations"))
    verification = session.get("verification") or []
    verification_ok = all(int(item.get("returncode") or 0) == 0 for item in verification)
    agent_failed = str(session.get("status") or "") == "agent_failed"
    return SessionOutcome(
        verification_ok=verification_ok,
        changed_count=changed_count,
        policy_violation=policy_violation,
        agent_failed=agent_failed,
    )


def auto_promotable(posture: str | EvolvePosture, risk_tier: str) -> bool:
    """Would a *clean, verified* change at this risk tier promote automatically?

    Used by the planner/UI to preview what the loop will do before it runs.
    """
    p = parse_posture(posture)
    tier = str(risk_tier or "medium").lower()
    if p is EvolvePosture.AUTONOMOUS:
        return True
    if p is EvolvePosture.AUTO_SAFE:
        return tier in ("low", "medium")
    return False  # PROPOSE


def decide_promotion(
    *,
    posture: str | EvolvePosture,
    risk_tier: str,
    verification_ok: bool,
    changed_count: int,
    policy_violation: bool,
    agent_failed: bool = False,
) -> PromotionDecision:
    """Decide what to do with a finished session. Pure and deterministic.

    Hard stops first (these reject regardless of posture), then the posture/risk
    matrix decides promote-vs-hold for clean, verified changes.
    """
    p = parse_posture(posture)
    tier = str(risk_tier or "medium").lower()

    # ---- hard stops: never promote a broken or out-of-bounds change ----
    if agent_failed:
        return PromotionDecision(ACTION_REJECT, "agent pass failed", p.value, tier)
    if int(changed_count) <= 0:
        return PromotionDecision(ACTION_REJECT, "no changes produced", p.value, tier)
    if not verification_ok:
        return PromotionDecision(ACTION_REJECT, "verification failed", p.value, tier)

    # A policy violation means the agent touched a protected guardrail file -- but
    # that edit was already reverted out of the mirror, so the guardrail is
    # unchanged. Promote the remaining clean changes and note the revert; don't
    # throw away the good work just because the agent also reached too far.
    note = " (guardrail edits reverted)" if policy_violation else ""

    # ---- clean, verified, non-empty change: posture/risk matrix ----
    if p is EvolvePosture.PROPOSE:
        return PromotionDecision(ACTION_APPROVE, "propose mode: awaiting your approval" + note, p.value, tier)

    if p is EvolvePosture.AUTONOMOUS:
        return PromotionDecision(ACTION_PROMOTE, "autonomous mode: verified, promoting" + note, p.value, tier)

    # AUTO_SAFE
    if tier in ("low", "medium"):
        return PromotionDecision(ACTION_PROMOTE, f"auto-safe: {tier}-risk verified, promoting" + note, p.value, tier)
    return PromotionDecision(ACTION_APPROVE, f"auto-safe: {tier}-risk held for approval" + note, p.value, tier)


def decide_for_session(
    posture: str | EvolvePosture,
    session: dict[str, Any],
    risk_tier: str,
) -> PromotionDecision:
    """Convenience wrapper: summarize a session and decide in one call."""
    outcome = summarize_session_outcome(session)
    return decide_promotion(
        posture=posture,
        risk_tier=risk_tier,
        verification_ok=outcome.verification_ok,
        changed_count=outcome.changed_count,
        policy_violation=outcome.policy_violation,
        agent_failed=outcome.agent_failed,
    )
