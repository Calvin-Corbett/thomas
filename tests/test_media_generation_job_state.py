"""What a job's record says, on a bare app, which a running server reaches through ``thomas.server.rows.media``.

That dotted name, here, is how a check of the row finds these tests, because no test imports a row.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import types
import unittest
from unittest.mock import patch

from tests.web_fixtures.media_generation_fixture import MediaGenerationFixture
from thomas.server.routes import media_generation_routes


class MediaGenerationJobStateTest(MediaGenerationFixture):
    async def test_requested_cancellation_prevents_late_verified_publication(
        self,
    ) -> None:
        from PIL import Image

        def finish(_medium, _prompt, output, _progress):
            Image.new("RGB", (8, 8), "blue").save(output, format="PNG")

        media_generation_routes._write_config(
            self.data_root / ".thomas" / "media_lanes.json",
            {"image": "local"},
        )
        with (
            patch.object(
                media_generation_routes,
                "_WORKSPACES_BASE",
                self.data_root / "workspaces",
            ),
            patch.object(media_generation_routes, "_local_model_ready", return_value=True),
            patch.object(media_generation_routes, "_local_generate", side_effect=finish),
            patch.object(
                media_generation_routes.task_bot_runtime,
                "create_execution",
                return_value={"execution_id": "exec-cancel-image"},
            ),
            patch.object(media_generation_routes.task_bot_runtime, "update_execution"),
            patch.object(
                media_generation_routes.task_bot_runtime,
                "get_execution",
                return_value={"cancel_requested": True},
            ),
            patch.object(media_generation_routes.task_bot_runtime, "attach_proof") as proof,
            patch.object(media_generation_routes.task_bot_runtime, "mark_verified") as verified,
        ):
            started = await media_generation_routes.start_media_generation(
                self.app,
                medium="image",
                prompt="A man",
                session_id="cancel-chat",
            )
            for _ in range(50):
                response = await self.client.get("/api/media/jobs/" + started["job_id"])
                job = (await response.json())["job"]
                if job["state"] == "cancelled":
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(job["state"], "cancelled")
            self.assertNotIn("deliverable", job)
            proof.assert_not_called()
            verified.assert_not_called()

    async def test_image_readiness_checks_only_fp16_pipeline_files(self) -> None:
        calls: list[dict[str, object]] = []

        def cached_snapshot(**kwargs: object) -> str:
            calls.append(kwargs)
            return str(self.data_root / "cached-model")

        hub = types.ModuleType("huggingface_hub")
        hub.snapshot_download = cached_snapshot
        with patch.dict("sys.modules", {"huggingface_hub": hub}):
            self.assertTrue(media_generation_routes._local_model_ready("image"))

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["repo_id"], "stabilityai/sd-turbo")
        self.assertTrue(calls[0]["local_files_only"])
        patterns = calls[0]["allow_patterns"]
        self.assertIn("*.fp16.safetensors", patterns)
        self.assertNotIn("*.safetensors", patterns)

    async def test_missing_optional_local_dependency_is_not_configured(self) -> None:
        with patch.dict("sys.modules", {"huggingface_hub": None}):
            self.assertFalse(media_generation_routes._local_model_ready("image"))

    async def test_cache_scan_does_not_block_other_requests(self) -> None:
        scanning, release = threading.Event(), threading.Event()
        media_generation_routes._write_config(
            self.data_root / ".thomas" / "media_lanes.json",
            {"image": "local"},
        )

        def slow_scan(_medium):
            scanning.set()
            release.wait(timeout=3)
            return True

        with patch.object(media_generation_routes, "_local_model_ready", side_effect=slow_scan):
            request = asyncio.create_task(self.client.get("/api/media/lanes"))
            try:
                for _ in range(100):
                    if scanning.is_set():
                        break
                    await asyncio.sleep(0.01)
                self.assertTrue(scanning.is_set())
                self.assertFalse(
                    request.done(),
                    "Readiness scan blocked the event loop until it finished",
                )
                response = await asyncio.wait_for(self.client.get("/probe"), timeout=1)
                self.assertEqual(response.status, 200)
                self.assertFalse(
                    request.done(),
                    "Other requests must complete while the scan is still pending",
                )
            finally:
                release.set()
                await request

    async def test_float_wav_from_music_generator_is_valid_media(self) -> None:
        import numpy as np
        from scipy.io import wavfile

        output = self.data_root / "music.wav"
        wavfile.write(output, 32000, np.array([0.0, 0.1, -0.1], dtype=np.float32))
        media_generation_routes._verify_media("music", output)

    async def test_generate_startup_failure_is_json(self) -> None:
        config_path = self.data_root / ".thomas" / "media_lanes.json"
        media_generation_routes._write_config(config_path, {"video": "local"})
        with (
            patch.object(media_generation_routes, "_local_model_ready", return_value=True),
            patch.object(
                media_generation_routes.task_bot_runtime,
                "create_execution",
                side_effect=RuntimeError("execution store unavailable"),
            ),
        ):
            response = await self.client.post(
                "/api/media/generate",
                json={"medium": "video", "prompt": "A sunrise"},
            )
            payload = await response.json()

        self.assertEqual(response.status, 500)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "execution store unavailable")
        self.assertEqual(response.content_type, "application/json")

    def saved_job(self, state, owner=None):
        record = {
            "execution_id": "exec-restore",
            "backend_type": "media_generation",
            "conversation_id": "saved-chat",
            "intent": "media_image",
            "state": state,
            "proof_status": "verified" if state == "verified" else "missing",
            "proof": {"artifacts": [{"path": "generated-image.png"}]},
            "runtime_profile": {"media": owner or {}},
        }
        path = self.data_root / "runtime/coordination/task_bots/exec-restore.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")
        return path

    async def test_verified_job_is_recovered_without_process_local_state(self):
        from PIL import Image

        self.saved_job("verified")
        base = self.data_root / "workspaces"
        output = base / "exec-restore/generated-image.png"
        output.parent.mkdir(parents=True)
        Image.new("RGB", (8, 8), "orange").save(output)
        with patch.object(media_generation_routes, "_WORKSPACES_BASE", base):
            response = await self.client.get("/api/media/jobs/exec-restore")
            job = (await response.json())["job"]
        self.assertEqual(job["state"], "completed")
        self.assertEqual(job["session_id"], "saved-chat")
        self.assertEqual(job["deliverable"]["url"], "/deliverable/exec-restore/generated-image.png")

    async def test_live_owner_is_not_failed_by_another_server(self):
        path = self.saved_job(
            "executing",
            {
                "owner_pid": os.getpid(),
                "owner_started_at": media_generation_routes._process_started_at(),
            },
        )
        before = path.read_bytes()
        response = await self.client.get("/api/media/jobs/exec-restore")
        self.assertEqual((await response.json())["job"]["state"], "running")
        self.assertEqual(before, path.read_bytes())

    async def test_unidentifiable_legacy_worker_is_unknown_not_guessed_dead(self):
        path = self.saved_job("executing")
        before = path.read_bytes()
        response = await self.client.get("/api/media/jobs/exec-restore")
        self.assertEqual((await response.json())["job"]["state"], "unknown")
        self.assertEqual(before, path.read_bytes())

    async def test_reused_pid_does_not_keep_a_dead_job_running(self):
        path = self.saved_job(
            "executing",
            {
                "owner_pid": os.getpid(),
                "owner_started_at": media_generation_routes._process_started_at() - 100,
            },
        )
        response = await self.client.get("/api/media/jobs/exec-restore")
        self.assertEqual((await response.json())["job"]["state"], "failed")
        self.assertEqual(json.loads(path.read_text())["state"], "failed")

    async def test_workspace_startup_failure_terminalizes_created_execution(self):
        media_generation_routes._write_config(
            self.data_root / ".thomas" / "media_lanes.json",
            {"image": "local"},
        )
        blocked = self.data_root / "not-a-directory"
        blocked.write_text("existing file")
        with (
            patch.object(media_generation_routes, "_WORKSPACES_BASE", blocked),
            patch.object(media_generation_routes, "_local_model_ready", return_value=True),
            patch.object(
                media_generation_routes.task_bot_runtime,
                "create_execution",
                return_value={"execution_id": "exec-startup"},
            ),
            patch.object(media_generation_routes.task_bot_runtime, "update_execution") as update,
        ):
            response = await self.client.post("/api/media/generate", json={"medium": "image", "prompt": "A man"})
        self.assertEqual(response.status, 500)
        self.assertEqual(update.call_args.kwargs["state"], "failed")


if __name__ == "__main__":
    unittest.main()
