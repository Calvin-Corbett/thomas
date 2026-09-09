"""Old tool outputs shrink to a stub long before full compaction.

TB-4.0 run 3 (2026-09-04): 14.9M prompt tokens over 128 iterations, about
116k per call, and auto-compaction never fired because it waits for 75% of a
200k window. Frontier harnesses (Claude Code) replace stale tool outputs with
a short stub deterministically, no model call, so the transcript stays small
and the recent turns stay verbatim.
"""

from __future__ import annotations

from thomas.agent.tool_output_pruning import PRUNED_MARKER, prune_stale_tool_outputs


def _conv(n_tools: int, size: int = 4000) -> list[dict]:
    conv: list[dict] = [{"role": "user", "content": "do the thing"}]
    for i in range(n_tools):
        conv.append(
            {"role": "assistant", "content": "", "tool_calls": [{"id": f"c{i}", "function": {"name": "fs.read_file"}}]}
        )
        conv.append({"role": "tool", "tool_call_id": f"c{i}", "name": "fs.read_file", "content": f"{i}:" + "x" * size})
    conv.append({"role": "assistant", "content": "still working"})
    return conv


def test_old_large_tool_outputs_become_stubs_and_recent_ones_stay() -> None:
    conv = _conv(8)
    saved = prune_stale_tool_outputs(conv, keep_recent_messages=6, min_chars=1500)

    tools = [m for m in conv if m["role"] == "tool"]
    assert PRUNED_MARKER in tools[0]["content"]
    assert tools[0]["content"].startswith("0:xxx")
    assert "fs.read_file" in tools[0]["content"]
    assert PRUNED_MARKER not in tools[-1]["content"]
    assert len(tools[-1]["content"]) > 4000
    assert saved > 0
    assert [m["role"] for m in conv][:3] == ["user", "assistant", "tool"]


def test_small_outputs_user_and_assistant_text_are_never_touched() -> None:
    conv = _conv(4, size=200)
    conv[0]["content"] = "y" * 9000
    saved = prune_stale_tool_outputs(conv, keep_recent_messages=2, min_chars=1500)

    assert saved == 0
    assert conv[0]["content"] == "y" * 9000
    assert all(PRUNED_MARKER not in m["content"] for m in conv if m["role"] == "tool")


def test_pruning_is_idempotent() -> None:
    conv = _conv(6)
    first = prune_stale_tool_outputs(conv, keep_recent_messages=2, min_chars=1500)
    second = prune_stale_tool_outputs(conv, keep_recent_messages=2, min_chars=1500)

    assert first > 0 and second == 0
    assert sum(m["content"].count(PRUNED_MARKER) for m in conv if m["role"] == "tool") == 5


def test_the_agent_loop_prunes_at_a_third_of_the_window_without_a_compactor() -> None:
    import asyncio

    from thomas.agent.loop import AgentLoop
    from thomas.core.config import AppConfig, ModelConfig
    from thomas.tools.registry import ToolRegistry

    class _Llm:
        config = ModelConfig(name="d", model="d", context_window=4000, max_tokens=64)

    cfg = AppConfig(models={"local": ModelConfig(name="local", model="d")}, default_model="local")
    agent = AgentLoop(cfg, _Llm(), ToolRegistry(), conversation=_conv(12, size=3000))
    agent._context_window = 4000
    agent._context_compactor = None

    asyncio.run(agent._auto_compact_if_needed())

    tools = [m for m in agent._conversation if m["role"] == "tool"]
    assert PRUNED_MARKER in tools[0]["content"]
    assert PRUNED_MARKER not in tools[-1]["content"]
