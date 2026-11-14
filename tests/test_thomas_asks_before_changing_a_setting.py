"""Thomas asks you to change a setting on a card; he cannot change it himself.

Owner direction, 2026-09-22: "if he's going to change a toggle, it should be
announced ... he puts like a card ... says, hey, do you want me to do this? It
will require a password ... And then the user gets to decide". And: "The thing
that stops Thomas from breaking his rules is not words. It's hard gates that
have passwords."

So the tool only asks. The card is the announcement; the wall is the server
(thomas/server/dial_elevation.py), which honours a raised limit only after the
one Thomas password prompt approves it.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from thomas.core import owner_wait
from thomas.core.user_questions import UserQuestionBook
from thomas.tools import setting_request as sr

ROOT = Path(__file__).resolve().parents[1]


def _run(args: dict, answer: list[str] | None) -> tuple:
    book = UserQuestionBook()
    tool = sr.SettingRequestTool(book=book, timeout_s=5)
    seen: dict = {}

    async def go():
        async def answer_it() -> None:
            while not book.pending(None):
                await asyncio.sleep(0.01)
            seen["card"] = book.pending(None)[0]
            seen["waiting"] = owner_wait.seconds_since_owner_wait()
            book.answer(seen["card"]["id"], answer)

        helper = asyncio.create_task(answer_it()) if answer is not None else None
        result = await tool.execute(args)
        if helper is not None:
            await helper
        return result

    return asyncio.run(go()), seen


ASK = {"setting": "internet", "value": "open", "reason": "The fix needs to download a package."}


def test_the_card_says_what_and_why_and_is_drawn_as_a_setting_card() -> None:
    result, seen = _run(ASK, [sr.APPROVED])
    card = seen["card"]
    assert card["kind"] == "setting_change"
    assert card["question"] == "Thomas wants to change Reaching the internet to Open"
    assert card["details"] == {
        "setting": "internet",
        "dial": "guardrails",
        "client_key": "guardrails",
        "label": "Reaching the internet",
        "value": "open",
        "value_label": "Open",
        "reason": "The fix needs to download a package.",
    }
    assert seen["waiting"] == 0.0, "waiting on the card must not count as a stuck worker"
    assert result.ok and "applies from the owner's next message" in result.data


@pytest.mark.parametrize("answer", [sr.DECLINED, sr.PASSWORD_REFUSED])
def test_no_and_a_refused_password_both_leave_it_unchanged(answer: str) -> None:
    result, _ = _run(ASK, [answer])
    assert not result.ok and "unchanged" in result.error


@pytest.mark.parametrize(
    "args",
    [
        {"setting": "self_destruct", "value": "yes", "reason": "x"},
        {"setting": "autonomy", "value": "9", "reason": "x"},
        {"setting": "file_access", "value": "full", "reason": "x"},  # not offered in the menu
        {"setting": "autonomy", "value": "5", "reason": ""},
    ],
)
def test_nothing_unknown_or_unexplained_reaches_a_card(args: dict) -> None:
    result, seen = _run(args, None)
    assert not result.ok and "card" not in seen


def test_the_tool_has_no_way_to_change_a_setting_itself() -> None:
    """It can only ask. The change is the owner's click, then the server's check."""
    src = (ROOT / "thomas/tools/setting_request.py").read_text(encoding="utf-8")
    code = src.split('"""', 2)[2]
    for forbidden in ("dial_elevation", "approve(", "verified_sign_in", "thomas_dials", "PreferencesStore"):
        assert forbidden not in code, f"setting_request reaches for {forbidden}"


def test_the_card_labels_are_the_menu_labels() -> None:
    js = (ROOT / "thomas/server/web/js/chat_preferences.js").read_text(encoding="utf-8")
    for spec in sr.SETTINGS.values():
        assert f"label: '{spec['label']}'" in js or f'label: "{spec["label"]}"' in js, spec["label"]
        for value, label in spec["values"].items():
            quoted = re.escape(label).replace("'", "(?:'|’)")
            assert re.search(rf"\[\s*'?{re.escape(value)}'?,\s*[\"']{quoted}[\"']", js), (value, label)


def test_the_card_answers_with_the_words_the_tool_listens_for() -> None:
    js = (ROOT / "thomas/server/web/js/ask_user_panel.js").read_text(encoding="utf-8")
    for word in (sr.APPROVED, sr.DECLINED, sr.PASSWORD_REFUSED):
        assert f"'{word}'" in js, f"the card never answers {word!r}"
    assert "/api/security/elevate" in js, "Yes on a raised limit must go through the server's password gate"


def _operator(events: list, session_id: str = "chat-1"):
    from thomas.server.chat_inline_actions import ChatInlineOperator

    async def emit(event: dict) -> None:
        events.append(event)

    return ChatInlineOperator(
        tools=None,
        guarded_runner=None,
        config=None,
        session_id=session_id,
        autonomy_level=1,
        user_prompt="",
        emit_event=emit,
    )


def test_chat_asks_through_the_card_even_at_the_lowest_autonomy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chat's model reaches settings through `operate`. Asking is not acting, so
    it works at every level, and the card belongs to the chat that asked."""
    book = UserQuestionBook()
    monkeypatch.setattr(sr, "question_book", lambda: book)
    events: list = []

    async def go():
        async def answer_it() -> dict:
            while not book.pending(None):
                await asyncio.sleep(0.01)
            card = book.pending(None)[0]
            book.answer(card["id"], [sr.DECLINED])
            return card

        helper = asyncio.create_task(answer_it())
        receipt = await _operator(events).execute(
            action="settings.request_change", key="autonomy", value=5, reason="The fix needs Autopilot."
        )
        return receipt, await helper

    receipt, card = asyncio.run(go())
    assert card["session_id"] == "chat-1" and card["kind"] == "setting_change"
    assert receipt["ok"] is False and "unchanged" in receipt["error"]


def test_a_setting_cannot_be_faked_as_a_preference_note() -> None:
    """Observed 2026-09-22: asked to go offline, Thomas wrote a free-form note
    and replied "Internet reach is now Off". Nothing reads that note; the reply
    was false. The note is refused and he is pointed at the card."""
    events: list = []
    receipt = asyncio.run(_operator(events).execute(action="preferences.set", key="internet_reach", value="off"))
    assert receipt["ok"] is False and "settings.request_change" in receipt["error"]


def test_the_operate_tool_offers_the_card_and_says_notes_are_not_settings() -> None:
    from thomas.core.send_task_tool import OPERATE_TOOL

    fn = OPERATE_TOOL["function"]
    assert "settings.request_change" in fn["parameters"]["properties"]["action"]["enum"]
    assert "reason" in fn["parameters"]["properties"]
    assert "do NOT control your own settings" in fn["description"]


def test_it_is_registered_classified_and_allowed_to_wait() -> None:
    from thomas.agent.loop_tool_exec import _waits_on_the_person
    from thomas.server.chat_tool_policy import _is_classified_tool
    from thomas.tools.registry import ToolRegistry

    registry = ToolRegistry()
    sr.register_setting_request_tool(registry)
    assert registry.get("settings.request_change") is not None
    assert _is_classified_tool("settings.request_change")
    assert _waits_on_the_person("settings.request_change")
