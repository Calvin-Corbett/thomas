import os
import unittest

from thomas.marketplace.autonomy.workflows import WorkflowExecutionError, WorkflowRunner


class _ChainParallelAdapter:
    async def generate_json(  # noqa: D401
        self,
        *,
        system_prompt,
        user_prompt,
        session_id=None,
        schema_hint=None,
        profile=None,
        model_id=None,
    ):
        if "workflow chain worker" in system_prompt:
            marker = "Current step"
            ix = user_prompt.find(marker)
            step_txt = user_prompt[ix:] if ix >= 0 else user_prompt
            return {"output": f"chain:{step_txt[:40]}", "summary": "ok"}
        if "routing controller" in system_prompt:
            return {"route_name": "math", "reason": "contains numeric clues"}
        if "routed worker" in system_prompt:
            return {"output": f"routed:{profile or 'default'}", "summary": "ok"}
        if "You are an orchestrator. Decompose the goal" in system_prompt:
            return {
                "workers": [
                    {"name": "worker-a", "prompt": "subtask a", "capability": "video_gen"},
                    {"name": "worker-b", "prompt": "subtask b", "capability": "chat"},
                ]
            }
        if "parallel workflow worker" in system_prompt:
            marker = "Assigned subtask:\n"
            ix = user_prompt.find(marker)
            subtask = user_prompt[ix + len(marker) :].strip() if ix >= 0 else "task"
            return {"output": f"parallel:{subtask}:{profile or 'default'}", "summary": "ok"}
        if "orchestrator that merges worker outputs" in system_prompt:
            return {"final_output": "synthesized"}
        return {"output": "default", "summary": "default"}


class _EvalOptAdapter:
    def __init__(self):
        self.eval_calls = 0

    async def generate_json(  # noqa: D401
        self,
        *,
        system_prompt,
        user_prompt,
        session_id=None,
        schema_hint=None,
        profile=None,
        model_id=None,
    ):
        if "You are a generator." in system_prompt:
            return {"draft": "draft-v1"}
        if "You are an evaluator." in system_prompt:
            self.eval_calls += 1
            if self.eval_calls == 1:
                return {"pass": False, "feedback": "needs more detail", "score_0_to_10": 5}
            return {"pass": True, "feedback": "good", "score_0_to_10": 9}
        if "You are an optimizer." in system_prompt:
            return {"revised_draft": "draft-v2", "changes": "added detail"}
        return {}


class _ProfileFallbackAdapter:
    def __init__(self):
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
    ):
        _ = user_prompt, session_id, schema_hint, model_id
        self.calls.append({"system_prompt": system_prompt, "profile": profile})
        if "workflow chain worker" in system_prompt and profile == "primary-profile":
            raise RuntimeError("primary profile temporary failure")
        return {"output": f"ok:{profile or 'default'}", "summary": "ok"}


class _InventedProfileAdapter:
    def __init__(self, *, fail_workers: bool = False):
        self.calls = []
        self.fail_workers = fail_workers

    async def generate_json(  # noqa: D401
        self,
        *,
        system_prompt,
        user_prompt,
        session_id=None,
        schema_hint=None,
        profile=None,
        model_id=None,
    ):
        _ = user_prompt, session_id, schema_hint, model_id
        self.calls.append({"system_prompt": system_prompt, "profile": profile})
        if "You are an orchestrator. Decompose the goal" in system_prompt:
            return {
                "workers": [
                    {
                        "name": "qa",
                        "prompt": "check local QA",
                        "capability": "local QA inspection",
                        "profile": "Independent QA reviewer",
                    }
                ]
            }
        if "parallel workflow worker" in system_prompt:
            if self.fail_workers:
                raise RuntimeError("worker backend failed")
            return {"output": "verified local QA", "summary": "verified"}
        if "orchestrator that merges worker outputs" in system_prompt:
            return {"final_output": "verified local QA"}
        return {"output": "ok", "summary": "ok"}


class _RouteFallbackAdapter:
    async def generate_json(  # noqa: D401
        self,
        *,
        system_prompt,
        user_prompt,
        session_id=None,
        schema_hint=None,
        profile=None,
        model_id=None,
    ):
        _ = session_id, schema_hint, profile, model_id
        if "routing controller" in system_prompt:
            return {"route_name": "math", "reason": "route heuristic"}
        if "routed worker" in system_prompt:
            if "Selected route: math" in user_prompt:
                raise RuntimeError("math route backend unavailable")
            return {"output": "fallback-route-ok", "summary": "ok"}
        return {"output": "ok", "summary": "ok"}


class _CodingPipelineAdapter:
    def __init__(self):
        self.review_calls = 0

    async def generate_json(  # noqa: D401
        self,
        *,
        system_prompt,
        user_prompt,
        session_id=None,
        schema_hint=None,
        profile=None,
        model_id=None,
    ):
        _ = user_prompt, session_id, schema_hint, profile, model_id
        if "You are the coding worker." in system_prompt:
            return {"code": "def solve():\n    return 1", "rationale": "initial draft"}
        if "You are a strict code reviewer." in system_prompt:
            self.review_calls += 1
            if self.review_calls == 1:
                return {"pass": False, "issues": ["wrong constant"], "summary": "needs fix"}
            return {"pass": True, "issues": [], "summary": "looks good"}
        if "You are a coding fixer." in system_prompt:
            return {"revised_code": "def solve():\n    return 2", "change_summary": "fixed constant"}
        return {"output": "ok"}


class _ApprovalBrokerStub:
    def __init__(self, approve: bool = True):
        self.approve = approve
        self.calls: list[dict[str, str]] = []

    async def require(
        self,
        *,
        run_id,
        tool_call_id,
        session_id,
        tool_name,
        args_preview,
        reason,
        timeout_s,
    ):
        self.calls.append(
            {
                "run_id": str(run_id),
                "tool_call_id": str(tool_call_id),
                "session_id": str(session_id),
                "tool_name": str(tool_name),
                "reason": str(reason),
                "timeout_s": str(timeout_s),
            }
        )
        return self.approve


class TestWorkflowRunner(unittest.IsolatedAsyncioTestCase):
    ENV_KEYS = ("THOMAS_AUTONOMY_NO_HUMAN_MODE", "THOMAS_NO_HUMAN_MODE", "THOMAS_GUARDRAILS_NO_HUMAN_MODE")

    async def asyncSetUp(self):
        self._previous_env = {k: os.environ.get(k) for k in self.ENV_KEYS}
        for k in self.ENV_KEYS:
            os.environ.pop(k, None)
        return await super().asyncSetUp()

    async def asyncTearDown(self):
        await super().asyncTearDown()
        for k in self.ENV_KEYS:
            previous = self._previous_env.get(k)
            if previous is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = previous

    async def test_chain_workflow_runs_multiple_steps(self):
        runner = WorkflowRunner(chat_adapter=_ChainParallelAdapter(), session_id="s1")
        out = await runner.run(
            {
                "workflow": "chain",
                "goal": "prepare release notes",
                "steps": ["collect changes", "summarize impact"],
            }
        )
        self.assertEqual(out.get("pattern"), "chain")
        self.assertEqual(len(out.get("steps", [])), 2)
        self.assertTrue(out.get("final_output"))

    async def test_parallel_workflow_returns_synthesis(self):
        runner = WorkflowRunner(
            chat_adapter=_ChainParallelAdapter(),
            session_id="s1",
            default_profile="chat-profile",
            capabilities_by_profile={
                "chat-profile": {"chat": True},
                "video-profile": {"video_gen": True, "chat": True},
            },
        )
        out = await runner.run(
            {
                "workflow": "parallel",
                "goal": "analyze issue from two angles",
                "workers": [
                    {"name": "arch", "prompt": "architecture analysis", "capability": "video_gen"},
                    {"name": "ops", "prompt": "operations analysis"},
                ],
            }
        )
        self.assertEqual(out.get("pattern"), "parallel")
        self.assertEqual(len(out.get("workers", [])), 2)
        self.assertEqual(out.get("final_output"), "synthesized")
        # capability-aware selection should route video_gen task to video-profile
        first = out.get("workers", [])[0]
        self.assertEqual(first.get("profile"), "video-profile")

    async def test_routing_workflow_selects_route(self):
        runner = WorkflowRunner(
            chat_adapter=_ChainParallelAdapter(),
            session_id="s1",
            default_profile="chat-profile",
            capabilities_by_profile={"chat-profile": {"chat": True}},
        )
        out = await runner.run(
            {
                "workflow": "routing",
                "goal": "solve this equation",
                "routes": [
                    {"name": "general", "when": "default", "prompt": "general handling"},
                    {"name": "math", "when": "math-heavy", "prompt": "math handling"},
                ],
            }
        )
        self.assertEqual(out.get("pattern"), "routing")
        self.assertEqual(out.get("selected_route", {}).get("name"), "math")

    async def test_orchestrator_worker_builds_workers_and_synthesizes(self):
        runner = WorkflowRunner(
            chat_adapter=_ChainParallelAdapter(),
            session_id="s1",
            default_profile="chat-profile",
            capabilities_by_profile={
                "chat-profile": {"chat": True},
                "video-profile": {"video_gen": True, "chat": True},
            },
        )
        out = await runner.run(
            {
                "workflow": "orchestrator_worker",
                "goal": "build a short campaign plan",
                "worker_count": 2,
            }
        )
        self.assertEqual(out.get("pattern"), "orchestrator_worker")
        self.assertEqual(len(out.get("workers", [])), 2)
        self.assertEqual(out.get("final_output"), "synthesized")

    async def test_orchestrator_ignores_untrusted_model_profile_without_registry(self):
        adapter = _InventedProfileAdapter()
        runner = WorkflowRunner(chat_adapter=adapter, session_id="s1")

        out = await runner.run(
            {
                "workflow": "orchestrator_worker",
                "goal": "return a local QA brief",
                "worker_count": 1,
            }
        )

        self.assertEqual(out.get("final_output"), "verified local QA")
        worker_calls = [call for call in adapter.calls if "parallel workflow worker" in str(call.get("system_prompt"))]
        self.assertEqual([call.get("profile") for call in worker_calls], [None])

    async def test_orchestrator_fails_closed_when_every_worker_fails(self):
        adapter = _InventedProfileAdapter(fail_workers=True)
        runner = WorkflowRunner(chat_adapter=adapter, session_id="s1")

        with self.assertRaisesRegex(WorkflowExecutionError, "failed closed"):
            await runner.run(
                {
                    "workflow": "orchestrator_worker",
                    "goal": "return a local QA brief",
                    "worker_count": 1,
                }
            )

    async def test_evaluator_optimizer_improves_until_pass(self):
        runner = WorkflowRunner(chat_adapter=_EvalOptAdapter(), session_id="s1")
        out = await runner.run(
            {
                "workflow": "evaluator_optimizer",
                "goal": "write concise rollout memo",
                "max_rounds": 3,
            }
        )
        self.assertEqual(out.get("pattern"), "evaluator_optimizer")
        self.assertTrue(out.get("passed"))
        self.assertEqual(out.get("rounds_used"), 2)
        self.assertEqual(out.get("final_output"), "draft-v2")

    async def test_chain_workflow_profile_fallback(self):
        adapter = _ProfileFallbackAdapter()
        runner = WorkflowRunner(
            chat_adapter=adapter,
            session_id="s1",
            default_profile="primary-profile",
            capabilities_by_profile={
                "primary-profile": {"chat": True},
                "backup-profile": {"chat": True},
            },
        )
        out = await runner.run(
            {
                "workflow": "chain",
                "goal": "summarize notes",
                "steps": [{"name": "draft", "prompt": "write summary", "profile": "primary-profile"}],
            }
        )
        step = out.get("steps", [])[0]
        self.assertEqual(step.get("profile"), "backup-profile")
        self.assertTrue(bool(step.get("fallback_used")))
        profiles = [c.get("profile") for c in adapter.calls if "workflow chain worker" in str(c.get("system_prompt"))]
        self.assertEqual(profiles[:2], ["primary-profile", "backup-profile"])

    async def test_parallel_capability_fallback_to_chat(self):
        runner = WorkflowRunner(
            chat_adapter=_ChainParallelAdapter(),
            session_id="s1",
            default_profile="chat-profile",
            capabilities_by_profile={"chat-profile": {"chat": True}},
        )
        out = await runner.run(
            {
                "workflow": "parallel",
                "goal": "produce media idea",
                "workers": [{"name": "media", "prompt": "make a concept", "capability": "video_gen"}],
                "synthesize": False,
            }
        )
        worker = out.get("workers", [])[0]
        self.assertEqual(worker.get("capability"), "video_gen")
        self.assertEqual(worker.get("resolved_capability"), "chat")
        self.assertTrue(bool(worker.get("fallback_used")))

    async def test_routing_fallback_to_alternate_route_when_selected_fails(self):
        runner = WorkflowRunner(chat_adapter=_RouteFallbackAdapter(), session_id="s1")
        out = await runner.run(
            {
                "workflow": "routing",
                "goal": "solve equation",
                "routes": [
                    {"name": "general", "when": "default", "prompt": "general handling"},
                    {"name": "math", "when": "math-heavy", "prompt": "math handling"},
                ],
            }
        )
        self.assertEqual(out.get("initial_route", {}).get("name"), "math")
        self.assertEqual(out.get("selected_route", {}).get("name"), "general")
        self.assertTrue(bool(out.get("route_fallback_used")))
        attempts = out.get("route_attempts") or []
        self.assertGreaterEqual(len(attempts), 2)

    async def test_coding_pipeline_runs_phases_and_repairs_once(self):
        runner = WorkflowRunner(chat_adapter=_CodingPipelineAdapter(), session_id="s1")
        out = await runner.run(
            {
                "workflow": "coding_pipeline",
                "goal": "implement solve() that returns two",
                "max_rounds": 2,
            }
        )
        self.assertEqual(out.get("pattern"), "coding_pipeline")
        self.assertTrue(bool(out.get("passed")))
        self.assertEqual(int(out.get("rounds_used") or 0), 2)
        self.assertIn("return 2", str(out.get("final_output") or ""))
        steps = out.get("steps") or []
        self.assertGreaterEqual(len(steps), 4)

    async def test_chain_allow_mode_skips_approval_broker(self):
        broker = _ApprovalBrokerStub(approve=False)
        runner = WorkflowRunner(
            chat_adapter=_ChainParallelAdapter(),
            session_id="s1",
            approval_broker=broker,
            no_human_mode="allow",
        )
        out = await runner.run(
            {
                "workflow": "chain",
                "goal": "update deployment notes",
                "steps": [{"name": "doc", "prompt": "rewrite notes", "approval": True}],
            }
        )
        self.assertEqual(out.get("pattern"), "chain")
        self.assertEqual(len(out.get("steps", [])), 1)
        self.assertEqual(len(broker.calls), 0)

    async def test_chain_deny_mode_blocks_approval_step(self):
        broker = _ApprovalBrokerStub(approve=True)
        runner = WorkflowRunner(
            chat_adapter=_ChainParallelAdapter(),
            session_id="s1",
            approval_broker=broker,
            no_human_mode="deny",
        )
        out = await runner.run(
            {
                "workflow": "chain",
                "goal": "update deployment notes",
                "steps": [{"name": "doc", "prompt": "rewrite notes", "approval": True}],
            }
        )
        self.assertEqual(out.get("pattern"), "chain")
        self.assertIs(out.get("ok"), False)
        self.assertIn("blocked by no-human deny", str(out.get("error") or ""))
        self.assertEqual(int(out.get("completed_steps") or 0), 0)
        self.assertEqual(len(broker.calls), 0)

    async def test_chain_mode_uses_no_human_env_mode_allow(self):
        os.environ["THOMAS_NO_HUMAN_MODE"] = "allow"
        broker = _ApprovalBrokerStub(approve=False)
        runner = WorkflowRunner(
            chat_adapter=_ChainParallelAdapter(),
            session_id="s1",
            approval_broker=broker,
            no_human_mode="human",
        )
        out = await runner.run(
            {
                "workflow": "chain",
                "goal": "env override review",
                "steps": [{"name": "doc", "prompt": "review release note", "approval": True}],
            }
        )
        self.assertEqual(out.get("pattern"), "chain")
        self.assertEqual(len(out.get("steps", [])), 1)
        self.assertEqual(len(broker.calls), 0)
