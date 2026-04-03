from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app
from thomas.server.routes import local_projects_aiohttp as local_projects

ROOT = Path(__file__).resolve().parent.parent


def _read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _read_all_runtime_js() -> str:
    """Read and concatenate all split runtime JS files in order."""
    runtime_dir = ROOT / "thomas" / "server" / "web" / "js" / "runtime"
    if not runtime_dir.exists():
        return ""
    parts = sorted(runtime_dir.glob("*.js"))
    return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in parts)


class TestServerLocalProjectsRoutes(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._projects_root = Path(self._tmpdir.name) / "linked-projects"
        self._projects_root.mkdir(parents=True, exist_ok=True)

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

    def _write_project(self, name: str, files: dict[str, str]) -> Path:
        root = self._projects_root / name
        root.mkdir(parents=True, exist_ok=True)
        for relative_path, content in files.items():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return root

    async def test_import_builds_project_dossier_and_layout_persists(self):
        project_root = self._write_project(
            "FreedomTMS",
            {
                "index.html": "<html><body><main>Freedom TMS</main></body></html>",
                "README.md": "# Freedom TMS\n\nA local dashboard for freight and dispatch operations.",
            },
        )

        resp = await self.client.post(
            "/api/local/projects/import",
            json={"path": str(project_root), "import_method": "picker"},
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        project = body.get("project") or {}
        self.assertTrue(body.get("ok"))
        self.assertEqual(str(project.get("kind") or ""), "static_site")
        self.assertEqual(str(project.get("project_type") or ""), "web_app")
        self.assertEqual(str(project.get("framework") or ""), "Static HTML")
        self.assertEqual(str(project.get("readiness", {}).get("state") or ""), "open_ready")
        self.assertTrue(bool(project.get("scope_summary")))
        self.assertIn("picker", str(project.get("analysis", {}).get("import_method") or ""))
        self.assertIn("x", project.get("board_position") or {})
        self.assertIn("emoji", project.get("board_icon") or {})

        project_id = str(project.get("id") or "")
        detail_resp = await self.client.get(f"/api/local/projects/{project_id}")
        self.assertEqual(detail_resp.status, 200)
        detail_project = (await detail_resp.json()).get("project") or {}
        self.assertEqual(str(detail_project.get("id") or ""), project_id)

        layout_resp = await self.client.patch(
            f"/api/local/projects/{project_id}/layout",
            json={"x": 412, "y": 288},
        )
        self.assertEqual(layout_resp.status, 200)

        listed = await self.client.get("/api/local/projects")
        self.assertEqual(listed.status, 200)
        rows = (await listed.json()).get("projects") or []
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0].get("board_position", {}).get("x") or 0), 412)
        self.assertEqual(int(rows[0].get("board_position", {}).get("y") or 0), 288)

    async def test_node_project_needs_prepare_before_launch_and_can_run_prepare_action(self):
        package_json = {
            "name": "freedom-node",
            "packageManager": "pnpm@9.0.0",
            "scripts": {
                "dev": "vite",
                "test": "vitest",
            },
            "dependencies": {
                "vite": "^5.0.0",
                "react": "^18.0.0",
            },
        }
        project_root = self._write_project(
            "FreedomNode",
            {
                "package.json": json.dumps(package_json, indent=2),
            },
        )

        with patch(
            "thomas.server.routes.local_projects_aiohttp.shutil.which",
            side_effect=lambda value: "pnpm" if value == "pnpm" else None,
        ):
            import_resp = await self.client.post("/api/local/projects/import", json={"path": str(project_root)})
            self.assertEqual(import_resp.status, 200)
            project = (await import_resp.json()).get("project") or {}
            self.assertEqual(str(project.get("kind") or ""), "node_app")
            self.assertEqual(str(project.get("readiness", {}).get("state") or ""), "preparation_required")
            self.assertTrue(bool(project.get("prepare", {}).get("needed")))
            self.assertEqual(str(project.get("actions", {}).get("primary") or ""), "prepare")
            launch_candidates = project.get("launch_candidates") or []
            self.assertEqual(str(launch_candidates[0].get("action") or ""), "prepare")

            project_id = str(project.get("id") or "")
            with patch(
                "thomas.server.routes.local_projects_aiohttp.subprocess.Popen", return_value=Mock(pid=4242)
            ) as popen:
                action_resp = await self.client.post(
                    f"/api/local/projects/{project_id}/action",
                    json={"action": "prepare"},
                )
                self.assertEqual(action_resp.status, 200)
                action_body = await action_resp.json()
                result = action_body.get("result") or {}
                self.assertEqual(str(action_body.get("action") or ""), "prepare")
                self.assertEqual(str(result.get("kind") or ""), "command_started")
                self.assertEqual(int(result.get("pid") or 0), 4242)
                popen.assert_called_once()

    async def test_pick_folder_route_returns_local_path(self):
        project_root = self._write_project(
            "FreedomPick",
            {
                "README.md": "# Freedom Pick\n\nFolder picker smoke.",
            },
        )
        with patch(
            "thomas.server.routes.local_projects_aiohttp._pick_folder_via_dialog", return_value=str(project_root)
        ):
            resp = await self.client.post("/api/local/projects/pick-folder")
            self.assertEqual(resp.status, 200)
            body = await resp.json()
            self.assertTrue(body.get("ok"))
            self.assertFalse(body.get("cancelled"))
            self.assertEqual(str(body.get("path") or ""), str(project_root.resolve()))

    async def test_delete_project_removes_registry_entry(self):
        project_root = self._write_project(
            "FreedomRemove",
            {
                "index.html": "<html><body>remove me</body></html>",
            },
        )
        link_resp = await self.client.post("/api/local/projects/import", json={"path": str(project_root)})
        self.assertEqual(link_resp.status, 200)
        project_id = str((await link_resp.json()).get("project", {}).get("id") or "")

        delete_resp = await self.client.delete(f"/api/local/projects/{project_id}")
        self.assertEqual(delete_resp.status, 200)
        delete_body = await delete_resp.json()
        self.assertTrue(delete_body.get("ok"))
        self.assertEqual(str(delete_body.get("removed_id") or ""), project_id)

        listed = await self.client.get("/api/local/projects")
        self.assertEqual(listed.status, 200)
        listed_body = await listed.json()
        self.assertEqual(listed_body.get("projects") or [], [])


def test_my_stuff_surface_is_wired_into_runtime_shell() -> None:
    index_html = _read_text("thomas/server/web/index.html")
    primary_runtime = _read_all_runtime_js()
    my_stuff_html = _read_text("thomas/server/web/static/my_stuff.html")
    my_stuff_script = _read_text("thomas/server/web/static/my_stuff.script01.js")

    assert 'data-nav-mode="my_stuff"' in index_html
    assert "/static/static/my_stuff.html?v=20260318-project-board-3" in primary_runtime
    assert "Project Board" in my_stuff_html
    assert 'id="board"' in my_stuff_html
    assert 'id="detailView"' in my_stuff_html
    assert "/api/local/projects/import" in my_stuff_script
    assert "/api/v2/chat" in my_stuff_script
    assert "/api/local/projects/pick-folder" in my_stuff_script
    assert "/api/local/projects/" in my_stuff_script
    assert "Choose Folder" in my_stuff_html
    assert "Drop a repo folder here" in my_stuff_html


def test_marketplace_uses_native_runtime_shell() -> None:
    primary_runtime = _read_all_runtime_js()
    architecture = _read_text("ARCHITECTURE.md")

    assert "/static/static/plugin_marketplace.html" not in primary_runtime
    assert "/api/marketplace/plugins?limit=600" in primary_runtime
    assert "data-module-marketplace-search" in primary_runtime
    assert "data-module-marketplace-select" in primary_runtime
    assert "marketplace-card-grid" in primary_runtime
    assert "marketplace-sticky-head" in primary_runtime
    assert "moduleRenderMarketplaceSurface(moduleQueueList);" in primary_runtime
    assert "[data-module-embedded-surface]" in primary_runtime
    assert "preferContentHeight: true" in primary_runtime
    assert "if (key === 'marketplace') return null;" in primary_runtime
    assert "focusSearchUntil" in primary_runtime
    assert "searchSelectionStart" in primary_runtime
    assert "data-marketplace-status" in primary_runtime
    assert "marketplace-card-id" not in primary_runtime
    assert "Web Surface Contract" in architecture


def test_run_command_wraps_windows_batch_shims() -> None:
    project_root = ROOT
    with patch("thomas.server.routes.local_projects_aiohttp.os.name", "nt"):
        with patch(
            "thomas.server.routes.local_projects_aiohttp.shutil.which", return_value=r"C:\Program Files\nodejs\pnpm.cmd"
        ):
            with patch(
                "thomas.server.routes.local_projects_aiohttp.subprocess.Popen", return_value=Mock(pid=9090)
            ) as popen:
                result = local_projects._run_command(["pnpm", "install"], project_root)
    assert result["kind"] == "command_started"
    assert result["command"] == ["pnpm", "install"]
    assert result["launched_command"] == ["cmd.exe", "/c", "pnpm", "install"]
    popen.assert_called_once()
