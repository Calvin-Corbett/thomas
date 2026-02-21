import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from thomas.autonomy.engine import AutonomyEngine
from thomas.autonomy.policy import AutonomyPolicy
from thomas.autonomy.scheduler import EngineTiming
from thomas.autonomy.store import AutonomyStore
from thomas.core.config import ModelConfig


class TestAutonomyEngineMedia(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "autonomy.sqlite3")
        self.store = AutonomyStore(self.db_path)
        self.policy = AutonomyPolicy()

        def _resolver(profile: str | None = None) -> ModelConfig:
            return ModelConfig(
                name=profile or "xai",
                provider="openai_compat",
                base_url="https://api.x.ai/v1",
                api_key="test-key",
                model="grok-4-1-fast-reasoning",
            )

        self.engine = AutonomyEngine(
            store=self.store,
            policy=self.policy,
            timing=EngineTiming(scheduler_tick_s=0.05, claim_batch=4, lock_ttl_s=5.0),
            max_concurrency=1,
            model_resolver=_resolver,
            artifact_root=os.path.join(self.tmpdir.name, "artifacts"),
        )
        await self.engine.start()

    async def asyncTearDown(self):
        await self.engine.stop()
        self.store.close()
        self.tmpdir.cleanup()

    async def _wait_terminal(self, job_id: str) -> str:
        for _ in range(80):
            j = self.store.get_job(job_id)
            if j.status in ("succeeded", "failed", "dead", "cancelled"):
                return j.status
            await asyncio.sleep(0.05)
        return self.store.get_job(job_id).status

    @patch("thomas.autonomy.engine.OpenAICompatMediaClient")
    async def test_video_generation_job_succeeds(self, mock_client_cls):
        fake_client = AsyncMock()
        fake_client.generate_video = AsyncMock(
            return_value={
                "id": "vid_123",
                "status": "queued",
                "url": "https://example.com/vid_123.mp4",
            }
        )
        fake_client.aclose = AsyncMock()
        mock_client_cls.return_value = fake_client

        job = self.store.create_job(
            name="video",
            kind="video_generation",
            payload={"prompt": "A cinematic sunrise over mountains"},
            schedule=None,
            next_run_at=datetime.now(timezone.utc),
            risk_class="low",
        )
        self.engine.wake_up()
        status = await self._wait_terminal(job.id)
        self.assertEqual(status, "succeeded")
        result = self.store.get_job(job.id).result or {}
        self.assertEqual(result.get("video_id"), "vid_123")

    @patch("thomas.autonomy.engine.OpenAICompatMediaClient")
    async def test_speech_transcription_job_succeeds(self, mock_client_cls):
        fake_client = AsyncMock()
        fake_client.transcribe_audio = AsyncMock(
            return_value={"text": "hello from audio transcript"}
        )
        fake_client.aclose = AsyncMock()
        mock_client_cls.return_value = fake_client

        job = self.store.create_job(
            name="stt",
            kind="speech_transcription",
            payload={"audio_path": "C:\\fake\\audio.wav"},
            schedule=None,
            next_run_at=datetime.now(timezone.utc),
            risk_class="low",
        )
        self.engine.wake_up()
        status = await self._wait_terminal(job.id)
        self.assertEqual(status, "succeeded")
        result = self.store.get_job(job.id).result or {}
        self.assertIn("hello from audio transcript", str(result.get("text") or ""))

    @patch("thomas.autonomy.engine.OpenAICompatMediaClient")
    async def test_speech_synthesis_job_succeeds(self, mock_client_cls):
        out_path = os.path.join(self.tmpdir.name, "artifacts", "speech.mp3")
        fake_client = AsyncMock()
        fake_client.synthesize_speech = AsyncMock(
            return_value={"output_path": out_path, "size_bytes": 4096}
        )
        fake_client.aclose = AsyncMock()
        mock_client_cls.return_value = fake_client

        job = self.store.create_job(
            name="tts",
            kind="speech_synthesis",
            payload={"text": "Testing Thomas speech synthesis"},
            schedule=None,
            next_run_at=datetime.now(timezone.utc),
            risk_class="low",
        )
        self.engine.wake_up()
        status = await self._wait_terminal(job.id)
        self.assertEqual(status, "succeeded")
        result = self.store.get_job(job.id).result or {}
        self.assertEqual(result.get("output_path"), out_path)

