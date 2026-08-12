"""A correct written answer survives a tool failure the worker recovered from.

`worker_text_is_confirmed_answer` rejected on `if failed_tools: return False` --
unconditionally, with no recovery check, while `succeeded_tools` sat unused in the
same signature. A research run whose first query 404s, searches again, gets the
answer and writes three good paragraphs was thrown away for the 404.

The check exists to stop a rubber stamp: "I'll get started on that", nothing run,
nothing written, terminating as a green VERIFIED card with zero artifacts. That
purpose never rested on the failure list -- it rests on there being answer text and
at least one successful tool -- so both of those still hold here.

Deliberately narrow: a tool that failed and NEVER succeeded still rejects. Widening
to "any success anywhere excuses any failure" would also excuse a worker whose real
work failed and which then wrote an answer from nothing, which is the very thing
this module was written to catch.
"""

from __future__ import annotations

from thomas.server.chat_delegation_result_policy import worker_text_is_confirmed_answer

ANSWER = ["Everest is 8849 m, K2 is 8611 m, and Kangchenjunga is 8586 m."]


def test_a_query_that_failed_then_succeeded_keeps_the_answer() -> None:
    assert worker_text_is_confirmed_answer(
        ANSWER, failed_tools=["web.search"], succeeded_tools=["web.search"]
    ), "a recovered search still discards the answer it went on to produce"


def test_recovery_is_read_from_telemetry_not_from_the_wording() -> None:
    """Same text, same tools, opposite recovery -- only telemetry may decide."""

    recovered = worker_text_is_confirmed_answer(
        ANSWER, failed_tools=["web.search"], succeeded_tools=["web.search"]
    )
    never_worked = worker_text_is_confirmed_answer(
        ANSWER, failed_tools=["web.search"], succeeded_tools=["fs.read_file"]
    )
    assert recovered and not never_worked


# --- the rubber stamp this module exists to refuse ------------------------


def test_an_answer_with_no_tool_run_is_still_refused() -> None:
    assert not worker_text_is_confirmed_answer(ANSWER, failed_tools=[], succeeded_tools=[])


def test_no_answer_text_is_still_refused() -> None:
    assert not worker_text_is_confirmed_answer([], failed_tools=[], succeeded_tools=["web.search"])
    assert not worker_text_is_confirmed_answer(["   "], failed_tools=[], succeeded_tools=["web.search"])


def test_a_tool_that_never_once_worked_is_still_refused() -> None:
    assert not worker_text_is_confirmed_answer(
        ANSWER, failed_tools=["shell"], succeeded_tools=["fs.list_dir"]
    ), "an unrecovered failure now passes; the check was widened rather than corrected"


def test_absent_telemetry_keeps_its_documented_behaviour() -> None:
    """``None`` means the caller has no telemetry to offer and judges by its own
    rubric; it must not start behaving like an empty list."""

    assert worker_text_is_confirmed_answer(ANSWER, failed_tools=[], succeeded_tools=None)
    assert not worker_text_is_confirmed_answer(ANSWER, failed_tools=["web.search"], succeeded_tools=None)
