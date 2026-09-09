"""AgentLoop bounds tool execution by default.

Plan-mode / CLI / integration callers historically constructed AgentLoop without
tool_timeout_s or max_parallel_tools, which the executor treated as "no timeout"
and unbounded parallelism -- a single hung tool could stall the whole turn. The
constructor now resolves those to safe defaults while honoring explicit values.
"""

from __future__ import annotations

from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, ModelConfig
from thomas.tools.registry import ToolRegistry


class _StubLLM:
    """Construction-only stub; the loop is never run in these tests."""

    def __init__(self) -> None:
        self.config = ModelConfig(name="local", model="dummy")


def _cfg() -> AppConfig:
    return AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")


def _loop(**kwargs) -> AgentLoop:
    return AgentLoop(_cfg(), _StubLLM(), ToolRegistry(), conversation=[], **kwargs)


def test_defaults_are_bounded_when_unspecified():
    agent = _loop()
    assert agent._tool_timeout_s == 600  # bounded, not None
    assert agent._max_parallel_tools == 6


def test_explicit_values_are_respected():
    agent = _loop(tool_timeout_s=120, max_parallel_tools=3)
    assert agent._tool_timeout_s == 120
    assert agent._max_parallel_tools == 3


def test_invalid_values_fall_back_to_bounded_defaults():
    agent = _loop(tool_timeout_s="nope", max_parallel_tools="x")
    assert agent._tool_timeout_s == 600
    assert agent._max_parallel_tools == 6
