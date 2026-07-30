from __future__ import annotations

import asyncio
import json
import re
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.chat.conversation import ConversationManager
from thomas.chat.session_store import SessionMeta
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app
from thomas.server.routes import local_projects_aiohttp as local_projects
from thomas.server.routes.chat_v2 import APP_SESSION_STORE

ROOT = Path(__file__).resolve().parent.parent


def _read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _read_all_runtime_js() -> str:
    """Read and concatenate all split runtime JS files in order.

    Fails loudly on an empty corpus instead of returning "". Callers assert both
    `in` and `not in` against this string, and every `not in` passes vacuously
    against "" -- so if this directory were ever renamed or moved, the shape of
    the failure would be a handful of assertions silently going green rather
    than a test going red. An empty read is not a clean result.
    """
    runtime_dir = ROOT / "thomas" / "server" / "web" / "js" / "runtime"
    assert runtime_dir.is_dir(), f"split runtime directory is missing: {runtime_dir}"
    parts = sorted(runtime_dir.glob("*.js"))
    assert parts, f"no runtime JS files found under {runtime_dir}"
    corpus = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in parts)
    assert len(corpus) > 100_000, (
        f"split runtime corpus is implausibly small ({len(corpus)} chars from "
        f"{len(parts)} files) -- the `not in` assertions below would pass vacuously"
    )
    return corpus


class TestServerLocalProjectsRoutes(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._projects_root = Path(self._tmpdir.name) / "linked-projects"
        self._projects_root.mkdir(parents=True, exist_ok=True)
        self._state_dir_patch = patch.dict(
            "os.environ",
            {
                "THOMAS_HOME": self._tmpdir.name,
                "THOMAS_STATE_DIR": self._tmpdir.name,
            },
        )
        self._task_list_patch = patch.object(local_projects.task_bot_runtime, "list_executions", return_value=[])
        self._task_get_patch = patch.object(local_projects.task_bot_runtime, "get_execution", return_value=None)
        self._state_dir_patch.start()
        self._task_list_patch.start()
        self._task_get_patch.start()

    def tearDown(self) -> None:
        try:
            self._task_get_patch.stop()
            self._task_list_patch.stop()
            self._state_dir_patch.stop()
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

    async def test_pick_folder_does_not_block_event_loop(self):
        # Regression: the native folder dialog blocks its thread. It must run in
        # an executor so the event loop keeps serving other requests. If it runs
        # inline, the concurrent GET below cannot complete until the sleep ends.
        project_root = self._write_project("FreedomNonBlock", {"README.md": "# nb"})

        def _slow_pick() -> str:
            time.sleep(0.6)
            return str(project_root)

        with patch("thomas.server.routes.local_projects_aiohttp._pick_folder_via_dialog", side_effect=_slow_pick):
            pick_task = asyncio.ensure_future(self.client.post("/api/local/projects/pick-folder"))
            # Let the picker handler enter its executor call before we probe.
            await asyncio.sleep(0.05)
            probe_start = time.monotonic()
            probe = await self.client.get("/api/local/projects")
            probe_elapsed = time.monotonic() - probe_start
            self.assertEqual(probe.status, 200)
            # Served concurrently: well under the 0.6s the dialog thread sleeps.
            self.assertLess(probe_elapsed, 0.4)
            pick_resp = await pick_task
            self.assertEqual(pick_resp.status, 200)
            self.assertEqual(str((await pick_resp.json()).get("path") or ""), str(project_root.resolve()))

    async def test_pick_folder_single_flight_rejects_overlap(self):
        # Regression: only one native dialog may be open. A second overlapping
        # request must be refused (409) instead of stacking a hidden dialog.
        project_root = self._write_project("FreedomSingleFlight", {"README.md": "# sf"})
        release = threading.Event()

        def _blocking_pick() -> str:
            release.wait(timeout=5)
            return str(project_root)

        with patch("thomas.server.routes.local_projects_aiohttp._pick_folder_via_dialog", side_effect=_blocking_pick):
            first = asyncio.ensure_future(self.client.post("/api/local/projects/pick-folder"))
            try:
                await asyncio.sleep(0.1)  # let the first request claim the single-flight slot
                second = await self.client.post("/api/local/projects/pick-folder")
                self.assertEqual(second.status, 409)
            finally:
                release.set()
            first_resp = await first
            self.assertEqual(first_resp.status, 200)

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

    async def test_project_workspace_resumes_chats_library_and_scoped_shares(self):
        project_a_root = self._write_project(
            "ProjectA",
            {
                "README.md": "# Project A\n\nPROJECT-LIBRARY-MARKER-936",
            },
        )
        project_b_root = self._write_project("ProjectB", {"README.md": "# Project B"})
        project_a = await (
            await self.client.post("/api/local/projects/import", json={"path": str(project_a_root)})
        ).json()
        project_b = await (
            await self.client.post("/api/local/projects/import", json={"path": str(project_b_root)})
        ).json()
        project_a_id = str(project_a["project"]["id"])
        project_b_id = str(project_b["project"]["id"])

        store = self.app[APP_SESSION_STORE]
        prior = ConversationManager().append_message(
            "user",
            "PROJECT-CHAT-MARKER-17\n\n[Bound project context]\nSTALE-HIDDEN-CONTEXT-99",
        )
        prior = prior.append_message("assistant", "Stored in Project A.")
        await store.save("project-chat-a", prior, SessionMeta(session_id="project-chat-a"), force=True)

        context_response = await self.client.patch(
            f"/api/local/projects/{project_a_id}/context",
            json={"objective": "Ship Project A", "instructions": "Prefer burnt orange."},
        )
        self.assertEqual(context_response.status, 200)
        attach = await self.client.post(
            f"/api/local/projects/{project_a_id}/chats",
            json={"session_id": "project-chat-a", "title": "Launch chat", "pinned": True},
        )
        self.assertEqual(attach.status, 200)
        isolation = await self.client.post(
            f"/api/local/projects/{project_b_id}/chats",
            json={"session_id": "project-chat-a", "title": "Cross-project leak"},
        )
        self.assertEqual(isolation.status, 409)

        library = await self.client.post(
            f"/api/local/projects/{project_a_id}/library",
            json={"path": "README.md", "title": "Owner brief"},
        )
        self.assertEqual(library.status, 200)
        library_entry = (await library.json())["entry"]

        context, receipt = await local_projects.build_project_chat_context(
            self.app,
            project_id=project_a_id,
            session_id="project-chat-b",
            session_store=store,
        )
        self.assertIn("Ship Project A", context)
        self.assertIn("PROJECT-CHAT-MARKER-17", context)
        self.assertNotIn("STALE-HIDDEN-CONTEXT-99", context)
        self.assertIn("PROJECT-LIBRARY-MARKER-936", context)
        self.assertEqual(receipt["prior_chats"], 1)
        self.assertEqual(receipt["fresh_library_files"], 1)

        resume = await self.client.get(f"/api/local/projects/{project_a_id}/resume")
        self.assertEqual(resume.status, 200)
        resume_payload = await resume.json()
        self.assertEqual(resume_payload["objective"], "Ship Project A")
        self.assertEqual(resume_payload["pinned_chats"][0]["session_id"], "project-chat-a")
        self.assertEqual(resume_payload["stale_library_count"], 0)

        share = await self.client.post(
            f"/api/local/projects/{project_a_id}/shares",
            json={"expires_in_seconds": 600},
        )
        self.assertEqual(share.status, 200)
        share_receipt = await share.json()
        share_id = share_receipt["share_id"]
        token = share_receipt["token"]
        denied = await self.client.get(f"/api/local/project-shares/{share_id}?token=wrong")
        self.assertEqual(denied.status, 403)
        shared = await self.client.get(f"/api/local/project-shares/{share_id}?token={token}")
        self.assertEqual(shared.status, 200)
        shared_payload = (await shared.json())["share"]
        self.assertEqual(shared_payload["permissions"], ["read"])
        self.assertNotIn("root_path", json.dumps(shared_payload))
        self.assertIn("PROJECT-CHAT-MARKER-17", json.dumps(shared_payload))

        project_a_root.joinpath("README.md").write_text("# Changed", encoding="utf-8")
        stale_resume = await self.client.get(f"/api/local/projects/{project_a_id}/resume")
        self.assertEqual((await stale_resume.json())["stale_library_count"], 1)

        revoked = await self.client.delete(f"/api/local/projects/{project_a_id}/shares/{share_id}")
        self.assertEqual(revoked.status, 200)
        after_revoke = await self.client.get(f"/api/local/project-shares/{share_id}?token={token}")
        self.assertEqual(after_revoke.status, 404)

        removed = await self.client.delete(f"/api/local/projects/{project_a_id}/library/{library_entry['id']}")
        self.assertEqual(removed.status, 200)

    async def test_project_library_rejects_paths_outside_project(self):
        project_root = self._write_project("IsolatedProject", {"README.md": "inside"})
        outside = Path(self._tmpdir.name) / "outside-secret.txt"
        outside.write_text("do not import", encoding="utf-8")
        imported = await self.client.post("/api/local/projects/import", json={"path": str(project_root)})
        project_id = str((await imported.json())["project"]["id"])

        response = await self.client.post(
            f"/api/local/projects/{project_id}/library",
            json={"path": "../outside-secret.txt"},
        )

        self.assertEqual(response.status, 400)

    async def test_generated_web_deliverables_are_my_stuff_projects(self):
        execution_id = "exec-generated123"
        generated_root = Path(self._tmpdir.name) / "generated" / execution_id
        generated_root.mkdir(parents=True, exist_ok=True)
        (generated_root / "My Stuff").mkdir(parents=True, exist_ok=True)
        (generated_root / "My Stuff" / "frontier-demo.html").write_text("<html>demo</html>", encoding="utf-8")
        record = {
            "execution_id": execution_id,
            "state": "completed",
            "progress_summary": "Created My Stuff/frontier-demo.html.",
            "created_at": "2026-06-17T20:00:00+00:00",
            "updated_at": "2026-06-17T20:01:00+00:00",
            "completed_at": "2026-06-17T20:01:00+00:00",
        }

        with (
            patch.object(local_projects.task_bot_runtime, "list_executions", return_value=[record]),
            patch.object(local_projects.task_bot_runtime, "get_execution", return_value=record),
            patch("thomas.server.routes.local_projects_generated.deliverable_kind", return_value="web"),
            patch(
                "thomas.server.routes.local_projects_generated.deliverable_url",
                return_value=f"/deliverable/{execution_id}/My%20Stuff/frontier-demo.html",
            ),
            patch(
                "thomas.server.routes.local_projects_generated.deliverable_entry",
                return_value="My Stuff/frontier-demo.html",
            ),
            patch("thomas.server.routes.local_projects_generated._workspace_dir", return_value=generated_root),
        ):
            listed = await self.client.get("/api/local/projects")
            self.assertEqual(listed.status, 200)
            body = await listed.json()
            rows = body.get("projects") or []
            self.assertEqual(len(rows), 1)
            project = rows[0]
            self.assertTrue(project.get("generated"))
            self.assertEqual(project.get("id"), f"generated-{execution_id}")
            self.assertEqual(project.get("kind"), "generated_deliverable")
            self.assertEqual(project.get("readiness", {}).get("state"), "open_ready")
            self.assertEqual(project.get("actions", {}).get("primary"), "open_entry")
            self.assertEqual(project.get("artifact_kind"), "web")

            detail_resp = await self.client.get(f"/api/local/projects/generated-{execution_id}")
            self.assertEqual(detail_resp.status, 200)
            detail_project = (await detail_resp.json()).get("project") or {}
            self.assertEqual(detail_project.get("artifact_name"), "frontier-demo.html")

            action_resp = await self.client.post(
                f"/api/local/projects/generated-{execution_id}/action",
                json={"action": "open_entry"},
            )
            self.assertEqual(action_resp.status, 200)
            result = (await action_resp.json()).get("result") or {}
            self.assertEqual(result.get("kind"), "open_url")
            self.assertIn(f"/deliverable/{execution_id}/", str(result.get("url") or ""))

            layout_resp = await self.client.patch(
                f"/api/local/projects/generated-{execution_id}/layout",
                json={"x": 320, "y": 180},
            )
            self.assertEqual(layout_resp.status, 200)
            layout_project = (await layout_resp.json()).get("project") or {}
            self.assertEqual(layout_project.get("board_position"), {"x": 320, "y": 180})


def test_my_stuff_surface_is_wired_into_runtime_shell() -> None:
    index_html = _read_text("thomas/server/web/index.html")
    primary_runtime = _read_all_runtime_js()
    my_stuff_html = _read_text("thomas/server/web/static/my_stuff.html")
    my_stuff_script = _read_text("thomas/server/web/static/my_stuff.script01.js")

    assert 'data-nav-mode="my_stuff"' in index_html
    assert "/static/my_stuff.html?v=" in primary_runtime
    # Was `"Project Board" in my_stuff_html` and red for the same reason as the
    # marketplace assertion below: the heading was recased to "Project board"
    # while the surface itself never went anywhere. Pinned on the stable ui-id
    # rather than the display copy, so a copy edit cannot turn this red again but
    # deleting the board surface still does.
    assert 'data-ui-id="my-stuff.project-board"' in my_stuff_html
    assert 'id="board"' in my_stuff_html
    assert 'id="detailView"' in my_stuff_html
    assert "/api/local/projects/import" in my_stuff_script
    # Was `"/api/v2/chat" in my_stuff_script`. My Stuff no longer POSTs to chat
    # itself; it hands the project to the shell through an "Ask Thomas" control
    # (`sendProjectChat` behind `data-open-workspace-chat`). The capability is
    # intact, so the assertion follows it rather than the retired endpoint.
    assert "data-open-workspace-chat" in my_stuff_script
    assert "/api/local/projects/pick-folder" in my_stuff_script
    assert "/api/local/projects/" in my_stuff_script
    assert "currentProfile ||" not in primary_runtime
    assert "appendDelegationResultMessage" in primary_runtime
    assert "Choose Folder" in my_stuff_html
    assert "Drop a repo folder here" in my_stuff_html


def test_marketplace_uses_native_runtime_shell() -> None:
    primary_runtime = _read_all_runtime_js()
    architecture = _read_text("ARCHITECTURE.md")

    assert "/static/static/plugin_marketplace.html" not in primary_runtime
    # Runtime moved from bare `/plugins?limit=600` to `/sync?limit=600` so the
    # marketplace shell can pull plugins + sync metadata in one round-trip
    # (catalog, generated_at, source_label, warnings, etc.). The legacy
    # `plugins` route is still served, but the shell no longer calls it.
    assert "/api/marketplace/sync?limit=600" in primary_runtime
    assert "data-module-marketplace-search" in primary_runtime
    assert "data-module-marketplace-select" in primary_runtime
    assert "marketplace-card-grid" in primary_runtime
    assert "marketplace-sticky-head" in primary_runtime
    # Pins the behaviour -- the marketplace branch renders the NATIVE surface into
    # the module queue container -- rather than one exact spelling of the call.
    #
    # This assertion was red from 2026-07-21 until 2026-07-30. It required the
    # literal `moduleRenderMarketplaceSurface(moduleQueueList);`, with the
    # semicolon directly after the closing paren. Commit 037bba3c wrapped the call
    # in a decorator, so the live runtime now reads
    # `moduleApplyMarketplaceUiContracts(moduleRenderMarketplaceSurface(moduleQueueList));`
    # and the literal became unreachable. Nothing regressed; the test just could
    # not pass again, and a permanently-red test is how a real regression gets
    # ignored.
    #
    # Deliberately NOT fixed by repointing _read_all_runtime_js at
    # app_runtime_primary.mjs, which still contains the original undecorated
    # literal: that would turn this green while measuring a bundle no page loads.
    assert re.search(
        r"moduleRenderMarketplaceSurface\(\s*moduleQueueList\s*\)", primary_runtime
    ), "the marketplace branch no longer renders the native surface into moduleQueueList"
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
    with (
        patch("thomas.server.routes.local_projects_aiohttp.os.name", "nt"),
        patch(
            "thomas.server.routes.local_projects_aiohttp.shutil.which", return_value=r"C:\Program Files\nodejs\pnpm.cmd"
        ),
        patch("thomas.server.routes.local_projects_aiohttp.subprocess.Popen", return_value=Mock(pid=9090)) as popen,
    ):
        result = local_projects._run_command(["pnpm", "install"], project_root)
    assert result["kind"] == "command_started"
    assert result["command"] == ["pnpm", "install"]
    assert result["launched_command"] == ["cmd.exe", "/c", "pnpm", "install"]
    popen.assert_called_once()


def test_local_project_routes_use_semantic_modules_below_architecture_limits() -> None:
    route_dir = ROOT / "thomas" / "server" / "routes"
    existing = (
        route_dir / "local_projects_aiohttp.py",
        route_dir / "local_projects_helpers_aiohttp.py",
    )
    extracted = (
        route_dir / "local_project_workspace.py",
        route_dir / "local_project_folder_picker.py",
    )

    for path in existing:
        assert len(path.read_text(encoding="utf-8").splitlines()) < 800, path
    for path in extracted:
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 300, path
