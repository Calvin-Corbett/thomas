"""Since 4ca23002, the first model call retrieves saved answers as knowledge.

Auto-capture used to keep blocked runs, Thomas's own retries and control turns,
refusals, and test answers; it also injected each retrieved entry twice.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests import conftest as guard
from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, QualityConfig
from thomas.core.events import EventType
from thomas.core.llm import StreamEvent
from thomas.core.rules_of_road import build_remediation_prompt
from thomas.library import ResearchLibrary, default_library_root
from thomas.server.routes.autopilot_goal import CONTINUATION_PREFIX, STEER_LINE
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry

ANSWER = (
    "HTTP retry patterns should use a bounded exponential backoff with jitter. "
    "Only retry transient failures and requests that are safe to repeat; respect "
    "server retry-after hints when present. Cap both attempt count and elapsed "
    "time, then surface the final failure with enough context to debug it."
)
REQUEST = "Explain HTTP retry patterns"


class FakeModel:
    def __init__(self, steps: list[str]) -> None:
        self.config = ModelConfig(name="dummy", model="dummy", context_window=32768, max_tokens=256)
        self.steps = steps
        self.calls: list[list[dict]] = []

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        self.calls.append([dict(m) for m in messages])
        step = self.steps[min(len(self.calls) - 1, len(self.steps) - 1)]
        if step == "edit":
            yield StreamEvent(type="tool_call_start", data={"id": "t1", "name": "diff.create"})
            yield StreamEvent(
                type="tool_call_end",
                data={"id": "t1", "name": "diff.create", "arguments": '{"path":"app.py"}'},
            )
        else:
            yield StreamEvent(type="token", data={"text": step})
        yield StreamEvent(type="done", data={})


class FakeEdit(Tool):
    name = "diff.create"
    category = "test"
    description = "Fake edit for completion-gate coverage"
    parameters = {"type": "object", "properties": {"path": {"type": "string"}}}

    async def execute(self, args):  # noqa: ANN001
        return ToolResult(ok=True, data={"path": args["path"]})


@pytest.fixture(autouse=True)
def isolated_checkout(tmp_path, monkeypatch):  # noqa: ANN001
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.chdir(checkout)
    monkeypatch.setenv("THOMAS_LIBRARY_ENABLED", "1")
    monkeypatch.setenv("THOMAS_LIBRARY_AUTO_CAPTURE_RESEARCH", "1")
    monkeypatch.delenv("THOMAS_VERIFICATION_CONTRACT", raising=False)


def config(tmp_path: Path, *, gate: bool = False, memory: MemoryConfig | None = None) -> AppConfig:
    return AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=memory if memory is not None else MemoryConfig(root=str(tmp_path / "runtime")),
        quality=QualityConfig(enabled=gate, enforce=gate, max_auto_retries=1 if gate else 0),
    )


def run(cfg: AppConfig, steps: list[str], request: str = REQUEST, **kwargs):  # noqa: ANN003
    model = FakeModel(steps)
    tools = ToolRegistry()
    tools.register(FakeEdit())
    agent = AgentLoop(cfg, model, tools, conversation=[], memory=None, thread_id="knowledge-test")

    async def collect():
        return [event async for event in agent.run(request, tools_policy="always", **kwargs)]

    return asyncio.run(collect()), model


def kept(cfg: AppConfig) -> list[dict]:
    return [row for row in ResearchLibrary(default_library_root(cfg)).list_entries(limit=100) if row["auto_captured"]]


def assert_done(events) -> None:  # noqa: ANN001
    assert len([event for event in events if event.type == EventType.AGENT_DONE]) == 1
    assert not any(event.type == EventType.AGENT_ERROR for event in events)


def test_finished_answer_is_kept_once(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    events, _ = run(cfg, [ANSWER])
    assert_done(events)
    assert [row["title"] for row in kept(cfg)] == [REQUEST]


def test_empty_answer_is_not_kept(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    run(cfg, ["   "])
    assert kept(cfg) == []


def test_blocked_run_and_its_retry_are_not_kept(tmp_path: Path) -> None:
    cfg = config(tmp_path, gate=True)
    events, _ = run(cfg, ["edit", ANSWER], "fix bug in app.py", job_type="coding")
    assert len([event for event in events if event.type == EventType.AGENT_START]) == 2
    assert not any(event.type == EventType.AGENT_DONE for event in events)
    errors = [event for event in events if event.type == EventType.AGENT_ERROR]
    assert errors and "Completion gate blocked AGENT_DONE" in errors[-1].data["error"]
    assert kept(cfg) == []


def test_remediation_pass_is_not_kept(tmp_path: Path) -> None:
    request = build_remediation_prompt(
        {
            "passed": False,
            "job_type": "coding",
            "checks": [
                {"title": "verification", "detail": "required checks failed", "required": True, "passed": False}
            ],
        }
    )
    assert request.startswith("Quality gate failed.")
    cfg = config(tmp_path)
    events, _ = run(cfg, [ANSWER], request, _quality_retry_count=1)
    assert_done(events)
    assert kept(cfg) == []


@pytest.mark.parametrize(
    "control_text",
    [
        f"{CONTINUATION_PREFIX}: done check. Check the retry helper against the goal.",
        f"{STEER_LINE}keep the retry cap at five attempts",
    ],
)
def test_thomas_control_requests_are_not_kept(tmp_path: Path, control_text: str) -> None:
    cfg = config(tmp_path)
    events, _ = run(cfg, [ANSWER], control_text)
    assert_done(events)
    assert kept(cfg) == []


@pytest.mark.parametrize(
    "opening",
    [
        "I can\u2019t do that because the path you gave is absolute",
        "TASK_TYPE: research\nBlocked: no browser tools are available in this run",
        "I'm sorry, but I can't assist with that request.",
    ],
)
def test_refusal_openings_are_not_kept(tmp_path: Path, opening: str) -> None:
    reply = opening + " " + ("There is no completed research to preserve in this response. " * 4)
    assert len(reply) >= 200
    cfg = config(tmp_path)
    events, _ = run(cfg, [reply])
    assert_done(events)
    assert kept(cfg) == []


def test_missing_memory_root_uses_isolated_environment(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("THOMAS_MEMORY_ROOT", str(tmp_path / "sandbox" / "runtime"))
    cfg = config(tmp_path, memory=MemoryConfig())
    events, _ = run(cfg, [ANSWER])
    assert_done(events)
    assert not (Path.cwd() / "library").exists()
    rows = ResearchLibrary(tmp_path / "sandbox" / "library").list_entries(limit=100)
    assert [row["title"] for row in rows] == [REQUEST]


def test_test_runs_library_is_under_guard_root() -> None:
    library = default_library_root(AppConfig())
    assert guard.TEST_DATA_ROOT in library.parents
    assert guard.ROOT not in library.parents


def test_explicit_memory_root_wins(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("THOMAS_MEMORY_ROOT", str(tmp_path / "elsewhere" / "runtime"))
    assert default_library_root(config(tmp_path)) == (tmp_path / "library").resolve()


def test_first_call_carries_library_once(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("THOMAS_LIBRARY_AUTO_CAPTURE_RESEARCH", "0")
    cfg = config(tmp_path)
    sentence = "Use bounded backoff for transient failures."
    ResearchLibrary(default_library_root(cfg)).add_entry(
        title="HTTP Retry Patterns",
        category="research",
        tags=["http", "retry", "patterns"],
        content=sentence,
    )
    events, model = run(cfg, [ANSWER])
    assert_done(events)
    system = next(message for message in model.calls[0] if message["role"] == "system")
    assert system["content"].count("<library_context>") == 1
    assert system["content"].count(sentence) == 1
