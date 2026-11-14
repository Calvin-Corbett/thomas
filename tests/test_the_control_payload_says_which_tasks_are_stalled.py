import tempfile

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app


class TestControlPayloadSaysWhichTasksAreStalled(AioHTTPTestCase):
    """The Agents workspace lifts stalled tasks, so every task in the control payload says whether it is one."""

    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    def tearDown(self) -> None:
        try:
            self._tmpdir.cleanup()
        finally:
            super().tearDown()

    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def test_a_task_that_just_ran_is_not_stalled_and_reports_how_long_it_has_been_idle(self):
        sess_resp = await self.client.post("/api/session/new")
        sid = str((await sess_resp.json()).get("session_id") or "")
        chat_resp = await self.client.post(
            "/api/chat",
            json={
                "session_id": sid,
                "profile": "local",
                "mode": "fast",
                "text": "Summarize the weather forecast for tomorrow.",
            },
        )
        self.assertEqual(chat_resp.status, 200)
        _ = await chat_resp.text()

        resp = await self.client.get("/api/mission/control")
        self.assertEqual(resp.status, 200)
        agents = (await resp.json()).get("agents") or []
        runs = [a for a in agents if str(a.get("source") or "") == "chat_run"]
        self.assertGreaterEqual(len(runs), 1)
        for run in runs:
            self.assertIs(run.get("stalled"), False)
            self.assertIn("idle_s", run)
