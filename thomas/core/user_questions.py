"""Questions the model asks the person mid-run, and the answers that release them.

One process-wide book. Lives in core because tools, routes and the CLI all
reach it (the tools layer may not import thomas.agent). The ``ask_user`` tool registers a question and awaits
its answer; the web route and the CLI answer it; ``pending()`` lets a page
that reloaded re-render whatever is still waiting. Thomas is a one-person
product, so the book is keyed by question id, not by user.
"""

from __future__ import annotations

import asyncio
import threading
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
    # "question" is a plain ask_user card; "setting_change" is Thomas asking to
    # change one of his own settings, drawn as its own card (details carry the
    # validated setting, value and reason).
    kind: str = "question"
    details: dict[str, Any] = field(default_factory=dict)
    future: asyncio.Future | None = field(default=None, repr=False)
    # Set when answered, for waiters on a plain thread (a protected write asks
    # from inside a synchronous tool call and cannot await).
    answered: threading.Event = field(default_factory=threading.Event, repr=False)
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
            "kind": self.kind,
            "details": dict(self.details),
        }


class UserQuestionBook:
    def __init__(self) -> None:
        self._open: dict[str, QuestionRecord] = {}
        self._lock = threading.RLock()

    def ask(
        self,
        *,
        question: str,
        options: list[dict[str, str]] | None = None,
        multi_select: bool = False,
        allow_free_text: bool = False,
        session_id: str = "",
        kind: str = "question",
        details: dict[str, Any] | None = None,
    ) -> QuestionRecord:
        record = QuestionRecord(
            id=uuid.uuid4().hex[:12],
            question=str(question).strip(),
            options=[dict(o) for o in (options or [])],
            multi_select=bool(multi_select),
            allow_free_text=bool(allow_free_text),
            created_at=time.time(),
            session_id=str(session_id or ""),
            kind=str(kind or "question"),
            details=dict(details or {}),
        )
        with self._lock:
            self._open[record.id] = record
        return record

    def pending(self, session_id: str | None = None) -> list[dict[str, Any]]:
        """Open questions: one session's with a session id, the session-less ones
        with "", every row with None (the console answerer). A page never sees
        another chat's questions."""
        with self._lock:
            if session_id is None:
                rows = list(self._open.values())
            else:
                wanted = str(session_id).strip()
                rows = [r for r in self._open.values() if r.session_id == wanted]
            return [r.to_dict() for r in sorted(rows, key=lambda r: r.created_at)]

    @staticmethod
    def _selected_labels(selected: list[str] | str | None) -> list[str]:
        if isinstance(selected, str):
            return [selected] if selected else []
        return [str(s) for s in (selected or []) if str(s)]

    def answer_problem(self, question_id: str, selected: list[str] | str | None, other: str = "") -> str:
        """Explain why an open question or card cannot take this answer."""
        with self._lock:
            record = self._open.get(str(question_id))
            if record is None or record.kind not in ("question", "card"):
                return ""
            chosen = self._selected_labels(selected)
            labels = {option.get("label") for option in record.options}
            if any(label not in labels for label in chosen):
                return "That is not one of this question's options."
            if not record.multi_select and len(chosen) > 1:
                return "This question takes one answer."
            if str(other or "").strip() and not record.allow_free_text:
                return "This question does not take a typed answer."
            if not chosen and not str(other or "").strip():
                return "Pick an option or type an answer."
            return ""

    def answer(
        self,
        question_id: str,
        selected: list[str] | str | None,
        other: str = "",
        *,
        session_id: str | None = None,
        password_verified: bool = False,
    ) -> bool:
        """Deliver an answer. False when the question is unknown, already answered,
        or asked by a different session than the one answering (a question with a
        session takes an answer only from that session; None skips the check for
        the console answerer, which has no session to offer).

        Also False when a chosen option needs a password and ``password_verified``
        is not True. Only the web route sets it, and only after the Windows
        sign-in accepted the owner's PIN or password in that same request. So a
        password option cannot be picked by anything that merely reaches this
        book -- an agent, a script, the console -- only by the person at the
        machine. The wall is here, not in the page."""
        with self._lock:
            record = self._open.get(str(question_id))
            if record is None:
                return False
            if record.session_id and session_id is not None and str(session_id).strip() != record.session_id:
                return False
            chosen = self._selected_labels(selected)
            if self.answer_problem(record.id, chosen, other):
                return False
            if self.needs_password(record.id, chosen) and not password_verified:
                return False
            self._open.pop(record.id)
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
            record.result = payload
            record.answered.set()
            return True

    def needs_password(self, question_id: str, selected: list[str]) -> bool:
        """True when any chosen option of an open question is marked requires_password."""
        with self._lock:
            record = self._open.get(str(question_id))
            if record is None:
                return False
            locked = {str(o.get("label")) for o in record.options if o.get("requires_password")}
            return any(str(choice) in locked for choice in selected)

    def wait_blocking(self, record: QuestionRecord, *, timeout_s: float) -> dict[str, Any]:
        """Wait on a plain thread. Raises TimeoutError when no answer arrives.

        For callers inside a synchronous tool call on a worker thread. Never call
        it on the server's own event-loop thread: the answer arrives through a
        route on that loop, so blocking it would wait for itself.
        """
        if not record.answered.wait(timeout=timeout_s):
            self.forget(record.id)
            raise TimeoutError(record.id)
        return dict(record.result or {})

    def forget(self, question_id: str) -> None:
        with self._lock:
            self._open.pop(str(question_id), None)

    async def wait(self, question_id: str, *, timeout_s: float) -> dict[str, Any]:
        """Await the answer to a registered question. Raises TimeoutError when none arrives."""
        with self._lock:
            record = self._open.get(str(question_id))
        if record is None:
            raise KeyError(question_id)
        return await self.wait_record(record, timeout_s=timeout_s)

    async def wait_record(self, record: QuestionRecord, *, timeout_s: float) -> dict[str, Any]:
        """Await a card's answer holding the record itself.

        A waiter that starts after the card is posted -- the end-of-run review
        card settles in its own task -- can find the question already answered
        and gone from the open list. The record keeps its answer, so waiting on
        it never loses one to that race.
        """
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
