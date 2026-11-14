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
async def test_announce_delegation_strips_sandbox_links_from_note(monkeypatch: pytest.MonkeyPatch) -> None:
    from aiohttp.test_utils import make_mocked_request

    from thomas.core import task_bot_runtime

    class _FakeLLM:
        def stream_chat(self, *args, **kwargs):  # noqa: ANN002, ANN003
            async def _events():
                yield SimpleNamespace(
                    type="token",
                    data={"text": "Done - your chart is ready: [download chart.png](sandbox:/mnt/data/chart.png)."},
                )

            return _events()

    class _FakeStore:
        async def load_meta(self, sid):
            return SessionMeta(session_id=sid)

        def __init__(self) -> None:
            self.loaded = mod.ConversationManager().append_message("user", "make a png chart")
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
    app[mod.APP_SESSION_LLM_CACHE] = {"sess-1": SimpleNamespace(llm=_FakeLLM())}
    monkeypatch.setattr(
        task_bot_runtime,
        "get_execution",
        lambda eid, *a, **k: {
            "execution_id": eid,
            "conversation_id": "sess-1",
            "state": "completed",
            "proof_status": "verified",
            "proof": {"status": "verified", "artifacts": [{"kind": "image", "path": "chart.png"}]},
            "progress_summary": "Rendered the chart",
            "bot_name": "Canvas Worker",
        },
    )
    monkeypatch.setattr(task_bot_runtime, "update_execution", lambda eid, **kw: None)
    req = make_mocked_request("POST", "/x", match_info={"session_id": "sess-1", "execution_id": "exec-9"}, app=app)
    resp = await mod.handle_announce_delegation(req)

    assert resp.status == 200
    assert resp.text is not None
    # The broken sandbox link is gone; the label and file name survive.
    assert "sandbox:" not in resp.text
    assert "](" not in resp.text
    assert "chart.png" in resp.text
    last = store.saved[1].last_assistant_message()
    assert "sandbox:" not in last
    assert last == "Done - your chart is ready: download chart.png."


@pytest.mark.asyncio
async def test_announce_device_action_with_script_and_docs_flags_built_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aiohttp.test_utils import make_mocked_request

    from thomas.core import task_bot_runtime

    captured: dict = {}

    class _FakeLLM:
        def stream_chat(self, *args, **kwargs):  # noqa: ANN002, ANN003
            captured["messages"] = kwargs.get("messages") or list(args)

            async def _events():
                yield SimpleNamespace(
                    type="token",
                    data={
                        "text": (
                            "I built a control for it: SETUP.md, kitchen-lights.ps1, and SETUP.pdf are "
                            "ready — connect your hub to run it."
                        )
                    },
                )

            return _events()

    class _FakeStore:
        async def load_meta(self, sid):
            return SessionMeta(session_id=sid)

        def __init__(self) -> None:
            self.loaded = mod.ConversationManager().append_message("user", "turn off my kitchen lights")
            self.saved = None

        async def load(self, sid: str):  # noqa: ANN201
            return self.loaded

        async def save(self, sid: str, conversation, meta, force: bool = False) -> None:  # noqa: ANN001
            self.saved = (sid, conversation, meta, force)

    app = web.Application()
    app[APP_SESSION_LOCKS] = {}
    app[APP_SESSION_LOCKS_LOCK] = asyncio.Lock()
    app[mod.APP_SESSION_STORE] = _FakeStore()
    app[mod.APP_SESSION_LLM_CACHE] = {"sess-1": SimpleNamespace(llm=_FakeLLM())}
    monkeypatch.setattr(
        task_bot_runtime,
        "get_execution",
        lambda eid, *a, **k: {
            "execution_id": eid,
            "conversation_id": "sess-1",
            "state": "completed",
            "proof_status": "verified",
            "proof": {
                "status": "verified",
                "artifacts": [
                    {"kind": "doc", "path": "SETUP.md"},
                    {"kind": "script", "path": "kitchen-lights.ps1"},
                    {"kind": "doc", "path": "SETUP.pdf"},
                ],
            },
            "summary": "turn off my kitchen lights",
            "bot_name": "Bridge Worker",
        },
    )
    monkeypatch.setattr(task_bot_runtime, "update_execution", lambda eid, **kw: None)
    req = make_mocked_request("POST", "/x", match_info={"session_id": "sess-1", "execution_id": "exec-9"}, app=app)
    resp = await mod.handle_announce_delegation(req)

    assert resp.status == 200
    # The bridge honesty instruction must fire even though SETUP.md/SETUP.pdf are
    # not scripts — a .ps1 control script means the physical action did NOT happen.
    user_prompt = " ".join(str(m.get("content", "")) for m in (captured.get("messages") or []) if isinstance(m, dict))
    assert "physical action has NOT been performed" in user_prompt
    assert "NEVER say the action happened" in user_prompt


@pytest.mark.asyncio
async def test_announce_delegation_persists_model_note_and_marks_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    from aiohttp.test_utils import make_mocked_request

    from thomas.core import task_bot_runtime

    class _FakeLLM:
        prompts: list[str] = []

        def stream_chat(self, *args, **kwargs):  # noqa: ANN002, ANN003
            self.prompts.append(str(kwargs.get("messages") or args))

            async def _events():
                yield SimpleNamespace(type="token", data={"text": "All set - report.html is ready."})

            return _events()

    class _FakeStore:
        async def load_meta(self, sid):
            return SessionMeta(session_id=sid)

        def __init__(self) -> None:
            self.loaded = mod.ConversationManager().append_message("user", "Please make the report.")
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
    app[mod.APP_SESSION_LLM_CACHE] = {"sess-1": SimpleNamespace(llm=_FakeLLM())}

    updates: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        task_bot_runtime,
        "get_execution",
        lambda eid, *a, **k: {
            "execution_id": eid,
            "conversation_id": "sess-1",
            "state": "completed",
            "proof_status": "verified",
            "proof": {"status": "verified", "artifacts": [{"kind": "web", "path": "report.html"}]},
            "progress_summary": "Wrote the report",
            "bot_name": "Report Worker",
        },
    )
    monkeypatch.setattr(task_bot_runtime, "update_execution", lambda eid, **kw: updates.append((eid, kw)))
    req = make_mocked_request(
        "POST",
        "/x",
        match_info={"session_id": "sess-1", "execution_id": "exec-9"},
        app=app,
    )
    resp = await mod.handle_announce_delegation(req)

    assert resp.status == 200
    assert resp.text is not None
    assert "All set" in resp.text
    assert "report.html" in resp.text
    # The prompt still hands the model the complete artifact list; only the
    # wording moved. 904c07bc ("Verified means what was checked") stopped the
    # prompt from calling a render-only artifact list a verified one, and
    # test_a_render_only_check_is_not_announced_as_bare_verified.py now guards
    # that the old wording never returns. What is asserted here is unchanged:
    # the model is told every artifact by name.
    assert _FakeLLM.prompts and "complete list of files it produced is: report.html" in _FakeLLM.prompts[0]
    assert store.saved is not None
    saved_sid, saved_conversation, _meta, force = store.saved
    assert saved_sid == "sess-1"
    assert force is True
    last = saved_conversation.last_assistant_message()
    assert last == "All set - report.html is ready."
    assert updates and updates[0][0] == "exec-9"
    assert "reported_to_chat_at" in updates[0][1]
