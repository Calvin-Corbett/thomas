"""A steer you queue for a running Thomas is read one way, wherever the agent loop looks for it.

bc4c642a (a self-fix) gave the loop a second place to read a queued steer, while the model composes its final
answer, as a copy of the reading between tool calls, and pushed thomas/agent/loop_execution.py to 833 lines. The
reading is one function now (thomas/agent/loop_interrupts.py). These drive it every way a queue can answer, and
check that the loop reads a steer through it and nowhere else.
"""

from __future__ import annotations

import asyncio
import queue
from pathlib import Path
from typing import Any

import pytest

from thomas.agent import loop_execution
from thomas.agent.loop_core import LoopState
from thomas.agent.loop_interrupts import add_steer, read_queued_steer, stopped_by_you, turn_for_steer
from thomas.core.events import EventType


def _queue(kind: str) -> Any:
    return asyncio.Queue() if kind == "asyncio" else queue.Queue()  # the loop is handed either kind


@pytest.mark.parametrize("kind", ["asyncio", "thread"])
@pytest.mark.parametrize(
    ("item", "expected"),
    [
        (None, ("stop", "")),
        ("stop", ("stop", "")),
        ("STOP ", ("stop", "")),
        ("  make the Send button blue \n", ("text", "make the Send button blue")),
        ("   ", ("none", "")),
    ],
)
def test_a_queued_steer_is_read_once_and_taken(kind: str, item: Any, expected: tuple[str, str]) -> None:
    waiting = _queue(kind)
    waiting.put_nowait(item)
    assert read_queued_steer(waiting) == expected
    assert waiting.empty()  # taken, so it is never read a second time
    assert read_queued_steer(waiting) == ("none", "")


@pytest.mark.parametrize("kind", ["asyncio", "thread", "no queue"])
def test_nothing_queued_is_nothing(kind: str) -> None:
    assert read_queued_steer(None if kind == "no queue" else _queue(kind)) == ("none", "")


def test_a_stop_ends_the_run_as_yours() -> None:
    state = LoopState()
    event = stopped_by_you(state, 4)
    assert (state.user_interrupted, state.finished) == (True, True)
    assert (event.type, event.iteration) == (EventType.AGENT_END, 4)
    assert event.data == {"reason": "user_interrupted", "message": "Run cancelled by user."}


def test_your_words_follow_an_unfinished_reply_and_always_get_a_model_turn() -> None:
    conversation: list[dict[str, Any]] = []
    add_steer(conversation, "make it blue", reply="Nearly done: the button is")
    add_steer(conversation, "and bigger")
    assert conversation == [
        {"role": "assistant", "content": "Nearly done: the button is"},
        {"role": "user", "content": "make it blue"},
        {"role": "user", "content": "and bigger"},
    ]
    assert [turn_for_steer(iteration, 5) for iteration in (3, 4, 5, 6)] == [5, 5, 6, 6]


def test_the_loop_reads_a_steer_only_through_it() -> None:
    source = Path(loop_execution.__file__).read_text(encoding="utf-8")
    assert "get_nowait" not in source
    assert source.count("read_queued_steer(") == 2  # between tool calls, and at the final answer
    assert len(source.splitlines()) <= 800
