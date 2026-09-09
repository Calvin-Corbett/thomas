from __future__ import annotations

import tempfile
import unittest

import pytest
from aiohttp.test_utils import AioHTTPTestCase

from thomas.agent.execution_plan import ExecutionPlan, PlanStep, plan_from_payload, plan_to_payload
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app
from thomas.server.app_keys import APP_SESSIONS
from thomas.server.routes import chat_plan_mode


@pytest.mark.asyncio
async def test_plan_draft_keeps_model_prose_display_only(monkeypatch: pytest.MonkeyPatch) -> None:
    prose = "1. Delete the database\n2. Publish the secrets"

    async def capture(*args, **kwargs) -> str:  # noqa: ANN002, ANN003, ARG001
        return prose

    monkeypatch.setattr(chat_plan_mode, "_run_agent_capture", capture)
    plan, display = await chat_plan_mode.draft_plan(
        "Prepare a safe release",
        config=None,
        llm=None,
        tools=None,
        conversation=[],
        memory=None,
        session_id="plan-prose-test",
        system_prompt=None,
    )

    assert plan.steps == []
    assert display == prose


@pytest.mark.asyncio
async def test_plan_refinement_clears_old_executable_steps_when_only_prose_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prose = "- Replace the approved plan with this unstructured model text"

    async def capture(*args, **kwargs) -> str:  # noqa: ANN002, ANN003, ARG001
        return prose

    monkeypatch.setattr(chat_plan_mode, "_run_agent_capture", capture)
    plan = ExecutionPlan(
        plan_id="plan-old",
        task_description="Prepare a safe release",
        steps=[PlanStep(step_id="step-old", description="Previously approved action")],
        status="approved",
    )

    refined, display = await chat_plan_mode.refine_plan(
        plan,
        "Change the plan",
        config=None,
        llm=None,
        tools=None,
        conversation=[],
        memory=None,
        session_id="plan-refine-test",
        system_prompt=None,
    )

    assert refined.steps == []
    assert refined.status == "draft"
    assert display == prose


@pytest.mark.asyncio
async def test_empty_structured_plan_executes_nothing() -> None:
    events: list[dict] = []

    async def send(event: dict) -> None:
        events.append(event)

    plan = ExecutionPlan(
        plan_id="plan-empty",
        task_description="Model returned only prose",
    )
    result, message = await chat_plan_mode.execute_plan(
        plan,
        config=None,
        llm=None,
        tools=None,
        conversation=[],
        memory=None,
        session_id="plan-empty-test",
        system_prompt=None,
        send_event=send,
    )

    assert result.status == "draft"
    assert result.steps == []
    assert "Nothing was run" in message
    assert events[-1]["plan"]["steps"] == []


class TestExecutionPlanRoundTrip(unittest.TestCase):
    def test_plan_payload_roundtrip_preserves_structure(self) -> None:
        plan = ExecutionPlan(
            plan_id="plan-1234",
            task_description="Ship plan mode",
            status="draft",
            note="Awaiting approval",
            steps=[
                PlanStep(step_id="step-1", description="Draft the UI", status="pending"),
                PlanStep(step_id="step-2", description="Wire the backend", status="running", result="In progress"),
            ],
        )

        payload = plan_to_payload(plan)
        restored = plan_from_payload(payload)

        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(restored.plan_id, plan.plan_id)
        self.assertEqual(restored.task_description, plan.task_description)
        self.assertEqual(restored.status, plan.status)
        self.assertEqual(restored.note, plan.note)
        self.assertEqual(len(restored.steps), 2)
        self.assertEqual(restored.steps[1].description, "Wire the backend")
        self.assertEqual(restored.steps[1].status, "running")
        self.assertEqual(restored.steps[1].result, "In progress")


class TestServerChatPlanRoutes(AioHTTPTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        try:
            super().tearDown()
        finally:
            self._tmpdir.cleanup()

    async def get_application(self):
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=self._tmpdir.name),
            server=ServerConfig(access_mode="local"),
        )
        return create_app(cfg)

    async def test_plan_state_route_and_slash_registry(self) -> None:
        new_resp = await self.client.post("/api/session/new", json={})
        self.assertEqual(new_resp.status, 200)
        sid = (await new_resp.json())["session_id"]

        session = self.app[APP_SESSIONS][sid]
        session.conversation_mode = "plan"
        session.active_plan = plan_to_payload(
            ExecutionPlan(
                plan_id="plan-state-1",
                task_description="Implement Thomas plan mode",
                status="draft",
                steps=[PlanStep(step_id="step-1", description="Add the routes")],
            )
        )

        plan_resp = await self.client.get(f"/api/chat/plan/{sid}")
        self.assertEqual(plan_resp.status, 200)
        plan_body = await plan_resp.json()
        self.assertEqual(plan_body["conversation_mode"], "plan")
        self.assertEqual(plan_body["plan"]["plan_id"], "plan-state-1")
        self.assertEqual(plan_body["plan"]["steps"][0]["description"], "Add the routes")

        slash_resp = await self.client.get("/api/chat/slash-commands")
        self.assertEqual(slash_resp.status, 200)
        slash_body = await slash_resp.json()
        commands = {item["cmd"]: item for item in slash_body["commands"]}
        self.assertIn("/plan", commands)
        self.assertEqual(commands["/plan"]["modeId"], "plan")

    async def test_session_fork_copies_plan_mode_state(self) -> None:
        new_resp = await self.client.post("/api/session/new", json={})
        self.assertEqual(new_resp.status, 200)
        src_sid = (await new_resp.json())["session_id"]
        src_session = self.app[APP_SESSIONS][src_sid]
        src_session.conversation_mode = "plan"
        src_session.active_plan = plan_to_payload(
            ExecutionPlan(
                plan_id="plan-fork-1",
                task_description="Fork plan state",
                status="draft",
                note="Original note",
                steps=[PlanStep(step_id="step-1", description="Keep copied plan state")],
            )
        )

        fork_resp = await self.client.post("/api/session/fork", json={"session_id": src_sid})
        self.assertEqual(fork_resp.status, 200)
        fork_sid = (await fork_resp.json())["session_id"]

        fork_session = self.app[APP_SESSIONS][fork_sid]
        self.assertEqual(fork_session.conversation_mode, "plan")
        self.assertIsNotNone(fork_session.active_plan)
        self.assertEqual(fork_session.active_plan["note"], "Original note")

        src_session.active_plan["note"] = "Changed later"
        self.assertEqual(fork_session.active_plan["note"], "Original note")


if __name__ == "__main__":
    unittest.main()
