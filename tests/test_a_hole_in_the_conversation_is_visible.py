"""When history is trimmed, the model is told there is a hole.

`get_context_window` keeps the first N and last M messages and drops from the
middle until the token budget is met. It used to do that in total silence, while
the compaction pass a few lines above already writes "...[truncated]" whenever it
shortens a single tool result. Cutting part of a message announced itself; cutting
twenty whole messages did not.

The cost is seamless amnesia. A constraint set early -- "never touch the staging
database" -- can vanish from the middle of a long session, and nothing in what the
model receives suggests the conversation it is reading has a gap. Visible amnesia
can be asked about; invisible amnesia just looks like Thomas ignoring you.
"""

from __future__ import annotations

from thomas.chat.conversation import ConversationManager

MARKER = "omitted here to fit the context window"


def _long_history(count: int = 30) -> list[dict[str, str]]:
    return [
        {"role": "user" if n % 2 == 0 else "assistant", "content": f"message {n} " + "x" * 400}
        for n in range(count)
    ]


def test_dropped_messages_are_announced() -> None:
    window = ConversationManager(messages=_long_history()).get_context_window(
        max_tokens=900, preserve_first=2, preserve_last=4
    )

    marked = [m for m in window if MARKER in str(m.get("content") or "")]
    assert marked, "history was silently cut; the model cannot tell it has a gap"
    assert "22 earlier messages" in str(marked[0]["content"]), "the count of dropped turns is wrong"


def test_the_marker_rides_on_an_existing_message() -> None:
    """It must not be inserted as its own entry: a mid-list system message breaks
    the user/assistant alternation some providers require."""

    history = _long_history()
    window = ConversationManager(messages=history).get_context_window(
        max_tokens=900, preserve_first=2, preserve_last=4
    )

    assert {str(m.get("role")) for m in window} <= {"user", "assistant"}
    marked = next(m for m in window if MARKER in str(m.get("content") or ""))
    assert "message " in str(marked["content"]), "the marker replaced a turn instead of prefixing it"


def test_nothing_is_announced_when_nothing_was_dropped() -> None:
    window = ConversationManager(messages=_long_history(3)).get_context_window(max_tokens=99_999)

    assert not any(MARKER in str(m.get("content") or "") for m in window)
    assert len(window) == 3


def test_the_stored_conversation_is_not_mutated() -> None:
    """The window is a view. Marking it must not rewrite what is on disk."""

    history = _long_history()
    manager = ConversationManager(messages=history)
    manager.get_context_window(max_tokens=900, preserve_first=2, preserve_last=4)

    assert not any(MARKER in str(m.get("content") or "") for m in history)
    assert not any(MARKER in str(m.get("content") or "") for m in manager.to_dict()["messages"])
