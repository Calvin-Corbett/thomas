
import json
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
        if idx >= len(self._scripts):
            raise AssertionError("unexpected extra model pass")
        events = self._scripts[idx]

        async def _gen():
            for ev in events:
                yield ev

        return _gen()


async def _run(scripts, send_task, operate=None, update_task=None):
    spec = ReasoningSpecialist(config=None, llm=_FakeLLM(scripts))
    contract = DelegationContract(
        specialist_id="reasoning",
        task_description="x",
        allowed_tools={"reasoning"},
        timeout_seconds=0,
        input_context={"send_task": send_task, "operate": operate, "update_task": update_task},
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
        ]
        events, llm = await _run(scripts, send_task)

        # The claim is TRUE: send_task was actually invoked.
        self.assertEqual(captured.get("title"), "Build a Pac-Man game")
        # The structured brief chosen by Thomas is authoritative. Replacing it
        # with the latest raw utterance is what turned a graph follow-up into a
        # detached, generic build task.
        self.assertEqual(captured.get("instructions"), "Build a pac-man browser game")
        # A task_request event was surfaced for the UI/brain.
        self.assertTrue(any(e.get("type") == "task_request" for e in events))
        # The receipt is runtime-owned and can only appear after the callback.
        done = next(e for e in events if e.get("type") == "done")
        self.assertEqual(done.get("content"), "Started the task card “Build a Pac-Man game”. Follow progress there.")
        # There is no discarded second model pass and no opportunity to dispatch
        # the same work twice.
        self.assertEqual(len(llm.calls), 1)
        self.assertIsNotNone(llm.calls[0]["tools"])

    async def test_model_authored_completion_claims_cannot_replace_the_runtime_receipt(self):
        claims = (
            "Done — I built all three files and they are ready.",
            "The requested deliverable already exists now.",
            "I wrote the requested report.",
            "Your generated artifact is available.",
        )

        for claim in claims:
            with self.subTest(claim=claim):
                calls = []

                async def send_task(*, title, instructions, surface=""):
                    calls.append(title)

                scripts = [
                    [
                        StreamEvent(
                            type="tool_call_end",
                            data={
                                "id": "c1",
                                "name": "send_task",
                                "arguments": (
                                    '{"title":"Build three files","instructions":"Build them",'
                                    f'"confirmation":{json.dumps(claim)}}}'
                                ),
                            },
                        ),
                        StreamEvent(type="done"),
                    ]
                ]

                events, llm = await _run(scripts, send_task)
                visible = "".join(str(event.get("text") or "") for event in events if event.get("type") == "text")
                done = next(event for event in events if event.get("type") == "done")
                self.assertEqual(calls, ["Build three files"])
                self.assertEqual(sum(event.get("type") == "task_request" for event in events), 1)
                self.assertEqual(len(llm.calls), 1)
                self.assertEqual(visible, "Started the task card “Build three files”. Follow progress there.")
                self.assertEqual(visible, str(done.get("content") or ""))
                self.assertNotEqual(visible, claim)

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
        ]

        events, _ = await _run(scripts, send_task)
        visible = "".join(str(event.get("text") or "") for event in events if event.get("type") == "text")
        self.assertNotIn("built all three", visible.lower())
        self.assertIn("Started the task card", visible)

    async def test_successful_send_uses_title_receipt_without_an_extra_pass(self):
        async def send_task(*, title, instructions, surface=""):
            return None

        scripts = [
            [
                StreamEvent(
                    type="tool_call_end",
                    data={
                        "id": "c1",
                        "name": "send_task",
                        "arguments": '{"title":"Draft the report","instructions":"Draft it"}',
                    },
                ),
                StreamEvent(type="done"),
            ]
        ]

        events, llm = await _run(scripts, send_task)
        done = next(event for event in events if event.get("type") == "done")
        self.assertIn("Draft the report", str(done.get("content") or ""))
        self.assertIn("task card", str(done.get("content") or ""))
        self.assertEqual(len(llm.calls), 1)

    async def test_failed_dispatch_may_use_a_second_pass_to_explain_the_failure(self):
        async def send_task(*, title, instructions, surface=""):
            raise RuntimeError("queue offline")

        scripts = [
            [
                StreamEvent(
                    type="tool_call_end",
                    data={
                        "id": "c1",
                        "name": "send_task",
                        "arguments": '{"title":"Draft the report","instructions":"Draft it"}',
                    },
                ),
                StreamEvent(type="done"),
            ],
            [
                StreamEvent(type="token", data={"text": "I couldn’t start that because the queue is offline."}),
                StreamEvent(type="done"),
            ],
        ]

        events, llm = await _run(scripts, send_task)
        self.assertFalse(any(event.get("type") == "task_request" for event in events))
        done = next(event for event in events if event.get("type") == "done")
        self.assertIn("couldn’t start", str(done.get("content") or ""))
        self.assertEqual(len(llm.calls), 2)

    async def test_successful_update_uses_runtime_receipt_once(self):
        captured = {}

        async def update_task(*, task_ref, update, cancel=False):
            captured.update({"task_ref": task_ref, "update": update, "cancel": cancel})
            return {"ok": True, "action": "steer"}

        scripts = [
            [
                StreamEvent(
                    type="tool_call_end",
                    data={
                        "id": "u1",
                        "name": "update_task",
                        "arguments": '{"task_ref":"exec-123","update":"make it blue"}',
                    },
                ),
                StreamEvent(type="done"),
            ]
        ]

        events, llm = await _run(scripts, None, update_task=update_task)
        self.assertEqual(captured, {"task_ref": "exec-123", "update": "make it blue", "cancel": False})
        self.assertTrue(any(event.get("type") == "task_update" for event in events))
        done = next(event for event in events if event.get("type") == "done")
        self.assertEqual(done.get("content"), "The requested change was sent to the running task.")
        self.assertEqual(len(llm.calls), 1)

    async def test_text_form_tool_call_never_dispatches(self):
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
        self.assertIn("send_task", visible)
        self.assertFalse(any(event.get("type") == "task_request" for event in events))

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
