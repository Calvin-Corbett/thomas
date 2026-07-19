"""The send_task tool — organic, no-regex, honest dispatch.

Proves the mechanism deterministically (mocked LLM, no live model): when the
model calls send_task, the reasoning specialist actually invokes the dispatch
callback (so any "handed off" claim is TRUE), emits a task_request, and replies
with the model's own confirmation. When the model doesn't call it, nothing
dispatches and nothing is faked. This is the fix for the dishonesty Calvin found
("I'll get that started" with nothing behind it).
"""

import unittest
from datetime import datetime, timedelta, timezone

from thomas.core.llm_shared import StreamEvent
from thomas.marketplace.orchestrator.protocol import CapabilityToken, DelegationContract
from thomas.marketplace.specialists.reasoning import ReasoningSpecialist


class _FakeLLM:
    """stream_chat returns a scripted event stream per call (pass 1, pass 2...)."""

    def __init__(self, scripts):
        self._scripts = scripts
        self.calls = []

    def stream_chat(self, *, messages, tools=None):
        idx = len(self.calls)
        self.calls.append({"messages": list(messages), "tools": tools})
        events = self._scripts[idx] if idx < len(self._scripts) else [StreamEvent(type="done")]

        async def _gen():
            for ev in events:
                yield ev

        return _gen()


async def _run(scripts, send_task, operate=None):
    spec = ReasoningSpecialist(config=None, llm=_FakeLLM(scripts))
    contract = DelegationContract(
        specialist_id="reasoning",
        task_description="x",
        allowed_tools={"reasoning"},
        timeout_seconds=0,
        input_context={"send_task": send_task, "operate": operate},
    )
    token = CapabilityToken(
        specialist_id="reasoning",
        session_id="s",
        allowed_tools={"reasoning"},
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    events = []
    async for ev in spec.execute(
        contract=contract,
        token=token,
        prompt="build me a pac-man game",
        conversation_context=[],
        memory_context="",
    ):
        events.append(ev)
    return events, spec.llm


class TestSendTaskTool(unittest.IsolatedAsyncioTestCase):
    async def test_model_call_creates_real_task_and_honest_reply(self):
        captured = {}

        async def send_task(*, title, instructions, surface=""):
            captured["title"] = title
            captured["instructions"] = instructions

        scripts = [
            # pass 1: the model decides to hand off (no regex involved)
            [
                StreamEvent(
                    type="tool_call_end",
                    data={
                        "id": "c1",
                        "name": "send_task",
                        "arguments": '{"title":"Build a Pac-Man game","instructions":"Build a pac-man browser game"}',
                    },
                ),
                StreamEvent(type="done"),
            ],
            # pass 2: natural confirmation after the task result
            [
                StreamEvent(type="token", data={"text": "On its way — "}),
                StreamEvent(type="token", data={"text": "the team is building your Pac-Man game."}),
                StreamEvent(type="done"),
            ],
        ]
        events, llm = await _run(scripts, send_task)

        # The claim is TRUE: send_task was actually invoked.
        self.assertEqual(captured.get("title"), "Build a Pac-Man game")
        # Instructions forward the USER'S RAW request, not the model's reworded version
        # (Calvin, 2026-06-26: the task manager reads the real ask, undistorted).
        self.assertEqual(captured.get("instructions"), "build me a pac-man game")
        # A task_request event was surfaced for the UI/brain.
        self.assertTrue(any(e.get("type") == "task_request" for e in events))
        # Final reply is the model's own confirmation — not a canned line.
        done = next(e for e in events if e.get("type") == "done")
        self.assertIn("Pac-Man", done.get("content", ""))
        # Tool offered on pass 1, withdrawn on pass 2 (no double-dispatch).
        self.assertIsNotNone(llm.calls[0]["tools"])
        self.assertIsNone(llm.calls[1]["tools"])

    async def test_post_dispatch_completion_claim_is_rewritten_before_emission(self):
        async def send_task(*, title, instructions, surface=""):
            return None

        scripts = [
            [
                StreamEvent(
                    type="tool_call_end",
                    data={
                        "id": "c1",
                        "name": "send_task",
                        "arguments": '{"title":"Build three files","instructions":"Build them"}',
                    },
                ),
                StreamEvent(type="done"),
            ],
            [
                StreamEvent(type="token", data={"text": "Done — I built all three files and they are ready."}),
                StreamEvent(type="done"),
            ],
        ]

        events, _ = await _run(scripts, send_task)
        visible = "".join(str(event.get("text") or "") for event in events if event.get("type") == "text")
        done = next(event for event in events if event.get("type") == "done")
        self.assertIn("running now", visible)
        self.assertNotIn("built all three", visible.lower())
        self.assertIn("running now", str(done.get("content") or ""))

    async def test_pre_tool_completion_claim_is_never_streamed(self):
        async def send_task(*, title, instructions, surface=""):
            return None

        scripts = [
            [
                StreamEvent(type="token", data={"text": "Done — I built all three files."}),
                StreamEvent(
                    type="tool_call_end",
                    data={
                        "id": "c1",
                        "name": "send_task",
                        "arguments": '{"title":"Build three files","instructions":"Build them"}',
                    },
                ),
                StreamEvent(type="done"),
            ],
            [
                StreamEvent(type="token", data={"text": "The three builds are running now."}),
                StreamEvent(type="done"),
            ],
        ]

        events, _ = await _run(scripts, send_task)
        visible = "".join(str(event.get("text") or "") for event in events if event.get("type") == "text")
        self.assertNotIn("built all three", visible.lower())
        self.assertIn("running now", visible.lower())

    async def test_text_form_tool_call_drops_false_pre_call_completion_claim(self):
        async def send_task(*, title, instructions, surface=""):
            return None

        scripts = [
            [
                StreamEvent(
                    type="token",
                    data={
                        "text": (
                            "Done — I built all three files. send_task "
                            '{"title":"Build three files","instructions":"Build them"}'
                        )
                    },
                ),
                StreamEvent(type="done"),
            ]
        ]
        events, _ = await _run(scripts, send_task)
        visible = "".join(str(event.get("text") or "") for event in events if event.get("type") == "text")
        self.assertNotIn("built all three", visible.lower())
        self.assertTrue(any(event.get("type") == "task_request" for event in events))

    async def test_no_tool_call_means_no_dispatch_no_fake(self):
        called = {"n": 0}

        async def send_task(*, title, instructions, surface=""):
            called["n"] += 1

        scripts = [
            [
                StreamEvent(type="token", data={"text": "A process has its own memory; a thread shares it."}),
                StreamEvent(type="done"),
            ]
        ]
        events, _ = await _run(scripts, send_task)
        self.assertEqual(called["n"], 0)  # nothing dispatched
        self.assertFalse(any(e.get("type") == "task_request" for e in events))
        done = next(e for e in events if e.get("type") == "done")
        self.assertIn("thread", done.get("content", "").lower())

    async def test_no_callback_means_tool_not_offered(self):
        scripts = [[StreamEvent(type="token", data={"text": "hi there"}), StreamEvent(type="done")]]
        _, llm = await _run(scripts, None)
        self.assertIsNone(llm.calls[0]["tools"])  # no send_task wired -> no tools offered

    async def test_governed_operator_call_returns_effect_receipt_to_model(self):
        captured = {}

        async def operate(*, action, key="", value=None):
            captured.update({"action": action, "key": key, "value": value})
            return {
                "ok": True,
                "action": action,
                "reversible": True,
                "evidence": {"previous_value": "light", "observed_value": value},
            }

        scripts = [
            [
                StreamEvent(
                    type="tool_call_end",
                    data={
                        "id": "op1",
                        "name": "operate",
                        "arguments": '{"action":"preferences.set","key":"theme","value":"dark"}',
                    },
                ),
                StreamEvent(type="done"),
            ],
            [
                StreamEvent(type="token", data={"text": "Done — your theme is dark, and I verified it."}),
                StreamEvent(type="done"),
            ],
        ]

        events, llm = await _run(scripts, None, operate=operate)

        self.assertEqual(
            captured,
            {"action": "preferences.set", "key": "theme", "value": "dark"},
        )
        receipt = next(e for e in events if e.get("type") == "tool_result" and e.get("name") == "operate")
        self.assertTrue(receipt.get("ok"))
        done = next(e for e in events if e.get("type") == "done")
        self.assertIn("verified", done.get("content", ""))
        offered = {spec["function"]["name"] for spec in llm.calls[0]["tools"]}
        self.assertIn("operate", offered)


if __name__ == "__main__":
    unittest.main()
