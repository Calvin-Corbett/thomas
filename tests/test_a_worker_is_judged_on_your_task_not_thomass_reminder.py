"""A worker's finish is judged against your task, not against Thomas's own reminder.

The chat worker puts a reminder in front of every task: "when the task names
`browser.open`, `browser.extract`, or another browser tool, call those exact
tools". The acceptance contract read the reminder as part of the task, took the
two backticked tool names for files the task must produce, and sent the finished
work back until the completion gate blocked it. On 2026-09-22 three self-fixes on
the caged server wrote the change and passed py_compile and ruff, then failed as
"a retryable provider error". The worker had also opened example.com to satisfy
a check that could never pass.

Build already judges the request and not its execution policy
(``tests/test_build_acceptance_user_intent.py``); this is the chat worker's half.
"""

from __future__ import annotations

import asyncio
import json
import sys

import pytest

from tests.test_agent_worker_parity import _app_with_model, _FakeLLM
from thomas.agent import acceptance_runtime
from thomas.agent.loop import AgentLoop
from thomas.core.llm import StreamEvent
from thomas.server import app_helpers, worker_runtime
from thomas.tools.filesystem import ReadFileTool, WriteFileTool
from thomas.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_a_finished_worker_is_not_sent_back_over_thomass_own_reminder(monkeypatch, tmp_path):
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("THOMAS_VERIFICATION_CONTRACT", "1")
    monkeypatch.setenv("THOMAS_TASK_CHECKLISTS", "0")
    monkeypatch.setattr(acceptance_runtime, "load_learned", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(acceptance_runtime, "record_misses", lambda *_args, **_kwargs: None)
    workspace = tmp_path / "task"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    prompt = "Create `note.txt` containing exactly NOTE-OK."
    check = f"from pathlib import Path; assert Path({str(workspace / 'note.txt')!r}).read_bytes() == b'NOTE-OK'"
    final_text = f'Created note.txt.\nEVIDENCE: wrote NOTE-OK\nVERIFY: "{sys.executable}" -c "{check}"'
    seen: dict = {}
    tools = ToolRegistry()
    tools.register(WriteFileTool(workspace))
    tools.register(ReadFileTool(workspace))

    class ObservedLoop(AgentLoop):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.llm.agent = self

    class FileLLM(_FakeLLM):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.calls = 0
            self.config.context_window = 100_000

        async def stream_chat(self, messages, tools):
            self.calls += 1
            seen.setdefault("first_messages", list(messages))
            seen["contract"] = self.agent._acceptance_state
            if self.calls == 1:
                args = {"path": "note.txt", "content": "NOTE-OK"}
                yield StreamEvent(type="tool_call_start", data={"id": "write-1", "name": "fs.write_file"})
                yield StreamEvent(
                    type="tool_call_end", data={"id": "write-1", "name": "fs.write_file", "arguments": json.dumps(args)}
                )
            else:
                yield StreamEvent(type="token", data={"text": final_text})
            yield StreamEvent(type="done", data={})

    monkeypatch.setattr(worker_runtime, "LLMClient", FileLLM)
    monkeypatch.setattr(worker_runtime, "AgentLoop", ObservedLoop)
    monkeypatch.setattr(app_helpers, "_build_tools", lambda *_args, **_kwargs: tools)
    app = _app_with_model("fixture", "offline", "local")
    app[worker_runtime.APP_CONFIG].memory.root = str(tmp_path / "memory")

    async def drain() -> list[dict]:
        stream = worker_runtime.run_agent_worker_events(
            app,
            prompt=prompt,
            instructions="Produce the real file and verify it.",
            work_dir=workspace,
            profile="local",
            reasoning_effort="medium",
        )
        return [event async for event in stream]

    events = await asyncio.wait_for(drain(), timeout=240)

    items = seen["contract"]["items"]
    assert not [item.item_id for item in items if "browser." in item.item_id], items
    assert seen["contract"]["prompt_text"] == prompt
    # The reminder is still the model's to read: only the judging changed.
    model_context = "\n".join(str(message.get("content", "")) for message in seen["first_messages"])
    assert "`browser.open`" in model_context and prompt in model_context
    assert not [event for event in events if event["type"] == "error"], events
    assert events[-1]["type"] == "done"
    assert (workspace / "note.txt").read_bytes() == b"NOTE-OK"
