"""The model keeps a visible checklist for multi-step work (frontier parity: Claude Code TodoWrite)."""

from __future__ import annotations

import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.core.todo_book import TodoBook
from thomas.server.routes.todo_routes import setup_todo_routes
from thomas.tools.todo import TodoWriteTool


def test_writing_replaces_the_list_and_an_empty_write_clears_it() -> None:
    book = TodoBook()
    first = book.write(
        "s1",
        title="Ship the fix",
        items=[{"text": "Write the test", "status": "in_progress"}, {"text": "Fix", "status": "pending"}],
    )
    assert [i["status"] for i in first["items"]] == ["in_progress", "pending"]
    second = book.write(
        "s1",
        title="Ship the fix",
        items=[{"text": "Write the test", "status": "done"}, {"text": "Fix", "status": "in_progress"}],
    )
    assert [i["status"] for i in second["items"]] == ["done", "in_progress"]
    assert len(book.all()) == 1
    assert book.write("s1", title="", items=[]) is None
    assert book.all() == []


def test_the_newest_list_comes_first_and_bad_items_are_dropped() -> None:
    book = TodoBook()
    book.write("a", title="Old", items=[{"text": "one"}])
    book.write("b", title="New", items=[{"text": "two", "status": "nonsense"}, {"text": ""}, 42])
    latest = book.all()[0]
    assert latest["title"] == "New"
    assert latest["items"] == [{"text": "two", "status": "pending"}]


def test_the_tool_rejects_more_than_one_item_in_progress_and_empty_text() -> None:
    tool = TodoWriteTool(book=TodoBook())
    two = asyncio.run(
        tool.execute({"items": [{"text": "a", "status": "in_progress"}, {"text": "b", "status": "in_progress"}]})
    )
    assert two.ok is False and "one item" in (two.error or "")
    nothing = asyncio.run(tool.execute({"items": [{"text": "   "}]}))
    assert nothing.ok is False


def test_the_tool_reports_progress_in_its_result() -> None:
    book = TodoBook()
    tool = TodoWriteTool(book=book)
    result = asyncio.run(
        tool.execute(
            {
                "title": "Cargo report",
                "items": [
                    {"text": "Read the CSV", "status": "done"},
                    {"text": "Compute turnaround", "status": "in_progress"},
                    {"text": "Write the summary", "status": "pending"},
                ],
            }
        )
    )
    assert result.ok is True
    assert result.data["done"] == 1
    assert result.data["in_progress"] == "Compute turnaround"
    assert result.data["remaining"] == 2
    assert book.all()[0]["title"] == "Cargo report"


def test_the_route_never_broadcasts_every_chats_list() -> None:
    book = TodoBook()
    book.write("s1", title="First", items=[{"text": "x"}])
    book.write("s2", title="Second", items=[{"text": "y", "status": "done"}])
    app = web.Application()
    setup_todo_routes(app, book=book, require_api_access=lambda _r: None)

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            res = await client.get("/api/chat/todos")
            assert res.status == 200
            return await res.json()

    body = asyncio.run(scenario())
    # no session id: nothing of anyone's; each chat asks for its own (test_session_scope covers the scoped read)
    assert body["todos"] == []


def test_todo_write_is_registered_and_treated_as_safe() -> None:
    from thomas.server.chat_tool_policy_model import _SAFE_READ_TOOLS
    from thomas.server.tool_extensions import register_all_optional_tools
    from thomas.tools.registry import ToolRegistry

    registry = ToolRegistry()
    register_all_optional_tools(registry)
    assert registry.get("todo.write") is not None
    assert "todo.write" in _SAFE_READ_TOOLS


def test_the_chat_page_carries_the_panel_once() -> None:
    from thomas.server.app_middleware_helpers import inject_ask_user_panel

    once = inject_ask_user_panel("<html><body><p>hi</p></body></html>")
    assert once.count("todo_panel.js") == 1
    assert inject_ask_user_panel(once) == once
