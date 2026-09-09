"""Verifier-panel roles for Thomas evolve supervision."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .decision import summarize_session_outcome
from .supervisor import SupervisorVerdict

PANEL_PASS = "pass"
PANEL_HOLD = "hold"
PANEL_REJECT = "reject"


@dataclass(frozen=True)
class VerifierVote:
    role: str
    status: str
    reason: str
    severity: str = "advisory"

    @property
    def passed(self) -> bool:
        return self.status == PANEL_PASS

    @property
    def critical_dissent(self) -> bool:
        return self.status == PANEL_REJECT and self.severity == "critical"

    def to_dict(self) -> dict[str, str]:
        return {
            "role": self.role,
            "status": self.status,
            "reason": self.reason,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class VerifierPanelResult:
    ok: bool
    quorum: int
    pass_count: int
    critical_dissent_count: int
    votes: tuple[VerifierVote, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": bool(self.ok),
            "quorum": int(self.quorum),
            "pass_count": int(self.pass_count),
            "critical_dissent_count": int(self.critical_dissent_count),
            "votes": [vote.to_dict() for vote in self.votes],
        }


def _vote(role: str, status: str, reason: str, *, severity: str = "advisory") -> VerifierVote:
    return VerifierVote(role=role, status=status, reason=reason, severity=severity)


def _verification_rows(session: dict[str, Any]) -> list[dict[str, Any]]:
    rows = session.get("verification") or []
    return [dict(item) for item in rows if isinstance(item, dict)]


SupervisorVerdictLike = SupervisorVerdict | dict[str, Any]


def _verdict_ok(supervisor_verdict: SupervisorVerdictLike | None) -> bool | None:
    if supervisor_verdict is None:
        return None
    if isinstance(supervisor_verdict, dict):
        return bool(supervisor_verdict.get("ok"))
    return bool(supervisor_verdict.ok)


def _finding_codes(supervisor_verdict: SupervisorVerdictLike | None) -> set[str]:
    if supervisor_verdict is None:
        return set()
    findings = (
        supervisor_verdict.get("findings") if isinstance(supervisor_verdict, dict) else supervisor_verdict.findings
    )
    codes: set[str] = set()
    for finding in findings or ():
        if isinstance(finding, dict):
            code = str(finding.get("code") or "").strip()
        else:
            code = str(getattr(finding, "code", "") or "").strip()
        if code:
            codes.add(code)
    return codes


def _correctness_vote(session: dict[str, Any]) -> VerifierVote:
    outcome = summarize_session_outcome(session)
    if outcome.agent_failed:
        return _vote("correctness", PANEL_REJECT, "agent pass failed", severity="critical")
    if outcome.changed_count <= 0:
        return _vote("correctness", PANEL_REJECT, "no candidate changes", severity="critical")
    if not outcome.verification_ran:
        return _vote("correctness", PANEL_HOLD, "no verification evidence")
    if not outcome.verification_ok:
        return _vote("correctness", PANEL_REJECT, "verification failed", severity="critical")
    return _vote("correctness", PANEL_PASS, "candidate has verified changes")


def _regression_vote(session: dict[str, Any]) -> VerifierVote:
    outcome = summarize_session_outcome(session)
    if outcome.verification_floor_failed:
        return _vote("regression", PANEL_REJECT, "verification floor failed", severity="critical")
    if not outcome.verification_ran:
        return _vote("regression", PANEL_HOLD, "regression checks did not run")
    if not outcome.verification_ok:
        return _vote("regression", PANEL_REJECT, "regression verification failed", severity="critical")
    return _vote("regression", PANEL_PASS, "regression checks passed")


def _security_vote(session: dict[str, Any], supervisor_verdict: SupervisorVerdictLike | None) -> VerifierVote:
    if session.get("policy_violations"):
        return _vote("security", PANEL_REJECT, "policy violations present", severity="critical")
    if session.get("session_rejections"):
        return _vote("security", PANEL_REJECT, "session rejected by supervisor policy", severity="critical")
    verdict_ok = _verdict_ok(supervisor_verdict)
    if verdict_ok is False:
        return _vote("security", PANEL_REJECT, "supervisor rejected candidate", severity="critical")
    if verdict_ok is None:
        return _vote("security", PANEL_HOLD, "no supervisor verdict supplied")
    return _vote("security", PANEL_PASS, "supervisor found no security blockers")


def _reward_hack_vote(session: dict[str, Any], supervisor_verdict: SupervisorVerdictLike | None) -> VerifierVote:
    codes = _finding_codes(supervisor_verdict)
    if {"test_infra_changed", "protected_path_changed", "corpus_hash_mismatch"} & codes:
        return _vote("reward_hack", PANEL_REJECT, "candidate appears to alter the exam or policy", severity="critical")
    if session.get("session_rejections"):
        return _vote(
            "reward_hack", PANEL_REJECT, "session-level rejection indicates reward-hack risk", severity="critical"
        )
    if not _verification_rows(session):
        return _vote("reward_hack", PANEL_HOLD, "no independent verification to inspect")
    return _vote("reward_hack", PANEL_PASS, "no exam-suppression signal found")


def _reproducibility_vote(session: dict[str, Any]) -> VerifierVote:
    rows = _verification_rows(session)
    if not rows:
        return _vote("reproducibility", PANEL_HOLD, "no verification transcript")
    for item in rows:
        if "returncode" not in item:
            return _vote("reproducibility", PANEL_REJECT, "verification row missing returncode", severity="critical")
        if bool(item.get("timed_out")):
            return _vote("reproducibility", PANEL_REJECT, "verification timed out", severity="critical")
    return _vote("reproducibility", PANEL_PASS, "verification transcript is replayable enough")


def run_verifier_panel(
    session: dict[str, Any],
    *,
    supervisor_verdict: SupervisorVerdictLike | None = None,
    quorum: int = 4,
) -> VerifierPanelResult:
    """Run deterministic verifier roles over a session and optional supervisor verdict."""
    session_dict = dict(session or {})
    votes = (
        _correctness_vote(session_dict),
        _regression_vote(session_dict),
        _security_vote(session_dict, supervisor_verdict),
        _reward_hack_vote(session_dict, supervisor_verdict),
        _reproducibility_vote(session_dict),
    )
    pass_count = sum(1 for vote in votes if vote.passed)
    critical_dissent_count = sum(1 for vote in votes if vote.critical_dissent)
    return VerifierPanelResult(
        ok=critical_dissent_count == 0 and pass_count >= int(quorum),
        quorum=int(quorum),
        pass_count=pass_count,
        critical_dissent_count=critical_dissent_count,
        votes=votes,
    )
