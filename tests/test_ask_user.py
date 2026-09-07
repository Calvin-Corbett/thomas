"""The model can ask the person a structured question and wait for the answer.

Frontier parity: Claude Code's AskUserQuestion and ChatGPT's clarifying
prompts render options the person taps; the answer returns as the tool
result and the same run continues. Thomas had a check-in acknowledgement
gate the loop awaited, and nothing anywhere that ever acknowledged it.
"""

from __future__ import annotations

import asyncio

from thomas.core.user_questions import UserQuestionBook
from thomas.tools.ask_user import AskUserTool


def test_an_answer_releases_the_waiting_question_with_the_chosen_label() -> None:
    book = UserQuestionBook()

    async def scenario():
        record = book.ask(question="Which database?", options=[{"label": "SQLite"}, {"label": "Postgres"}])
        assert book.pending()[0]["id"] == record.id
        answered = asyncio.get_running_loop().create_task(book.wait(record.id, timeout_s=5))
        await asyncio.sleep(0)
        assert book.answer(record.id, ["Postgres"]) is True
        result = await answered
        assert result == {"selected": ["Postgres"], "other": ""}
        assert book.pending() == []

    asyncio.run(scenario())


def test_an_unknown_or_already_answered_question_is_refused() -> None:
    book = UserQuestionBook()

    async def scenario():
        record = book.ask(question="Go on?", options=[{"label": "Yes"}, {"label": "No"}])
        waiter = asyncio.get_running_loop().create_task(book.wait(record.id, timeout_s=5))
        await asyncio.sleep(0)
        assert book.answer("nope", ["Yes"]) is False
        assert book.answer(record.id, ["Yes"]) is True
        await waiter
        assert book.answer(record.id, ["No"]) is False

    asyncio.run(scenario())


def test_the_tool_returns_the_answer_as_its_result() -> None:
    book = UserQuestionBook()
    tool = AskUserTool(book=book)

    async def scenario():
        run = asyncio.get_running_loop().create_task(
            tool.execute({"question": "Deploy where?", "options": [{"label": "Staging"}, {"label": "Prod"}]})
        )
        for _ in range(20):
            await asyncio.sleep(0)
            if book.pending():
                break
        question_id = book.pending()[0]["id"]
        book.answer(question_id, ["Staging"], other="")
        result = await run
        assert result.ok is True
        assert result.data["selected"] == ["Staging"]
        assert "Staging" in result.to_content()

    asyncio.run(scenario())


def test_no_answer_in_time_tells_the_model_to_proceed_with_an_assumption() -> None:
    tool = AskUserTool(book=UserQuestionBook(), timeout_s=0.05)

    result = asyncio.run(tool.execute({"question": "Colour?", "options": [{"label": "Red"}, {"label": "Blue"}]}))

    assert result.ok is False
    assert "no answer" in str(result.error).lower()
    assert "assum" in str(result.error).lower()


def test_a_question_needs_text_and_at_least_two_options_or_free_text() -> None:
    tool = AskUserTool(book=UserQuestionBook(), timeout_s=0.05)

    bad = asyncio.run(tool.execute({"question": "", "options": [{"label": "A"}, {"label": "B"}]}))
    assert bad.ok is False and "question" in str(bad.error)
    one = asyncio.run(tool.execute({"question": "Pick", "options": [{"label": "Only"}]}))
    assert one.ok is False and "option" in str(one.error)
    free = asyncio.run(tool.execute({"question": "Name it", "allow_free_text": True}))
    assert "no answer" in str(free.error).lower()


# ── Wiring: registered, never timed out by the tool timeout, reachable over HTTP ──


def test_ask_user_is_registered_with_the_optional_tools() -> None:
    from thomas.server.tool_extensions import register_all_optional_tools
    from thomas.tools.registry import ToolRegistry

    registry = ToolRegistry()
    register_all_optional_tools(registry)
    assert registry.get("ask_user") is not None


def test_the_tool_timeout_does_not_cut_a_question_short() -> None:
    from types import SimpleNamespace

    from thomas.agent.loop_tool_exec import execute_tools
    from thomas.tools.base import ToolResult

    class _SlowAsk:
        async def execute(self, name, args):  # noqa: ANN001, ARG002
            await asyncio.sleep(0.2)
            return ToolResult(ok=True, data={"selected": ["A"]})

    loop = SimpleNamespace(
        _autonomy_level=4,
        _run_id="r",
        _session_id="s",
        _guarded_tool_runner=None,
        _tool_timeout_s=0.05,
        _max_parallel_tools=None,
        _conversation=[],
        tools=_SlowAsk(),
        config=SimpleNamespace(
            tools=SimpleNamespace(sandbox_path="/tmp/sb"), memory=SimpleNamespace(root_path="/tmp/m")
        ),
    )

    async def _audit(**_kw):
        return None

    loop._audit_action = _audit

    async def _collect():
        out = []
        async for ev in execute_tools(
            loop, [{"id": "t1", "name": "ask_user", "arguments": {"question": "?"}}], 0, file_audit_module=None
        ):
            out.append(ev)
        return out

    events = asyncio.run(_collect())
    assert events[0].data["ok"] is True, events[0].data


def test_the_routes_list_and_answer_a_pending_question() -> None:
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from thomas.server.routes.user_questions_routes import setup_user_question_routes

    book = UserQuestionBook()
    app = web.Application()
    setup_user_question_routes(app, book=book, require_api_access=lambda _r: None)

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            record = book.ask(question="Which one?", options=[{"label": "A"}, {"label": "B"}])
            waiter = asyncio.get_running_loop().create_task(book.wait(record.id, timeout_s=5))
            await asyncio.sleep(0)
            listed = await (await client.get("/api/chat/questions")).json()
            assert [q["id"] for q in listed["questions"]] == [record.id]
            posted = await client.post(f"/api/chat/questions/{record.id}/answer", json={"selected": ["B"], "other": ""})
            assert posted.status == 200
            assert await waiter == {"selected": ["B"], "other": ""}
            again = await client.post(f"/api/chat/questions/{record.id}/answer", json={"selected": ["A"]})
            assert again.status == 404

    asyncio.run(scenario())


def test_the_chat_policy_treats_ask_user_as_safe() -> None:
    from thomas.server.chat_runtime_policy_model import ToolRuntimePolicy
    from thomas.server.chat_tool_policy import _is_classified_tool, _tool_denial

    assert _is_classified_tool("ask_user") is True
    locked = ToolRuntimePolicy(
        allow_shell=False,
        allow_file_write=False,
        allow_network=False,
        allow_browser=False,
        allow_channels=False,
        allow_git=False,
        require_command_approval=True,
        tool_timeout_s=120,
        max_parallel_tools=1,
        allowed_paths=[],
        blocked_commands=[],
    )
    assert _tool_denial("ask_user", locked) == ""


def test_the_chat_page_carries_the_question_panel_once() -> None:
    from thomas.server.app_middleware_helpers import inject_ask_user_panel

    page = "<html><body><p>hi</p></body></html>"
    once = inject_ask_user_panel(page)
    assert once.count("ask_user_panel.js") == 1
    assert once.count("slash_palette.js") == 1
    assert once.count("message_feedback.js") == 1
    assert once.endswith("</script></body></html>")
    assert inject_ask_user_panel(once) == once
    assert inject_ask_user_panel("<p>no body</p>") == "<p>no body</p>"
    # chat.html carries "</body>" inside an inline script template; the tag
    # must go before the LAST one or it lands inside that script.
    decoy = "<html><body><script>const t = `</body>`;</script><p>hi</p></body></html>"
    spliced = inject_ask_user_panel(decoy)
    assert spliced.startswith("<html><body><script>const t = `</body>`;</script><p>hi</p><script")


def test_the_settings_page_carries_its_runtime_cards_once() -> None:
    from thomas.server.app_middleware_helpers import inject_settings_parity

    page = "<html><body><p>settings</p></body></html>"
    once = inject_settings_parity(page)
    assert once.count("settings_parity.js") == 1
    assert inject_settings_parity(once) == once
