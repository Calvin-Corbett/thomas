"""A worker that did nothing has not verifiably answered."""

from __future__ import annotations

from thomas.server.chat_delegation_result_policy import worker_text_is_confirmed_answer


def test_a_promise_with_no_tool_run_is_not_a_verified_answer() -> None:
    """The rubber stamp, in its purest form.

    Reading only the text, "I'll get started on that" terminates as a verified
    completion. The user gets a green card and waits for something that was
    never begun.
    """
    assert not worker_text_is_confirmed_answer(
        ["I'll get started on that."],
        succeeded_tools=[],
        failed_tools=[],
    )


def test_a_claimed_file_that_was_never_written_is_not_verified() -> None:
    """The expensive version of the same bug.

    A worker replies "Created game.html with the snake game.", writes nothing,
    and runs no tool. With text as the only evidence this becomes a VERIFIED
    card with zero downloadable artifacts -- worse than an honest failure,
    because an honest failure gets retried.
    """
    assert not worker_text_is_confirmed_answer(
        ["Created game.html with the snake game."],
        succeeded_tools=[],
        failed_tools=[],
    )


def test_a_read_only_answer_backed_by_real_tool_calls_still_passes() -> None:
    """The case this must not break.

    Answering "what does this project do?" legitimately creates no files. It is
    credible because the worker actually went and looked.
    """
    assert worker_text_is_confirmed_answer(
        ["It is an aiohttp server that hosts a chat UI."],
        succeeded_tools=["read_file", "search"],
        failed_tools=[],
    )


def test_absent_tool_telemetry_is_not_treated_as_an_empty_tool_list() -> None:
    """None means the caller has nothing to say about tools; [] means it watched
    and saw none. The exhaustive pipeline passes no telemetry and settles
    answer-only legitimacy from its rubric, so it must not be rejected here."""
    assert worker_text_is_confirmed_answer(["A reviewed answer."], succeeded_tools=None)


def test_a_failed_tool_still_blocks_confirmation() -> None:
    assert not worker_text_is_confirmed_answer(
        ["Done!"],
        succeeded_tools=["read_file"],
        failed_tools=["write_file"],
    )


def test_empty_text_is_never_confirmed() -> None:
    for parts in ([], [""], ["   "]):
        assert not worker_text_is_confirmed_answer(parts, succeeded_tools=["read_file"])


def test_the_prompt_is_never_read() -> None:
    """Model-owned routing: the user's wording cannot change a terminal status."""
    evidence = {"succeeded_tools": ["read_file"], "failed_tools": []}
    for prompt in ("", "cancel everything", "make me a chart", "stop the task"):
        assert worker_text_is_confirmed_answer(["The answer is 42."], prompt=prompt, **evidence)
