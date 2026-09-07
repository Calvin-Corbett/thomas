"""Tests for the generate-an-app loop: description in, installed surface out."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app

GENERATED_HTML = """<!doctype html>
<html><head><title>Water Tracker</title><style>body{background:#0b0e18}</style></head>
<body><button id="add">Add a glass</button><div id="count"></div>
<script>
async function draw() {
  const n = (await thomas.storage.get('glasses')) || 0;
  document.getElementById('count').textContent = n;
}
document.getElementById('add').onclick = async () => {
  const n = (await thomas.storage.get('glasses')) || 0;
  await thomas.storage.set('glasses', n + 1);
  draw();
};
draw();
</script></body></html>"""


class _FakeClient:
    """Stands in for LLMClient so the loop is testable without a provider."""

    reply = GENERATED_HTML

    def __init__(self, *_args, **_kwargs):
        pass

    async def chat(self, _messages, tools=None):
        assert tools is None, "generation must not hand the model tools"
        return {"text": self.reply, "tool_calls": [], "usage": None}


class TestCompanionGenerate(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._old_secret = os.environ.get("THOMAS_COMPANION_UPDATE_SECRET")
        os.environ["THOMAS_COMPANION_UPDATE_SECRET"] = "topsecret"

    def tearDown(self) -> None:
        if self._old_secret is None:
            os.environ.pop("THOMAS_COMPANION_UPDATE_SECRET", None)
        else:
            os.environ["THOMAS_COMPANION_UPDATE_SECRET"] = self._old_secret
        try:
            self._tmpdir.cleanup()
        finally:
            super().tearDown()

    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=str(Path(self._tmpdir.name) / "runtime")),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def _generate(self, description="track my water intake", reply=None):
        client = _FakeClient
        if reply is not None:
            client = type("_Client", (_FakeClient,), {"reply": reply})
        with mock.patch("thomas.core.llm_client.LLMClient", client):
            return await self.client.post(
                "/api/companion/v1/surface/generate", json={"description": description}
            )

    async def test_description_becomes_an_installed_surface(self):
        resp = await self._generate()
        self.assertEqual(resp.status, 200, await resp.text())
        data = await resp.json()
        self.assertTrue(data.get("ok"))

        module_id = data["module_id"]
        self.assertTrue(module_id.startswith("app."), module_id)
        # The <title> is the natural name; falling back to the prompt is worse.
        self.assertEqual(data["display_name"], "Water Tracker")
        self.assertEqual(data["module"]["surface_type"], "surface")
        self.assertEqual(data["module"]["status"], "enabled")

        listed = await self.client.get("/api/companion/v1/modules")
        rows = (await listed.json())["modules"]
        self.assertIn(module_id, [r["module_id"] for r in rows])

        # And it is immediately openable through the normal surface host.
        doc = await self.client.get(f"/api/companion/v1/surface/{module_id}/document")
        self.assertEqual(doc.status, 200)
        body = await doc.text()
        self.assertIn("Add a glass", body)
        self.assertIn("window.thomas", body)

    async def test_generated_app_can_use_its_own_storage(self):
        resp = await self._generate()
        module_id = (await resp.json())["module_id"]

        wrote = await self.client.post(
            f"/api/companion/v1/surface/{module_id}/storage/set",
            json={"key": "glasses", "value": 3},
        )
        self.assertEqual(wrote.status, 200, await wrote.text())
        read = await self.client.post(
            f"/api/companion/v1/surface/{module_id}/storage/get", json={"key": "glasses"}
        )
        self.assertEqual((await read.json())["value"], 3)

    async def test_repeat_builds_do_not_collide(self):
        first = await self._generate()
        second = await self._generate()
        self.assertEqual(second.status, 200, await second.text())
        self.assertNotEqual((await first.json())["module_id"], (await second.json())["module_id"])

    async def test_fenced_output_is_unwrapped(self):
        resp = await self._generate(reply=f"```html\n{GENERATED_HTML}\n```")
        self.assertEqual(resp.status, 200, await resp.text())
        module_id = (await resp.json())["module_id"]
        body = await (await self.client.get(f"/api/companion/v1/surface/{module_id}/document")).text()
        self.assertNotIn("```", body)

    async def test_non_html_reply_is_rejected(self):
        resp = await self._generate(reply="Sure! I can help you build that app.")
        self.assertEqual(resp.status, 502)
        self.assertIn("did not return an HTML document", (await resp.json())["error"])

    async def test_oversized_document_is_rejected(self):
        huge = "<!doctype html><html><body>" + ("x" * 300_000) + "</body></html>"
        resp = await self._generate(reply=huge)
        self.assertEqual(resp.status, 413)

    async def test_missing_description_is_rejected(self):
        resp = await self.client.post("/api/companion/v1/surface/generate", json={})
        self.assertEqual(resp.status, 400)


class TestGeneratedNameHandling(unittest.TestCase):
    """The model picks the app's name, so the name is untrusted input."""

    def test_markup_is_stripped_from_names(self):
        from thomas.server.routes.companion_generate_aiohttp import _clean_title

        self.assertNotIn("<", _clean_title('<img src=x onerror=alert(1)>Fit'))
        self.assertNotIn(">", _clean_title("<b>Fit</b>"))
        self.assertNotIn('"', _clean_title('say "hi"'))

    def test_title_tag_wins_over_the_description(self):
        from thomas.server.routes.companion_generate_aiohttp import _derive_title

        self.assertEqual(_derive_title("anything", "<title>Water Tracker</title>"), "Water Tracker")
        self.assertEqual(_derive_title("track my water", "<html></html>"), "Track My Water")

    def test_module_ids_cannot_escape_their_namespace(self):
        from thomas.server.routes.companion_generate_aiohttp import _slugify_module_id

        for hostile in ["../etc", "..", "a/b", "\\x", "!!!", ""]:
            module_id = _slugify_module_id(hostile)
            self.assertTrue(module_id.startswith("app."), module_id)
            self.assertNotIn("/", module_id)
            self.assertNotIn("..", module_id)


if __name__ == "__main__":
    unittest.main()
