"""The card Thomas shows before he changes one of his own protected files.

Owner direction, 2026-09-22: "Every protected file needs to be its own thing"
-- and "leave the option open, like would you like to approve just this task or
allow me to do whatever, because sometimes you work, you don't want to get
asked questions."

So before a protected write, the chat that started the work shows a card: which
file, why, and four answers -- this file, this whole task, everything, or no.
Every approve option is marked ``requires_password``. The question book refuses
such an answer unless the server's route ran the Windows sign-in and it
accepted the owner's PIN or password (thomas/core/user_questions.py). An agent
that reaches the book or the route cannot pick one. The grant it leads to lives
in thomas/core/protected_write_grants.py.

This waits on a plain thread because protected writes are checked inside a
synchronous tool call. It is only used off the server's own event-loop thread,
where the answer route runs; see :func:`can_ask_on_a_card`.
"""

from __future__ import annotations

import threading

from thomas.core import protected_write_grants as grants
from thomas.core.owner_wait import awaiting_owner
from thomas.core.user_questions import UserQuestionBook, question_book

APPROVE_FILE = "Approve this file"
APPROVE_TASK = "Approve this whole task"
APPROVE_ALL = "Approve everything"
APPROVE_ONCE = "Approve this change only"
DECLINE = "No"

_SCOPES = {APPROVE_FILE: grants.SCOPE_FILE, APPROVE_TASK: grants.SCOPE_TASK, APPROVE_ALL: grants.SCOPE_ALL}

CARD_TIMEOUT_S = 20 * 60


def can_ask_on_a_card(task: str) -> bool:
    """A card needs a chat to show in, and a thread that may block.

    The answer arrives through a route on the server's event-loop thread, so
    waiting for it there would wait for itself. That thread gets the plain
    Windows prompt instead, still one file at a time.
    """
    return bool(task) and threading.current_thread() is not threading.main_thread()


_SCOPE_OPTIONS = [
    {"label": APPROVE_FILE, "description": "Only this file, for this task.", "requires_password": True},
    {
        "label": APPROVE_TASK,
        "description": "Every protected file this task touches. No more cards for it.",
        "requires_password": True,
    },
    {
        "label": APPROVE_ALL,
        "description": "Every protected file, until you restart Thomas.",
        "requires_password": True,
    },
    {"label": DECLINE, "description": "Leave the file as it is."},
]
# Policy C: a file that guards Thomas -- a gate, the cage, an approval module, a
# change that adds network reach -- is approved one change at a time and never
# remembered, so it cannot ride inside a scope you granted for something else.
_ONCE_OPTIONS = [
    {
        "label": APPROVE_ONCE,
        "description": "Only this exact change. It asks again next time.",
        "requires_password": True,
    },
    {"label": DECLINE, "description": "Leave the file as it is."},
]


def _card_details(card: object, why: str) -> dict:
    action, reason = card.dialog()
    fields = [
        {"label": "File", "value": card.details["path"]},
        {"label": "Change", "value": card.details["diffstat"]},
        {"label": "Pairing code", "value": card.code},
    ]
    if why:
        fields.append({"label": "Thomas says", "value": why})
    return {
        "kicker": "Guards Thomas - its own approval" if card.danger else "Protected file",
        "fields": fields,
        "pairing_code": card.code,
        "excerpt": card.excerpt,
        "note": "Your Windows prompt shows the same pairing code. If it does not match, choose No.",
        # The Windows dialog's words: the pinned catalogue's, never the model's.
        "prompt_action": f"{action}\n\n{reason}",
    }


def ask_on_card(
    *,
    task: str,
    path: str,
    why: str,
    book: UserQuestionBook | None = None,
    timeout_s: float = CARD_TIMEOUT_S,
    card: object | None = None,
) -> bool:
    """Show the card and wait. True only when the owner approved (with a password).

    With a trusted card (thomas/tools/trusted_card.py) it shows the real diff and
    the pairing code, and a dangerous file offers only this change or no.
    """
    book = book or question_book()
    dangerous = bool(card is not None and getattr(card, "danger", None))
    if card is not None:
        question = card.title
        details = _card_details(card, why)
    else:
        question = "Thomas wants to change one of his protected files"
        details = {
            "kicker": "Protected file",
            "fields": [{"label": "File", "value": path}, {"label": "Why", "value": why}],
            "note": "Each approval asks for your Windows PIN or password.",
            "prompt_action": f"Let Thomas change {path}",
        }
    record = book.ask(
        question=question,
        options=_ONCE_OPTIONS if dangerous else _SCOPE_OPTIONS,
        session_id=task,
        kind="card",
        details=details,
    )
    try:
        with awaiting_owner():
            answer = book.wait_blocking(record, timeout_s=timeout_s)
    except TimeoutError:
        return False
    selected = (answer.get("selected") or [""])[0]
    if selected == APPROVE_ONCE:
        return True  # this change only; nothing is remembered
    scope = _SCOPES.get(selected)
    if scope is None:
        return False
    if not dangerous:
        grants.grant(scope, task, path)
    return True


__all__ = [
    "APPROVE_ALL",
    "APPROVE_FILE",
    "APPROVE_ONCE",
    "APPROVE_TASK",
    "CARD_TIMEOUT_S",
    "DECLINE",
    "ask_on_card",
    "can_ask_on_a_card",
]
