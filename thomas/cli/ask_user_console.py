"""Answer ``ask_user`` questions on the terminal.

The chat page answers the model's questions with chips; a headless or
terminal run has no page. This watcher polls the shared question book from a
daemon thread, prints the question and its numbered options, reads one line,
and answers. A number picks an option; anything else is a free-text answer.
Without a terminal it does nothing, so the tool's own timeout tells the model
to proceed on a stated assumption.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from typing import Any

from thomas.core.user_questions import UserQuestionBook, question_book


def _render(question: dict[str, Any]) -> str:
    lines = ["", f"Thomas asks: {question.get('question', '')}"]
    options = question.get("options") or []
    for index, option in enumerate(options, start=1):
        label = str(option.get("label", ""))
        description = str(option.get("description") or "").strip()
        lines.append(f"  {index}. {label}" + (f"  - {description}" if description else ""))
    hint = "type a number"
    if question.get("multi_select"):
        hint = "type numbers separated by spaces"
    if question.get("allow_free_text") or not options:
        hint += ", or your own answer"
    lines.append(f"  ({hint}, Enter to send)")
    lines.append("> ")
    return "\n".join(lines)


def answer_once(
    book: UserQuestionBook,
    *,
    read_line: Callable[[], str],
    write: Callable[[str], Any],
) -> bool:
    """Answer the oldest pending question, if any. Returns True when one was answered."""
    pending = book.pending()
    if not pending:
        return False
    question = pending[0]
    write(_render(question))
    try:
        raw = str(read_line() or "").strip()
    except (EOFError, OSError, StopIteration):
        return False
    options = question.get("options") or []
    picks: list[str] = []
    tokens = raw.replace(",", " ").split()
    if tokens and all(t.isdigit() and 1 <= int(t) <= len(options) for t in tokens):
        picks = [str(options[int(t) - 1].get("label", "")) for t in tokens]
        if not question.get("multi_select"):
            picks = picks[:1]
        return book.answer(question["id"], picks, other="")
    return book.answer(question["id"], [], other=raw)


def start_console_answerer(
    book: UserQuestionBook | None = None,
    *,
    read_line: Callable[[], str] = input,
    write: Callable[[str], Any] | None = None,
    is_tty: bool | None = None,
    poll_s: float = 0.5,
) -> threading.Thread | None:
    """Start the watcher thread; None when there is no terminal to ask on."""
    tty = bool(sys.stdin.isatty() and sys.stdout.isatty()) if is_tty is None else bool(is_tty)
    if not tty:
        return None
    active = book or question_book()
    emit = write or (lambda text: (sys.stdout.write(text), sys.stdout.flush()))

    def _loop() -> None:
        while True:
            try:
                if not answer_once(active, read_line=read_line, write=emit):
                    threading.Event().wait(poll_s)
            except (EOFError, OSError, StopIteration, RuntimeError):
                return

    thread = threading.Thread(target=_loop, name="thomas-ask-user-console", daemon=True)
    thread.start()
    return thread


__all__ = ["answer_once", "start_console_answerer"]
