"""A saved chat whose file cannot be read right now is not an empty chat.

On Windows a read can be refused while another writer replaces the file. ``SessionStore.load`` used to answer
``None`` for that, and the two callers that load, append and save then built a near-empty conversation and wrote it
over the real one. ``load`` raises ``SessionUnreadable`` now, and both callers leave the file alone.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from tests.web_fixtures.media_generation_fixture import MediaGenerationFixture
from thomas.chat.conversation import ConversationManager
from thomas.chat.session_store import SessionMeta, SessionStore, SessionUnreadable
from thomas.core import action_receipt, task_bot_runtime
from thomas.server.app_keys import APP_SESSION_LOCKS, APP_SESSION_LOCKS_LOCK
from thomas.server.routes import chat_v2_announcements as announcements
from thomas.server.routes import media_generation_routes
from thomas.server.routes.chat_v2_keys import APP_ANNOUNCE_LOCKS, APP_SESSION_STORE

_real_read_text = Path.read_text


def _refused_for(store: SessionStore, sid: str):
    """Path.read_text that is refused for the one session file, as a replace in flight would refuse it."""
    target = store._session_path(sid)

    def read_text(self: Path, *args, **kwargs):
        if self == target:
            raise PermissionError(13, "The process cannot access the file because it is being used", str(self))
        return _real_read_text(self, *args, **kwargs)

    return patch.object(Path, "read_text", read_text)


async def _seed(store: SessionStore, sid: str) -> bytes:
    conversation = ConversationManager()
    for index in range(6):
        conversation = conversation.append_message("user" if index % 2 == 0 else "assistant", f"message {index}")
    await store.save(sid, conversation, SessionMeta(session_id=sid, profile="kept"), force=True)
    return store._session_path(sid).read_bytes()


def test_load_raises_for_a_file_that_is_there_and_refused(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = SessionStore(tmp_path)
        before = await _seed(store, "s1")
        with _refused_for(store, "s1"):
            try:
                await store.load("s1")
            except SessionUnreadable:
                pass
            else:
                raise AssertionError("an unreadable session answered as if it were empty")
        assert store._session_path("s1").read_bytes() == before

    asyncio.run(scenario())


def test_a_missing_or_listed_session_reads_as_before(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = SessionStore(tmp_path)
        assert await store.load("never-saved") is None
        await _seed(store, "s2")
        loaded = await store.load("s2")
        assert loaded is not None and loaded.length == 6

    asyncio.run(scenario())


def test_the_stat_check_failing_is_also_unreadable_not_missing(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = SessionStore(tmp_path)
        await _seed(store, "s3")
        target = store._session_path("s3")
        real_exists = Path.exists

        def exists(self: Path, *args, **kwargs):
            if self == target:
                raise PermissionError(13, "refused", str(self))
            return real_exists(self, *args, **kwargs)

        with patch.object(Path, "exists", exists):
            try:
                await store.load("s3")
            except SessionUnreadable:
                return
        raise AssertionError("a refused check read as a missing session")

    asyncio.run(scenario())


def test_an_announcement_over_an_unreadable_session_leaves_the_file_and_the_stamp(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = web.Application()
        store = SessionStore(tmp_path)
        app[APP_SESSION_STORE] = store
        app[APP_SESSION_LOCKS] = {}
        app[APP_SESSION_LOCKS_LOCK] = asyncio.Lock()
        sid = "announce-chat"
        before = await _seed(store, sid)
        row = {
            "execution_id": "exec-x",
            "conversation_id": sid,
            "state": "verified",
            "backend_type": "media_generation",
            "proof_status": "verified",
            "proof": {"artifacts": [{"name": "a.png", "path": "a.png"}]},
        }
        request = make_mocked_request(
            "POST", "/announce", app=app, match_info={"session_id": sid, "execution_id": "exec-x"}
        )
        with (
            patch.object(task_bot_runtime, "get_execution", return_value=row),
            patch.object(task_bot_runtime, "update_execution") as stamped,
            patch.object(
                action_receipt, "delegated_action_receipt", return_value=SimpleNamespace(to_dict=lambda: {"ok": True})
            ),
            _refused_for(store, sid),
        ):
            response = await announcements.handle_announce_delegation(request)
        assert response.status == 503
        assert json.loads(response.text)["error"] == "conversation_unreadable"
        stamped.assert_not_called()
        assert store._session_path(sid).read_bytes() == before

    asyncio.run(scenario())


class MediaMessageOverAnUnreadableSessionTest(MediaGenerationFixture):
    async def test_the_request_fails_and_the_file_is_byte_identical(self) -> None:
        self.app.setdefault(APP_ANNOUNCE_LOCKS, {})
        (self.data_root / ".thomas").mkdir(parents=True, exist_ok=True)
        (self.data_root / ".thomas" / "media_lanes.json").write_text(json.dumps({"image": "local"}), encoding="utf-8")
        store: SessionStore = self.app[APP_SESSION_STORE]
        sid = "media-chat"
        before = await _seed(store, sid)
        with (
            patch.object(media_generation_routes, "_local_model_ready", return_value=True),
            _refused_for(store, sid),
        ):
            response = await self.client.post(
                "/api/media/generate", json={"medium": "image", "prompt": "a cat", "session_id": sid}
            )
        assert response.status == 503, await response.text()
        assert store._session_path(sid).read_bytes() == before
        reopened = await SessionStore(self.data_root / "sessions").load(sid)
        assert reopened is not None and reopened.length == 6
