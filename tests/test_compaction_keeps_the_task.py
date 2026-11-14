"""Compaction keeps the task, each amendment in order, and every tool call together with its results.

Run 20260912T221756Z-compaction-3a1d59 compacted a worker whose history was the task, one assistant message with
14 tool calls, and their 14 results. compact() cut a raw message count, so it summarized the task together with
the calls and left 14 results whose calls no longer existed. The wire sanitizer then dropped all 14, and the next
request carried the system prompt and a summary: no task.
"""

from __future__ import annotations

import asyncio
import json

from tests.compaction_support import (
    AMENDMENT,
    FACT,
    _build,
    _group,
    _group_state,
    _interleaved_history,
    _loop,
    _orphans,
    _ResponsesOwner,
)
from thomas.core.llm_streaming_codex import _build_openai_codex_request


def test_compaction_keeps_the_task_when_one_tool_group_fills_the_window() -> None:
    task = {"role": "user", "content": f"Write the pad files, then report. {FACT}"}
    agent, summarizer = _loop([task, *_group("w", 14, 6000)], window=24000)
    agent._context_anchors = [task]

    result = asyncio.run(agent._auto_compact_if_needed(hard_cap=24000, threshold=0.70, preserve_recent=14))

    assert summarizer.calls >= 1, "the conversation is over the line, so a summary must be requested"
    assert result and result["tokens_saved"] > 0
    assert any(message is task for message in agent._conversation), "the task was compacted away"
    assert task["content"].endswith(FACT)
    assert _orphans(agent._conversation) == []
    assert _group_state(agent._conversation, "w", 14) in {"whole", "absent"}

    wire = _build(agent)
    assert any(message.get("role") == "user" and FACT in str(message.get("content")) for message in wire)
    assert _orphans(wire) == []


def test_compaction_never_ends_between_a_tool_call_and_its_results() -> None:
    task = {"role": "user", "content": f"Do the work. {FACT}"}
    conversation = [task, *_group("a", 1, 20000), *_group("b", 2, 10)]
    agent, summarizer = _loop(conversation, window=4000)
    agent._context_anchors = [task]

    asyncio.run(agent._auto_compact_if_needed(hard_cap=4000, threshold=0.70, preserve_recent=2))

    assert summarizer.calls >= 1
    assert any(message is task for message in agent._conversation)
    assert _orphans(agent._conversation) == []
    assert _group_state(agent._conversation, "a", 1) in {"whole", "absent"}
    assert _group_state(agent._conversation, "b", 2) in {"whole", "absent"}


def test_forward_compaction_never_takes_an_in_flight_tool_group() -> None:
    task = {"role": "user", "content": f"Write the pad files. {FACT}"}
    in_flight = _group("f", 14, 6000)[:-1]  # the last call has no result yet
    agent, summarizer = _loop([task, *in_flight], window=24000)
    agent._context_anchors = [task]
    before = list(agent._conversation)

    # 15 messages with 13 preserved puts the boundary inside the group (index 2), so it straddles.
    asyncio.run(agent._auto_compact_if_needed(hard_cap=24000, threshold=0.70, preserve_recent=13))

    assert summarizer.calls == 0
    assert agent._conversation == before


def test_repeated_compaction_keeps_the_task_and_each_user_amendment_in_order() -> None:
    task = {"role": "user", "content": f"Write the pad files. {FACT}"}
    agent, summarizer = _loop([task, *_group("r", 14, 6000)], window=24000)
    agent._context_anchors = [task]
    asyncio.run(agent._auto_compact_if_needed(hard_cap=24000, threshold=0.70, preserve_recent=14))

    amendment = {"role": "user", "content": "AMENDMENT: also write notes.txt"}
    agent._conversation.extend([amendment, *_group("s", 14, 6000)])
    agent._context_anchors = [task, amendment]
    asyncio.run(agent._auto_compact_if_needed(hard_cap=24000, threshold=0.70, preserve_recent=14))

    assert summarizer.calls >= 2
    users = [message for message in agent._conversation if message.get("role") == "user"]
    assert users[0] is task
    assert users[1] is amendment
    assert _orphans(agent._conversation) == []
    assert _group_state(agent._conversation, "s", 14) in {"whole", "absent"}
    wire_users = [str(message.get("content")) for message in _build(agent) if message.get("role") == "user"]
    assert wire_users[:2] == [task["content"], amendment["content"]]


def test_codex_request_keeps_the_task_once_and_valid_pairs_after_compaction() -> None:
    task = {"role": "user", "content": f"Write the pad files, then report. {FACT}"}
    agent, _summarizer = _loop([task, *_group("c", 14, 6000)], window=24000)
    agent._context_anchors = [task]
    asyncio.run(agent._auto_compact_if_needed(hard_cap=24000, threshold=0.70, preserve_recent=14))

    body = _build_openai_codex_request(_ResponsesOwner(), _build(agent), None, turn_user_content=task["content"])

    users = [item for item in body["input"] if item.get("role") == "user"]
    assert sum(1 for item in users if FACT in json.dumps(item.get("content"))) == 1
    calls = {item.get("call_id") for item in body["input"] if item.get("type") == "function_call"}
    outputs = [item.get("call_id") for item in body["input"] if item.get("type") == "function_call_output"]
    assert all(call_id in calls for call_id in outputs)


def test_compaction_keeps_an_exchange_with_an_amendment_between_its_results() -> None:
    history, task, amendment = _interleaved_history(20000)
    agent, _summarizer = _loop([*history, *_group("t", 1, 10)], window=4000)
    agent._context_anchors = [task, amendment]

    asyncio.run(agent._auto_compact_if_needed(hard_cap=4000, threshold=0.70, preserve_recent=2))

    assert any(message is amendment for message in agent._conversation)
    assert _orphans(agent._conversation) == []
    assert _group_state(agent._conversation, "i", 2) in {"whole", "absent"}
    users = [message for message in agent._conversation if message.get("role") == "user"]
    assert users.index(task) < users.index(amendment)


def test_repeated_compaction_keeps_the_task_and_two_amendments_in_order() -> None:
    task = {"role": "user", "content": f"Write the pad files. {FACT}"}
    first = {"role": "user", "content": AMENDMENT}
    second = {"role": "user", "content": "AMENDMENT-TWO: and a summary line"}
    agent, summarizer = _loop([task, *_group("p", 14, 6000)], window=24000)
    agent._context_anchors = [task]
    asyncio.run(agent._auto_compact_if_needed(hard_cap=24000, threshold=0.70, preserve_recent=14))
    agent._conversation.extend([first, *_group("q", 14, 6000)])
    agent._context_anchors = [task, first]
    asyncio.run(agent._auto_compact_if_needed(hard_cap=24000, threshold=0.70, preserve_recent=14))
    agent._conversation.extend([second, *_group("u", 14, 6000)])
    agent._context_anchors = [task, first, second]
    asyncio.run(agent._auto_compact_if_needed(hard_cap=24000, threshold=0.70, preserve_recent=14))

    assert summarizer.calls >= 3
    users = [message for message in agent._conversation if message.get("role") == "user"]
    assert all(kept is expected for kept, expected in zip(users[:3], [task, first, second], strict=True))
    assert _orphans(agent._conversation) == []
    wire_users = [str(message.get("content")) for message in _build(agent) if message.get("role") == "user"]
    assert wire_users[:3] == [task["content"], first["content"], second["content"]]


def test_due_compaction_reduces_the_preserve_window_rather_than_leave_it_to_the_request_builder() -> None:
    task = {"role": "user", "content": f"Read the files. {FACT}"}
    agent, summarizer = _loop([task, *_group("z", 10, 5000)], window=24000)
    agent._context_anchors = [task]

    result = asyncio.run(agent._auto_compact_if_needed(hard_cap=13_000, threshold=0.70, preserve_recent=14))

    assert summarizer.calls >= 1
    assert result and result["tokens_saved"] > 0
    assert result["preserve_recent_reduced"] is True
    assert any(message is task for message in agent._conversation)
    assert _orphans(agent._conversation) == []
