"""Completion persistence survives reload and serializes with foreground sends."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from thomas.chat.conversation import ConversationManager
from thomas.chat.session_store import SessionMeta, SessionStore
from thomas.core import action_receipt, task_bot_runtime
from thomas.server.app_keys import APP_SESSION_LOCKS, APP_SESSION_LOCKS_LOCK
from thomas.server.routes import chat_v2_announcements as announcements
from thomas.server.routes.chat_v2_keys import APP_SESSION_STORE
from thomas.server.routes.chat_v2_session_guard import session_turn_lock


def test_menu_completion_is_durable_without_a_chat_model_and_waits_for_foreground(
    tmp_path,
):
    async def run():
        app = web.Application()
        store = SessionStore(tmp_path)
        app[APP_SESSION_STORE] = store
        app[APP_SESSION_LOCKS] = {}
        app[APP_SESSION_LOCKS_LOCK] = asyncio.Lock()
        sid = "menu-chat"
        original = ConversationManager().append_message("user", "Create image: A man")
        meta = SessionMeta(
            session_id=sid,
            profile="chosen-provider",
            model_id="chosen-model",
            memory_enabled=False,
        )
        await store.save(sid, original, meta, force=True)
        row = {
            "execution_id": "exec-menu",
            "conversation_id": sid,
            "state": "verified",
            "backend_type": "media_generation",
            "proof_status": "verified",
            "proof": {"artifacts": [{"name": "generated-image.png", "path": "generated-image.png"}]},
        }
        request = make_mocked_request(
            "POST",
            "/announce",
            app=app,
            match_info={"session_id": sid, "execution_id": "exec-menu"},
        )
        with (
            patch.object(task_bot_runtime, "get_execution", return_value=row),
            patch.object(task_bot_runtime, "update_execution") as stamped,
            patch.object(
                action_receipt,
                "delegated_action_receipt",
                return_value=SimpleNamespace(to_dict=lambda: {"ok": True}),
            ),
        ):
            lock = await session_turn_lock(app, sid)
            async with lock:
                pending = asyncio.create_task(announcements.handle_announce_delegation(request))
                await asyncio.sleep(0)
                assert not pending.done()
                await store.save(
                    sid,
                    original.append_message("user", "Keep the blue shirt"),
                    meta,
                    force=True,
                )
            response = await asyncio.wait_for(pending, 2)
            assert response.status == 200, response.text
            assert json.loads(response.text)["message"]
            # A fresh store instance reads the actual saved transcript, not UI state.
            reopened = await SessionStore(tmp_path).load(sid)
            messages = reopened.get_messages()
            assert [m["content"] for m in messages[:2]] == [
                "Create image: A man",
                "Keep the blue shirt",
            ]
            assert messages[-1]["metadata"]["announce"] == "exec-menu"
            assert "generated-image.png" in messages[-1]["content"]
            assert messages[-1]["metadata"]["artifacts"][0]["url"] == "/deliverable/exec-menu/generated-image.png"
            assert (await SessionStore(tmp_path).load_meta(sid)).to_dict() == meta.to_dict()
            stamped.assert_called_once()
            # The execution stamp can be lost after a successful transcript
            # save. Retrying against that same unstamped row must not duplicate.
            again = await announcements.handle_announce_delegation(request)
            assert json.loads(again.text)["skipped"] == "already_reported"
            assert (await SessionStore(tmp_path).load(sid)).get_messages() == messages

            # A separate execution whose disk write fails stays unreported,
            # then produces exactly one durable receipt on retry.
            row["execution_id"] = "exec-second"
            retry_request = make_mocked_request(
                "POST",
                "/announce",
                app=app,
                match_info={"session_id": sid, "execution_id": "exec-second"},
            )
            stamped.reset_mock()
            with patch.object(store, "save", new=AsyncMock(return_value=False)):
                failed = await announcements.handle_announce_delegation(retry_request)
                assert failed.status == 503
                stamped.assert_not_called()
                assert (await SessionStore(tmp_path).load(sid)).get_messages() == messages
            succeeded = await announcements.handle_announce_delegation(retry_request)
            assert succeeded.status == 200
            stamped.assert_called_once()
            assert len((await SessionStore(tmp_path).load(sid)).get_messages()) == len(messages) + 1

    asyncio.run(run())


def test_saved_completion_is_recognized_after_execution_record_disappears(tmp_path):
    async def run():
        app = web.Application()
        store = SessionStore(tmp_path)
        app[APP_SESSION_STORE] = store
        app[APP_SESSION_LOCKS] = {}
        app[APP_SESSION_LOCKS_LOCK] = asyncio.Lock()
        conversation = ConversationManager().append_message(
            "assistant",
            "Image ready",
            metadata={
                "announce": "exec-lost",
                "artifacts": [{"url": "/deliverable/exec-lost/image.png", "kind": "image"}],
            },
        )
        conversation.append_message("user", "Explain what create an image means")
        conversation.append_message("assistant", "It means producing a visual representation.")
        await store.save("chat", conversation, force=True)
        before = (await SessionStore(tmp_path).load("chat")).get_messages()
        request = make_mocked_request(
            "POST",
            "/announce",
            app=app,
            match_info={"session_id": "chat", "execution_id": "exec-lost"},
        )
        with (
            patch.object(task_bot_runtime, "get_execution", return_value=None),
            patch.object(task_bot_runtime, "update_execution") as stamp,
        ):
            response = await announcements.handle_announce_delegation(request)
            assert response.status == 200
            assert json.loads(response.text)["skipped"] == "already_reported"
            stamp.assert_not_called()
            assert (await SessionStore(tmp_path).load("chat")).get_messages() == before
            missing = make_mocked_request(
                "POST",
                "/announce",
                app=app,
                match_info={"session_id": "chat", "execution_id": "exec-never-existed"},
            )
            response = await announcements.handle_announce_delegation(missing)
            assert response.status == 404
            assert json.loads(response.text)["error"] == "execution_not_found"

    asyncio.run(run())
