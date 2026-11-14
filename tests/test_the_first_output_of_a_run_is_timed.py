"""How long a run takes to say anything is measured, so a slow first reply can be told apart from a slow start."""

from __future__ import annotations

from thomas.core import step_log
from thomas.core.events import EventType
from thomas.forge.anvil.dispatch_agent_loop_translator import _AgentLoopForgeTranslator


def test_only_the_first_output_is_recorded(monkeypatch):
    rows: list[tuple[str, dict]] = []
    monkeypatch.setattr(step_log, "record", lambda step, **fields: rows.append((step, fields)))
    translator = _AgentLoopForgeTranslator(lambda event: None)

    translator.feed(EventType.TEXT_DELTA.value, {"text": "I'll get this started"})
    translator.feed(EventType.TEXT_DELTA.value, {"text": " for you."})
    translator.feed(EventType.TOOL_CALL_START.value, {"tool_id": "t1", "tool_name": "read"})

    first = [fields for step, fields in rows if step == "run_first_output"]
    assert len(first) == 1
    assert first[0]["kind"] == EventType.TEXT_DELTA.value
    assert first[0]["seconds"] >= 0
