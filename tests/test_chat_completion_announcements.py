from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from aiohttp import web

from thomas.chat.session_store import SessionMeta
from thomas.server.app_keys import APP_SESSION_LOCKS, APP_SESSION_LOCKS_LOCK
from thomas.server.routes import chat_v2 as mod


def test_announcement_lock_reuses_session_llm_lock_and_fallback() -> None:
    app = web.Application()
    app[APP_SESSION_LOCKS] = {}
    app[APP_SESSION_LOCKS_LOCK] = asyncio.Lock()
    cached = asyncio.Lock()
    app[mod.APP_SESSION_LLM_CACHE] = {"cached": SimpleNamespace(lock=cached)}
    app[mod.APP_ANNOUNCE_LOCKS] = {}
    assert mod._announcement_lock_for(app, "cached") is cached

    fallback = mod._announcement_lock_for(app, "other")
    assert mod._announcement_lock_for(app, "other") is fallback
    assert mod._UNSUPPORTED_GAP_CLAIM_RE.search("report.html is ready; the other item still needs to be created")
    assert mod._UNSUPPORTED_GAP_CLAIM_RE.search("report.html is ready; the remaining task is pending")
    for claim in (
        "the recipe isn't ready",
        "I didn't finish the recipe",
        "the recipe is still pending",
        "the recipe has yet to land",
        "The chart is forthcoming",
        "The rest will follow shortly",
    ):
        assert mod._UNSUPPORTED_GAP_CLAIM_RE.search(claim), claim


@pytest.mark.asyncio
async def test_announce_delegation_skips_already_reported_or_non_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock

    from aiohttp.test_utils import make_mocked_request

    from thomas.core import task_bot_runtime

    app = web.Application()
    app[APP_SESSION_LOCKS] = {}
    app[APP_SESSION_LOCKS_LOCK] = asyncio.Lock()
    app[mod.APP_SESSION_STORE] = SimpleNamespace(load=AsyncMock(return_value=mod.ConversationManager()))

    def _req(sid: str, eid: str):
        return make_mocked_request("POST", "/x", match_info={"session_id": sid, "execution_id": eid}, app=app)

    monkeypatch.setattr(
        task_bot_runtime,
        "get_execution",
        lambda eid, *a, **k: {"conversation_id": "sess-1", "reported_to_chat_at": "2026-06-17T00:00:00Z"},
    )
    resp = await mod.handle_announce_delegation(_req("sess-1", "exec-9"))
    assert resp.status == 200
    assert resp.text is not None
    assert "already_reported" in resp.text

    monkeypatch.setattr(
        task_bot_runtime,
        "get_execution",
        lambda eid, *a, **k: {"conversation_id": "sess-1", "state": "running"},
    )
    resp = await mod.handle_announce_delegation(_req("sess-1", "exec-9"))
    assert resp.status == 200
    assert resp.text is not None
    assert "not_terminal" in resp.text

    monkeypatch.setattr(
        task_bot_runtime,
        "get_execution",
        lambda eid, *a, **k: {
            "execution_id": eid,
            "conversation_id": "sess-1",
            "state": "completed",
            "proof_status": "missing",
        },
    )
    resp = await mod.handle_announce_delegation(_req("sess-1", "exec-9"))
    assert resp.status == 200
    assert resp.text is not None
    assert "unverified_completion" in resp.text

    monkeypatch.setattr(
        task_bot_runtime,
        "get_execution",
        lambda eid, *a, **k: {
            "execution_id": eid,
            "conversation_id": "sess-1",
            "state": "completed",
            "proof_status": "verified",
            "runtime_profile": {"canvas": True},
            "proof": {"status": "verified", "artifacts": []},
        },
    )
    resp = await mod.handle_announce_delegation(_req("sess-1", "exec-9"))
    assert resp.status == 200
    assert resp.text is not None
    assert "canvas_without_verified_artifact" in resp.text


@pytest.mark.asyncio
async def test_parallel_announcements_serialize_llm_and_preserve_both_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aiohttp.test_utils import make_mocked_request

    from thomas.core import task_bot_runtime

    class _GuardedLLM:
        active = 0
        max_active = 0

        def stream_chat(self, *args, **kwargs):  # noqa: ANN002, ANN003
            async def _events():
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                await asyncio.sleep(0.01)
                yield SimpleNamespace(type="token", data={"text": "A verified result is ready."})
                self.active -= 1

            return _events()

    class _Store:
        async def load_meta(self, sid):
            return SessionMeta(session_id=sid)

        def __init__(self) -> None:
            self.loaded = mod.ConversationManager().append_message("user", "Make both files.")

        async def load(self, sid: str):  # noqa: ANN201
            return self.loaded

        async def save(self, sid: str, conversation, meta, force: bool = False) -> None:  # noqa: ANN001
            self.loaded = conversation

    app = web.Application()
    app[APP_SESSION_LOCKS] = {}
    app[APP_SESSION_LOCKS_LOCK] = asyncio.Lock()
    llm = _GuardedLLM()
    store = _Store()
    app[mod.APP_SESSION_STORE] = store
    app[mod.APP_ANNOUNCE_LOCKS] = {}
    app[mod.APP_SESSION_LLM_CACHE] = {
        "sess-1": SimpleNamespace(llm=llm, lock=asyncio.Lock()),
    }
    rows = {
        exec_id: {
            "execution_id": exec_id,
            "conversation_id": "sess-1",
            "state": "completed",
            "proof_status": "verified",
            "proof": {"status": "verified", "artifacts": [{"kind": "text", "path": f"{exec_id}.md"}]},
            "summary": f"Build {exec_id}",
        }
        for exec_id in ("one", "two")
    }
    monkeypatch.setattr(task_bot_runtime, "get_execution", lambda eid, *a, **k: rows[eid])

    def _updated(eid, **kwargs):  # noqa: ANN001, ANN202
        rows[eid].update(kwargs)

    monkeypatch.setattr(task_bot_runtime, "update_execution", _updated)

    def _req(exec_id: str):
        return make_mocked_request(
            "POST",
            "/x",
            match_info={"session_id": "sess-1", "execution_id": exec_id},
            app=app,
        )

    responses = await asyncio.gather(
        mod.handle_announce_delegation(_req("one")),
        mod.handle_announce_delegation(_req("two")),
    )
    assert all(response.status == 200 for response in responses)
    assert llm.max_active == 1
    assistants = [
        row for row in store.loaded.get_context_window(max_tokens=2000) if str(row.get("role")) == "assistant"
    ]
    assert len(assistants) == 2
