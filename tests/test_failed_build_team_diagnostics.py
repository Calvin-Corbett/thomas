"""A failed real Build team remains inspectable by the lead's next model call."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_build_agent_scheduler import registry
from tests.test_build_agent_team import runtime  # noqa: F401
from thomas.agent.loop import AgentLoop
from thomas.core.events import AgentEvent, EventType
from thomas.core.llm import StreamEvent
from thomas.forge.anvil import build_agent_team as team
from thomas.tools.base import ToolResult


class _InspectingLead:
    def __init__(self, config):
        self.config = config
        self.called = False
        self.tool_messages = []

    async def stream_chat(self, messages, tools):
        if not self.called:
            self.called = True
            yield StreamEvent(type="tool_call_start", data={"id": "failed-team", "name": "task.team"})
            yield StreamEvent(
                type="tool_call_end",
                data={
                    "id": "failed-team",
                    "name": "task.team",
                    "arguments": json.dumps(
                        {
                            "assignments": [
                                {"title": path, "instructions": "Write a draft", "path": path}
                                for path in ("index.html", "game.js")
                            ]
                        }
                    ),
                },
            )
        else:
            self.tool_messages = [item for item in messages if item.get("role") == "tool"]
            yield StreamEvent(type="token", data={"text": "The team failed; inspect its retained drafts."})
        yield StreamEvent(type="done", data={})


@pytest.mark.asyncio
async def test_failed_real_team_receipts_reach_actual_lead_model(monkeypatch, tmp_path, runtime):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("THOMAS_VERIFICATION_CONTRACT", "0")

    class InterruptedChild:
        def __init__(self, config, client, tools, **kwargs):
            self.tools = tools

        async def run(self, prompt, **kwargs):
            output = self.acceptance_owned_output
            written = await self.tools.execute("fs.write_file", {"path": output, "content": "Retained draft"})
            assert written.ok
            yield AgentEvent(EventType.AGENT_ERROR, {"error": "builder helper deadline reached before completion"})

    monkeypatch.setattr(team, "AgentLoop", InterruptedChild)
    tools = registry(runtime, tmp_path, [])
    model = _InspectingLead(runtime.models["selected"])
    lead = AgentLoop(runtime, model, tools, conversation=[])
    events = [
        event
        async for event in lead.run("Run the file team and report its result", tools_policy="always", max_iterations=2)
    ]

    assert len(model.tool_messages) == 1
    received = json.loads(model.tool_messages[0]["content"])
    assert received["ok"] is False and "Only 0/2" in received["error"]
    details = json.loads(received["output"])
    saved = json.loads(Path(details["receipt"]).read_text(encoding="utf-8"))
    assert saved["team_id"] == details["team_id"] and saved["state"] == "failed"
    assert details["integrated"] == 0 and details["total"] == 2
    assert {child["path"] for child in details["children"]} == {"index.html", "game.js"}
    for child in details["children"]:
        assert child["state"] == "failed" and "deadline" in child["error"]
        receipt = tmp_path / child["receipt"]
        assert json.loads(receipt.read_text(encoding="utf-8"))["state"] == "failed"
        assert (receipt.parent / "workspace" / child["path"]).read_text(encoding="utf-8") == "Retained draft"
        assert not (tmp_path / child["path"]).exists()
    visible = next(event for event in events if event.type == EventType.TOOL_RESULT)
    assert json.loads(visible.data["result_text"]) == received


@pytest.mark.parametrize("data", ["", False, 0, [], {}, {"receipt": "team.json", "error": "café"}])
def test_failed_structured_and_empty_diagnostics_keep_failure(data):
    result = json.loads(ToolResult(ok=False, error="failed", data=data).to_content())
    expected = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, default=str)
    assert result == {"ok": False, "error": "failed", "output": expected}


@pytest.mark.parametrize("limit", [-1, 0, 10, 200])
def test_failure_output_limit_keeps_valid_json(limit):
    result = json.loads(ToolResult(ok=False, error="failed", data={"details": "z" * 1000}).to_content(limit))
    assert result["ok"] is False and result["error"] == "failed"
    assert len(result["output"]) <= max(0, limit)


@pytest.mark.parametrize("limit", [0, 10, 200, 50_000])
def test_success_content_contract_is_unchanged(limit):
    text = "a" * 1000
    expected = text if len(text) <= limit else text[: limit - 50] + f"\n... (truncated, {len(text)} chars total)"
    assert ToolResult(ok=True, data=text).to_content(limit) == expected
    assert ToolResult(ok=True, data={"ready": True}).to_content() == '{"ready": true}'
    assert ToolResult(ok=False, error="Denied").to_content() == '{"ok": false, "error": "Denied"}'
