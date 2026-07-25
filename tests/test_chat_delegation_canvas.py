from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from thomas.server import chat_delegation
from thomas.server import chat_delegation_canvas_worker as canvas_worker
from thomas.server.chat_budget_ledger import get_chat_budget_ledger
from thomas.server.chat_delegation_canvas import canvas_get, run_canvas_worker

# A valid choreography spec — the planner's only job now. The render is deterministic code,
# so the worker makes exactly ONE LLM call (the plan) and never a second render call.
_FAKE_PLAN = (
    '{"stage":{"w":720,"h":520,"bg":"#ffffff"},"title":"Sales","reveal_ms":1200,'
    '"elements":[{"id":"bar1","kind":"bar","role":"primary","color":"#14B8A6",'
    '"geometry":{"x":160,"y":260,"w":64,"h":130},"motion":"grow-y","dur_ms":520}],'
    '"sequence":{"order":["bar1"],"stagger_ms":70,"stagger_from":"first","total_ms":1200,"hero":"bar1"}}'
)

_REPAIRED_QUARTER_PLAN = (
    '{"stage":{"w":720,"h":520,"bg":"#ffffff"},"title":"Quarterly Results","reveal_ms":1200,'
    '"elements":[{"id":"q1","kind":"text","role":"text","label":"Q1 12","color":"#111827",'
    '"geometry":{"x":100,"y":120,"size":24},"motion":"rise-fade"},'
    '{"id":"q2","kind":"text","role":"text","label":"Q2 18","color":"#111827",'
    '"geometry":{"x":100,"y":180,"size":24},"motion":"rise-fade"},'
    '{"id":"q3","kind":"text","role":"text","label":"Q3 15","color":"#111827",'
    '"geometry":{"x":100,"y":240,"size":24},"motion":"rise-fade"},'
    '{"id":"q4","kind":"text","role":"text","label":"Q4 24","color":"#111827",'
    '"geometry":{"x":100,"y":300,"size":24},"motion":"rise-fade"}],'
    '"sequence":{"order":["q1","q2","q3","q4"],"stagger_ms":70}}'
)


class _FakeStreamLLM:
    def __init__(self, plans: list[str] | None = None) -> None:
        self.calls: list[list[dict[str, object]]] = []
        self.plans = list(plans or [_FAKE_PLAN])

    async def stream_chat(self, *, messages, tools=None):  # noqa: ANN001, ANN202
        self.calls.append(list(messages))
        # The planner emits the JSON spec; code renders it (no second LLM call).
        for chunk in (self.plans[min(len(self.calls) - 1, len(self.plans) - 1)],):
            yield SimpleNamespace(type="token", data={"text": chunk})
        yield SimpleNamespace(type="done", data={})


class _CloneableLLM(_FakeStreamLLM):
    instances: list[_CloneableLLM] = []

    def __init__(self, config=None, **_kwargs) -> None:  # noqa: ANN001
        super().__init__()
        self.config = config or SimpleNamespace()
        self.closed = False
        self._fallback_configs = []
        self._failover_enabled = False
        self._failover_cooldown_s = 300
        self._failover_on_auth_error = False
        self._max_retries = 3
        self._base_retry_delay = 0.8
        self._request_overrides = {}
        self.session_usage = SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        self.instances.append(self)

    async def close(self) -> None:
        self.closed = True

    async def stream_chat(self, *, messages, tools=None):  # noqa: ANN001, ANN202
        self.session_usage.prompt_tokens += 5
        self.session_usage.completion_tokens += 3
        self.session_usage.total_tokens += 8
        async for event in super().stream_chat(messages=messages, tools=tools):
            yield event


class _SharedBudgetCanvasLLM(_FakeStreamLLM):
    def __init__(self) -> None:
        super().__init__()
        self.budget_scope = None
        self.stream_scopes: list[str | None] = []
        self.session_usage = SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0)

    def set_budget_scope(self, scope):  # noqa: ANN001, ANN201
        previous = self.budget_scope
        self.budget_scope = scope
        return previous

    async def stream_chat(self, *, messages, tools=None):  # noqa: ANN001, ANN202
        self.stream_scopes.append(getattr(self.budget_scope, "session_id", None))
        self.session_usage.prompt_tokens += 5
        self.session_usage.completion_tokens += 3
        self.session_usage.total_tokens += 8
        await asyncio.sleep(0)
        async for event in super().stream_chat(messages=messages, tools=tools):
            yield event


class _BotStub:
    id = "nova"
    name = "Nova"

    def to_event_dict(self) -> dict[str, str]:
        return {"bot_id": self.id, "bot_name": self.name}


class TestCanvasWorker(unittest.IsolatedAsyncioTestCase):
    async def test_run_canvas_worker_renders_plan_deterministically(self) -> None:
        llm = _FakeStreamLLM()

        with tempfile.TemporaryDirectory() as d:
            with patch("thomas.server.chat_delegation_canvas.build_canvas_llm", return_value=llm):
                html = await run_canvas_worker(
                    execution_id="exec-canvas-stream",
                    prompt="Draw a bar chart",
                    root=Path(d),
                )

        # Exactly ONE LLM call (the plan) — the render is deterministic code.
        self.assertEqual(len(llm.calls), 1)
        self.assertIn('id="tc-stage"', html)
        self.assertIn("grow-y", html)  # the bar's motion verb, compiled to the contract
        live = canvas_get("exec-canvas-stream")
        self.assertIsNotNone(live)
        assert live is not None
        self.assertEqual(live["status"], "done")
        self.assertIn("tc-stage", live["html"])

    async def test_run_canvas_worker_propagates_selected_profile(self) -> None:
        llm = _FakeStreamLLM()

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with patch("thomas.server.chat_delegation_canvas.build_canvas_llm", return_value=llm) as build_llm:
                html = await run_canvas_worker(
                    execution_id="exec-canvas-profile",
                    prompt="Draw a line chart",
                    root=root,
                    profile="visual-fast",
                    model_id="gpt-5.6-terra",
                )

        self.assertIn('id="tc-stage"', html)
        # Canvas is part of the same user request, so its hidden construction
        # and review must honor the selected model profile rather than silently
        # falling back to a warm default client.
        build_llm.assert_called_once_with(root, "visual-fast", "gpt-5.6-terra")

    async def test_run_canvas_worker_uses_authenticated_session_llm_as_fallback(self) -> None:
        llm = _FakeStreamLLM()

        with tempfile.TemporaryDirectory() as d:
            with patch("thomas.server.chat_delegation_canvas.build_canvas_llm", return_value=None) as build_llm:
                html = await run_canvas_worker(
                    execution_id="exec-canvas-session-llm",
                    prompt="Draw a bar chart",
                    root=Path(d),
                    session_llm=llm,
                )

        self.assertIn('id="tc-stage"', html)
        self.assertEqual(len(llm.calls), 1)
        build_llm.assert_called_once_with(Path(d), None, None)

    async def test_run_canvas_worker_does_not_share_foreground_stream_client(self) -> None:
        canvas_llm = _FakeStreamLLM()
        foreground_llm = _FakeStreamLLM()

        with tempfile.TemporaryDirectory() as d:
            with patch("thomas.server.chat_delegation_canvas.build_canvas_llm", return_value=canvas_llm):
                html = await run_canvas_worker(
                    execution_id="exec-canvas-dedicated-llm",
                    prompt="Draw a bar chart",
                    root=Path(d),
                    session_llm=foreground_llm,
                )

        self.assertIn('id="tc-stage"', html)
        self.assertEqual(len(canvas_llm.calls), 1)
        self.assertEqual(foreground_llm.calls, [])

    async def test_run_canvas_worker_applies_policy_instructions_and_closes_owned_clone(self) -> None:
        _CloneableLLM.instances.clear()
        foreground_llm = _CloneableLLM()
        runtime_policy = {
            "system_instructions": "CANVAS_POLICY_SENTINEL",
            "quality": {"enforce": True, "max_agent_iterations": 3},
        }

        with tempfile.TemporaryDirectory() as d:
            budget_path = Path(d) / "budget.json"
            runtime_policy.update(
                {
                    "budget_context": {"ledger_path": str(budget_path), "user_id": "u1", "session_id": "s1"},
                    "cost": {"session_token_budget": 100, "daily_token_budget": 100, "throttle_on_budget": True},
                    "model": {"max_output_tokens": 100},
                }
            )
            html = await run_canvas_worker(
                execution_id="exec-canvas-runtime-policy",
                prompt="Draw a bar chart",
                root=Path(d),
                session_llm=foreground_llm,
                runtime_policy=runtime_policy,
            )
            totals = await get_chat_budget_ledger(budget_path).snapshot(user_id="u1", session_id="s1")

        clone = _CloneableLLM.instances[-1]
        self.assertIsNot(clone, foreground_llm)
        self.assertIn("CANVAS_POLICY_SENTINEL", str(clone.calls[0][0]["content"]))
        self.assertTrue(clone.closed)
        self.assertFalse(foreground_llm.closed)
        self.assertEqual(totals.session_tokens, 8)
        self.assertEqual(totals.daily_tokens, 8)
        self.assertIn('id="tc-stage"', html)

    async def test_budgeted_canvas_fails_closed_when_no_dedicated_client_exists(self) -> None:
        foreground_llm = _FakeStreamLLM()
        foreground_llm.budget_scope = "foreground-scope"
        foreground_llm.set_budget_scope = lambda scope: setattr(foreground_llm, "budget_scope", scope)

        with tempfile.TemporaryDirectory() as d:
            runtime_policy = {
                "budget_context": {
                    "ledger_path": str(Path(d) / "budget.sqlite3"),
                    "user_id": "u1",
                    "session_id": "s1",
                },
                "cost": {"session_token_budget": 100, "daily_token_budget": 100},
                "model": {"max_output_tokens": 100},
            }
            with patch("thomas.server.chat_delegation_canvas.build_canvas_llm", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "dedicated streaming LLM"):
                    await run_canvas_worker(
                        execution_id="exec-canvas-clone-failure",
                        prompt="Draw a bar chart",
                        root=Path(d),
                        session_llm=foreground_llm,
                        runtime_policy=runtime_policy,
                    )

        self.assertEqual(foreground_llm.calls, [])
        self.assertEqual(foreground_llm.budget_scope, "foreground-scope")

    async def test_concurrent_budgeted_canvas_jobs_isolate_cached_client_scopes(self) -> None:
        shared_llm = _SharedBudgetCanvasLLM()

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            budget_path = root / "budget.sqlite3"

            def policy(session_id: str) -> dict[str, object]:
                return {
                    "budget_context": {
                        "ledger_path": str(budget_path),
                        "user_id": "u1",
                        "session_id": session_id,
                    },
                    "cost": {"session_token_budget": 100, "daily_token_budget": 100},
                    "model": {"max_output_tokens": 100},
                }

            with patch("thomas.server.chat_delegation_canvas.build_canvas_llm", return_value=shared_llm):
                await asyncio.gather(
                    run_canvas_worker(
                        execution_id="exec-canvas-budget-a",
                        prompt="Draw a bar chart",
                        root=root,
                        runtime_policy=policy("A"),
                    ),
                    run_canvas_worker(
                        execution_id="exec-canvas-budget-b",
                        prompt="Draw a bar chart",
                        root=root,
                        runtime_policy=policy("B"),
                    ),
                )
            ledger = get_chat_budget_ledger(budget_path)
            totals_a = await ledger.snapshot(user_id="u1", session_id="A")
            totals_b = await ledger.snapshot(user_id="u1", session_id="B")

        self.assertCountEqual(shared_llm.stream_scopes, ["A", "B"])
        self.assertIsNone(shared_llm.budget_scope)
        self.assertEqual(totals_a.session_tokens, 8)
        self.assertEqual(totals_b.session_tokens, 8)

    async def test_run_canvas_worker_repairs_a_failed_semantic_review_before_presenting(self) -> None:
        llm = _FakeStreamLLM([_FAKE_PLAN, _REPAIRED_QUARTER_PLAN])
        prompt = (
            "Create a polished static bar chart showing Q1=12, Q2=18, Q3=15, and Q4=24. "
            "Render it live on Canvas and deliver chart.pdf plus the backing chart-data.csv."
        )

        with tempfile.TemporaryDirectory() as d:
            with patch("thomas.server.chat_delegation_canvas.build_canvas_llm", return_value=llm):
                html = await run_canvas_worker(
                    execution_id="exec-canvas-repair",
                    prompt=prompt,
                    root=Path(d),
                )

        self.assertEqual(len(llm.calls), 2)
        self.assertIn("REVIEW FINDINGS", str(llm.calls[1][1]["content"]))
        self.assertIn("Q4 24", html)
        live = canvas_get("exec-canvas-repair")
        self.assertIsNotNone(live)
        assert live is not None
        self.assertEqual(live["status"], "done")
        self.assertEqual(live["review_status"], "passed")

    async def test_visual_delegation_starts_canvas_worker_instead_of_agent_fallback(self) -> None:
        emit_event = AsyncMock()
        created_background = []
        execution_state = {"state": "executing", "progress_summary": "Drawing it on the canvas..."}

        def _create_execution(**kwargs):  # noqa: ANN202
            return {
                "execution_id": "exec-canvas-route",
                "conversation_id": kwargs["session_id"],
                "bot_id": kwargs["bot_id"],
            }

        def _get_execution(*_args, **_kwargs):  # noqa: ANN202
            return {
                "execution_id": "exec-canvas-route",
                "conversation_id": "sess-canvas",
                "backend_type": chat_delegation.PROVIDER_NATIVE_BACKEND,
                "state": execution_state["state"],
                "summary": "Draw a bar chart",
                "progress_summary": execution_state["progress_summary"],
                "bot_id": "nova",
                "runtime_profile": {"canvas": True},
            }

        def _update_execution(*_args, **kwargs):  # noqa: ANN202
            execution_state.update({k: v for k, v in kwargs.items() if k in execution_state})

        def _create_task(coro):  # noqa: ANN001, ANN202
            created_background.append(coro)
            coro.close()
            return SimpleNamespace()

        with (
            patch("thomas.server.chat_delegation.session_active_delegations", return_value=[]),
            patch("thomas.server.chat_delegation.pick_bot_for_specialist", return_value=_BotStub()),
            patch("thomas.server.chat_delegation.task_bot_runtime.create_execution", side_effect=_create_execution),
            patch("thomas.server.chat_delegation.task_bot_runtime.update_execution", side_effect=_update_execution),
            patch("thomas.server.chat_delegation.task_bot_runtime.get_execution", side_effect=_get_execution),
            patch("thomas.server.chat_delegation.asyncio.create_task", side_effect=_create_task),
            patch("thomas.server.chat_delegation._start_agent_worker_delegation", new=AsyncMock()) as start_agent,
        ):
            result = await chat_delegation.start_background_delegation(
                {},
                session_id="sess-canvas",
                prompt="Draw a bar chart of sales by quarter",
                mode="max",
                recent_messages=[],
                emit_event=emit_event,
                session_llm=_FakeStreamLLM(),
            )

        self.assertEqual(result["execution_id"], "exec-canvas-route")
        self.assertTrue(result["is_canvas"])
        self.assertEqual(len(created_background), 1)
        start_agent.assert_not_awaited()


_PIE_SPEC = """
{
  "stage": {"w": 720, "h": 520, "bg": "#ffffff"},
  "title": "Fruit Sales",
  "reveal_ms": 1300,
  "elements": [
    {"id": "panel", "kind": "box", "role": "background", "color": "#F6F8FB",
     "geometry": {"x": 44, "y": 44, "w": 632, "h": 432, "rx": 28}, "motion": "rise-fade", "dur_ms": 360},
    {"id": "title", "kind": "text", "role": "text", "label": "Fruit Sales", "color": "#263238",
     "geometry": {"x": 72, "y": 72, "size": 28, "weight": 700, "anchor": "start"}, "motion": "rise-fade", "dur_ms": 320},
    {"id": "apples", "kind": "wedge", "role": "primary", "color": "#E53935",
     "geometry": {"cx": 286, "cy": 270, "r": 128, "r_inner": 62, "a0": -90, "a1": 54}, "motion": "sweep", "dur_ms": 620},
    {"id": "total", "kind": "number", "role": "text", "value": 100, "color": "#263238",
     "geometry": {"x": 226, "y": 250, "w": 120, "size": 34, "weight": 800, "anchor": "middle"}, "motion": "count-up", "dur_ms": 700}
  ],
  "sequence": {"order": ["panel", "title", "apples", "total"], "stagger_ms": 70,
               "stagger_from": "first", "total_ms": 1300, "hero": "apples"}
}
"""


class TestDeterministicRenderer(unittest.TestCase):
    """The render is now CODE, not a second LLM call. These asserts are the CI gate that a
    future change can't break the no-flash entrance contract (mirrors the static checks the
    backend conformance gate runs)."""

    def test_build_canvas_html_conforms_to_contract(self) -> None:
        from thomas.server.chat_delegation_canvas import _conforms_to_contract, build_canvas_html

        html = build_canvas_html(_PIE_SPEC)
        low = html.lower()
        self.assertTrue(html.startswith("<!DOCTYPE html"))
        self.assertTrue(_conforms_to_contract(html))
        # The fixed render contract — the no-flash / no-stuck guarantees:
        self.assertIn('id="tc-stage"', html)
        self.assertIn('data-reveal="pending"', html)  # starts hidden via the animated channel
        self.assertIn("--i:", html)  # per-element stagger index
        self.assertIn("prefers-reduced-motion", low)  # reduced-motion support
        self.assertIn("2500", html)  # in-doc stuck-hidden safety net
        self.assertNotIn("display:none", html.replace(" ", ""))  # never hide via display:none
        self.assertIn(".el{position:absolute;pointer-events:none", html)

    def test_renders_each_primitive(self) -> None:
        from thomas.server.chat_delegation_canvas import build_canvas_html

        html = build_canvas_html(_PIE_SPEC)
        self.assertIn("<path", html)  # wedge -> svg path
        self.assertIn('data-count="100"', html)  # number -> count-up
        self.assertIn("Fruit Sales", html)  # text label rendered

    def test_raw_escape_hatch_passes_svg_through(self) -> None:
        from thomas.server.chat_delegation_canvas import build_canvas_html

        spec = (
            '{"stage":{"w":400,"h":300},"elements":['
            '{"id":"art","kind":"raw","motion":"draw-stroke",'
            '"geometry":{"x":10,"y":10,"svg":"<svg><path d=\\"M0 0 L9 9\\"/></svg>"}}],'
            '"sequence":{"order":["art"],"stagger_ms":60}}'
        )
        html = build_canvas_html(spec)
        self.assertIn("M0 0 L9 9", html)  # arbitrary SVG survives verbatim
        # Later full-stage animation wrappers must not steal pointer input from interactive
        # descendants in an earlier raw SVG layer (for example a game's Restart control).
        self.assertIn(".el{position:absolute;pointer-events:none", html)
        self.assertIn('class="el raw-el ', html)
        self.assertIn(".raw-el [role='button']", html)

    def test_malformed_spec_raises_for_fallback(self) -> None:
        from thomas.server.chat_delegation_canvas import build_canvas_html

        with self.assertRaises(ValueError):
            build_canvas_html("this is not json")  # caller then falls back to the LLM render

    def test_parse_spec_tolerates_fence_and_prose(self) -> None:
        from thomas.server.chat_delegation_canvas import parse_spec

        got = parse_spec('Sure! ```json\n{"a": 1, "elements": []}\n```')
        self.assertEqual(got, {"a": 1, "elements": []})

    def test_donut_path_is_valid_svg(self) -> None:
        from thomas.server.chat_delegation_canvas import _donut_path

        d = _donut_path(100, 100, 80, 40, 0, 90)
        self.assertTrue(d.startswith("M"))
        self.assertIn("A", d)  # arc command
        self.assertTrue(d.endswith("Z"))


if __name__ == "__main__":
    unittest.main()


class _DeadSocketLLM:
    """A provider that accepts the request and then never says anything."""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, object]]] = []

    async def stream_chat(self, *, messages, tools=None):  # noqa: ANN001, ANN202
        self.calls.append(list(messages))
        await asyncio.sleep(3600)
        yield SimpleNamespace(type="done", data={})  # pragma: no cover - never reached


class CanvasDeadConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_silent_connection_is_not_retried(self) -> None:
        """The canvas LLM lock is global and is held across every attempt, so
        retrying a socket that produced nothing blocks every OTHER
        conversation's canvas for twice as long -- and a connection that said
        nothing the first time has no more reason to speak the second.

        A stall AFTER data arrived is a different thing and is still retried.
        """
        llm = _DeadSocketLLM()

        with patch.object(canvas_worker, "_DEAD_SOCKET_S", 0.05):
            with tempfile.TemporaryDirectory() as d:
                with patch(
                    "thomas.server.chat_delegation_canvas.build_canvas_llm", return_value=llm
                ):
                    with self.assertRaises(Exception) as caught:
                        await run_canvas_worker(
                            execution_id="exec-canvas-dead",
                            prompt="Draw a simple bar chart of quarterly sales",
                            root=Path(d),
                        )

        self.assertEqual(len(llm.calls), 1, "a dead connection must not be dialled twice")
        self.assertIn("1 attempt", str(caught.exception))
