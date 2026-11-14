"""The four ``/api/media`` routes on a bare app, which a running server reaches through ``thomas.server.rows.media``.

That dotted name, here, is how a check of the row finds these tests, because no test imports a row.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

from aiohttp import web

from tests.web_fixtures.media_generation_fixture import MediaGenerationFixture
from thomas.chat.conversation import ConversationManager
from thomas.server.routes import media_generation_routes
from thomas.server.routes.chat_v2_keys import APP_SESSION_STORE
from thomas.server.routes.chat_v2_session_guard import session_turn_lock


class MediaGenerationRoutesTest(MediaGenerationFixture):
    async def test_menu_request_waits_for_foreground_save_and_preserves_both_messages(
        self,
    ) -> None:
        from PIL import Image

        def finish(_medium, _prompt, output, _progress):
            Image.new("RGB", (8, 8), "blue").save(output, format="PNG")

        store = self.app[APP_SESSION_STORE]
        sid = "concurrent-chat"
        original = ConversationManager().append_message("user", "Earlier question")
        await store.save(sid, original, force=True)
        lock = await session_turn_lock(self.app, sid)
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
        ):
            async with lock:
                pending = asyncio.create_task(
                    self.client.post(
                        "/api/media/generate",
                        json={
                            "medium": "image",
                            "prompt": "A blue sky",
                            "session_id": sid,
                        },
                    )
                )
                # Allow the media request to reach the held foreground guard.
                for _ in range(20):
                    await asyncio.sleep(0.005)
                self.assertFalse(pending.done())
                await store.save(
                    sid,
                    original.append_message("assistant", "Earlier answer"),
                    force=True,
                )
            response = await asyncio.wait_for(pending, timeout=2)
            self.assertEqual(response.status, 202, await response.text())
            saved = await store.load(sid)
            self.assertEqual(
                [m["content"] for m in saved.to_dict()["messages"]],
                ["Earlier question", "Earlier answer", "Create image: A blue sky"],
            )
            # Drain the actual worker before restoring its patched dependencies.
            job_id = (await response.json())["job_id"]
            for _ in range(100):
                job = (await (await self.client.get("/api/media/jobs/" + job_id)).json())["job"]
                if job["state"] != "running":
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(job["state"], "completed")

    async def test_local_image_generate_returns_decoded_artifact(self) -> None:
        execution = {"execution_id": "exec-media-test"}

        def finish_without_model(
            _medium: str,
            _prompt: str,
            output: Path,
            _progress: object,
        ) -> None:
            from PIL import Image

            Image.new("RGB", (16, 16), "orange").save(output, format="PNG")

        with (
            patch.object(
                media_generation_routes,
                "_WORKSPACES_BASE",
                self.data_root / "workspaces",
            ),
            patch.object(media_generation_routes, "_ensure_local_model"),
            patch.object(media_generation_routes, "_local_model_ready", return_value=True),
            patch.object(
                media_generation_routes,
                "_local_generate",
                side_effect=finish_without_model,
            ),
            patch.object(
                media_generation_routes.task_bot_runtime,
                "create_execution",
                return_value=execution,
            ),
            patch.object(media_generation_routes.task_bot_runtime, "update_execution"),
            patch.object(media_generation_routes.task_bot_runtime, "attach_proof"),
            patch.object(media_generation_routes.task_bot_runtime, "mark_verified"),
            patch.object(
                media_generation_routes.task_bot_runtime,
                "get_execution",
                return_value={},
            ),
        ):
            configured = await self.client.put("/api/media/lanes/image", json={"provider": "local"})
            self.assertEqual(configured.status, 200)

            response = await self.client.post(
                "/api/media/generate",
                json={
                    "medium": "image",
                    "prompt": "A sunrise",
                    "session_id": "session-test",
                },
            )
            payload = await response.json()
            self.assertEqual(response.status, 202)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["job_id"], "exec-media-test")
            for _ in range(20):
                job_response = await self.client.get("/api/media/jobs/exec-media-test")
                job = (await job_response.json())["job"]
                if job["state"] == "completed":
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(job["state"], "completed")
            self.assertEqual(job["deliverable"]["kind"], "image")
            self.assertTrue(job["deliverable"]["url"].endswith("/generated-image.png"))

    async def test_invalid_image_never_receives_verified_proof(self) -> None:
        def corrupt_output(_medium, _prompt, output, _progress):
            output.write_bytes(b"<html>This is not an image</html>")

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
            patch.object(media_generation_routes, "_local_generate", side_effect=corrupt_output),
            patch.object(
                media_generation_routes.task_bot_runtime,
                "create_execution",
                return_value={"execution_id": "exec-bad-image"},
            ),
            patch.object(media_generation_routes.task_bot_runtime, "update_execution"),
            patch.object(media_generation_routes.task_bot_runtime, "attach_proof") as proof,
            patch.object(media_generation_routes.task_bot_runtime, "mark_verified") as verified,
        ):
            started = await media_generation_routes.start_media_generation(
                self.app,
                medium="image",
                prompt="A man",
                session_id="existing-chat",
            )
            for _ in range(50):
                response = await self.client.get("/api/media/jobs/" + started["job_id"])
                job = (await response.json())["job"]
                if job["state"] == "failed":
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(job["state"], "failed")
            self.assertNotIn("deliverable", job)
            proof.assert_not_called()
            verified.assert_not_called()

    async def test_structured_media_request_does_not_fall_back_without_setup(
        self,
    ) -> None:
        with self.assertRaises(web.HTTPConflict):
            await media_generation_routes.start_media_generation(
                self.app,
                medium="image",
                prompt="A man",
                session_id="existing-chat",
            )
