"""The Library lists what Thomas actually made -- every kind, not just HTML.

Measured 2026-08-06 on the real ledger (~/.thomas/workspaces, 331 completed
executions): 122 web deliverables were listed while 163 finished deliverables
-- 89 text, 55 pdf, 8 image, 11 other -- were silently dropped by a
``artifact_kind != "web"`` gate in ``_generated_deliverable_project``. A chat
delegation that wrote ``packing.txt`` showed a download card in the chat, but
the Library's Creations stayed empty for it: the only path back to the file
was the chat that made it.

These tests seed real workspace files (no patched kind detection: the real
``deliverable_kind`` must classify them) and assert the catalogue endpoint
lists every one of them, newest first, with a working open URL.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app
from thomas.server.routes import deliverable_aiohttp
from thomas.server.routes import local_projects_aiohttp as local_projects

# One finished chat deliverable per kind the detector can produce. None of
# these are HTML: before the fix, every single one was invisible.
_DELIVERABLES = (
    ("exec-libtext0001", "packing.txt", "A packing list.\n- socks\n- charger\n", "text"),
    ("exec-libpdf00001", "report.pdf", "%PDF-1.4 fake-but-real-enough", "pdf"),
    ("exec-libimage001", "art.png", "\x89PNG fake bytes", "image"),
)


def _record(execution_id: str, minute: int) -> dict:
    stamp = f"2026-08-05T10:{minute:02d}:00+00:00"
    return {
        "execution_id": execution_id,
        "state": "completed",
        "summary": f"make me {execution_id}",
        "created_at": stamp,
        "updated_at": stamp,
        "completed_at": stamp,
    }


class TestLibraryListsChatDeliverablesOfEveryKind(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._tmpdir.name)
        self._workspaces = root / "workspaces"
        for execution_id, filename, content, _kind in _DELIVERABLES:
            workspace = self._workspaces / execution_id
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / filename).write_text(content, encoding="utf-8", newline="\n")

        self._records = [
            _record(execution_id, minute)
            for minute, (execution_id, _f, _c, _k) in enumerate(_DELIVERABLES)
        ]
        by_id = {row["execution_id"]: row for row in self._records}

        self._patches = [
            patch.dict(
                "os.environ",
                {"THOMAS_HOME": self._tmpdir.name, "THOMAS_STATE_DIR": self._tmpdir.name},
            ),
            # Point the REAL workspace resolver at the seeded directory so the
            # real deliverable_kind/entry/url functions do the classification.
            patch.object(deliverable_aiohttp, "_WORKSPACES_BASE", self._workspaces),
            patch.object(
                local_projects.task_bot_runtime,
                "list_executions",
                return_value=list(reversed(self._records)),  # ledger is newest-first
            ),
            patch.object(
                local_projects.task_bot_runtime,
                "get_execution",
                side_effect=lambda execution_id, *a, **k: by_id.get(str(execution_id)),
            ),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        try:
            for p in reversed(self._patches):
                p.stop()
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

    async def _generated_rows(self) -> list[dict]:
        resp = await self.client.get("/api/local/projects")
        assert resp.status == 200
        body = await resp.json()
        return [row for row in (body.get("projects") or []) if row.get("generated")]

    async def test_every_finished_deliverable_is_listed_with_its_kind(self):
        rows = await self._generated_rows()
        by_execution = {str(row.get("source_execution_id")): row for row in rows}
        self.assertEqual(
            sorted(by_execution),
            sorted(execution_id for execution_id, _f, _c, _k in _DELIVERABLES),
            "every finished chat deliverable must appear in the Library catalogue",
        )
        for execution_id, filename, _content, kind in _DELIVERABLES:
            row = by_execution[execution_id]
            self.assertEqual(row.get("artifact_kind"), kind)
            self.assertEqual(row.get("artifact_name"), filename)
            self.assertIn(f"/deliverable/{execution_id}/", str(row.get("artifact_url")))
            # The card title is the user's ask, never a bare filename stem.
            self.assertIn(execution_id, str(row.get("name")))

    async def test_open_entry_action_opens_a_text_deliverable(self):
        execution_id = _DELIVERABLES[0][0]
        resp = await self.client.post(
            f"/api/local/projects/generated-{execution_id}/action",
            json={"action": "open_entry"},
        )
        self.assertEqual(resp.status, 200)
        result = (await resp.json()).get("result") or {}
        self.assertEqual(result.get("kind"), "open_url")
        self.assertIn(f"/deliverable/{execution_id}/packing.txt", str(result.get("url")))

    async def test_the_served_file_is_the_real_bytes(self):
        execution_id, filename, content, _kind = _DELIVERABLES[0]
        resp = await self.client.get(f"/deliverable/{execution_id}/{filename}")
        self.assertEqual(resp.status, 200)
        self.assertEqual((await resp.text()), content)
