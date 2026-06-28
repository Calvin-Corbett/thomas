from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from thomas.server import chat_delegation
from thomas.server.chat_delegation_canvas import canvas_get, run_canvas_worker

# A valid choreography spec — the planner's only job now. The render is deterministic code,
# so the worker makes exactly ONE LLM call (the plan) and never a second render call.
_FAKE_PLAN = (
    '{"stage":{"w":720,"h":520,"bg":"#ffffff"},"title":"Sales","reveal_ms":1200,'
    '"elements":[{"id":"bar1","kind":"bar","role":"primary","color":"#14B8A6",'
    '"geometry":{"x":160,"y":260,"w":64,"h":130},"motion":"grow-y","dur_ms":520}],'
    '"sequence":{"order":["bar1"],"stagger_ms":70,"stagger_from":"first","total_ms":1200,"hero":"bar1"}}'
)


class _FakeStreamLLM:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, object]]] = []

    async def stream_chat(self, *, messages, tools=None):  # noqa: ANN001, ANN202
        self.calls.append(list(messages))
        # The planner emits the JSON spec; code renders it (no second LLM call).
        for chunk in (_FAKE_PLAN,):
            yield SimpleNamespace(type="token", data={"text": chunk})
        yield SimpleNamespace(type="done", data={})


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

    async def test_run_canvas_worker_pins_profile_none_for_warm_client(self) -> None:
        llm = _FakeStreamLLM()

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with patch("thomas.server.chat_delegation_canvas.build_canvas_llm", return_value=llm) as build_llm:
                html = await run_canvas_worker(
                    execution_id="exec-canvas-profile",
                    prompt="Draw a line chart",
                    root=root,
                    profile="visual-fast",
                )

        self.assertIn('id="tc-stage"', html)
        # The worker pins profile=None so a single warm client serves every canvas request
        # (the caller's chat profile is ignored to avoid a cold per-profile stall).
        build_llm.assert_called_once_with(root, None)

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
