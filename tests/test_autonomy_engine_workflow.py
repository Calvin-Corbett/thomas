import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timezone

from thomas.marketplace.autonomy.engine import AutonomyEngine
from thomas.marketplace.autonomy.policy import AutonomyPolicy
from thomas.marketplace.autonomy.scheduler import EngineTiming
from thomas.marketplace.autonomy.store import AutonomyStore


class _WorkflowChatAdapter:
    def __init__(self) -> None:
        self.calls = []

    async def generate_json(  # noqa: D401
        self,
        *,
        system_prompt,
        user_prompt,
        session_id=None,
        schema_hint=None,
        profile=None,
        model_id=None,
        **controls,
    ):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "profile": profile,
                "model_id": model_id,
                **controls,
            }
        )
        if "You are an orchestrator. Decompose the goal" in system_prompt:
            return {"workers": [{"name": "w1", "prompt": "subtask 1"}]}
        if "parallel workflow worker" in system_prompt:
            return {"output": "worker-done", "summary": "worker-summary"}
        if "orchestrator that merges worker outputs" in system_prompt:
            return {"final_output": "merged", "rationale": "ok"}
        if "You are the coding worker." in system_prompt:
            return {"code": "def solve():\n    return 1", "rationale": "draft"}
        if "You are a strict code reviewer." in system_prompt:
            return {"pass": True, "issues": [], "summary": "ok"}
        if "You are a coding fixer." in system_prompt:
            return {"revised_code": "def solve():\n    return 1", "change_summary": "none"}
        if "workflow chain worker" in system_prompt:
            return {"output": "step-done", "summary": "step-summary"}
        return {"output": "ok", "summary": "ok"}


class TestAutonomyEngineWorkflow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "autonomy.sqlite3")
        self.store = AutonomyStore(self.db_path)
        self.policy = AutonomyPolicy()
        self.chat = _WorkflowChatAdapter()
        self.engine = AutonomyEngine(
            store=self.store,
            policy=self.policy,
            timing=EngineTiming(scheduler_tick_s=0.05, claim_batch=4, lock_ttl_s=5.0),
            max_concurrency=1,
            chat_adapter=self.chat,
        )
        await self.engine.start()

    async def asyncTearDown(self):
        await self.engine.stop()
        self.store.close()
        self.tmpdir.cleanup()

    async def test_workflow_task_chain_succeeds(self):
        job = self.store.create_job(
            name="workflow chain",
            kind="workflow_task",
            payload={
                "workflow": "chain",
                "goal": "prepare release checklist",
                "steps": ["collect requirements", "draft checklist"],
            },
            schedule=None,
            next_run_at=datetime.now(timezone.utc),
            risk_class="low",
        )
        self.engine.wake_up()
        for _ in range(80):
            current = self.store.get_job(job.id)
            if current.status in ("succeeded", "failed", "dead", "cancelled"):
                break
            await asyncio.sleep(0.05)
        done = self.store.get_job(job.id)
        self.assertEqual(done.status, "succeeded")
        result = done.result or {}
        self.assertEqual(result.get("pattern"), "chain")
        self.assertEqual(len(result.get("steps", [])), 2)
        self.assertEqual(int((result.get("telemetry") or {}).get("step_count") or 0), 2)
        self.assertEqual(int((result.get("workflow_policy") or {}).get("autonomy_level") or 0), 3)

    async def test_workflow_task_propagates_work_controls_and_private_context(self):
        markers = {
            "model_id": "MODEL_Z9",
            "reasoning_effort": "REASON_Z9",
            "file_access": "ACCESS_Z9",
            "thomas_guardrails": "GUARD_Z9",
            "token_economy": "TOKEN_Z9",
            "work_app_id": "APP_Z9",
            "work_job_id": "JOB_Z9",
            "private_skills": [{"name": "SKILL_Z9"}],
            "job_memory": {"summary": "MEMORY_Z9"},
            "connector_bindings": [{"provider": "PROVIDER_Z9", "label": "LABEL_Z9", "identity": "IDENTITY_Z9"}],
        }
        job = self.store.create_job(
            name="work propagation",
            kind="workflow_task",
            payload={
                "workflow": "chain",
                "goal": "propagate controls",
                "steps": ["one"],
                **markers,
            },
            schedule=None,
            next_run_at=datetime.now(timezone.utc),
            risk_class="low",
            session_id="work:APP_Z9:JOB_Z9",
        )
        self.engine.wake_up()
        for _ in range(80):
            current = self.store.get_job(job.id)
            if current.status in ("succeeded", "failed", "dead", "cancelled"):
                break
            await asyncio.sleep(0.05)

        assert self.store.get_job(job.id).status == "succeeded"
        call = self.chat.calls[-1]
        assert call["model_id"] == "MODEL_Z9"
        assert call["reasoning_effort"] == "REASON_Z9"
        assert call["file_access"] == "ACCESS_Z9"
        assert call["thomas_guardrails"] == "GUARD_Z9"
        assert call["token_economy"] == "TOKEN_Z9"
        assert call["work_app_id"] == "APP_Z9"
        assert call["work_job_id"] == "JOB_Z9"
        assert "SKILL_Z9" in call["system_prompt"]
        assert "MEMORY_Z9" in call["system_prompt"]
        assert "IDENTITY_Z9" in call["system_prompt"]

    async def test_workflow_task_autonomy_preset_applies_to_orchestrator(self):
        job = self.store.create_job(
            name="workflow orchestrator",
            kind="workflow_task",
            payload={
                "workflow": "orchestrator_worker",
                "goal": "ship feature proposal",
                "autonomy_level": 1,
            },
            schedule=None,
            next_run_at=datetime.now(timezone.utc),
            risk_class="low",
        )
        self.engine.wake_up()
        for _ in range(80):
            current = self.store.get_job(job.id)
            if current.status in ("succeeded", "failed", "dead", "cancelled"):
                break
            await asyncio.sleep(0.05)
        done = self.store.get_job(job.id)
        self.assertEqual(done.status, "succeeded")
        result = done.result or {}
        policy = result.get("workflow_policy") or {}
        self.assertEqual(int(policy.get("autonomy_level") or 0), 1)
        self.assertEqual(int(policy.get("worker_count") or 0), 1)
        prompts = [str(c.get("user_prompt") or "") for c in self.chat.calls]
        self.assertTrue(any("Create up to 1 workers" in p for p in prompts))

    async def test_workflow_task_compiles_natural_language_payload(self):
        job = self.store.create_job(
            name="workflow nl compile",
            kind="workflow_task",
            payload={
                "text": "In parallel, collect requirements; draft solution; estimate implementation effort.",
            },
            schedule=None,
            next_run_at=datetime.now(timezone.utc),
            risk_class="low",
        )
        self.engine.wake_up()
        for _ in range(80):
            current = self.store.get_job(job.id)
            if current.status in ("succeeded", "failed", "dead", "cancelled"):
                break
            await asyncio.sleep(0.05)
        done = self.store.get_job(job.id)
        self.assertEqual(done.status, "succeeded")
        result = done.result or {}
        self.assertEqual(result.get("pattern"), "parallel")
        self.assertIn("workflow_compile", result)
        workers = result.get("workers") or []
        self.assertGreaterEqual(len(workers), 1)

    async def test_workflow_task_max_coding_routes_to_coding_pipeline(self):
        job = self.store.create_job(
            name="workflow max coding",
            kind="workflow_task",
            payload={
                "goal": "Fix bug in app.py and add tests",
                "mode": "thinking",
                "token_economy": "max",
            },
            schedule=None,
            next_run_at=datetime.now(timezone.utc),
            risk_class="low",
        )
        self.engine.wake_up()
        for _ in range(80):
            current = self.store.get_job(job.id)
            if current.status in ("succeeded", "failed", "dead", "cancelled"):
                break
            await asyncio.sleep(0.05)
        done = self.store.get_job(job.id)
        self.assertEqual(done.status, "succeeded")
        result = done.result or {}
        self.assertEqual(result.get("pattern"), "coding_pipeline")
        mode_policy = result.get("workflow_mode_policy") or {}
        self.assertTrue(bool(mode_policy.get("applied")))
        self.assertEqual(str(mode_policy.get("effective_workflow") or ""), "coding_pipeline")
        self.assertEqual(str(mode_policy.get("task_class") or ""), "coding")
