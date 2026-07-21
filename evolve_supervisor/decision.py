"""Blue-only promotion decision matrix for Thomas evolve sessions.

The green mirror can rewrite ``thomas/forge/anvil``. Keep the pure posture and
promotion decision logic in this supervisor-owned package so the loop can ask
blue-owned code whether a finished session may promote.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .independent_verifier import CLAIM_REJECTED, IndependentVerdict

LOOP_PACKAGE_PREFIX = "thomas/forge/anvil/"
SUPERVISOR_PACKAGE_PREFIX = "evolve_supervisor/"
SUPERVISOR_OWNED_PATHS = frozenset(
    {
        "thomas/forge/anvil/doppelganger.py",
        "thomas/forge/anvil/evolve.py",
        "thomas/forge/anvil/evolve_autonomy.py",
        "thomas/forge/anvil/evolve_loop.py",
    }
)


class EvolvePosture(str, Enum):
    PROPOSE = "propose"
    AUTO_SAFE = "auto_safe"
    AUTONOMOUS = "autonomous"


DEFAULT_POSTURE = EvolvePosture.AUTO_SAFE

POSTURE_LABELS: dict[str, str] = {
    EvolvePosture.PROPOSE.value: "Ask first -- talks and proposes, but changes nothing until you say go",
    EvolvePosture.AUTO_SAFE.value: "Auto-safe -- makes the safe changes itself, asks before risky ones",
    EvolvePosture.AUTONOMOUS.value: "Full autonomy -- keeps working on its own until done or the limit you set",
}

ACTION_PROMOTE = "promote"
ACTION_APPROVE = "approve"
ACTION_REJECT = "reject"


def parse_posture(value: str | EvolvePosture | None) -> EvolvePosture:
    """Coerce a string/enum into a posture, defaulting to auto_safe."""
    if isinstance(value, EvolvePosture):
        return value
    key = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "propose": EvolvePosture.PROPOSE,
        "propose_only": EvolvePosture.PROPOSE,
        "ask_first": EvolvePosture.PROPOSE,
        "manual": EvolvePosture.PROPOSE,
        "review": EvolvePosture.PROPOSE,
        "auto_safe": EvolvePosture.AUTO_SAFE,
        "safe": EvolvePosture.AUTO_SAFE,
        "balanced": EvolvePosture.AUTO_SAFE,
        "auto": EvolvePosture.AUTO_SAFE,
        "autonomous": EvolvePosture.AUTONOMOUS,
        "full_autonomy": EvolvePosture.AUTONOMOUS,
        "full": EvolvePosture.AUTONOMOUS,
        "full_send": EvolvePosture.AUTONOMOUS,
        "yolo": EvolvePosture.AUTONOMOUS,
    }
    return aliases.get(key, DEFAULT_POSTURE)


@dataclass(frozen=True)
class PromotionDecision:
    action: str
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
    verification_ran: bool = True
    session_rejected: bool = False
    verification_floor_failed: bool = False
    risk_floor: str = ""
    human_hold_required: bool = False
    human_hold_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "verification_ok": self.verification_ok,
            "changed_count": self.changed_count,
            "policy_violation": self.policy_violation,
            "agent_failed": self.agent_failed,
            "verification_ran": self.verification_ran,
            "session_rejected": self.session_rejected,
            "verification_floor_failed": self.verification_floor_failed,
            "risk_floor": self.risk_floor,
            "human_hold_required": self.human_hold_required,
            "human_hold_reason": self.human_hold_reason,
        }


def summarize_session_outcome(session: dict[str, Any]) -> SessionOutcome:
    """Reduce a ``run_evolve_session`` session dict to decision inputs."""
    session = dict(session or {})
    delta = dict(session.get("delta") or {})
    changed_count = int(delta.get("changed_count") or len(session.get("changed_files") or []))
    policy_violation = bool(session.get("policy_violations"))
    session_rejected = bool(session.get("session_rejections")) or _supervisor_verdict_rejected(session)
    verification = session.get("verification") or []
    verification_ran = bool(verification)
    verification_floor_failed = bool(session.get("verification_floor_failures"))
    verification_ok = all(_verification_item_ok(item) for item in verification) and not verification_floor_failed
    agent_failed = str(session.get("status") or "") == "agent_failed"
    human_hold_reason = risk_floor_human_hold_reason(session)
    return SessionOutcome(
        verification_ok=verification_ok,
        changed_count=changed_count,
        policy_violation=policy_violation,
        agent_failed=agent_failed,
        verification_ran=verification_ran,
        session_rejected=session_rejected,
        verification_floor_failed=verification_floor_failed,
        risk_floor=session_risk_floor(session),
        human_hold_required=bool(human_hold_reason),
        human_hold_reason=human_hold_reason,
    )


def _verification_item_ok(item: dict[str, Any]) -> bool:
    if int(item.get("returncode") or 0) == 0:
        return True
    return str(item.get("source") or "") == "charter" and int(item.get("baseline_returncode") or 0) != 0


def _normalize_relpath(value: Any) -> str:
    return str(value or "").replace("\\", "/").lstrip("./")


def _changed_files_from_session(session: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    delta = session.get("delta")
    if isinstance(delta, dict):
        changed.extend(str(item) for item in (delta.get("changed_files") or []))
    changed.extend(str(item) for item in (session.get("changed_files") or []))
    verdict = session.get("supervisor_verdict")
    if isinstance(verdict, dict):
        verdict_delta = verdict.get("delta")
        if isinstance(verdict_delta, dict):
            changed.extend(str(item) for item in (verdict_delta.get("changed_files") or []))
    return sorted({_normalize_relpath(item) for item in changed if _normalize_relpath(item)})


def _non_python_changed_files(session: dict[str, Any]) -> list[str]:
    return [rel for rel in _changed_files_from_session(session) if not rel.endswith(".py")]


def _supervisor_risk_floor(session: dict[str, Any]) -> str:
    verdict = session.get("supervisor_verdict")
    if not isinstance(verdict, dict):
        return ""
    return str(verdict.get("risk_floor") or "").strip().lower()


def _supervisor_verdict_rejected(session: dict[str, Any]) -> bool:
    verdict = session.get("supervisor_verdict")
    return isinstance(verdict, dict) and verdict.get("ok") is False


def session_risk_floor(session: dict[str, Any]) -> str:
    """Return the strongest blue-derived floor visible on the session."""
    session = dict(session or {})
    explicit = str(session.get("risk_floor") or "").strip().lower()
    supervisor_floor = _supervisor_risk_floor(session)
    if explicit == "critical" or supervisor_floor == "critical":
        return "critical"
    if str(session.get("category") or "").strip().lower() == "meta":
        return "critical"
    for rel in _changed_files_from_session(session):
        if rel in SUPERVISOR_OWNED_PATHS:
            return "critical"
        if rel.startswith(LOOP_PACKAGE_PREFIX) or rel.startswith(SUPERVISOR_PACKAGE_PREFIX):
            return "critical"
    if _non_python_changed_files(session):
        return "critical"
    return explicit or supervisor_floor


def risk_floor_human_hold_reason(session: dict[str, Any]) -> str:
    """Explain why a session is forced into human approval, if applicable."""
    session = dict(session or {})
    if str(session.get("category") or "").strip().lower() == "meta":
        return "meta candidate risk floor requires human approval"
    supervisor_floor = _supervisor_risk_floor(session)
    if supervisor_floor == "critical":
        return "blue supervisor risk floor critical: awaiting human approval"
    explicit = str(session.get("risk_floor") or "").strip().lower()
    if explicit == "critical":
        return "critical risk floor requires human approval"
    for rel in _changed_files_from_session(session):
        if rel in SUPERVISOR_OWNED_PATHS:
            return f"supervisor-owned evolve file requires human approval: {rel}"
        if rel.startswith(SUPERVISOR_PACKAGE_PREFIX):
            return f"blue supervisor package change requires human approval: {rel}"
        if rel.startswith(LOOP_PACKAGE_PREFIX):
            return f"evolve-loop file change requires human approval: {rel}"
    non_python = _non_python_changed_files(session)
    if non_python:
        preview = ", ".join(non_python[:8])
        return f"non-Python delta requires human approval pending verification coverage: {preview}"
    return ""


def auto_promotable(posture: str | EvolvePosture, risk_tier: str) -> bool:
    """Would a clean, verified change at this risk tier promote automatically?"""
    p = parse_posture(posture)
    tier = str(risk_tier or "medium").lower()
    if p is EvolvePosture.AUTONOMOUS:
        return True
    if p is EvolvePosture.AUTO_SAFE:
        return tier in ("low", "medium")
    return False


def decide_promotion(
    *,
    posture: str | EvolvePosture,
    risk_tier: str,
    verification_ok: bool,
    changed_count: int,
    policy_violation: bool,
    agent_failed: bool = False,
    verification_ran: bool = True,
    session_rejected: bool = False,
    verification_floor_failed: bool = False,
    human_hold_required: bool = False,
    human_hold_reason: str = "",
) -> PromotionDecision:
    """Decide what to do with a finished session."""
    p = parse_posture(posture)
    tier = str(risk_tier or "medium").lower()

    if agent_failed:
        return PromotionDecision(ACTION_REJECT, "agent pass failed", p.value, tier)
    if int(changed_count) <= 0:
        return PromotionDecision(ACTION_REJECT, "no changes produced", p.value, tier)
    if policy_violation:
        return PromotionDecision(ACTION_REJECT, "protected path tamper detected", p.value, tier)
    if session_rejected:
        return PromotionDecision(ACTION_REJECT, "session rejected by supervisor policy", p.value, tier)

    if not verification_ran:
        return PromotionDecision(
            ACTION_APPROVE,
            "no verification ran -- held for your approval (cannot confirm safe)",
            p.value,
            tier,
        )
    if not verification_ok:
        reason = "verification floor failed" if verification_floor_failed else "verification failed"
        return PromotionDecision(ACTION_REJECT, reason, p.value, tier)

    if human_hold_required:
        reason = human_hold_reason or "critical risk floor requires human approval"
        return PromotionDecision(ACTION_APPROVE, reason, p.value, tier)

    if p is EvolvePosture.PROPOSE:
        return PromotionDecision(ACTION_APPROVE, "propose mode: awaiting your approval", p.value, tier)
    if p is EvolvePosture.AUTONOMOUS:
        return PromotionDecision(ACTION_PROMOTE, "autonomous mode: verified, promoting", p.value, tier)
    if tier in ("low", "medium"):
        return PromotionDecision(ACTION_PROMOTE, f"auto-safe: {tier}-risk verified, promoting", p.value, tier)
    return PromotionDecision(ACTION_APPROVE, f"auto-safe: {tier}-risk held for approval", p.value, tier)


def decide_for_session(
    posture: str | EvolvePosture,
    session: dict[str, Any],
    risk_tier: str,
    *,
    independent_verifier: Callable[[dict[str, Any]], IndependentVerdict | None] | None = None,
) -> PromotionDecision:
    """Summarize a session and decide in one call.

    When ``independent_verifier`` is supplied (see
    ``independent_verifier.build_session_verifier``), any completion claim that
    carries runnable evidence is rerun in a fresh subprocess, and a rejected
    rerun OVERRIDES an approving in-path review: the session is rejected with
    the diverging evidence in the reason.  An ``unverifiable`` verdict never
    upgrades or downgrades the in-path decision -- it simply is not treated as
    independent confirmation (evidence-free sessions are already held by the
    ``verification_ran`` gate in :func:`decide_promotion`).
    """
    outcome = summarize_session_outcome(session)
    effective_risk_tier = outcome.risk_floor or risk_tier
    decision = decide_promotion(
        posture=posture,
        risk_tier=effective_risk_tier,
        verification_ok=outcome.verification_ok,
        verification_ran=outcome.verification_ran,
        changed_count=outcome.changed_count,
        policy_violation=outcome.policy_violation,
        agent_failed=outcome.agent_failed,
        session_rejected=outcome.session_rejected,
        verification_floor_failed=outcome.verification_floor_failed,
        human_hold_required=outcome.human_hold_required,
        human_hold_reason=outcome.human_hold_reason,
    )
    if independent_verifier is None or decision.action == ACTION_REJECT:
        return decision
    verdict = independent_verifier(dict(session or {}))
    if verdict is not None and verdict.status == CLAIM_REJECTED:
        return PromotionDecision(
            ACTION_REJECT,
            f"independent verifier rejected completion claim: {verdict.summary()}",
            decision.posture,
            decision.risk_tier,
        )
    return decision
