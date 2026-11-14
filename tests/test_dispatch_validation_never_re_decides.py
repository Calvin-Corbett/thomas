"""Praxis validates a dispatch; it never re-decides one, and never refuses forever.

Two rules from the design (S2.2) that are easy to violate by accident:

1. The chat model owns surface, specialist, kind, deliverable_format, needs_build,
   project and acceptance, decided in ONE `send_task` call. Validation may check
   enums, reject an unknown project, and veto with a visible reason. It may not
   rewrite a choice - a specialist that looks wrong for the kind is a note, not a
   correction. Thomas has been bitten by silent reclassification before.

2. After two failed repairs the task is dispatched ANYWAY, with invalid acceptance
   items dropped and the ceiling lowered to `completed_unverified`. A validator
   able to refuse indefinitely is a way for Thomas to say "sorry, I can't", which
   Rule 0 forbids.
"""

from __future__ import annotations

from thomas.core.praxis import dispatch_validate as dv

INSTRUCTIONS = "Build a habit tracker.   The grid must show seven days, and Sunday starts the week."


def _check(text: str, cites: str) -> dict[str, str]:
    return {
        "id": "grid",
        "kind": "file_contains",
        "path": "grid.html",
        "needle": "seven days",
        "text": text,
        "cites": cites,
    }


def _payload(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "surface": "task",
        "specialist": "coding",
        "kind": "code",
        "deliverable_format": "repo_changes",
        "needs_build": True,
        "instructions": INSTRUCTIONS,
        "project": {"mode": "existing", "id": "proj-habit"},
        "acceptance": [_check("seven day grid", "The grid must show seven days")],
    }
    base.update(over)
    return base


def test_a_well_formed_dispatch_passes_cleanly() -> None:
    verdict = dv.validate_dispatch(_payload(), known_project_ids=["proj-habit"])

    assert verdict.ok
    assert verdict.may_dispatch
    assert verdict.best_end_state == dv.END_STATE_COMPLETED
    assert verdict.dropped_acceptance == ()


def test_needs_build_requires_the_task_surface() -> None:
    verdict = dv.validate_dispatch(_payload(surface="chat"), known_project_ids=["proj-habit"])

    assert dv.NEEDS_BUILD_REQUIRES_TASK_SURFACE in verdict.errors


def test_needs_build_requires_a_code_kind_or_repo_changes() -> None:
    verdict = dv.validate_dispatch(
        _payload(kind="document", deliverable_format="pdf"), known_project_ids=["proj-habit"]
    )

    assert dv.NEEDS_BUILD_KIND_MISMATCH in verdict.errors


def test_repo_changes_alone_satisfies_needs_build() -> None:
    """The spec allows EITHER a build kind OR deliverable_format=repo_changes."""
    verdict = dv.validate_dispatch(
        _payload(kind="other", deliverable_format="repo_changes"), known_project_ids=["proj-habit"]
    )

    assert dv.NEEDS_BUILD_KIND_MISMATCH not in verdict.errors


def test_an_unknown_project_is_rejected() -> None:
    verdict = dv.validate_dispatch(_payload(), known_project_ids=["proj-other"])

    assert dv.UNKNOWN_PROJECT in verdict.errors


def test_the_thomas_source_project_is_a_note_not_an_error() -> None:
    """Q2 routes this to the self-development worker. Refusing would be a can't-do."""
    verdict = dv.validate_dispatch(
        _payload(), known_project_ids=["proj-habit"], thomas_source_project_ids=["proj-habit"]
    )

    assert verdict.ok, "naming the Thomas repo is handled, not refused"
    assert dv.PROJECT_IS_THOMAS_SOURCE in verdict.notes


def test_a_specialist_that_looks_wrong_is_never_rewritten() -> None:
    """The model's choice stands. This is the reclassification rule."""
    payload = _payload(specialist="reasoning")

    verdict = dv.validate_dispatch(payload, known_project_ids=["proj-habit"])

    assert verdict.ok
    assert payload["specialist"] == "reasoning", "the payload must not be mutated"


def test_an_uncited_acceptance_item_is_caught() -> None:
    verdict = dv.validate_dispatch(
        _payload(acceptance=[{"text": "must be blue", "cites": "the grid must be blue"}]),
        known_project_ids=["proj-habit"],
    )

    assert dv.UNCITED_ACCEPTANCE in verdict.errors


def test_a_citation_is_matched_after_collapsing_whitespace_and_case() -> None:
    """A model that re-wraps a quoted line has still cited it."""
    verdict = dv.validate_dispatch(
        _payload(acceptance=[_check("seven days", "the  GRID   must\n show seven days")]),
        known_project_ids=["proj-habit"],
    )

    assert verdict.ok


def test_an_empty_citation_does_not_count_as_cited() -> None:
    """Otherwise every unsubstantiated check would pass by omitting its quote."""
    verdict = dv.validate_dispatch(
        _payload(acceptance=[{"text": "anything", "cites": ""}]), known_project_ids=["proj-habit"]
    )

    assert dv.UNCITED_ACCEPTANCE in verdict.errors


def test_two_failed_repairs_dispatch_the_task_anyway() -> None:
    """Rule 0: the validator may not become a permanent refusal."""
    bad = _payload(acceptance=[{"text": "unsupported", "cites": "nowhere in the instructions"}])

    blocked = dv.validate_dispatch(bad, known_project_ids=["proj-habit"], repair_attempts=1)
    forced = dv.validate_dispatch(bad, known_project_ids=["proj-habit"], repair_attempts=dv.MAX_REPAIRS)

    assert not blocked.may_dispatch, "the first repair attempt still asks for a fix"
    assert forced.may_dispatch
    assert forced.dispatch_anyway
    assert forced.dropped_acceptance == (0,), "the invalid item is dropped, not the task"
    assert forced.best_end_state == dv.END_STATE_UNVERIFIED
    assert forced.errors, "and the reason survives for the card to show"


def test_a_forced_dispatch_never_drops_a_non_acceptance_error() -> None:
    """Dropping a bad enum would change what actually runs."""
    bad = _payload(kind="document", deliverable_format="pdf")

    forced = dv.validate_dispatch(bad, known_project_ids=["proj-habit"], repair_attempts=dv.MAX_REPAIRS)

    assert forced.dispatch_anyway
    assert dv.NEEDS_BUILD_KIND_MISMATCH in forced.errors
    assert forced.dropped_acceptance == ()


def test_an_unknown_kind_is_an_error() -> None:
    verdict = dv.validate_dispatch(_payload(kind="sculpture"), known_project_ids=["proj-habit"])

    assert dv.UNKNOWN_KIND in verdict.errors


def test_acceptance_is_optional() -> None:
    verdict = dv.validate_dispatch(_payload(acceptance=[]), known_project_ids=["proj-habit"])

    assert verdict.ok
    assert verdict.best_end_state == dv.END_STATE_COMPLETED


def test_a_malformed_acceptance_block_does_not_raise() -> None:
    """A model can emit the wrong shape; that must not crash the dispatch path."""
    for broken in ("not a list", {"text": "a mapping"}, None, 7):
        verdict = dv.validate_dispatch(_payload(acceptance=broken), known_project_ids=["proj-habit"])

        assert verdict.ok, f"{broken!r} should be treated as no acceptance items"
