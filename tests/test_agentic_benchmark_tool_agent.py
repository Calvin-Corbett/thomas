from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from thomas.demo.agentic_benchmark import _run_tool_agent_task
from thomas.tools.base import ToolResult


def test_run_tool_agent_task_executes_tool_loop_directly() -> None:
    class _FakeConfig:
        def get_model(self, _profile):
            return object()

    class _FakeLLM:
        def __init__(self):
            self.calls = 0

        async def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return {
                    "text": "",
                    "tool_calls": [
                        {
                            "id": "tc1",
                            "name": "read_file",
                            "arguments": json.dumps({"path": "thomas.toml"}),
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
                }
            return {
                "text": "codex",
                "tool_calls": [],
                "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
            }

        async def close(self):
            return None

    class _FakeRegistry:
        def get_openai_specs(self):
            return [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}]

        async def execute(self, name, args):
            self.last_call = (name, args)
            return ToolResult(ok=True, data="default_model = 'codex'")

    fake_llm = _FakeLLM()
    fake_registry = _FakeRegistry()

    with (
        patch("thomas.demo.agentic_benchmark_tool_agent.LLMClient", return_value=fake_llm),
        patch("thomas.demo.agentic_benchmark_tool_agent._build_tools", return_value=fake_registry),
    ):
        result = asyncio.run(
            _run_tool_agent_task(
                _FakeConfig(),
                profile="codex",
                prompt="Read thomas.toml and reply with the default model only.",
            )
        )

    assert result["ok"] is True
    assert result["text"] == "codex"
    assert result["tool_calls"] == 1
    assert fake_registry.last_call == ("read_file", {"path": "thomas.toml"})
