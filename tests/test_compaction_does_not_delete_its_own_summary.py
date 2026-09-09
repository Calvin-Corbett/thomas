"""Compaction must not throw away the summary it just wrote.

Pass 3 drops the oldest messages until the conversation fits. Its own comment says
"Drop oldest non-system, non-summary messages" -- but it inspected `messages[0]`
and then popped `messages[1]` without ever looking at what index 1 was. A real
conversation is `[system prompt, [context-summary], ...turns]`, so index 1 is
exactly the compaction summary: the one artifact carrying the forty turns that were
already compacted away.

Losing it is worse than losing forty ordinary messages, because everything those
turns established -- a constraint, a chosen schema, a decision not to use a
database -- lived only there. And the marker left behind reported it as one of "N
earlier messages", so the loss read as routine trimming.
"""

from __future__ import annotations

from thomas.agent.context_compaction import _COMPACTION_MARKER, _apply_heuristic_compaction

SUMMARY = (
    f"{_COMPACTION_MARKER}\nForty earlier turns: the user set the constraint NEVER USE "
    "THE STAGING DB, agreed schema v3, and chose Postgres."
)


def _conversation(turns: int = 20) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "You are Thomas." + " padding" * 40},
        {"role": "system", "content": SUMMARY},
        *[
            {"role": "user" if n % 2 == 0 else "assistant", "content": f"turn {n} " + "z" * 600}
            for n in range(turns)
        ],
    ]


def _has_summary(messages: list[dict[str, str]]) -> bool:
    return any(_COMPACTION_MARKER in str(m.get("content") or "") for m in messages)


def test_the_compaction_summary_survives_aggressive_compaction() -> None:
    messages = _conversation()
    assert _has_summary(messages)

    _apply_heuristic_compaction(messages, target_tokens=400, preserve_recent=4)

    assert _has_summary(messages), (
        "compaction deleted its own summary -- every constraint from the turns it had "
        "already compacted is now gone, and nothing says so"
    )


def test_the_system_prompt_also_survives() -> None:
    messages = _conversation()

    _apply_heuristic_compaction(messages, target_tokens=400, preserve_recent=4)

    assert any("You are Thomas" in str(m.get("content") or "") for m in messages)


def test_it_still_compacts() -> None:
    """Protecting the summary must not mean giving up on fitting the window."""

    messages = _conversation()
    before = len(messages)

    _apply_heuristic_compaction(messages, target_tokens=400, preserve_recent=4)

    assert len(messages) < before, "nothing was dropped; compaction stopped working"


def test_the_recent_turns_are_preserved() -> None:
    messages = _conversation()

    _apply_heuristic_compaction(messages, target_tokens=400, preserve_recent=4)

    assert any("turn 19" in str(m.get("content") or "") for m in messages), (
        "the most recent turn was dropped"
    )


def test_a_conversation_with_no_summary_still_compacts() -> None:
    messages = [
        {"role": "system", "content": "You are Thomas."},
        *[
            {"role": "user" if n % 2 == 0 else "assistant", "content": f"turn {n} " + "z" * 600}
            for n in range(20)
        ],
    ]

    _apply_heuristic_compaction(messages, target_tokens=400, preserve_recent=4)

    assert len(messages) < 21
    assert any("You are Thomas" in str(m.get("content") or "") for m in messages)
