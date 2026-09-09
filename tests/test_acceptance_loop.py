"""The agent loop holds "done" to the acceptance contract: the missed field is caught, fixed, and reported."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from thomas.agent import loop_completion
from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, ModelConfig
from thomas.core.events import EventType
from thomas.core.llm import StreamEvent
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry

PROMPT = (
    "Fix `dispatch.py` so it honours every limit in `data/aircraft.json`. Running `python dispatch.py` must succeed."
)


class _RealWriteTool(Tool):
    name = "fs.write_file"
    category = "test"
    description = "writes a file into the cwd"
    parameters = {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}}

    async def execute(self, args):  # noqa: ANN001
        path = Path(str(args.get("path", "")))
        path.write_text(str(args.get("content", "")), encoding="utf-8")
        return ToolResult(ok=True, data={"path": str(path)})


class _ScriptedLLM:
    """Each step is either ("write", path, content) or ("say", text). Records every prompt it saw."""

    def __init__(self, steps, effort: str = "") -> None:  # noqa: ANN001
        self.config = ModelConfig(
            name="dummy", model="dummy", context_window=32768, max_tokens=64, reasoning_effort=effort
        )
        self._steps = list(steps)
        self.seen: list[list[dict]] = []
        self.judge_calls: list[list[dict]] = []
        self.judge_reply = ""

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        self.seen.append([dict(m) for m in messages])
        step = self._steps.pop(0) if self._steps else ("say", "Done.")
        if step[0] == "write":
            args = json.dumps({"path": step[1], "content": step[2]})
            yield StreamEvent(type="tool_call_start", data={"id": "t1", "name": "fs.write_file"})
            yield StreamEvent(type="tool_call_end", data={"id": "t1", "name": "fs.write_file", "arguments": args})
        else:
            yield StreamEvent(type="token", data={"text": step[1]})
        yield StreamEvent(type="done", data={})

    async def chat(self, messages):  # noqa: ANN001
        self.judge_calls.append([dict(m) for m in messages])
        return {"text": self.judge_reply, "tool_calls": [], "usage": None}


def _run(llm: _ScriptedLLM) -> list:
    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    tools = ToolRegistry()
    tools.register(_RealWriteTool())
    agent = AgentLoop(cfg, llm, tools, conversation=[])

    async def _collect():
        out = []
        async for event in agent.run(PROMPT, tools_policy="always", job_type="coding"):
            out.append(event)
        return out

    return asyncio.run(_collect())


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "aircraft.json").write_text(
        json.dumps({"fuel_flow_gph": 60.0, "turnaround_time_min": 25}), encoding="utf-8"
    )
    (tmp_path / "dispatch.py").write_text("burn = aircraft['fuel_flow_gph']\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("THOMAS_VERIFICATION_CONTRACT", raising=False)
    # Isolate the contract from the rules-of-the-road report and from real command runs.
    monkeypatch.setattr(
        loop_completion, "evaluate_rules", lambda **kwargs: {"passed": True, "job_type": "coding", "checks": []}
    )
    monkeypatch.setattr("thomas.core.acceptance_contract.default_runner", lambda cmd, cwd, timeout: (0, "ok"))
    return tmp_path


def _text(event) -> str:
    return str(event.data.get("text") or "")


def test_the_ignored_field_blocks_done_then_the_fix_is_accepted_and_reported(workspace: Path) -> None:
    llm = _ScriptedLLM(
        [
            ("write", "dispatch.py", "burn = aircraft['fuel_flow_gph']\n"),
            ("say", "All limits honoured."),
            ("write", "dispatch.py", "burn = aircraft['fuel_flow_gph']\nturn = aircraft['turnaround_time_min']\n"),
            ("say", "Turnaround added.\nEVIDENCE: ran it\nVERIFY: python dispatch.py"),
        ]
    )
    events = _run(llm)
    starts = [e for e in events if e.type == EventType.AGENT_START]
    done = [e for e in events if e.type == EventType.AGENT_DONE]
    assert len(starts) == 1, "revision rounds happen inside the one run, never as a second run"
    assert len(done) == 1 and not [e for e in events if e.type == EventType.AGENT_ERROR]

    system = str(llm.seen[0][0]["content"])  # turn context, never the stored conversation
    assert "--- Acceptance Contract ---" in system and "turnaround_time_min" in system
    first_user = next(m for m in llm.seen[0] if m.get("role") == "user")
    assert "Acceptance Contract" not in str(first_user["content"])
    remediation = next(m for m in llm.seen[2] if m.get("role") == "user" and "NOT finished" in str(m.get("content")))
    assert "turnaround_time_min" in str(remediation["content"])

    report = done[0].data["token_report"]["acceptance_contract"]
    assert report["active"] and report["verdict"]["met"] and report["rounds"] == 1
    assert "Verification:" in _text(done[0]) and "Unchecked" in _text(done[0])


def test_words_alone_never_satisfy_the_contract(workspace: Path) -> None:
    llm = _ScriptedLLM([("say", "I added turnaround_time_min handling, all good."), ("say", "Really, it is handled.")])
    events = _run(llm)
    errors = [e for e in events if e.type == EventType.AGENT_ERROR]
    assert not [e for e in events if e.type == EventType.AGENT_DONE]
    assert errors and "turnaround_time_min" in str(errors[-1].data.get("error") or "")


def test_flag_off_restores_the_old_behaviour(workspace: Path, monkeypatch) -> None:
    monkeypatch.setenv("THOMAS_VERIFICATION_CONTRACT", "0")
    events = _run(_ScriptedLLM([("say", "Done without touching anything.")]))
    done = [e for e in events if e.type == EventType.AGENT_DONE]
    assert len(done) == 1
    assert done[0].data["token_report"]["acceptance_contract"] == {"active": False}
    assert "Verification:" not in _text(done[0])


def test_low_effort_builds_the_list_but_never_blocks(workspace: Path) -> None:
    events = _run(_ScriptedLLM([("say", "Done.")], effort="low"))
    done = [e for e in events if e.type == EventType.AGENT_DONE]
    assert len(done) == 1
    report = done[0].data["token_report"]["acceptance_contract"]
    assert report["active"] and not report["verdict"]["met"]
    assert "FAILED" in _text(done[0])  # honest about it, even when it does not block


def test_xhigh_asks_a_separate_evaluator_that_may_overturn_a_pass(workspace: Path) -> None:
    (workspace / "dispatch.py").write_text(
        "a = aircraft['fuel_flow_gph']; b = aircraft['turnaround_time_min']\n", encoding="utf-8"
    )
    llm = _ScriptedLLM([("say", "Done."), ("say", "Done again.")], effort="xhigh")
    llm.judge_reply = json.dumps(
        {"item_verdicts": {"req:1": "unmet"}, "findings": ["the command was never proven deterministic"]}
    )
    events = _run(llm)
    assert llm.judge_calls, "the evaluator was consulted"
    judge_prompt = str(llm.judge_calls[0][0]["content"])
    assert "did not do the work" in judge_prompt
    errors = [e for e in events if e.type == EventType.AGENT_ERROR]
    assert errors and "evaluator: unmet" in str(errors[-1].data.get("error") or "")


def test_a_reply_without_a_verify_command_is_not_a_finish(workspace: Path) -> None:
    (workspace / "dispatch.py").write_text(
        "a = aircraft['fuel_flow_gph']; b = aircraft['turnaround_time_min']\n", encoding="utf-8"
    )
    llm = _ScriptedLLM([("say", "All done, trust me."), ("say", "Done.\nEVIDENCE: it ran\nVERIFY: python dispatch.py")])
    events = _run(llm)
    done = [e for e in events if e.type == EventType.AGENT_DONE]
    assert len(done) == 1 and len(llm.seen) == 2
    hold = next(m for m in llm.seen[1] if m.get("role") == "user" and "NOT finished" in str(m.get("content")))
    assert "VERIFY" in str(hold["content"])
    report = done[0].data["token_report"]["acceptance_contract"]
    assert report["verdict"]["met"] and report["rounds"] == 1


def test_a_failing_verify_command_holds_the_run(workspace: Path, monkeypatch) -> None:
    (workspace / "dispatch.py").write_text(
        "a = aircraft['fuel_flow_gph']; b = aircraft['turnaround_time_min']\n", encoding="utf-8"
    )
    monkeypatch.setattr("thomas.core.acceptance_contract.default_runner", lambda cmd, cwd, timeout: (1, "boom"))
    llm = _ScriptedLLM(
        [("say", "Done.\nVERIFY: python dispatch.py"), ("say", "Done again.\nVERIFY: python dispatch.py")]
    )
    events = _run(llm)
    errors = [e for e in events if e.type == EventType.AGENT_ERROR]
    assert not [e for e in events if e.type == EventType.AGENT_DONE]
    assert (
        errors
        and "finish:verify" in str(errors[-1].data.get("error") or "")
        or "VERIFY" in str(errors[-1].data.get("error") or "")
    )
