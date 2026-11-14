"""Only offered answers may settle a question, and only one answer may win."""

from __future__ import annotations

import asyncio
import threading

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.core.user_questions import UserQuestionBook
from thomas.server.routes.user_questions_routes import setup_user_question_routes
from thomas.tools.ask_user import AskUserTool
from thomas.tools.setting_request import PASSWORD_REFUSED


def _options(*labels: str) -> list[dict[str, str]]:
    return [{"label": label} for label in labels]


def test_single_select_refuses_every_answer_it_did_not_offer() -> None:
    book = UserQuestionBook()
    record = book.ask(question="Pick one?", options=_options("A", "B"))

    for selected, other in [(["Z"], ""), (["A", "B"], ""), ([], "hello"), ([], ""), ("", "")]:
        assert book.answer(record.id, selected, other=other) is False
        assert [row["id"] for row in book.pending()] == [record.id]

    assert book.answer(record.id, ["B"]) is True
    assert record.result == {"selected": ["B"], "other": ""}


def test_answer_problem_explains_why_a_question_remains_open() -> None:
    book = UserQuestionBook()
    record = book.ask(question="Pick one?", options=_options("A", "B"))

    assert book.answer_problem(record.id, ["Z"]) == "That is not one of this question's options."
    assert book.answer_problem(record.id, ["A", "B"]) == "This question takes one answer."
    assert book.answer_problem(record.id, [], other="hello") == "This question does not take a typed answer."
    assert book.answer_problem(record.id, [], other="") == "Pick an option or type an answer."
    assert book.answer_problem(record.id, ["Z", "A"], other="hello") == "That is not one of this question's options."
    assert book.answer_problem(record.id, ["A"]) == ""
    assert book.answer_problem("missing", ["Z"]) == ""


def test_multi_select_refuses_unknown_options_but_takes_multiple_known_options() -> None:
    book = UserQuestionBook()
    record = book.ask(question="Pick some?", options=_options("A", "B", "C"), multi_select=True)

    assert book.answer(record.id, ["A", "D"]) is False
    assert [row["id"] for row in book.pending()] == [record.id]
    assert book.answer(record.id, ["A", "C"]) is True
    assert record.result == {"selected": ["A", "C"], "other": ""}


def test_questions_that_allow_free_text_take_it() -> None:
    book = UserQuestionBook()
    text = book.ask(question="Name it?", allow_free_text=True)
    assert book.answer(text.id, [], other="call it Bob") is True
    assert text.result == {"selected": [], "other": "call it Bob"}

    mixed = book.ask(question="Pick and explain?", options=_options("A", "B"), multi_select=True, allow_free_text=True)
    assert book.answer(mixed.id, ["A"], other="and a note") is True
    assert mixed.result == {"selected": ["A"], "other": "and a note"}


def test_cards_and_ask_user_headings_refuse_unoffered_labels() -> None:
    book = UserQuestionBook()
    card = book.ask(question="Continue?", options=_options("Yes", "No"), kind="card")
    assert book.answer(card.id, ["Maybe"]) is False
    assert [row["id"] for row in book.pending()] == [card.id]
    assert book.answer(card.id, ["Yes"]) is True
    assert card.result == {"selected": ["Yes"], "other": ""}

    async def scenario() -> None:
        tool = AskUserTool(book=book)
        run = asyncio.create_task(
            tool.execute(
                {"question": "Deploy where?", "heading": "Before deploy", "options": _options("Staging", "Prod")}
            )
        )
        for _ in range(20):
            await asyncio.sleep(0)
            if book.pending():
                break
        rows = book.pending()
        assert len(rows) == 1
        assert rows[0]["kind"] == "card"
        question_id = rows[0]["id"]
        assert book.answer(question_id, ["Z"]) is False
        assert [row["id"] for row in book.pending()] == [question_id]
        assert book.answer(question_id, ["Staging"]) is True
        result = await run
        assert result.ok is True
        assert result.data["selected"] == ["Staging"]

    asyncio.run(scenario())


def test_setting_change_still_accepts_its_password_refusal_sentinel() -> None:
    book = UserQuestionBook()
    record = book.ask(question="Change setting?", options=_options("Yes", "No"), kind="setting_change")
    assert book.answer(record.id, [PASSWORD_REFUSED]) is True
    assert record.result == {"selected": [PASSWORD_REFUSED], "other": ""}


def test_route_refuses_unoffered_option_and_keeps_question_open() -> None:
    book = UserQuestionBook()
    app = web.Application()
    setup_user_question_routes(app, book=book, require_api_access=lambda _r: None)

    async def scenario() -> None:
        async with TestClient(TestServer(app)) as client:
            record = book.ask(question="Pick one?", options=_options("A", "B"))
            url = f"/api/chat/questions/{record.id}/answer"
            bad = await client.post(url, json={"selected": ["Z"], "other": ""})
            assert bad.status != 200
            listed = await (await client.get("/api/chat/questions")).json()
            assert [row["id"] for row in listed["questions"]] == [record.id]
            good = await client.post(url, json={"selected": ["A"], "other": ""})
            assert good.status == 200
            assert record.result == {"selected": ["A"], "other": ""}

    asyncio.run(scenario())


def test_two_simultaneous_answers_deliver_only_the_winner(monkeypatch) -> None:
    book = UserQuestionBook()
    record = book.ask(question="Pick one?", options=_options("A", "B"))
    barrier = threading.Barrier(2)

    def fake_needs_password(question_id: str, selected: list[str]) -> bool:
        try:
            barrier.wait(timeout=1.0)
        except threading.BrokenBarrierError:
            pass
        return False

    monkeypatch.setattr(book, "needs_password", fake_needs_password)
    outcomes: dict[str, bool | BaseException] = {}

    def submit(label: str) -> None:
        try:
            outcomes[label] = book.answer(record.id, [label])
        except BaseException as exc:  # capture any thread failure for an assertion in the test thread
            outcomes[label] = exc

    threads = [threading.Thread(target=submit, args=(label,)) for label in ("A", "B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10.0)
    assert all(not thread.is_alive() for thread in threads)
    assert set(outcomes) == {"A", "B"}
    assert sorted(outcomes.values(), key=str) == [False, True]
    winner = next(label for label, outcome in outcomes.items() if outcome is True)
    assert record.result == {"selected": [winner], "other": ""}
    assert record.answered.is_set() is True
    assert book.pending() == []
