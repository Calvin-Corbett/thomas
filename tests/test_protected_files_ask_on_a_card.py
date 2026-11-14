"""A protected file is its own approval, asked on a card, behind a password.

Owner direction, 2026-09-22: "Every protected file needs to be its own thing."
"leave the option open, like would you like to approve just this task or allow
me to do whatever, because sometimes you work, you don't want to get asked
questions." And: "then it prompts the password. And there should be no bypass."

These pin the wall, not the wording: an approve option cannot be answered
without the server's password check, an approval reaches exactly as far as the
owner chose, and nothing reuses an approval by time.
"""

from __future__ import annotations

import asyncio
import inspect
import threading

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.agent import loop_tool_exec
from thomas.core import protected_write_grants as grants
from thomas.core.user_questions import UserQuestionBook
from thomas.server.routes import user_questions_routes
from thomas.tools import native_auth
from thomas.tools import protected_write_card as card
from thomas.tools.ask_user import AskUserTool


@pytest.fixture(autouse=True)
def _clean() -> None:
    grants.revoke_all()
    yield
    grants.revoke_all()


def _card_in_a_worker(book: UserQuestionBook, *, task: str, path: str, answer: str, verified: bool) -> bool:
    """Run ask_on_card on a worker thread, answer it from this one."""
    out: dict = {}

    def worker() -> None:
        out["ok"] = card.ask_on_card(task=task, path=path, why="fix a crash", book=book, timeout_s=5)

    t = threading.Thread(target=worker)
    t.start()
    for _ in range(500):
        if book.pending(None):
            break
        threading.Event().wait(0.01)
    row = book.pending(None)[0]
    assert row["kind"] == "card" and row["session_id"] == task
    assert book.answer(row["id"], [answer], password_verified=verified)
    t.join(5)
    return out["ok"]


def test_an_approve_option_cannot_be_answered_without_the_password() -> None:
    """The wall is in the book: anything that reaches it -- an agent, a script,
    the console -- is refused unless the route's password check passed."""
    book = UserQuestionBook()
    record = book.ask(
        question="q",
        options=[{"label": card.APPROVE_FILE, "requires_password": True}, {"label": card.DECLINE}],
        session_id="chat-1",
    )
    assert book.answer(record.id, [card.APPROVE_FILE]) is False
    assert book.pending(None), "a refused answer must leave the card open"
    assert book.answer(record.id, [card.APPROVE_FILE], password_verified=True) is True


def test_no_needs_no_password() -> None:
    book = UserQuestionBook()
    record = book.ask(question="q", options=[{"label": card.APPROVE_FILE, "requires_password": True}, {"label": "No"}])
    assert book.answer(record.id, ["No"]) is True


def test_this_file_reaches_only_this_file_for_this_task() -> None:
    book = UserQuestionBook()
    assert _card_in_a_worker(book, task="chat-1", path="thomas/core/a.py", answer=card.APPROVE_FILE, verified=True)
    assert grants.allowed("chat-1", "thomas/core/a.py")
    assert not grants.allowed("chat-1", "thomas/core/b.py"), "every protected file is its own approval"
    assert not grants.allowed("chat-2", "thomas/core/a.py")


def test_this_whole_task_reaches_every_file_of_that_task_only() -> None:
    book = UserQuestionBook()
    assert _card_in_a_worker(book, task="chat-1", path="thomas/core/a.py", answer=card.APPROVE_TASK, verified=True)
    assert grants.allowed("chat-1", "thomas/server/web/js/x.js")
    assert not grants.allowed("chat-2", "thomas/core/a.py")


def test_everything_reaches_everything_until_revoked() -> None:
    book = UserQuestionBook()
    assert _card_in_a_worker(book, task="chat-1", path="thomas/core/a.py", answer=card.APPROVE_ALL, verified=True)
    assert grants.allowed("chat-9", "anything.py")
    grants.revoke_all()
    assert not grants.allowed("chat-9", "anything.py")


def test_no_grants_nothing() -> None:
    book = UserQuestionBook()
    assert not _card_in_a_worker(book, task="chat-1", path="thomas/core/a.py", answer=card.DECLINE, verified=False)
    assert grants.snapshot() == {"everything": False, "tasks": [], "files": []}


def test_the_server_thread_never_waits_on_a_card() -> None:
    """The answer arrives through a route on the server's own thread; blocking
    it would wait for itself. That thread gets the plain prompt instead."""
    assert threading.current_thread() is threading.main_thread()
    assert card.can_ask_on_a_card("chat-1") is False
    assert card.can_ask_on_a_card("") is False


def test_no_approval_is_reused_by_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """The old default reused a Windows approval for five minutes."""
    calls: list[str] = []
    monkeypatch.setattr(native_auth.platform, "system", lambda: "Windows")
    monkeypatch.setattr(native_auth, "verified_sign_in", lambda action, reason: calls.append(action) or True)
    assert native_auth.request_native_authorization("write a.py", "why")
    assert native_auth.request_native_authorization("write b.py", "why")
    assert calls == ["write a.py", "write b.py"], "the second protected file must ask again"


def _route_app(book: UserQuestionBook) -> web.Application:
    app = web.Application()
    user_questions_routes.setup_user_question_routes(app, book=book)
    return app


def test_the_route_asks_for_the_password_and_keeps_the_card_open_on_no(monkeypatch: pytest.MonkeyPatch) -> None:
    book = UserQuestionBook()
    record = book.ask(
        question="Thomas wants to change one of his protected files",
        options=[{"label": card.APPROVE_FILE, "requires_password": True}, {"label": card.DECLINE}],
        session_id="chat-1",
        kind="card",
        details={"prompt_action": "Let Thomas change thomas/core/a.py"},
    )
    answers = iter([False, True])
    prompted: list[str] = []

    def prompt(action: str, reason: str) -> bool:
        prompted.append(action)
        return next(answers)

    monkeypatch.setattr(native_auth, "request_native_authorization", prompt)
    monkeypatch.setattr(user_questions_routes, "REFUSAL_COOLDOWN_S", 0.0)

    async def go() -> tuple[int, int]:
        client = TestClient(TestServer(_route_app(book)))
        await client.start_server()
        try:
            body = {"selected": [card.APPROVE_FILE], "session_id": "chat-1"}
            refused = await client.post(f"/api/chat/questions/{record.id}/answer", json=body)
            approved = await client.post(f"/api/chat/questions/{record.id}/answer", json=body)
            return refused.status, approved.status
        finally:
            await client.close()

    refused, approved = asyncio.run(go())
    assert (refused, approved) == (403, 200)
    assert prompted == ["Let Thomas change thomas/core/a.py"] * 2
    assert record.result == {"selected": [card.APPROVE_FILE], "other": ""}


def test_every_tool_call_knows_its_chat() -> None:
    """session_scope said the runner binds the session around each tool call;
    nothing did, so cards were filed under no chat and never shown."""
    src = inspect.getsource(loop_tool_exec.execute_tools)
    assert "bind_session(" in src


def test_a_card_thomas_makes_cannot_carry_a_password_option() -> None:
    book = UserQuestionBook()
    tool = AskUserTool(book=book, timeout_s=5)

    async def go():
        async def answer_it() -> dict:
            while not book.pending(None):
                await asyncio.sleep(0.01)
            row = book.pending(None)[0]
            book.answer(row["id"], ["Publish"])
            return row

        helper = asyncio.create_task(answer_it())
        await tool.execute(
            {
                "question": "Publish the report now?",
                "heading": "Before I publish",
                "fields": [{"label": "File", "value": "report.pdf"}],
                "options": [{"label": "Publish", "requires_password": True}, {"label": "Not yet"}],
            }
        )
        return await helper

    row = asyncio.run(go())
    assert row["kind"] == "card" and row["details"]["kicker"] == "Before I publish"
    assert all("requires_password" not in o for o in row["options"])
