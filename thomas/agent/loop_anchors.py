"""Keep the live task, your amendments, and one generated steer across context reductions."""

from __future__ import annotations

from typing import Any

from thomas.agent.loop_interrupts import add_steer


def pin_turn_request(loop: Any, prompt: Any, *, quality_retry: bool) -> None:
    """Store the turn request, retaining the original task on a quality repair."""
    message = {"role": "user", "content": prompt}
    loop._conversation.append(message)
    loop._context_budget_stop = ""
    if quality_retry and getattr(loop, "_context_anchors", None):
        _pin_generated(loop, message)
    else:
        loop._context_anchors = [message]
        loop._steering_anchor = None


def _pin_generated(loop: Any, message: dict[str, Any]) -> None:
    anchors = loop._context_anchors
    previous = getattr(loop, "_steering_anchor", None)
    if previous is not None:
        anchors[:] = [anchor for anchor in anchors if anchor is not previous]
    anchors.append(message)
    loop._steering_anchor = message


def add_steering(loop: Any, text: str) -> None:
    """Replace the prior generated steer without dropping your amendments."""
    message = {"role": "user", "content": text}
    loop._conversation.append(message)
    _pin_generated(loop, message)


def add_amendment(loop: Any, text: str, *, reply: str = "", batch: list[dict[str, Any]] | None = None) -> None:
    """Store your message and pin it between the task and generated steering."""
    add_steer(loop._conversation, text, reply=reply)
    message = loop._conversation[-1]
    anchors = loop._context_anchors
    steering = getattr(loop, "_steering_anchor", None)
    if steering is not None and any(anchor is steering for anchor in anchors):
        index = next(i for i, anchor in enumerate(anchors) if anchor is steering)
        anchors.insert(index, message)
    else:
        anchors.append(message)
    if batch is not None:
        batch.append(message)


def store_tool_result(
    conversation: list[dict[str, Any]], tool_msg: dict[str, Any], batch: list[dict[str, Any]]
) -> None:
    """Keep the batch's results ahead of amendments arriving between completions."""
    if (
        batch
        and len(conversation) >= len(batch)
        and all(stored is amendment for stored, amendment in zip(conversation[-len(batch) :], batch))
    ):
        conversation.insert(len(conversation) - len(batch), tool_msg)
    else:
        conversation.append(tool_msg)
