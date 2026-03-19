from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_agent_loop_base_import_matches_monolith_contract() -> None:
    part01 = _read("thomas/agent/loop_part01.py")
    part02 = _read("thomas/agent/loop_part02.py")

    assert "from thomas.agent.loop_core import AgentLoop as _AgentLoopBase" in part01
    assert "from thomas.agent.loop_core import LoopState" in part01
    assert "from thomas.agent.loop_tools import execute_tools, parse_tool_args, select_tools" in part01
    assert "class AgentLoop(_AgentLoopBase):" in part02
