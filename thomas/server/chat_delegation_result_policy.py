"""Structured completion evidence for delegated workers."""

from __future__ import annotations

from thomas.server.chat_delegation_deliverable import _worker_answer_text


def worker_text_is_confirmed_answer(
    result_text_parts: list[str],
    *,
    prompt: str = "",
    succeeded_tools: list[str] | None = None,
    failed_tools: list[str] | None = None,
) -> bool:
    """Accept an answer on a structured worker terminal event, with evidence.

    The caller invokes this only after the worker emits ``done`` or the
    exhaustive pipeline returns a reviewed result. Natural-language wording
    never changes that terminal status -- the prompt is deliberately unread.

    Text alone is NOT evidence. Reading only the text made "I'll get started on
    that" and "Created game.html with the snake game." -- with nothing written
    and no tool run -- both terminate as a green VERIFIED card carrying zero
    artifacts. That is the rubber-stamp failure this project keeps rediscovering,
    and it is worse than an honest failure because there is nothing to retry.

    So a run that produced no files must at least have DONE something: at least
    one tool call succeeded and none failed. That is execution telemetry from
    _record_tool_outcome, not a reading of anyone's wording, so it stays inside
    model-owned routing.

    ``succeeded_tools`` distinguishes absent from empty on purpose. ``None``
    means the caller has no tool telemetry to offer -- the exhaustive pipeline
    decides answer-only legitimacy from its rubric instead -- and the tool
    requirement is not applied. ``[]`` means the caller watched and the worker
    ran nothing, which is exactly the case to reject.
    """

    del prompt
    if not _worker_answer_text(result_text_parts):
        return False
    if failed_tools:
        return False
    if succeeded_tools is None:
        return True
    return bool(succeeded_tools)


__all__ = ["worker_text_is_confirmed_answer"]
