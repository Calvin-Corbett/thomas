"""Uninstalling a workspace removes the plugin, keeps what you made with it, and can be undone (2026-11-10).

You said: "I also still can't remove workspaces. It says remove from list, but I actually want to remove like the entire
thing ... that's supposed to work like a download thing from the marketplace ... And I want to undo it ... Save the
data ... so I can re-download it and keep all my data."

Three things stood in the way, and each has a test here:

* The sidebar row's menu could only hide a row. It now uninstalls a workspace that came from Marketplace.
* Paper Trading saved its state inside the folder that uninstall deletes, so uninstalling deleted your data.
* A plugin imported from a file, or one whose folder has left ``extensions/``, had no other copy. Uninstalling it was
  permanent and Marketplace stopped listing it. Uninstall now keeps a copy and Marketplace offers it.

The routes are driven through the real app (``thomas.server.app.create_app``), whose Marketplace routes live in
``thomas.server.routes.marketplace_catalog_aiohttp`` and belong to the ``catalog`` row.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.core.plugin_data import keep_plugin_data, plugin_data_dir
from thomas.server.app import create_app
from thomas.server.plugin_shelf import has_kept_copy, kept_copies
from thomas.server.routes.marketplace_catalog_rows import _add_kept_copy_rows

WEB = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web"
PLUGIN = "paper-trading"
SAVED = {"version": 1, "proposals": [{"id": "p-1", "symbol": "TEST"}]}


def test_saved_files_leave_the_install_folder_and_the_manifest_stays(tmp_path: Path) -> None:
    installed = tmp_path / ".thomas" / "plugins" / PLUGIN
    installed.mkdir(parents=True)
    (installed / "manifest.json").write_text("{}", "utf-8")
    (installed / "state.json").write_text(json.dumps(SAVED), "utf-8")
    (installed / "hooks.py").write_text("", "utf-8")

    data = plugin_data_dir(tmp_path, PLUGIN)

    assert data == tmp_path / ".thomas" / "plugin-data" / PLUGIN
    assert json.loads((data / "state.json").read_text("utf-8")) == SAVED
    assert sorted(p.name for p in installed.iterdir()) == ["hooks.py", "manifest.json"]


def test_a_newer_saved_file_is_not_replaced_by_one_left_in_the_old_place(tmp_path: Path) -> None:
    installed, data = tmp_path / "plugins" / PLUGIN, tmp_path / "plugin-data" / PLUGIN
    installed.mkdir(parents=True)
    data.mkdir(parents=True)
    (installed / "state.json").write_text('{"old": true}', "utf-8")
    (data / "state.json").write_text('{"new": true}', "utf-8")

    assert keep_plugin_data(installed, data) == []
    assert json.loads((data / "state.json").read_text("utf-8")) == {"new": True}


class UninstallAndInstallAgain(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    def tearDown(self) -> None:
        try:
            self._tmpdir.cleanup()
        finally:
            super().tearDown()

    async def get_application(self):
        self.config = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(self.config)

    async def _installed_ids(self) -> set[str]:
        body = await (await self.client.get("/api/marketplace/installed")).json()
        return {str(row.get("plugin_id")) for row in body.get("plugins") or []}

    async def _install_and_save_something_the_old_way(self) -> Path:
        resp = await self.client.post(f"/api/marketplace/plugins/{PLUGIN}/install")
        self.assertEqual(resp.status, 200, await resp.text())
        installed = Path(self._tmpdir.name) / ".thomas" / "plugins" / PLUGIN
        (installed / "state.json").write_text(json.dumps(SAVED), "utf-8")
        return installed

    async def test_uninstall_removes_the_plugin_and_keeps_what_you_made(self):
        installed = await self._install_and_save_something_the_old_way()

        resp = await self.client.post(f"/api/marketplace/plugins/{PLUGIN}/uninstall")
        body = await resp.json()

        self.assertEqual(resp.status, 200, body)
        self.assertIs(body.get("data_kept"), True)
        self.assertIs(body.get("kept_copy"), True)
        self.assertFalse(installed.exists(), "the plugin's folder is gone")
        self.assertNotIn(PLUGIN, await self._installed_ids())
        saved = Path(self._tmpdir.name) / ".thomas" / "plugin-data" / PLUGIN / "state.json"
        self.assertEqual(json.loads(saved.read_text("utf-8")), SAVED)

    async def test_installing_again_brings_it_back_with_your_data_and_none_of_it_in_the_install_folder(self):
        installed = await self._install_and_save_something_the_old_way()
        await self.client.post(f"/api/marketplace/plugins/{PLUGIN}/uninstall")

        resp = await self.client.post(f"/api/marketplace/plugins/{PLUGIN}/install")

        self.assertEqual(resp.status, 200, await resp.text())
        self.assertIn(PLUGIN, await self._installed_ids())
        self.assertFalse((installed / "state.json").exists())
        saved = Path(self._tmpdir.name) / ".thomas" / "plugin-data" / PLUGIN / "state.json"
        self.assertEqual(json.loads(saved.read_text("utf-8")), SAVED)
        self.assertFalse(has_kept_copy(self.config, PLUGIN), "the kept copy is cleared once it is installed again")

    async def test_a_plugin_with_no_other_copy_is_listed_and_installs_from_the_copy_uninstall_kept(self):
        await self._install_and_save_something_the_old_way()
        await self.client.post(f"/api/marketplace/plugins/{PLUGIN}/uninstall")

        kept = kept_copies(self.config)
        self.assertEqual([row["plugin_id"] for row in kept], [PLUGIN])
        self.assertIs(kept[0]["installed"], False)

        rows: list[dict] = []
        _add_kept_copy_rows(rows, kept)
        self.assertEqual(len(rows), 1)
        self.assertIs(rows[0]["installable"], True)
        self.assertIs(rows[0]["installed"], False)
        self.assertEqual(rows[0]["install_url"], f"/api/marketplace/plugins/{PLUGIN}/install")
        already_listed = [{"plugin_id": PLUGIN}]
        _add_kept_copy_rows(already_listed, kept)
        self.assertEqual(len(already_listed), 1, "one the catalog lists is not listed twice")

        # As if its folder had left extensions/, which is the case for two of the plugins installed here today.
        gone = FileNotFoundError("not in extensions")
        with patch("thomas.server.routes.marketplace_catalog_aiohttp.install_bundled_plugin", side_effect=gone):
            resp = await self.client.post(f"/api/marketplace/plugins/{PLUGIN}/install")
            self.assertEqual(resp.status, 200, await resp.text())
            self.assertIn(PLUGIN, await self._installed_ids())
            self.assertEqual(kept_copies(self.config), [])

            # And one that was never kept still says so, rather than installing nothing.
            missing = await self.client.post("/api/marketplace/plugins/never-installed/install")
            self.assertEqual(missing.status, 400)
            self.assertIn("no copy of it was kept", (await missing.json())["error"])

    async def test_an_uninstall_that_cannot_set_your_data_aside_removes_nothing(self):
        installed = await self._install_and_save_something_the_old_way()

        with patch("thomas.server.plugin_shelf.keep_plugin_data", side_effect=PermissionError("in use")):
            resp = await self.client.post(f"/api/marketplace/plugins/{PLUGIN}/uninstall")

        self.assertEqual(resp.status, 409)
        self.assertIn("was not uninstalled", (await resp.json())["error"])
        self.assertTrue((installed / "state.json").exists())
        self.assertIn(PLUGIN, await self._installed_ids())

    async def test_thomas_own_workspaces_are_plugins_you_can_uninstall_and_install_again(self):
        """You said: "Those should be plugins. There should be no build-ins ... everything should be a plugin."""
        listed = await (await self.client.get("/api/marketplace/installed")).json()
        self.assertEqual(listed["removed_workspaces"], [])

        resp = await self.client.post("/api/marketplace/plugins/thomas-office/uninstall")
        self.assertEqual(resp.status, 200, await resp.text())
        listed = await (await self.client.get("/api/marketplace/installed")).json()
        self.assertEqual(listed["removed_workspaces"], ["office"], "the sidebar reads this and leaves the row out")
        self.assertNotIn("thomas-office", {row["plugin_id"] for row in listed["plugins"]})

        for address in ("/api/marketplace/plugins", "/api/marketplace/sync"):
            body = await (await self.client.get(address)).json()
            rows = {row["plugin_id"]: row for row in body["plugins"] if str(row.get("plugin_id")).startswith("thomas-")}
            self.assertEqual(
                sorted(rows),
                ["thomas-channels", "thomas-my_stuff", "thomas-office", "thomas-system", "thomas-token_economy"],
                address,
            )
            self.assertEqual({key for key, row in rows.items() if not row["installed"]}, {"thomas-office"}, address)
            self.assertTrue(all(row["installable"] and row["install_url"] for row in rows.values()), address)

        resp = await self.client.post("/api/marketplace/plugins/thomas-office/install")
        self.assertEqual(resp.status, 200, await resp.text())
        listed = await (await self.client.get("/api/marketplace/installed")).json()
        self.assertEqual(listed["removed_workspaces"], [])

        # Marketplace is where the others come back from, so it has no id to uninstall.
        resp = await self.client.post("/api/marketplace/plugins/thomas-marketplace/uninstall")
        self.assertEqual(resp.status, 404)


def test_every_sidebar_workspace_but_marketplace_carries_an_id_its_menu_can_uninstall() -> None:
    arrange = (WEB / "js" / "chat_workspace_arrange.js").read_text("utf-8")
    navigation = (WEB / "js" / "chat_workspace_navigation.js").read_text("utf-8")

    assert "(w.mode === 'marketplace' ? w : Object.assign({ pluginId: `thomas-${w.mode}` }, w))" in navigation
    assert "].filter((w) => !removedStock.includes(w.mode))" in navigation
    assert "setRemovedStock(body.removed_workspaces)" in navigation
    assert "built into Thomas" not in arrange and "built in" not in arrange.lower().replace("built into", "")
    assert "Marketplace is where the others are installed again" in arrange


def test_the_row_menu_uninstalls_a_marketplace_workspace_and_only_hides_a_built_in_one() -> None:
    arrange = (WEB / "js" / "chat_workspace_arrange.js").read_text("utf-8")
    navigation = (WEB / "js" / "chat_workspace_navigation.js").read_text("utf-8")
    tabs = (WEB / "js" / "browser_shell.js").read_text("utf-8")

    assert "if (w.pluginId) b.dataset.pluginId = w.pluginId;" in navigation
    assert "{ action: 'uninstall', label: 'Uninstall', danger: true }" in arrange
    assert "{ action: 'hide', label: 'Hide from list', danger: true }" in arrange
    assert "Remove from list" not in arrange, "the old label promised a removal it did not do"
    # The menu asks; the file that already talks to the server does it, and says what happened under the list.
    assert "new CustomEvent('thomas:workspace:uninstall'," in arrange
    assert "`/api/marketplace/plugins/${encodeURIComponent(pluginId)}/uninstall`" in navigation
    assert "What you made with it is kept. Install it again from Marketplace." in navigation
    assert "was not uninstalled: ${failed}." in navigation
    assert 'window.addEventListener("thomas:workspace:uninstalled"' in tabs, "its open tabs close"


def test_the_dots_on_a_row_open_its_menu_and_not_the_workspace() -> None:
    """The tab bar takes clicks on a sidebar row before the row sees them. It took the "⋯" too, so pressing it opened
    the workspace and the menu, the only place Uninstall is, never showed. Clicked through in a browser 2026-11-10."""
    tabs = (WEB / "js" / "browser_shell.js").read_text("utf-8")
    handler = tabs.split('const btn = e.target.closest("#tc-workspaces button[data-bt-mode]");', 1)[1]
    handler = handler.split("openWorkspaceTab(btn.dataset.btMode);", 1)[0]
    assert 'if (!btn || e.target.closest(".tc-ws-more, .tc-ws-rename")) return;' in handler
    assert handler.index("return;") < handler.index("e.stopPropagation();")
