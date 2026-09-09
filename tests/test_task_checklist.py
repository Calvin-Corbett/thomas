"""Tests for the per-task-type completion checklist contract (review/explain).

The load-bearing property: an evidence_read item is satisfied ONLY by a real
observed source read, NEVER by words in the reply.
"""

from __future__ import annotations

import pytest

from thomas.core import task_checklist as tc


def test_task_type_coerce_is_fail_closed():
    assert tc.TaskType.coerce("review_explain") == tc.TaskType.REVIEW_EXPLAIN
    assert tc.TaskType.coerce("code-change") == tc.TaskType.CODE_CHANGE
    assert tc.TaskType.coerce("research") == tc.TaskType.RESEARCH
    # unknown / blank -> strictest type (review_explain), never a weaker one
    assert tc.TaskType.coerce("") == tc.TaskType.REVIEW_EXPLAIN
    assert tc.TaskType.coerce("nonsense") == tc.TaskType.REVIEW_EXPLAIN


def test_review_explain_has_read_and_cite_items_others_passthrough():
    items = tc.build_checklist("review_explain")
    kinds = {i.kind for i in items}
    assert kinds == {tc.KIND_EVIDENCE_READ, tc.KIND_CITATION}
    # types without a shipped playbook attach an empty (pass-through) checklist
    assert tc.build_checklist("code_change") == []
    assert tc.build_checklist("plan") == []


def test_evidence_read_satisfied_only_by_a_real_source_read():
    items = tc.build_checklist("review_explain")
    # Output that CLAIMS verification but with NO read evidence must NOT satisfy.
    claims = "I reviewed the code and verified it thoroughly. thomas/core/x.py:5"
    evaluated = tc.evaluate_checklist(items, read_paths=[], output_text=claims)
    read_item = next(i for i in evaluated if i.kind == tc.KIND_EVIDENCE_READ)
    assert read_item.satisfied is False  # words are not proof
    # A real read of a source file satisfies it.
    evaluated = tc.evaluate_checklist(items, read_paths=["thomas/core/dispatch.py"], output_text=claims)
    read_item = next(i for i in evaluated if i.kind == tc.KIND_EVIDENCE_READ)
    assert read_item.satisfied is True


def test_non_source_read_does_not_satisfy_evidence():
    items = tc.build_checklist("review_explain")
    evaluated = tc.evaluate_checklist(items, read_paths=["assets/logo.png", "data/blob.bin"], output_text="x.py:1")
    read_item = next(i for i in evaluated if i.kind == tc.KIND_EVIDENCE_READ)
    assert read_item.satisfied is False


def test_citation_requires_file_line_in_output():
    items = tc.build_checklist("review_explain")
    assert tc.has_file_line_citation("see thomas/agent/dispatch.py:139 for the cascade") is True
    assert tc.has_file_line_citation("it works by classifying messages") is False
    # citation item tracks the OUTPUT, not the reads
    ev = tc.evaluate_checklist(items, read_paths=["a.py"], output_text="no citation here")
    cite = next(i for i in ev if i.kind == tc.KIND_CITATION)
    assert cite.satisfied is False


def test_review_explain_fully_satisfied_blocks_until_both_hold():
    items = tc.build_checklist("review_explain")
    # read but no citation -> not satisfied
    ev = tc.evaluate_checklist(items, read_paths=["thomas/core/config.py"], output_text="it loads config")
    assert tc.checklist_satisfied(ev) is False
    assert {i.item_id for i in tc.unmet_items(ev)} == {"cite_file_line"}
    # read AND cite -> satisfied
    ev = tc.evaluate_checklist(
        items,
        read_paths=["thomas/core/config.py"],
        output_text="config is loaded in thomas/core/config.py:744",
    )
    assert tc.checklist_satisfied(ev) is True
    assert tc.unmet_items(ev) == []


def test_empty_checklist_is_trivially_satisfied():
    assert tc.checklist_satisfied([]) is True
    assert tc.checklist_satisfied(tc.build_checklist("research")) is True  # pass-through type


def test_round_trips_through_dicts():
    items = tc.evaluate_checklist(tc.build_checklist("review_explain"), read_paths=["a.py"], output_text="a.py:1")
    restored = tc.checklist_from_dicts(tc.checklist_to_dicts(items))
    assert [i.to_dict() for i in restored] == [i.to_dict() for i in items]


def test_flag_default_on_and_zero_turns_it_off(monkeypatch):
    monkeypatch.delenv("THOMAS_TASK_CHECKLISTS", raising=False)
    assert tc.checklists_enabled() is True
    monkeypatch.setenv("THOMAS_TASK_CHECKLISTS", "0")
    assert tc.checklists_enabled() is False
    monkeypatch.setenv("THOMAS_TASK_CHECKLISTS", "1")
    assert tc.checklists_enabled() is True
