"""Mission Control, System Map and Agent Ops are gone: their old addresses lead to Agents, and the sidebar lists Agents."""

import tempfile
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app

JS = Path("thomas/server/web/js")


class TestOldAddressesLeadToAgents(AioHTTPTestCase):
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

    async def test_an_old_workspace_address_redirects_to_agents(self):
        for path in ("/mission", "/agent-ops", "/agent-ops/", "/system-map", "/system-map/"):
            resp = await self.client.get(path, allow_redirects=False)
            self.assertEqual(resp.status, 302, path)
            self.assertEqual(resp.headers["Location"], "/agents", path)

    async def test_the_embed_flag_survives_the_redirect(self):
        for path in ("/mission", "/agent-ops", "/system-map"):
            resp = await self.client.get(path + "?embed=1", allow_redirects=False)
            self.assertEqual(resp.headers["Location"], "/agents?embed=1", path)

    async def test_the_system_map_reading_is_still_served(self):
        resp = await self.client.get("/api/system-map")
        self.assertEqual(resp.status, 200)


def test_each_sidebar_script_lists_agents_and_none_of_the_old_three():
    for name in ("chat_workspace_navigation.js", "browser_shell.js"):
        js = (JS / name).read_text(encoding="utf-8")
        assert "agents" in js and "/agents?embed=1" in js, name
        code = "\n".join(line for line in js.splitlines() if not line.strip().startswith(("*", "/*", "//")))
        for gone in (
            "'Mission Control'",
            '"Mission Control"',
            "System Map",
            "Agent Ops",
            "system_map",
            "agent_ops",
            "/system-map",
            "/agent-ops",
        ):
            assert gone not in code, (name, gone)
