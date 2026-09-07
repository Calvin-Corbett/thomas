"""On the terminal, Thomas's question is printed and the person types the answer.

The web page answers ``ask_user`` with chips; a headless or terminal run has
no page. The console answerer watches the question book from a thread, prints
the options, reads one line, and answers. Without a terminal it does nothing,
so the tool's own timeout tells the model to proceed on an assumption.
"""

from __future__ import annotations

import asyncio
import io
import time

from thomas.core.user_questions import UserQuestionBook
from thomas.cli.ask_user_console import answer_once, start_console_answerer


def test_answer_once_prints_the_options_and_answers_with_the_chosen_number() -> None:
    book = UserQuestionBook()
    out = io.StringIO()

    async def scenario():
        record = book.ask(
            question="Tea or coffee?", options=[{"label": "Tea"}, {"label": "Coffee", "description": "hot"}]
        )
        waiter = asyncio.get_running_loop().create_task(book.wait(record.id, timeout_s=5))
        await asyncio.sleep(0)
        answered = answer_once(book, read_line=lambda: "2", write=out.write)
        assert answered is True
        assert await waiter == {"selected": ["Coffee"], "other": ""}

    asyncio.run(scenario())
    text = out.getvalue()
    assert "Tea or coffee?" in text and "1" in text and "Coffee" in text and "hot" in text


def test_free_text_and_bad_numbers_become_other() -> None:
    book = UserQuestionBook()

    async def scenario():
        record = book.ask(question="Name it?", options=[{"label": "A"}], allow_free_text=True)
        waiter = asyncio.get_running_loop().create_task(book.wait(record.id, timeout_s=5))
        await asyncio.sleep(0)
        assert answer_once(book, read_line=lambda: "call it Bob", write=lambda _s: None) is True
        assert await waiter == {"selected": [], "other": "call it Bob"}

    asyncio.run(scenario())


def test_the_thread_answers_a_question_that_appears_later_and_stays_quiet_without_a_tty() -> None:
    book = UserQuestionBook()
    lines = iter(["1"])
    thread = start_console_answerer(
        book, read_line=lambda: next(lines), write=lambda _s: None, is_tty=True, poll_s=0.01
    )
    assert thread is not None

    async def scenario():
        record = book.ask(question="Go?", options=[{"label": "Yes"}, {"label": "No"}])
        return await book.wait(record.id, timeout_s=3)

    assert asyncio.run(scenario()) == {"selected": ["Yes"], "other": ""}
    assert start_console_answerer(UserQuestionBook(), read_line=input, write=print, is_tty=False) is None
    time.sleep(0.02)
