import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

import thomas.marketplace.autonomy.engine as engine_module
from thomas.marketplace.autonomy.engine import AutonomyEngine
from thomas.marketplace.autonomy.policy import AutonomyPolicy
from thomas.marketplace.autonomy.scheduler import EngineTiming
from thomas.marketplace.autonomy.store import AutonomyStore


class _FakeProcess:
    def __init__(self, stdout_text: str, stderr_text: str = "", returncode: int = 0):
        self._stdout = stdout_text.encode("utf-8")
        self._stderr = stderr_text.encode("utf-8")
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self):
        return None


class TestAutonomyEngineEvolve(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = AutonomyStore(os.path.join(self.tmpdir.name, "autonomy.sqlite3"))
        self.engine = AutonomyEngine(
            store=self.store,
            policy=AutonomyPolicy(),
            timing=EngineTiming(scheduler_tick_s=0.05, claim_batch=4, lock_ttl_s=5.0),
            max_concurrency=1,
            artifact_root=os.path.join(self.tmpdir.name, "artifacts"),
        )
        await self.engine.start()
        self._orig_exec = engine_module.asyncio.create_subprocess_exec

    async def asyncTearDown(self):
        engine_module.asyncio.create_subprocess_exec = self._orig_exec
        await self.engine.stop()
        self.store.close()
        self.tmpdir.cleanup()

    async def test_evolve_session_job_runs_via_cli_bridge(self):
        seen = {}

        async def fake_exec(*args, **kwargs):
            seen["args"] = args
            seen["kwargs"] = kwargs
            payload = {
                "ok": True,
                "session": {
                    "session_id": "evolve-123",
                    "status": "ready",
                    "changed_files": ["thomas/cli/main_part02.py"],
                    "promotable": True,
                },
            }
            return _FakeProcess(json.dumps(payload))

        engine_module.asyncio.create_subprocess_exec = fake_exec

        job = self.store.create_job(
            name="Evolve Thomas",
            kind="evolve_session",
            payload={"goal": "Improve startup polish"},
            schedule=None,
            next_run_at=datetime.now(timezone.utc),
            risk_class="low",
        )

        await self.engine.stop()
        result = await self.engine._handle_evolve_session(job)
        self.assertEqual((result or {}).get("session", {}).get("session_id"), "evolve-123")
        env = seen.get("kwargs", {}).get("env") or {}
        self.assertEqual(env.get("PYTHONIOENCODING"), "utf-8")
        self.assertEqual(env.get("PYTHONUTF8"), "1")
        self.assertTrue(str(env.get("THOMAS_SPEND_PATH") or "").endswith("thomas_spend.jsonl"))
        messages = self.store.list_messages(limit=10)
        self.assertTrue(any("evolve-123" in str(item.get("text") or "") for item in messages))
