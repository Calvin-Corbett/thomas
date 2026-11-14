from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from aiohttp import web

from thomas.chat.session_store import SessionMeta
from thomas.server.app_keys import APP_SESSION_LOCKS, APP_SESSION_LOCKS_LOCK
from thomas.server.routes import chat_v2 as mod


@pytest.mark.asyncio
async def test_announce_delegation_presents_exact_max_verified_answer_without_rewriting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aiohttp.test_utils import make_mocked_request

    from thomas.core import task_bot_runtime

    answer = "# Audited decision\n\nChat wins 94/100.\n\nMAX_VERIFIED_ANSWER"

    class _FakeStore:
        async def load_meta(self, sid):
            return SessionMeta(session_id=sid)

        def __init__(self) -> None:
            self.loaded = mod.ConversationManager().append_message("assistant", "Max review is running.")
            self.saved = None

        async def load(self, sid: str):  # noqa: ANN201
            return self.loaded

        async def save(self, sid: str, conversation, meta, force: bool = False) -> None:  # noqa: ANN001
            self.saved = (sid, conversation, meta, force)

    app = web.Application()
    app[APP_SESSION_LOCKS] = {}
    app[APP_SESSION_LOCKS_LOCK] = asyncio.Lock()
    store = _FakeStore()
    app[mod.APP_SESSION_STORE] = store
    monkeypatch.setattr(
        task_bot_runtime,
        "get_execution",
        lambda eid, *a, **k: {
            "execution_id": eid,
            "conversation_id": "sess-max-answer",
            "state": "completed",
            "proof_status": "verified",
            "runtime_profile": {
                "max_answer_only": True,
                "max_verified_answer_text": answer,
            },
            "progress_summary": "Audited decision ready.",
            "bot_name": "Max crew",
        },
    )
    updates: list[tuple[str, dict]] = []
    monkeypatch.setattr(task_bot_runtime, "update_execution", lambda eid, **kw: updates.append((eid, kw)))
    req = make_mocked_request(
        "POST",
        "/x",
        match_info={"session_id": "sess-max-answer", "execution_id": "exec-max-answer"},
        app=app,
    )

    resp = await mod.handle_announce_delegation(req)

    assert resp.status == 200
    assert json.loads(resp.text)["message"] == answer
    assert store.saved is not None
    assert store.saved[1].last_assistant_message() == answer
    assert updates and "reported_to_chat_at" in updates[0][1]


@pytest.mark.asyncio
async def test_announce_delegation_presents_verified_text_deliverable_without_rewriting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aiohttp.test_utils import make_mocked_request

    from thomas.core import task_bot_runtime

    answer = (
        "## Eight-step QA plan\n\n"
        "1. Start a long Chat task.\n"
        "2. Switch to Code while Chat is running.\n"
        "3. Return and verify the exact final marker.\n\n"
        "CHAT_SWITCH_SURVIVED_0718"
    )

    class _NoRewriteLLM:
        def stream_chat(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("verified text deliverable must not be rewritten")

    class _FakeStore:
        async def load_meta(self, sid):
            return SessionMeta(session_id=sid)

        def __init__(self) -> None:
            self.loaded = mod.ConversationManager().append_message("user", "Give me an eight-step QA plan.")
            self.saved = None

        async def load(self, sid: str):  # noqa: ANN201
            return self.loaded

        async def save(self, sid: str, conversation, meta, force: bool = False) -> None:  # noqa: ANN001
            self.saved = (sid, conversation, meta, force)

    app = web.Application()
    app[APP_SESSION_LOCKS] = {}
    app[APP_SESSION_LOCKS_LOCK] = asyncio.Lock()
    store = _FakeStore()
    app[mod.APP_SESSION_STORE] = store
    app[mod.APP_SESSION_LLM_CACHE] = {"sess-text": SimpleNamespace(llm=_NoRewriteLLM())}
    monkeypatch.setattr(
        task_bot_runtime,
        "get_execution",
        lambda eid, *a, **k: {
            "execution_id": eid,
            "conversation_id": "sess-text",
            "state": "completed",
            "summary": "Give me an eight-step QA plan.",
            "progress_summary": answer,
            "proof_status": "verified",
            "proof": {"status": "verified", "artifacts": []},
            "bot_name": "Zach",
        },
    )
    updates: list[tuple[str, dict]] = []
    monkeypatch.setattr(task_bot_runtime, "update_execution", lambda eid, **kw: updates.append((eid, kw)))
    request = make_mocked_request(
        "POST",
        "/x",
        match_info={"session_id": "sess-text", "execution_id": "exec-text"},
        app=app,
    )

    response = await mod.handle_announce_delegation(request)

    assert response.status == 200
    assert json.loads(response.text)["message"] == answer
    assert store.saved is not None
    assert store.saved[1].last_assistant_message() == answer
    assert updates and "reported_to_chat_at" in updates[0][1]


@pytest.mark.asyncio
async def test_announce_delegation_never_echoes_task_title_as_verified_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aiohttp.test_utils import make_mocked_request

    from thomas.core import task_bot_runtime

    class _FakeStore:
        async def load_meta(self, sid):
            return SessionMeta(session_id=sid)

        def __init__(self) -> None:
            self.loaded = mod.ConversationManager().append_message("user", "Give me an eight-step plan.")
            self.saved = None

        async def load(self, sid: str):  # noqa: ANN201
            return self.loaded

        async def save(self, sid: str, conversation, meta, force: bool = False) -> None:  # noqa: ANN001
            self.saved = (sid, conversation, meta, force)

    app = web.Application()
    app[APP_SESSION_LOCKS] = {}
    app[APP_SESSION_LOCKS_LOCK] = asyncio.Lock()
    store = _FakeStore()
    app[mod.APP_SESSION_STORE] = store
    monkeypatch.setattr(
        task_bot_runtime,
        "get_execution",
        lambda eid, *a, **k: {
            "execution_id": eid,
            "conversation_id": "sess-missing-text",
            "state": "completed",
            "summary": "Give me an eight-step plan.",
            "progress_summary": "",
            "proof_status": "verified",
            "proof": {"status": "verified", "artifacts": []},
        },
    )
    monkeypatch.setattr(
        task_bot_runtime,
        "update_execution",
        lambda *args, **kwargs: pytest.fail("missing text must not be marked reported"),
    )
    request = make_mocked_request(
        "POST",
        "/x",
        match_info={"session_id": "sess-missing-text", "execution_id": "exec-missing-text"},
        app=app,
    )

    response = await mod.handle_announce_delegation(request)

    assert response.status == 200
    assert json.loads(response.text) == {"ok": True, "skipped": "verified_text_missing"}
    assert store.saved is None
