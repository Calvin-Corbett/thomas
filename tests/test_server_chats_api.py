import tempfile
import unittest

from aiohttp.test_utils import AioHTTPTestCase

from thomas.chat.conversation import ConversationManager
from thomas.chat.session_store import SessionMeta
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app
from thomas.server.routes.chat_v2_keys import APP_SESSION_STORE


class TestServerChatsApiLocal(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        try:
            super().tearDown()
        finally:
            self._tmpdir.cleanup()

    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def test_put_get_delete_chat(self):
        payload = {
            "id": "chat-1",
            "title": "Hello",
            "model": "local",
            "messages": [
                {"id": "m1", "role": "user", "content": "hi", "createdAt": 1},
                {"id": "m2", "role": "assistant", "content": "hello", "createdAt": 2},
            ],
            "createdAt": 1,
            "updatedAt": 2,
            "pinned": False,
            "sessionId": "sess-1",
        }

        put_resp = await self.client.put("/api/chats/chat-1", json=payload)
        self.assertEqual(put_resp.status, 200)
        put_body = await put_resp.json()
        self.assertTrue(put_body.get("ok"))
        self.assertEqual(put_body.get("chat", {}).get("id"), "chat-1")
        self.assertEqual(put_body.get("chat", {}).get("model"), "local")

        list_resp = await self.client.get("/api/chats")
        self.assertEqual(list_resp.status, 200)
        list_body = await list_resp.json()
        chats = list_body.get("chats", [])
        self.assertEqual(len(chats), 1)
        self.assertEqual(chats[0].get("id"), "chat-1")
        self.assertEqual(chats[0].get("title"), "Hello")
        self.assertEqual(chats[0].get("model"), "local")

        del_resp = await self.client.delete("/api/chats/chat-1")
        self.assertEqual(del_resp.status, 200)
        del_body = await del_resp.json()
        self.assertTrue(del_body.get("deleted"))

        list_resp2 = await self.client.get("/api/chats")
        self.assertEqual(list_resp2.status, 200)
        list_body2 = await list_resp2.json()
        self.assertEqual(list_body2.get("chats", []), [])

    async def test_put_chat_rejects_id_mismatch(self):
        payload = {"id": "not-the-same", "title": "Oops", "messages": []}
        resp = await self.client.put("/api/chats/chat-1", json=payload)
        self.assertEqual(resp.status, 400)

    async def test_mode_and_work_context_filters_isolate_mixed_histories(self):
        legacy = {
            "id": "legacy-chat",
            "title": "Legacy defaults to Chat",
            "messages": [],
            "createdAt": 1,
            "updatedAt": 1,
        }
        self.assertEqual((await self.client.put("/api/chats/legacy-chat", json=legacy)).status, 200)

        store = self.app[APP_SESSION_STORE]
        fixtures = [
            ("v2-chat", "chat", None, "Chat session"),
            ("work-mail", "work", "mail:triage", "Mail triage"),
            ("work-drive", "work", "drive:reports", "Drive reports"),
        ]
        for session_id, mode, context_id, title in fixtures:
            conversation = ConversationManager().append_message("user", title)
            meta = SessionMeta(session_id=session_id, surface_mode=mode, context_id=context_id)
            await store.save(session_id, conversation, meta, force=True)

        chat_response = await self.client.get("/api/chats?mode=chat")
        self.assertEqual(chat_response.status, 200)
        chat_ids = {row["id"] for row in (await chat_response.json())["chats"]}
        self.assertEqual(chat_ids, {"legacy-chat", "v2-chat"})

        work_response = await self.client.get("/api/chats?mode=work&context_id=mail:triage")
        self.assertEqual(work_response.status, 200)
        work_rows = (await work_response.json())["chats"]
        self.assertEqual([row["id"] for row in work_rows], ["work-mail"])
        self.assertEqual(work_rows[0]["contextId"], "mail:triage")

        invalid = await self.client.get("/api/chats?mode=code")
        self.assertEqual(invalid.status, 400)


class TestServerChatsApiRemoteAuth(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        try:
            super().tearDown()
        finally:
            self._tmpdir.cleanup()

    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="remote", api_token="test-token"),
        )
        return create_app(cfg)

    async def test_chats_endpoint_requires_remote_token(self):
        no_auth = await self.client.get("/api/chats")
        self.assertEqual(no_auth.status, 401)

        with_auth = await self.client.get(
            "/api/chats",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(with_auth.status, 200)


if __name__ == "__main__":
    unittest.main()
