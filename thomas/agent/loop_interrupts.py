"""A steer you queue for a running agent loop, read one way wherever the loop looks for it.

The loop looks between tool calls and, since bc4c642a, once more while the model composes its final answer, so a
steer that arrives then is answered in the same run instead of being left queued and unread. Both places read the
queue the same way: nothing queued, or a blank line, is nothing; ``None`` or ``stop`` (any case, any spacing) ends
the run as yours to end; anything else is your words, which join the run as its next user turn. That reading was two
copies in ``loop_execution`` until it became these functions.
"""

from __future__ import annotations

import asyncio
from queue import Empty
from typing import Any

from thomas.agent.loop_core import LoopState
from thomas.core.events import AgentEvent, EventType

NONE, STOP, TEXT = "none", "stop", "text"


def read_queued_steer(queue: Any) -> tuple[str, str]:
    """Take one queued steer, if any: ``("none", "")``, ``("stop", "")`` or ``("text", <your words>)``.

    ``queue`` is an ``asyncio.Queue`` or a ``queue.Queue`` (the loop is handed either), or None for a run nobody can
    steer.
    """
    if queue is None:
        return NONE, ""
    try:
        item = queue.get_nowait()
    except (asyncio.QueueEmpty, Empty):
        return NONE, ""
    if item is None or str(item).strip().lower() == "stop":
        return STOP, ""
    text = str(item).strip()
    return (TEXT, text) if text else (NONE, "")


def stopped_by_you(state: LoopState, iteration: int) -> AgentEvent:
    """Mark the run stopped by you, and return the event that ends it."""
    state.user_interrupted = True
    state.finished = True
    return AgentEvent(
        type=EventType.AGENT_END,
        data={"reason": "user_interrupted", "message": "Run cancelled by user."},
        iteration=iteration,
    )


def add_steer(conversation: list[dict[str, Any]], text: str, *, reply: str = "") -> None:
    """Your words as the run's next user turn, after the model's unfinished reply when it had one."""
    if reply:
        conversation.append({"role": "assistant", "content": reply})
    conversation.append({"role": "user", "content": text})


def turn_for_steer(iteration: int, max_iter: int) -> int:
    """The pass budget, one larger on the last pass: a steer the loop has taken always gets a model turn."""
    return max_iter + 1 if iteration >= max_iter else max_iter


def adapting(iteration: int) -> AgentEvent:
    """What the run says when your words arrive between its tool calls."""
    return AgentEvent(
        type=EventType.THINKING,
        data={"text": "Received additional user instructions. Adapting plan.\n"},
        iteration=iteration,
    )


__all__ = ["NONE", "STOP", "TEXT", "adapting", "add_steer", "read_queued_steer", "stopped_by_you", "turn_for_steer"]
