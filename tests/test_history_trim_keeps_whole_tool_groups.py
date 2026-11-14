"""The heuristic fallback, the soft trim and the hard cap keep whole tool groups and every required message."""

from __future__ import annotations

import pytest

from tests.compaction_support import AMENDMENT, FACT, _group, _group_state, _interleaved_history, _orphans
from thomas.agent.context_compaction import _apply_heuristic_compaction
from thomas.core.tokens import estimate_messages_tokens, fit_messages_to_hard_cap, trim_messages_to_budget


def test_heuristic_fallback_drops_whole_tool_groups_and_never_the_pinned_task() -> None:
    task = {"role": "user", "content": f"Keep this. {FACT}"}
    messages = [task, *_group("x", 2, 4000), *_group("y", 1, 4000), {"role": "user", "content": "latest"}]

    _apply_heuristic_compaction(messages, target_tokens=300, preserve_recent=2, pinned={id(task)})

    assert any(message is task for message in messages)
    assert _orphans(messages) == []
    assert _group_state(messages, "x", 2) in {"whole", "absent"}
    assert _group_state(messages, "y", 1) in {"whole", "absent"}


def test_heuristic_fallback_does_not_rewrite_a_pinned_amendment_inside_a_group() -> None:
    task = {"role": "user", "content": "task"}
    amendment = {"role": "user", "content": "amendment"}
    call = {
        "role": "assistant",
        "content": "a" * 1000,
        "tool_calls": [{"id": "pin", "function": {"name": "x", "arguments": "{}"}}],
    }
    result = {"role": "tool", "tool_call_id": "pin", "content": "z" * 4000}
    messages = [task, call, amendment, result, {"role": "user", "content": "latest"}]

    _apply_heuristic_compaction(messages, target_tokens=100, preserve_recent=1, pinned={id(task), id(amendment)})

    assert any(message is call for message in messages)
    assert any(message is result for message in messages)
    assert any(message is amendment for message in messages)
    assert _orphans(messages) == []


def test_soft_trim_never_splits_a_tool_group_at_the_tail() -> None:
    task = {"role": "user", "content": "task"}
    messages = [task, *_group("m", 3, 800), {"role": "user", "content": "now report"}]

    trimmed = trim_messages_to_budget(messages, budget=500, preserve_first=1, preserve_last=2)

    assert _orphans(trimmed) == []
    assert _group_state(trimmed, "m", 3) in {"whole", "absent"}


def test_soft_trim_keeps_a_required_message_from_the_middle() -> None:
    task = {"role": "user", "content": f"the real task {FACT}"}
    messages = [
        {"role": "user", "content": "older chat " * 50},
        task,
        *_group("n", 1, 3000),
        {"role": "user", "content": "go"},
    ]

    trimmed = trim_messages_to_budget(messages, budget=400, preserve_first=1, preserve_last=1, required=[task])

    assert any(message is task for message in trimmed)
    assert _orphans(trimmed) == []


def test_hard_cap_keeps_a_required_anchor_that_is_not_the_latest_user() -> None:
    task = {"role": "user", "content": f"the real task {FACT}"}
    latest = {"role": "user", "content": "latest"}
    messages = [{"role": "system", "content": "system"}, task, *_group("h", 1, 8000), latest]

    fitted = fit_messages_to_hard_cap(messages, hard_cap=600, required_anchors=[task])

    assert any(message.get("content") == task["content"] for message in fitted)
    assert any(message.get("content") == "latest" for message in fitted)
    assert _orphans(fitted) == []


def test_hard_cap_restores_a_required_anchor_missing_from_the_list() -> None:
    task = {"role": "user", "content": f"the real task {FACT}"}
    messages = [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "[context-summary] earlier"},
    ]

    fitted = fit_messages_to_hard_cap(messages, hard_cap=600, required_anchors=[task])

    assert [message.get("role") for message in fitted] == ["system", "user", "assistant"]
    assert fitted[1]["content"] == task["content"]


def test_hard_cap_refuses_when_required_anchors_cannot_fit() -> None:
    task = {"role": "user", "content": "task " * 2000}
    messages = [{"role": "system", "content": "system"}, task, {"role": "user", "content": "latest"}]

    with pytest.raises(ValueError, match="Required"):
        fit_messages_to_hard_cap(messages, hard_cap=300, required_anchors=[task])


def test_soft_trim_keeps_an_exchange_with_an_amendment_between_its_results() -> None:
    history, task, amendment = _interleaved_history(3000)
    messages = [*history, {"role": "user", "content": "latest"}]

    trimmed = trim_messages_to_budget(
        messages, budget=300, preserve_first=1, preserve_last=2, required=[task, amendment]
    )

    assert any(message is amendment for message in trimmed)
    assert _orphans(trimmed) == []
    assert _group_state(trimmed, "i", 2) in {"whole", "absent"}


def test_hard_cap_refuses_rather_than_orphan_a_result_after_an_amendment() -> None:
    history, task, amendment = _interleaved_history(3000)
    messages = [{"role": "system", "content": "system"}, *history, {"role": "user", "content": "latest"}]
    required = [task, amendment]
    full = estimate_messages_tokens(fit_messages_to_hard_cap(messages, hard_cap=100_000, required_anchors=required))

    with pytest.raises(ValueError, match="Required"):
        fit_messages_to_hard_cap(messages, hard_cap=full - 5, required_anchors=required)


def test_hard_cap_restores_a_missing_amendment_after_the_task_that_is_present() -> None:
    task = {"role": "user", "content": f"the real task {FACT}"}
    amendment = {"role": "user", "content": AMENDMENT}
    messages = [
        {"role": "system", "content": "system"},
        task,
        {"role": "assistant", "content": "[context-summary] earlier"},
    ]

    fitted = fit_messages_to_hard_cap(messages, hard_cap=600, required_anchors=[task, amendment])

    contents = [message.get("content") for message in fitted]
    assert contents.index(task["content"]) < contents.index(amendment["content"])


def test_hard_cap_restores_every_missing_anchor_in_order() -> None:
    task = {"role": "user", "content": f"the real task {FACT}"}
    first = {"role": "user", "content": AMENDMENT}
    second = {"role": "user", "content": "AMENDMENT-TWO: and a summary line"}
    messages = [{"role": "system", "content": "system"}, {"role": "assistant", "content": "[context-summary] earlier"}]

    fitted = fit_messages_to_hard_cap(messages, hard_cap=600, required_anchors=[task, first, second])

    assert [message.get("content") for message in fitted[1:4]] == [task["content"], first["content"], second["content"]]
