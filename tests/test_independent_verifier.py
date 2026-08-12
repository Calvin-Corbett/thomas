"""CAP-047: independent condition verifier for evolve completion claims.

Acceptance line: use a separate verifier process that RERUNS commands and
rejects false completion claims.  Everything here is hermetic: tiny generated
files in tmp_path, fresh subprocesses via the real venv python, no live model.
"""

from __future__ import annotations

import shlex
import sys
from typing import Any

from evolve_supervisor import (
    ACTION_PROMOTE,
    ACTION_REJECT,
    CLAIM_REJECTED,
    CLAIM_VERIFIED,
    UNVERIFIABLE,
    ClaimedCheck,
    CompletionClaim,
    build_session_verifier,
    claim_from_session,
    decide_for_session,
    verify_claim,
)
from evolve_supervisor.independent_verifier import (
    EVIDENCE_DIVERGED,
    EVIDENCE_MATCHED,
    EVIDENCE_REFUSED,
    EVIDENCE_SKIPPED,
    allowlist_refusal_reason,
)


def _display(argv: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in argv)


def _py_compile_check(filename: str, expected: int = 0) -> ClaimedCheck:
    return ClaimedCheck(
        command=[sys.executable, "-m", "py_compile", filename],
        expected_returncode=expected,
    )


def _session(tmp_path, command: str | list[str], returncode: int = 0) -> dict[str, Any]:
    return {
        "session_id": "cap047-session",
        "status": "ready",
        "delta": {"changed_count": 1, "changed_files": ["some_module.py"]},
        "policy_violations": [],
        "session_rejections": [],
        "verification": [{"command": command, "returncode": returncode, "source": "generated"}],
        "verification_root": str(tmp_path),
    }


class TestRerunVerdicts:
    def test_true_claim_whose_command_passes_is_verified(self, tmp_path):
        (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
        claim = CompletionClaim(cwd=str(tmp_path), checks=(_py_compile_check("ok.py"),))
        verdict = verify_claim(claim, timeout_seconds=120)
        assert verdict.status == CLAIM_VERIFIED
        assert verdict.verified is True
        assert verdict.evidence[0].status == EVIDENCE_MATCHED
        assert verdict.evidence[0].actual_returncode == 0

    def test_false_claim_is_rejected_with_diverging_evidence(self, tmp_path):
        (tmp_path / "bad.py").write_text("def broken(:\n", encoding="utf-8")
        # The claim asserts py_compile exited 0; the independent rerun disproves it.
        claim = CompletionClaim(cwd=str(tmp_path), checks=(_py_compile_check("bad.py"),))
        verdict = verify_claim(claim, timeout_seconds=120)
        assert verdict.status == CLAIM_REJECTED
        assert verdict.rejected is True
        evidence = verdict.evidence[0]
        assert evidence.status == EVIDENCE_DIVERGED
        assert evidence.expected_returncode == 0
        assert evidence.actual_returncode not in (None, 0)
        assert "SyntaxError" in evidence.stderr_snippet
        assert "expected exit 0" in verdict.reason
        assert "expected exit 0" in verdict.summary()

    def test_display_string_transcript_command_is_rerun(self, tmp_path):
        # Real evolve transcripts store shlex-quoted display strings, not lists.
        (tmp_path / "ok.py").write_text("y = 2\n", encoding="utf-8")
        command = _display([sys.executable, "-m", "py_compile", "ok.py"])
        claim = CompletionClaim(cwd=str(tmp_path), checks=(ClaimedCheck(command=command),))
        verdict = verify_claim(claim, timeout_seconds=120)
        assert verdict.status == CLAIM_VERIFIED

    def test_claim_with_no_runnable_evidence_is_unverifiable(self, tmp_path):
        empty = verify_claim(CompletionClaim(cwd=str(tmp_path), checks=()))
        assert empty.status == UNVERIFIABLE
        assert empty.verified is False

        only_refused = verify_claim(
            CompletionClaim(
                cwd=str(tmp_path),
                checks=(ClaimedCheck(command=[sys.executable, "-c", "print('claimed proof')"]),),
            )
        )
        assert only_refused.status == UNVERIFIABLE
        assert only_refused.evidence[0].status == EVIDENCE_REFUSED

    def test_nonzero_claimed_exit_codes_are_skipped_not_rerun(self, tmp_path):
        claim = CompletionClaim(cwd=str(tmp_path), checks=(_py_compile_check("missing.py", expected=2),))
        verdict = verify_claim(claim, timeout_seconds=120)
        assert verdict.status == UNVERIFIABLE
        assert verdict.evidence[0].status == EVIDENCE_SKIPPED


class TestAllowlist:
    def test_allowlist_refuses_mutating_commands(self, tmp_path):
        victim = tmp_path / "precious.txt"
        victim.write_text("do not delete\n", encoding="utf-8")
        mutating: list[str | list[str]] = [
            ["cmd", "/c", "del", "precious.txt"],
            "rm -rf .",
            ["git", "push", "origin", "main"],
            ["pip", "install", "anything"],
            [sys.executable, "-c", "open('precious.txt', 'w').close()"],
            [sys.executable, "-m", "pip", "install", "anything"],
            "pytest; del precious.txt",
        ]
        claim = CompletionClaim(cwd=str(tmp_path), checks=tuple(ClaimedCheck(command=cmd) for cmd in mutating))
        verdict = verify_claim(claim, timeout_seconds=120)
        assert verdict.status == UNVERIFIABLE
        assert all(item.status == EVIDENCE_REFUSED for item in verdict.evidence)
        assert all(item.refusal_reason for item in verdict.evidence)
        assert victim.read_text(encoding="utf-8") == "do not delete\n"

    def test_allowlist_accepts_read_only_test_class_commands(self):
        allowed = [
            [sys.executable, "-m", "pytest", "tests/test_x.py", "-q"],
            [sys.executable, "-m", "py_compile", "a.py"],
            [sys.executable, "-m", "ruff", "check", "a.py"],
            ["pytest", "-q"],
            ["git", "status"],
            ["git", "diff", "--stat"],
        ]
        for argv in allowed:
            assert allowlist_refusal_reason(argv) == "", argv

    def test_missing_cwd_refuses_rerun(self, tmp_path):
        claim = CompletionClaim(cwd=str(tmp_path / "nope"), checks=(_py_compile_check("ok.py"),))
        verdict = verify_claim(claim, timeout_seconds=120)
        assert verdict.status == UNVERIFIABLE
        assert verdict.evidence[0].status == EVIDENCE_REFUSED
        assert "cwd" in verdict.evidence[0].refusal_reason


class TestModelReviewHook:
    def test_separate_model_can_reject_non_runnable_claims(self, tmp_path):
        calls: list[CompletionClaim] = []

        def adapter(claim: CompletionClaim) -> dict[str, Any]:
            calls.append(claim)
            return {"status": CLAIM_REJECTED, "reason": "narrative does not match diff"}

        claim = CompletionClaim(cwd=str(tmp_path), checks=())
        verdict = verify_claim(claim, model_review=adapter)
        assert verdict.status == CLAIM_REJECTED
        assert verdict.model_reviewed is True
        assert "narrative does not match diff" in verdict.reason
        assert len(calls) == 1

    def test_separate_model_can_accept_non_runnable_claims(self, tmp_path):
        def adapter(_claim: CompletionClaim) -> dict[str, Any]:
            return {"status": CLAIM_VERIFIED, "reason": "manually cross-checked"}

        verdict = verify_claim(CompletionClaim(cwd=str(tmp_path), checks=()), model_review=adapter)
        assert verdict.status == CLAIM_VERIFIED
        assert verdict.model_reviewed is True

    def test_model_hook_not_consulted_when_runnable_evidence_exists(self, tmp_path):
        calls: list[CompletionClaim] = []

        def adapter(claim: CompletionClaim) -> dict[str, Any]:
            calls.append(claim)
            return {"status": CLAIM_VERIFIED, "reason": "should not be needed"}

        (tmp_path / "ok.py").write_text("z = 3\n", encoding="utf-8")
        claim = CompletionClaim(cwd=str(tmp_path), checks=(_py_compile_check("ok.py"),))
        verdict = verify_claim(claim, timeout_seconds=120, model_review=adapter)
        assert verdict.status == CLAIM_VERIFIED
        assert verdict.model_reviewed is False
        assert calls == []


class TestDecisionPathOverride:
    def test_rejected_rerun_overrides_approving_in_path_review(self, tmp_path):
        (tmp_path / "bad.py").write_text("def broken(:\n", encoding="utf-8")
        command = _display([sys.executable, "-m", "py_compile", "bad.py"])
        session = _session(tmp_path, command, returncode=0)

        # In-path review believes the transcript and promotes.
        trusting = decide_for_session("autonomous", session, "low")
        assert trusting.action == ACTION_PROMOTE

        # The independent rerun disproves the claim and overrides the approval.
        decision = decide_for_session(
            "autonomous",
            session,
            "low",
            independent_verifier=build_session_verifier(timeout_seconds=120),
        )
        assert decision.action == ACTION_REJECT
        assert decision.reason.startswith("independent verifier rejected completion claim")
        assert "expected exit 0" in decision.reason

    def test_verified_rerun_keeps_promotion(self, tmp_path):
        (tmp_path / "ok.py").write_text("w = 4\n", encoding="utf-8")
        command = _display([sys.executable, "-m", "py_compile", "ok.py"])
        session = _session(tmp_path, command, returncode=0)
        decision = decide_for_session(
            "autonomous",
            session,
            "low",
            independent_verifier=build_session_verifier(timeout_seconds=120),
        )
        assert decision.action == ACTION_PROMOTE

    def test_unverifiable_claim_leaves_in_path_decision_unchanged(self, tmp_path):
        session = _session(tmp_path, "pytest -q", returncode=0)
        session.pop("verification_root")  # no rerun cwd -> nothing rerunnable
        baseline = decide_for_session("autonomous", session, "low")
        decision = decide_for_session(
            "autonomous",
            session,
            "low",
            independent_verifier=build_session_verifier(timeout_seconds=120),
        )
        assert decision.action == baseline.action
        assert decision.reason == baseline.reason

    def test_claim_from_session_maps_transcript_and_root(self, tmp_path):
        session = _session(tmp_path, "pytest -q", returncode=0)
        session["verification"].append({"source": "generated", "returncode": 0})  # no command -> dropped
        claim = claim_from_session(session)
        assert claim.cwd == str(tmp_path)
        assert len(claim.checks) == 1
        assert claim.checks[0].command == "pytest -q"
        assert claim.checks[0].expected_returncode == 0
