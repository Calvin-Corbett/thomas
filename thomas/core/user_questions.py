"""Questions the model asks the person mid-run, and the answers that release them.

One process-wide book. Lives in core because tools, routes and the CLI all
reach it (the tools layer may not import thomas.agent). The ``ask_user`` tool registers a question and awaits
its answer; the web route and the CLI answer it; ``pending()`` lets a page
that reloaded re-render whatever is still waiting. Thomas is a one-person
product, so the book is keyed by question id, not by user.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class QuestionRecord:
    id: str
    question: str
    options: list[dict[str, str]]
    multi_select: bool
    allow_free_text: bool
    created_at: float
    session_id: str = ""
    future: asyncio.Future | None = field(default=None, repr=False)
    result: dict[str, Any] | None = field(default=None, repr=False)  # an answer that arrived before anyone awaited

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "options": [dict(o) for o in self.options],
            "multi_select": self.multi_select,
            "allow_free_text": self.allow_free_text,
            "created_at": self.created_at,
            "session_id": self.session_id,
        }


class UserQuestionBook:
    def __init__(self) -> None:
        self._open: dict[str, QuestionRecord] = {}

    def ask(
        self,
        *,
        question: str,
        options: list[dict[str, str]] | None = None,
        multi_select: bool = False,
        allow_free_text: bool = False,
        session_id: str = "",
    ) -> QuestionRecord:
        record = QuestionRecord(
            id=uuid.uuid4().hex[:12],
            question=str(question).strip(),
            options=[dict(o) for o in (options or [])],
            multi_select=bool(multi_select),
            allow_free_text=bool(allow_free_text),
            created_at=time.time(),
            session_id=str(session_id or ""),
        )
        self._open[record.id] = record
        return record

    def pending(self, session_id: str | None = None) -> list[dict[str, Any]]:
        """Open questions: one session's with a session id, the session-less ones
        with "", every row with None (the console answerer). A page never sees
        another chat's questions."""
        if session_id is None:
            rows = list(self._open.values())
        else:
            wanted = str(session_id).strip()
            rows = [r for r in self._open.values() if r.session_id == wanted]
        return [r.to_dict() for r in sorted(rows, key=lambda r: r.created_at)]

    def answer(
        self,
        question_id: str,
        selected: list[str] | str | None,
        other: str = "",
        *,
        session_id: str | None = None,
    ) -> bool:
        """Deliver an answer. False when the question is unknown, already answered,
        or asked by a different session than the one answering (a question with a
        session takes an answer only from that session; None skips the check for
        the console answerer, which has no session to offer)."""
        record = self._open.get(str(question_id))
        if record is None:
            return False
        if record.session_id and session_id is not None and str(session_id).strip() != record.session_id:
            return False
        if isinstance(selected, str):
            chosen = [selected] if selected else []
        else:
            chosen = [str(s) for s in (selected or []) if str(s)]
        payload = {"selected": chosen, "other": str(other or "")}
        future = record.future
        if future is not None and not future.done():
            # The console answerer calls from its own thread; a future must be
            # resolved on the loop that owns it or the waiter never wakes.
            owner = future.get_loop()
            try:
                current = asyncio.get_running_loop()
            except RuntimeError:
                current = None
            if current is owner:
                future.set_result(payload)
            else:

                def _resolve() -> None:
                    if not future.done():
                        future.set_result(payload)

                owner.call_soon_threadsafe(_resolve)
        else:
            record.result = payload
        del self._open[record.id]
        return True

    def forget(self, question_id: str) -> None:
        self._open.pop(str(question_id), None)

    async def wait(self, question_id: str, *, timeout_s: float) -> dict[str, Any]:
        """Await the answer to a registered question. Raises TimeoutError when none arrives."""
        record = self._open.get(str(question_id))
        if record is None:
            raise KeyError(question_id)
        if record.result is not None:
            return record.result
        if record.future is None:
            record.future = asyncio.get_running_loop().create_future()
        try:
            return await asyncio.wait_for(asyncio.shield(record.future), timeout=timeout_s)
        except (TimeoutError, asyncio.CancelledError):
            # No answer in time, or the run that asked is gone (the specialist's
            # own deadline cancels the turn): the page must not keep showing a
            # question nobody is waiting on.
            self.forget(record.id)
            raise


_BOOK = UserQuestionBook()


def question_book() -> UserQuestionBook:
    """The process-wide book the tool, the route and the CLI share."""
    return _BOOK


__all__ = ["QuestionRecord", "UserQuestionBook", "question_book"]
