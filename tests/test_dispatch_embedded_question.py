"""Embedded-question routing.

A conversational question that does not START with a wh-word -- e.g.
"quick note, what is 8 x 7?" -- is still an information request and must route to
a direct reply (``casual``), not a dispatched background task. Genuine,
directive-led work must still dispatch. These pin that behaviour so the
classifier refinement cannot silently regress.
"""

from __future__ import annotations

from thomas.agent.dispatch import should_dispatch


def test_embedded_question_routes_to_reply():
    for msg in [
        "quick note - what is 8 times 7?",
        "Hey Thomas, quick test: what is 17 times 23?",
        "btw, what is the capital of France?",
        "so, how does the token economy work here?",
    ]:
        assert should_dispatch(msg, mode="auto").action == "casual", msg


def test_leading_directive_wins_over_embedded_question():
    # A leading directive ("can you ...") must still dispatch even though the
    # message also contains a trailing question mark.
    decision = should_dispatch("can you build me a dashboard? I need it today", mode="auto")
    assert decision.action == "dispatch", decision


def test_real_tasks_still_dispatch():
    for msg in [
        "build me a website for my bakery",
        "create a sales report",
        "fix the login bug",
        "research the best database and build me a schema",
        "use your tools to list the top-level files in the repo",
    ]:
        assert should_dispatch(msg, mode="auto").action == "dispatch", msg


def test_plain_leading_questions_still_reply():
    for msg in ["what is 8 times 7?", "what's the capital of France?"]:
        assert should_dispatch(msg, mode="auto").action == "casual", msg
