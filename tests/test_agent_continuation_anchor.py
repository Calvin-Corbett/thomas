"""Internal corrections remain the latest semantic input on the actual Codex request."""

from __future__ import annotations

import asyncio
import json

import pytest

from tests.test_build_agent_team import OfflineClient, runtime  # noqa: F401
from thomas.agent import acceptance_runtime
from thomas.agent.loop import AgentLoop
from thomas.core.events import EventType
from thomas.core.llm_client import LLMClient
from thomas.core.llm_shared import StreamEvent
from thomas.core.llm_streaming_codex import _build_openai_codex_request
from thomas.forge.anvil import build_agent_team as team
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.registry import ToolRegistry


def configure(monkeypatch, runtime, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("THOMAS_VERIFICATION_CONTRACT", "1")
    monkeypatch.setenv("THOMAS_TASK_CHECKLISTS", "1")
    monkeypatch.setenv("THOMAS_LIBRARY_ENABLED", "0")
    monkeypatch.setattr(acceptance_runtime, "load_learned", lambda *_: [])
    monkeypatch.setattr(acceptance_runtime, "record_misses", lambda *_: None)
    runtime.models["selected"].reasoning_effort = "medium"
    runtime.models["selected"].context_window = 65536
    runtime.models["selected"].max_tokens = 1024
    runtime.max_agent_iterations = 6


def user_contents(body):
    return [item["content"] for item in body["input"] if item.get("role") == "user"]


@pytest.mark.asyncio
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("steer", [False, True])
async def test_builder_missing_verify_hold_is_last_outbound_input(monkeypatch, runtime, tmp_path, compact, steer):
    configure(monkeypatch, runtime, tmp_path)
    requests = []
    corrections = []
    compacted = []
    queue = asyncio.Queue()
    steering = "Keep the assigned file's text exactly VERIFIED."
    real_factory = team.build_agent_loop

    def factory(*args, **kwargs):
        agent = real_factory(*args, **kwargs)
        agent._message_queue = queue
        if compact:

            async def compact_history(**_kwargs):
                last = agent._conversation[-1]
                if last.get("role") == "user" and str(last.get("content", "")).startswith(
                    acceptance_runtime.NOT_FINISHED
                ):
                    corrections.append(last["content"])
                    # Simulate a compacted tail that dropped the latest user item.
                    # The original task remains in the retained history.
                    agent._conversation[:] = [
                        agent._conversation[0],
                        {"role": "assistant", "content": "File written and read back."},
                    ]
                    compacted.append(True)
                return None

            agent._auto_compact_if_needed = compact_history
        return agent

    class Model(OfflineClient):
        _sanitize_tool_name = staticmethod(LLMClient._sanitize_tool_name)
        calls = 0

        async def stream_chat(self, messages, tools, *, turn_user_content=None):
            self.calls += 1
            requests.append(_build_openai_codex_request(self, messages, tools, turn_user_content=turn_user_content))
            if self.calls in (1, 2) or (self.calls == 4 and steer):
                name = "fs.write_file" if self.calls == 1 else "fs.read_file"
                args = {"path": "answer.txt"}
                if self.calls == 1:
                    args["content"] = "VERIFIED"
                elif self.calls == 4:
                    queue.put_nowait(steering)
                yield StreamEvent(type="tool_call_start", data={"id": str(self.calls), "name": name})
                yield StreamEvent(
                    type="tool_call_end", data={"id": str(self.calls), "name": name, "arguments": json.dumps(args)}
                )
            else:
                reply = "Wrote the assigned file."
                if self.calls > 3:
                    reply += (
                        "\nEVIDENCE: fs.write_file wrote the requested text.\n"
                        "VERIFY: python -c \"from pathlib import Path; assert Path('answer.txt').read_text() == 'VERIFIED'\""
                    )
                yield StreamEvent(type="token", data={"text": reply})
            yield StreamEvent(type="done", data={})

    monkeypatch.setattr(team, "build_agent_loop", factory)
    monkeypatch.setattr(team, "LLMClient", Model)
    tools = ToolRegistry()
    register_filesystem_tools(tools, tmp_path)
    events = []
    team.register_build_team(
        tools,
        config=runtime,
        model_config=runtime.models["selected"],
        emit=events.append,
        timeout=20,
        autonomy_level=3,
        tools_policy="auto",
        token_economy="cheap",
        protected_paths=[],
        can_write=True,
    )
    result = await asyncio.wait_for(
        tools.execute(
            "task.spawn",
            {
                "title": "Write answer",
                "path": "answer.txt",
                "context_files": [],
                "instructions": "Create answer.txt containing exactly VERIFIED.",
            },
        ),
        timeout=25,
    )
    assert result.ok, result.error
    assert (tmp_path / "answer.txt").read_text() == "VERIFIED"
    assert len(requests) == (5 if steer else 4)
    original = user_contents(requests[0])[-1]
    after_hold = user_contents(requests[3])
    assert after_hold[-1].startswith(acceptance_runtime.NOT_FINISHED)
    assert "the reply declares no VERIFY: command" in after_hold[-1]
    assert original in after_hold[:-1] and after_hold.count(original) == 1
    assert sum("not finished yet" in event.get("text", "") for event in events) == 1
    if compact:
        assert compacted and after_hold[-1] == corrections[0]
    if steer:
        assert user_contents(requests[4])[-1] == steering
    assert all(client.closed for client in OfflineClient.instances)


@pytest.mark.asyncio
async def test_steer_during_final_answer_continues_same_agent_run(monkeypatch, runtime, tmp_path):
    configure(monkeypatch, runtime, tmp_path)
    requests = []
    queue = asyncio.Queue()
    update = "Use tomorrow instead; do not create a second task."

    class Model(OfflineClient):
        _sanitize_tool_name = staticmethod(LLMClient._sanitize_tool_name)

        async def stream_chat(self, messages, tools, *, turn_user_content=None):
            requests.append(_build_openai_codex_request(self, messages, tools, turn_user_content=turn_user_content))
            if len(requests) == 1:
                queue.put_nowait(update)
            yield StreamEvent(type="token", data={"text": "Adjusted the work."})
            yield StreamEvent(type="done", data={})

    loop = AgentLoop(runtime, Model(runtime.models["selected"]), ToolRegistry(), conversation=[], message_queue=queue)
    events = [event async for event in loop.run("Finish the report.", tools_policy="never", max_iterations=1)]
    assert len(requests) == 2
    assert user_contents(requests[1])[-1] == update
    assert user_contents(requests[1])[0] == "Finish the report."
    assert sum(event.type == EventType.AGENT_DONE for event in events) == 1


@pytest.mark.asyncio
async def test_code_output_correction_is_last_outbound_input(monkeypatch, runtime, tmp_path):
    configure(monkeypatch, runtime, tmp_path)
    requests = []

    class Model(OfflineClient):
        _sanitize_tool_name = staticmethod(LLMClient._sanitize_tool_name)

        async def stream_chat(self, messages, tools, *, turn_user_content=None):
            requests.append(_build_openai_codex_request(self, messages, tools, turn_user_content=turn_user_content))
            text = "for i in range(3):\nprint(i)" if len(requests) == 1 else "    for i in range(3):\n        print(i)"
            yield StreamEvent(type="token", data={"text": text})
            yield StreamEvent(type="done", data={})

    model = Model(runtime.models["selected"])
    loop = AgentLoop(runtime, model, ToolRegistry(), conversation=[])
    prompt = "Return ONLY the Python code continuation.\n---PROMPT START---\ndef demo():\n---PROMPT END---\n"
    events = [event async for event in loop.run(prompt, tools_policy="never", job_type="benchmark", max_iterations=4)]
    assert len(requests) == 2
    after_correction = user_contents(requests[1])
    assert after_correction[0] == prompt
    assert "Previous continuation failed code-output validation" in after_correction[-1]
    assert after_correction[-1] != prompt
    done = [event for event in events if event.type == EventType.AGENT_DONE]
    assert len(done) == 1
    compile("def demo():\n" + done[0].data["text"], "<verified continuation>", "exec")
