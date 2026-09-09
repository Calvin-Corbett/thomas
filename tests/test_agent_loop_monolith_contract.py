from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_agent_loop_base_import_matches_monolith_contract() -> None:
    # After merging: the monolith parts have been consolidated into:
    # - loop.py (main class)
    # - loop_execution.py (run method)
    # - loop_helpers.py (utility functions)
    loop = _read("thomas/agent/loop.py")
    loop_execution = _read("thomas/agent/loop_execution.py")
    loop_helpers = _read("thomas/agent/loop_helpers.py")

    # Verify key imports exist in the proper modules
    assert "from thomas.agent.loop_core import AgentLoop as _AgentLoopBase" in loop
    assert "from thomas.agent.loop_core import LoopState" in loop
    assert "from thomas.agent.loop_tools import execute_tools, parse_tool_args, select_tools" in loop
    assert "class AgentLoop(_AgentLoopBase):" in loop

    # Verify the execution logic is in loop_execution
    assert "async def _agent_loop_run(" in loop_execution

    # Verify helpers are in loop_helpers
    assert "async def _coerce_async_iterator(" in loop_helpers
