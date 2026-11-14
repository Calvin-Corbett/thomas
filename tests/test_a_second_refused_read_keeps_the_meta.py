"""A refusal that lands on the second read of a session file must not blank its settings.

``load`` was fixed to raise ``SessionUnreadable``, but both save-after-load callers then called ``load_meta``, which
turned a refused read into ``None``: the announcement saved a blank meta and the media message saved no meta at all.
``load_meta`` raises the same way now, and both callers leave the file alone.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from tests.test_an_unreadable_session_is_not_an_empty_one import _seed
from tests.web_fixtures.media_generation_fixture import MediaGenerationFixture
from thomas.chat.session_store import SessionStore, SessionUnreadable
from thomas.core import action_receipt, task_bot_runtime
from thomas.server.app_keys import APP_SESSION_LOCKS, APP_SESSION_LOCKS_LOCK
from thomas.server.routes import chat_v2_announcements as announcements
from thomas.server.routes import media_generation_routes
from thomas.server.routes.chat_v2_keys import APP_ANNOUNCE_LOCKS, APP_SESSION_STORE

_real_read_text = Path.read_text


def _second_read_refused(store: SessionStore, sid: str):
    """Path.read_text that answers the first read of the session file and refuses every one after it."""
    target = store._session_path(sid)
    seen = {"reads": 0}

    def read_text(self: Path, *args, **kwargs):
        if self == target:
            seen["reads"] += 1
            if seen["reads"] >= 2:
                raise PermissionError(32, "The process cannot access the file", str(self))
        return _real_read_text(self, *args, **kwargs)

    return patch.object(Path, "read_text", read_text)


def test_load_meta_raises_for_a_refused_read(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = SessionStore(tmp_path)
        await _seed(store, "m1")
        with _second_read_refused(store, "m1"):
            assert await store.load("m1") is not None
            try:
                await store.load_meta("m1")
            except SessionUnreadable:
                return
        raise AssertionError("a refused meta read answered as if there were no meta")

    asyncio.run(scenario())


def test_a_missing_session_still_has_no_meta(tmp_path: Path) -> None:
    assert asyncio.run(SessionStore(tmp_path).load_meta("never-saved")) is None


def test_an_announcement_whose_second_read_is_refused_keeps_the_meta(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = web.Application()
        store = SessionStore(tmp_path)
        app[APP_SESSION_STORE] = store
        app[APP_SESSION_LOCKS] = {}
        app[APP_SESSION_LOCKS_LOCK] = asyncio.Lock()
        sid = "announce-meta"
        before = await _seed(store, sid)
        row = {
            "execution_id": "exec-y",
            "conversation_id": sid,
            "state": "verified",
            "backend_type": "media_generation",
            "proof_status": "verified",
            "proof": {"artifacts": [{"name": "a.png", "path": "a.png"}]},
        }
        request = make_mocked_request(
            "POST", "/announce", app=app, match_info={"session_id": sid, "execution_id": "exec-y"}
        )
        with (
            patch.object(task_bot_runtime, "get_execution", return_value=row),
            patch.object(task_bot_runtime, "update_execution") as stamped,
            patch.object(
                action_receipt, "delegated_action_receipt", return_value=SimpleNamespace(to_dict=lambda: {"ok": True})
            ),
            _second_read_refused(store, sid),
        ):
            response = await announcements.handle_announce_delegation(request)
        assert response.status == 503
        assert json.loads(response.text)["error"] == "conversation_unreadable"
        stamped.assert_not_called()
        assert store._session_path(sid).read_bytes() == before

    asyncio.run(scenario())


class MediaMessageWhoseSecondReadIsRefusedTest(MediaGenerationFixture):
    async def test_the_file_keeps_its_meta(self) -> None:
        self.app.setdefault(APP_ANNOUNCE_LOCKS, {})
        (self.data_root / ".thomas").mkdir(parents=True, exist_ok=True)
        (self.data_root / ".thomas" / "media_lanes.json").write_text(json.dumps({"image": "local"}), encoding="utf-8")
        store: SessionStore = self.app[APP_SESSION_STORE]
        sid = "media-meta"
        before = await _seed(store, sid)
        with (
            patch.object(media_generation_routes, "_local_model_ready", return_value=True),
            _second_read_refused(store, sid),
        ):
            response = await self.client.post(
                "/api/media/generate", json={"medium": "image", "prompt": "a cat", "session_id": sid}
            )
        assert response.status == 503, await response.text()
        assert store._session_path(sid).read_bytes() == before
