"""Questions and checklists belong to the chat that raised them (2026-09-05).

codex's finding: the tools read ``_session_id`` from model args (forgeable, and
never sent), the books answered every caller with every row, and the answer
route bound nothing. Now the runner binds the session in a core context
variable, the tools read only that, the books scope by it, and an answer from
another chat is refused.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.core.session_scope import active_session_id, bind_session
from thomas.core.todo_book import TodoBook
from thomas.core.user_questions import UserQuestionBook
from thomas.server.routes.todo_routes import setup_todo_routes
from thomas.server.routes.user_questions_routes import setup_user_question_routes
from thomas.tools.ask_user import AskUserTool
from thomas.tools.todo import TodoWriteTool


def test_the_bound_session_is_visible_inside_and_gone_after() -> None:
    assert active_session_id() == ""
    with bind_session("chat-A"):
        assert active_session_id() == "chat-A"
        with bind_session("chat-B"):
            assert active_session_id() == "chat-B"
        assert active_session_id() == "chat-A"
    assert active_session_id() == ""


def test_the_tools_take_the_bound_session_and_ignore_a_forged_one() -> None:
    questions = UserQuestionBook()
    todos = TodoBook()
    ask = AskUserTool(book=questions, timeout_s=0.05)
    todo = TodoWriteTool(book=todos)

    async def run():
        with bind_session("chat-A"):
            await todo.execute({"_session_id": "chat-FORGED", "items": [{"text": "step"}]})
            # no answer arrives: the tool returns its timeout result rather than raising
            timed_out = await ask.execute(
                {"_session_id": "chat-FORGED", "question": "Which?", "options": [{"label": "x"}, {"label": "y"}]}
            )
            assert timed_out.ok is False and "assumption" in (timed_out.error or "")

    asyncio.run(run())
    assert todos.get("chat-A") is not None and todos.get("chat-FORGED") is None
    # the question timed out and was forgotten; nothing was ever filed under the forged id
    assert questions.pending("chat-FORGED") == []


def test_pending_is_scoped_and_unscoped_rows_are_opt_in() -> None:
    book = UserQuestionBook()
    a = book.ask(question="A?", options=[{"label": "1"}, {"label": "2"}], session_id="chat-A")
    b = book.ask(question="B?", options=[{"label": "1"}, {"label": "2"}], session_id="chat-B")
    headless = book.ask(question="H?", options=[{"label": "1"}, {"label": "2"}], session_id="")
    assert [q["id"] for q in book.pending("chat-A")] == [a.id]
    assert [q["id"] for q in book.pending("chat-B")] == [b.id]
    assert [q["id"] for q in book.pending("")] == [headless.id]
    assert {q["id"] for q in book.pending(None)} == {a.id, b.id, headless.id}


def test_an_answer_from_another_chat_is_refused_by_the_book_and_the_route() -> None:
    book = UserQuestionBook()
    q = book.ask(question="A?", options=[{"label": "1"}, {"label": "2"}], session_id="chat-A")
    assert book.answer(q.id, ["1"], session_id="chat-B") is False
    assert book.pending("chat-A") != []
    assert book.answer(q.id, ["1"], session_id="chat-A") is True

    q2 = book.ask(question="A2?", options=[{"label": "1"}, {"label": "2"}], session_id="chat-A")
    app = web.Application()
    setup_user_question_routes(app, book=book, require_api_access=lambda _r: None)

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            wrong = await client.post(
                f"/api/chat/questions/{q2.id}/answer", json={"selected": ["1"], "session_id": "chat-B"}
            )
            missing = await client.post(f"/api/chat/questions/{q2.id}/answer", json={"selected": ["1"]})
            listed_b = await client.get("/api/chat/questions?session_id=chat-B")
            right = await client.post(
                f"/api/chat/questions/{q2.id}/answer", json={"selected": ["1"], "session_id": "chat-A"}
            )
            return wrong.status, missing.status, (await listed_b.json())["questions"], right.status

    assert asyncio.run(scenario()) == (403, 403, [], 200)


def test_a_headless_question_still_takes_an_answer_without_a_session() -> None:
    book = UserQuestionBook()
    q = book.ask(question="H?", options=[{"label": "1"}, {"label": "2"}], session_id="")
    assert book.answer(q.id, ["1"]) is True


def test_the_todo_route_returns_one_chat_and_never_broadcasts(tmp_path: Path) -> None:
    book = TodoBook()
    book.write("chat-A", title="A", items=[{"text": "a"}])
    book.write("chat-B", title="B", items=[{"text": "b"}])
    book.write("", title="headless", items=[{"text": "h"}])
    app = web.Application()
    setup_todo_routes(app, book=book, require_api_access=lambda _r: None)

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            a = await client.get("/api/chat/todos?session_id=chat-A")
            none = await client.get("/api/chat/todos")
            return [t["title"] for t in (await a.json())["todos"]], [t["title"] for t in (await none.json())["todos"]]

    assert asyncio.run(scenario()) == (["A"], ["headless"])


def test_a_cancelled_wait_forgets_the_question() -> None:
    """codex's runner cancels the specialist turn at its deadline; the question must
    not stay pending on the page for a run that has already gone."""
    book = UserQuestionBook()
    tool = AskUserTool(book=book, timeout_s=60)

    async def run():
        with bind_session("chat-a"):
            task = asyncio.create_task(
                tool.execute({"question": "Which?", "options": [{"label": "x"}, {"label": "y"}]})
            )
            await asyncio.sleep(0.05)
            assert len(book.pending("chat-a")) == 1
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        return book.pending("chat-a")

    assert asyncio.run(run()) == []


def test_the_route_without_a_session_lists_only_headless_questions_never_every_chats() -> None:
    """codex's finding: an absent session_id was coerced to None, and pending(None)
    is the console answerer's "everything" view, so GET /api/chat/questions with
    no session broadcast every conversation's questions."""
    book = UserQuestionBook()
    book.ask(question="A?", options=[{"label": "1"}, {"label": "2"}], session_id="chat-A")
    book.ask(question="B?", options=[{"label": "1"}, {"label": "2"}], session_id="chat-B")
    headless = book.ask(question="H?", options=[{"label": "1"}, {"label": "2"}], session_id="")
    app = web.Application()
    setup_user_question_routes(app, book=book, require_api_access=lambda _r: None)

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            none = await (await client.get("/api/chat/questions")).json()
            empty = await (await client.get("/api/chat/questions?session_id=")).json()
            only_a = await (await client.get("/api/chat/questions?session_id=chat-A")).json()
            return [q["id"] for q in none["questions"]], [q["id"] for q in empty["questions"]], len(only_a["questions"])

    assert asyncio.run(scenario()) == ([headless.id], [headless.id], 1)
