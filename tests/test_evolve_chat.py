"""Tests for conversational control of the evolve loop (deep chat)."""

from __future__ import annotations

from thomas.forge.anvil.evolve_chat import (
    ACTION_APPROVE,
    ACTION_HELP,
    ACTION_PAUSE,
    ACTION_REJECT,
    ACTION_START,
    ACTION_STATUS,
    EvolveChatIntent,
    interpret_evolve_message,
    resolve_approval_ids,
    status_summary,
)


def test_start_with_focus_and_posture():
    intent = interpret_evolve_message("focus on hardening this week, but ask me before promoting")
    assert intent.action == ACTION_START
    assert intent.focus == "security"
    assert intent.posture == "propose"
    assert "hardening" in intent.reply or "security" in intent.reply


def test_start_maps_perf_alias_to_efficiency():
    intent = interpret_evolve_message("go work on performance")
    assert intent.action == ACTION_START
    assert intent.focus == "efficiency"


def test_start_autonomous_posture():
    intent = interpret_evolve_message("evolve yourself and go wild, don't ask")
    assert intent.action == ACTION_START
    assert intent.posture == "autonomous"


def test_start_without_focus_defaults_blank_focus():
    intent = interpret_evolve_message("start evolving")
    assert intent.action == ACTION_START
    assert intent.focus == ""
    assert intent.posture == ""  # caller defaults to auto_safe


def test_refactor_keyword_alone_starts_a_focused_run():
    intent = interpret_evolve_message("refactor the big files please")
    assert intent.action == ACTION_START
    assert intent.focus == "refactor"


def test_stop_reads_as_pause_not_start():
    # "stop evolving" contains the start hint 'evolv' but must read as pause.
    intent = interpret_evolve_message("stop evolving for now")
    assert intent.action == ACTION_PAUSE


def test_status_intents():
    for msg in ("what are you working on?", "status", "how's it going", "show me progress"):
        assert interpret_evolve_message(msg).action == ACTION_STATUS


def test_approve_with_reference():
    intent = interpret_evolve_message("approve the first one")
    assert intent.action == ACTION_APPROVE
    assert intent.approval_ref == "first"

    by_id = interpret_evolve_message("approve hold-ab12cd34")
    assert by_id.action == ACTION_APPROVE
    assert by_id.approval_ref == "hold-ab12cd34"


def test_approve_all():
    intent = interpret_evolve_message("approve all of them")
    assert intent.action == ACTION_APPROVE
    assert intent.approval_ref == "all"


def test_reject_intent():
    intent = interpret_evolve_message("dismiss that one")
    assert intent.action == ACTION_REJECT


def test_empty_and_unknown_give_help():
    assert interpret_evolve_message("").action == ACTION_HELP
    assert interpret_evolve_message("tell me a joke").action == ACTION_HELP
    assert "evolve" in interpret_evolve_message("???").reply.lower()


def test_intent_roundtrips_through_dict():
    intent = interpret_evolve_message("focus on tests")
    restored = EvolveChatIntent.from_dict(intent.to_dict())
    assert restored.action == intent.action
    assert restored.focus == intent.focus


def test_resolve_approval_ids():
    state = {
        "pending_approvals": [
            {"id": "hold-aaaa1111", "status": "pending"},
            {"id": "hold-bbbb2222", "status": "pending"},
            {"id": "hold-cccc3333", "status": "rejected"},
        ]
    }
    assert resolve_approval_ids(state, "first") == ["hold-aaaa1111"]
    assert resolve_approval_ids(state, "all") == ["hold-aaaa1111", "hold-bbbb2222"]
    assert resolve_approval_ids(state, "hold-bbbb2222") == ["hold-bbbb2222"]
    assert resolve_approval_ids({"pending_approvals": []}, "first") == []


def test_status_summary():
    state = {
        "status": "running",
        "counters": {"promoted": 2},
        "pending_count": 1,
        "current": {"title": "Harden auth"},
    }
    summary = status_summary(state)
    assert "running" in summary
    assert "2 change" in summary
    assert "1 awaiting" in summary
    assert "Harden auth" in summary
