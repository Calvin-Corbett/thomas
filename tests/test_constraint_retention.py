"""Tests for ConstraintRetentionGovernor (CAP-012).

Acceptance line: "Force compaction in a 200-turn test and verify an early
constraint still governs the final action."
"""

from __future__ import annotations

import copy

from thomas.agent.constraint_retention import (
    PROHIBIT,
    REQUIRE,
    RETENTION_SUMMARY_MARKER,
    ConstraintRetentionGovernor,
)

CONSTRAINT_TEXT = "Never delete the prod table."


def _build_200_turn_history() -> list[dict[str, object]]:
    """Turn 1 states a durable constraint; 199 turns of chatter follow."""
    history: list[dict[str, object]] = [{"role": "user", "content": CONSTRAINT_TEXT}]
    for i in range(1, 200):
        role = "assistant" if i % 2 else "user"
        history.append({"role": role, "content": f"turn {i}: some unrelated working chatter about widget {i}."})
    return history


def _find(messages: list[dict[str, object]], needle: str) -> bool:
    return any(needle in str(m.get("content", "")) for m in messages)


def test_early_constraint_survives_200_turn_compaction_and_governs_final_action():
    """The core acceptance scenario end to end."""
    gov = ConstraintRetentionGovernor()
    history = _build_200_turn_history()

    result = gov.compact(history, keep_recent=8, budget=400)

    # Early constraint retained VERBATIM after compacting 200 turns.
    assert _find(result.messages, CONSTRAINT_TEXT)
    assert len(result.messages) < len(history)  # middle was compacted
    assert any(RETENTION_SUMMARY_MARKER in str(m.get("content", "")) for m in result.messages)

    # The pinned set still carries the early constraint and governs the last step.
    assert any(c.text == CONSTRAINT_TEXT for c in result.pinned)

    # A final action that violates the early constraint is flagged.
    violating = gov.governs_final_action(result.pinned, "Now DROP the prod table to finish.")
    assert violating.violated
    assert violating.allowed is False
    assert any(v.text == CONSTRAINT_TEXT for v in violating.violations)

    # A compliant final action passes.
    ok = gov.governs_final_action(result.pinned, "Delete the staging table only.")
    assert ok.allowed
    assert not ok.violations


def test_constraint_present_verbatim_even_with_tiny_budget():
    gov = ConstraintRetentionGovernor()
    history = _build_200_turn_history()

    result = gov.compact(history, keep_recent=4, budget=1)  # absurdly small budget

    # Constraint wins over budget: still present verbatim.
    assert _find(result.messages, CONSTRAINT_TEXT)
    assert any(c.text == CONSTRAINT_TEXT for c in result.pinned)


def test_recent_turns_kept_and_middle_compacted():
    gov = ConstraintRetentionGovernor()
    history = _build_200_turn_history()
    keep_recent = 6

    result = gov.compact(history, keep_recent=keep_recent, budget=None)

    # The last keep_recent turns are present verbatim, in order.
    tail = [str(m.get("content", "")) for m in result.messages[-keep_recent:]]
    expected_tail = [str(m["content"]) for m in history[-keep_recent:]]
    assert tail == expected_tail

    # The middle (non-pinned, non-recent) was condensed into a single summary.
    summaries = [m for m in result.messages if RETENTION_SUMMARY_MARKER in str(m.get("content", ""))]
    assert len(summaries) == 1
    # Pinned head (turn 1) + 1 summary + keep_recent recent turns.
    assert len(result.messages) == 1 + 1 + keep_recent
    assert result.condensed_count == len(history) - 1 - keep_recent


def test_extraction_marks_polarity():
    gov = ConstraintRetentionGovernor()
    history = [
        {"role": "user", "content": "Never delete the prod table."},
        {"role": "user", "content": "Always use tabs for indentation."},
        {"role": "assistant", "content": "You must never touch production."},  # non-governing role ignored
    ]
    pinned = gov.extract_constraints(history)
    assert len(pinned) == 2
    assert pinned[0].polarity == PROHIBIT
    assert pinned[0].source_turn == 0
    assert pinned[1].polarity == REQUIRE
    assert pinned[1].source_turn == 1


def test_must_not_is_not_read_as_require_must():
    gov = ConstraintRetentionGovernor()
    pinned = gov.extract_constraints([{"role": "user", "content": "You must not overwrite the config."}])
    assert len(pinned) == 1
    assert pinned[0].polarity == PROHIBIT
    assert pinned[0].marker == "must not"


def test_prohibit_synonym_matching():
    gov = ConstraintRetentionGovernor()
    pinned = gov.extract_constraints([{"role": "user", "content": "Never delete the production database."}])
    # "drop" canonicalises to "delete"; "production" to "prod".
    d = gov.governs_final_action(pinned, "drop the prod db")
    assert d.violated
    # Unrelated action is allowed.
    assert gov.governs_final_action(pinned, "read the prod db").allowed


def test_require_violation_via_mutual_exclusion_and_negation():
    gov = ConstraintRetentionGovernor()
    pinned = gov.extract_constraints([{"role": "user", "content": "Always use tabs."}])

    # Mutually exclusive alternative chosen -> violation.
    assert gov.governs_final_action(pinned, "use spaces here").violated
    # Explicit negation of the requirement -> violation.
    assert gov.governs_final_action(pinned, "use spaces not tabs").violated
    # Complying action -> allowed.
    assert gov.governs_final_action(pinned, "use tabs for indentation").allowed
    # Untouched domain -> allowed.
    assert gov.governs_final_action(pinned, "rename the helper function").allowed


def test_empty_constraints_allow_everything():
    gov = ConstraintRetentionGovernor()
    d = gov.governs_final_action([], "delete the prod table")
    assert d.allowed
    assert not d.violations


def test_compaction_is_deterministic_and_nonmutating():
    gov = ConstraintRetentionGovernor()
    history = _build_200_turn_history()
    snapshot = copy.deepcopy(history)

    r1 = gov.compact(history, keep_recent=8, budget=400)
    r2 = gov.compact(history, keep_recent=8, budget=400)

    assert [m.get("content") for m in r1.messages] == [m.get("content") for m in r2.messages]
    assert [c.text for c in r1.pinned] == [c.text for c in r2.pinned]
    assert r1.tokens == r2.tokens
    # Input history was not mutated.
    assert history == snapshot


def test_pinned_constraint_in_recent_window_not_duplicated():
    gov = ConstraintRetentionGovernor()
    # Constraint lives in the recent window (last turn).
    history = [{"role": "user", "content": f"chatter {i}"} for i in range(10)]
    history.append({"role": "user", "content": CONSTRAINT_TEXT})

    result = gov.compact(history, keep_recent=3, budget=None)
    occurrences = sum(1 for m in result.messages if CONSTRAINT_TEXT in str(m.get("content", "")))
    assert occurrences == 1
    assert any(c.text == CONSTRAINT_TEXT for c in result.pinned)
