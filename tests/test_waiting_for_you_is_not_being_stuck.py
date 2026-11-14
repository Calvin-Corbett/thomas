"""A worker waiting for the owner must not be failed as stuck.

Observed live on 2026-09-22: on Autopilot, Thomas's self-development worker
reached a protected file and the password prompt opened on your screen. The
worker watchdog counts seconds since the last progress event; after 135 it
failed the task -- "provider-native worker produced no further progress within
135s" -- while the prompt was still open. You were looking at a prompt for a
task that had already been given up.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from scripts import breakglass_auth

from thomas.core import owner_wait
from thomas.core.user_questions import UserQuestionBook
from thomas.server.chat_delegation_session import _heartbeat_age_s
from thomas.tools import windows_auth
from thomas.tools.ask_user import AskUserTool


@pytest.fixture(autouse=True)
def _fresh() -> None:
    owner_wait.reset()
    yield
    owner_wait.reset()


def _record_seconds_old(seconds: float) -> dict:
    stamp = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return {"last_heartbeat_at": stamp.isoformat()}


def test_a_silent_worker_still_ages_when_nobody_is_being_asked() -> None:
    """The watchdog is not disabled: a genuinely stuck worker still times out."""
    assert _heartbeat_age_s(_record_seconds_old(500)) >= 499


def test_the_clock_stops_while_you_are_being_asked() -> None:
    with owner_wait.awaiting_owner():
        assert _heartbeat_age_s(_record_seconds_old(500)) == 0.0


def test_answering_restarts_the_grace_period_instead_of_firing_at_once() -> None:
    """After a long prompt the record's last heartbeat is minutes old; the
    watchdog must measure from your answer, not from that heartbeat."""
    with owner_wait.awaiting_owner():
        pass
    assert _heartbeat_age_s(_record_seconds_old(500)) < 5


def test_the_password_prompt_marks_the_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list = []

    def prompt(*, prompt_caption: str, prompt_message: str):
        seen.append(owner_wait.seconds_since_owner_wait())
        return SimpleNamespace(ok=True)

    monkeypatch.setattr(breakglass_auth, "_run_windows_credential_prompt", prompt)
    monkeypatch.setattr(windows_auth.platform, "system", lambda: "Windows")
    assert windows_auth.verified_sign_in("write a protected file", "self-fix") is True
    assert seen == [0.0], "the prompt was open but the watchdog clock kept running"


def test_a_question_card_marks_the_wait() -> None:
    book = UserQuestionBook()
    tool = AskUserTool(book=book, timeout_s=5)
    seen: list = []

    async def run() -> None:
        async def answer_when_asked() -> None:
            while not book.pending(None):
                await asyncio.sleep(0.01)
            seen.append(owner_wait.seconds_since_owner_wait())
            book.answer(book.pending(None)[0]["id"], ["Yes"])

        answering = asyncio.create_task(answer_when_asked())
        result = await tool.execute({"question": "Go?", "options": ["Yes", "No"]})
        await answering
        assert result.ok

    asyncio.run(run())
    assert seen == [0.0]
