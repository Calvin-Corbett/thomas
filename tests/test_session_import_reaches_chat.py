"""An imported conversation must land where the chat reads."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from thomas.server.routes import sessions_aiohttp as sessions
from thomas.server.routes.chat_v2_keys import APP_SESSION_STORE


class _Req:
    def __init__(self, app: dict) -> None:
        self.app = app


@pytest.mark.asyncio
async def test_an_imported_conversation_is_published_to_the_chat_store() -> None:
    """The post-restart amnesia.

    APP_SESSIONS is written in four places, all in sessions_aiohttp, and read in
    none -- /api/v2/chat loads from SessionStore. So the reconnect flow handed
    the on-screen history to /api/session/import, got a session id back, and the
    next message started from nothing while every imported message was still
    visible. Tell it a codeword, reconnect, ask for the codeword: "Unknown".
    """
    store = SimpleNamespace(save=AsyncMock(return_value=True))
    req = _Req({APP_SESSION_STORE: store})
    messages = [
        {"role": "user", "content": "Remember the codeword: PELICAN-42."},
        {"role": "assistant", "content": "Got it."},
    ]

    published = await sessions._publish_to_chat_store(
        req, "sid-1", messages, profile="openai_codex", model_id="gpt-5.6-sol", autonomy_level=2
    )

    assert published is True
    store.save.assert_awaited_once()
    saved_sid, conversation = store.save.await_args.args[0], store.save.await_args.args[1]
    assert saved_sid == "sid-1"
    assert "PELICAN-42" in str(conversation.get_messages())


@pytest.mark.asyncio
async def test_publishing_never_breaks_session_creation() -> None:
    """Best effort by design: a store failure must not stop the session being
    created, it only means the history is not carried across."""
    store = SimpleNamespace(save=AsyncMock(side_effect=OSError("disk gone")))
    req = _Req({APP_SESSION_STORE: store})

    assert await sessions._publish_to_chat_store(req, "sid", [{"role": "user", "content": "hi"}]) is False


@pytest.mark.asyncio
async def test_nothing_is_published_when_there_is_no_history() -> None:
    store = SimpleNamespace(save=AsyncMock())
    req = _Req({APP_SESSION_STORE: store})

    assert await sessions._publish_to_chat_store(req, "sid", []) is False
    store.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_missing_store_is_survivable() -> None:
    assert await sessions._publish_to_chat_store(_Req({}), "sid", [{"role": "user", "content": "hi"}]) is False
