"""A render-only check must never present itself to the user as a bare "Verified".

Measured (gauntlet g-fieldgoal, live): the chat deliverable card read
"Done / Verified retro-field-goal.html" while the delivered game was
mathematically unwinnable. What actually ran was existence/render verification
(`chat_delegation_artifact_verification.py` opens with `del prompt` — it never
reads the ask), yet every user-facing word said "Verified", which a person reads
as "it works".

The Code side already fixed this exact wording pattern ("Passed 2 automatic
checks · your specific ask was not separately verified"). This pins the chat
side to the same rule: the label scopes its claim to what ran, and no input can
produce an unscoped "Verified" for a render-only check. The CHECKS themselves
are untouched — only the words change.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_SCOPE_PHRASE = "not checked against your ask"


def _without_comments(source: str) -> str:
    """Strip full-line comments so prose documenting OLD wording cannot match."""

    return "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )


def test_the_scope_label_scopes_a_render_only_verification() -> None:
    from thomas.server.chat_delegation_artifact_verification import verification_scope_label

    label = verification_scope_label(
        "verified",
        artifact_names=["retro-field-goal.html"],
        summary="Created retro-field-goal.html.",
    )
    assert label, "a verified render-only proof must still get a label"
    assert _SCOPE_PHRASE in label, (
        "the label must say the ask itself was not checked — existence/render "
        "verification never reads the request"
    )
    assert label.strip().lower() not in {"verified", "verified result", "done"}, (
        "a bare status word is exactly the wording that shipped an unwinnable game "
        "as 'Verified'"
    )


def test_a_bare_unscoped_verified_cannot_be_produced() -> None:
    from thomas.server.chat_delegation_artifact_verification import verification_scope_label

    cases = [
        {"proof_status": "verified", "artifact_names": ["retro-field-goal.html"], "summary": ""},
        {"proof_status": "verified", "artifact_names": ["report.pdf"], "summary": ""},
        {"proof_status": "attached", "artifact_names": ["a.html", "b.js"], "summary": "Created files."},
        {
            "proof_status": "verified",
            "artifact_names": ["x.html"],
            "summary": "Created x.html. ⚠ The app did not run cleanly when opened — boom.",
        },
        {
            "proof_status": "verified",
            "artifact_names": ["x.html"],
            "summary": "",
            "runtime_profile": {"requested_profile": "max"},
        },
        {"proof_status": "verified", "artifact_names": [], "summary": ""},
    ]
    for case in cases:
        label = verification_scope_label(
            case["proof_status"],
            artifact_names=case.get("artifact_names"),
            summary=case.get("summary", ""),
            runtime_profile=case.get("runtime_profile"),
        )
        assert label, f"no label for {case!r}"
        assert not re.fullmatch(r"\s*verified\W*\s*", label, re.I), (
            f"bare 'Verified' produced for {case!r}"
        )
        # Every label must carry an explicit scope clause: either the render-only
        # honesty phrase, or (Max runs) naming the review that actually graded it.
        assert _SCOPE_PHRASE in label or "review" in label.lower(), (
            f"label {label!r} claims verification without saying what ran ({case!r})"
        )


def test_an_unverified_proof_gets_no_label() -> None:
    from thomas.server.chat_delegation_artifact_verification import verification_scope_label

    for status in ("missing", "", "pending", "failed"):
        assert verification_scope_label(status, artifact_names=["a.html"]) == ""


def test_a_flagged_run_does_not_claim_it_renders() -> None:
    from thomas.server.chat_delegation_artifact_verification import verification_scope_label

    label = verification_scope_label(
        "verified",
        artifact_names=["app.html"],
        summary="Created app.html. ⚠ The app did not run cleanly when opened — ref error.",
    )
    assert "renders" not in label.lower(), (
        "a run whose own summary says the app did not open cleanly must not be "
        "labelled as rendering"
    )
    assert "concern" in label.lower() or "flag" in label.lower(), (
        "the label must point at the warning instead of hiding it"
    )


def test_the_deliverable_card_payload_carries_the_scoped_label() -> None:
    from thomas.server.chat_delegation_session import _normalize_record

    verified_row = {
        "execution_id": "exec-test-scope-label",
        "state": "completed",
        "proof_status": "verified",
        "proof": {"status": "verified", "artifacts": [{"path": "retro-field-goal.html"}]},
        "summary": "Created retro-field-goal.html.",
    }
    normalized = _normalize_record(verified_row)
    label = str(normalized.get("verification_label") or "")
    assert label, "the card payload must carry a server-authored scoped label"
    assert _SCOPE_PHRASE in label

    failed_row = dict(verified_row, state="failed")
    assert str(_normalize_record(failed_row).get("verification_label") or "") == "", (
        "a failed run must not carry a success label"
    )

    unproven_row = dict(verified_row, proof_status="missing", proof={})
    assert str(_normalize_record(unproven_row).get("verification_label") or "") == ""


def test_the_announcement_fallback_scopes_its_claim() -> None:
    source = (
        ROOT / "thomas" / "server" / "routes" / "chat_v2_announcements.py"
    ).read_text(encoding="utf-8")
    body = _without_comments(
        source.split("note = await _generate_note", 1)[1].split("strip_sandbox_links", 1)[0]
    )
    assert "I have a verified result ready" not in body, (
        "the fallback template is back to claiming a verified result for a "
        "render-only check"
    )
    assert "separately check" in body, (
        "the fallback must say the result was not separately checked against the ask"
    )


def test_the_announcement_prompt_does_not_coach_the_model_to_say_verified() -> None:
    source = (
        ROOT / "thomas" / "server" / "routes" / "chat_v2_announcements.py"
    ).read_text(encoding="utf-8")
    stripped = _without_comments(source)
    assert "complete verified artifact list" not in stripped, (
        "the LLM prompt still describes render-only artifacts as 'verified', "
        "coaching the announcement to overclaim"
    )
    assert "automatic" in stripped.lower(), (
        "the prompt must tell the model what the checks actually were (automatic "
        "file checks), so its sentence matches what ran"
    )


def test_the_task_event_stream_scopes_the_verified_state() -> None:
    from thomas.server.routes.task_events import _runtime_status_message

    message = _runtime_status_message(
        {"state": "verified", "task_id": "t1", "summary": "build a field goal game"}
    )
    assert not re.match(r"^\s*task\s+verified\b", message, re.I), (
        "the event feed still says a bare 'Task verified', which a user reads as "
        "'it works' when only file checks ran"
    )
    assert "check" in message.lower(), "the event message must name what actually passed"
