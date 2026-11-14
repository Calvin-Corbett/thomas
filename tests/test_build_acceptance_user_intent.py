"""Build contracts judge the request; execution guidance still reaches the model.

Offline regression: the production Build dispatcher, AgentLoop, contract
builder and forge translator run with disposable config and a fake model.
Unrelated rules evaluation and learned checks are isolated; no provider runs.
"""

from __future__ import annotations

import subprocess

import pytest

from thomas.agent import acceptance_runtime, loop_completion
from thomas.core import config as config_module
from thomas.core import llm_client
from thomas.core.config import AppConfig, ModelConfig
from thomas.core.llm import StreamEvent
from thomas.forge.anvil import dispatch_agent_loop as dispatch

REQUEST = (
    "Build a polished single-page stop checklist in index.html with a dark background "
    "and burnt-orange accent. Show four stops and a 9:15 AM start, clickable completion "
    "checkboxes, and a completed-count that updates immediately. Keep it simple, "
    "with no external dependencies. Do not edit Thomas itself."
)


class OfflineModel:
    instances: list = []

    def __init__(self, cfg, **kwargs):
        self.config = cfg
        self.seen: list[list[dict]] = []
        self.closed = False
        self.instances.append(self)

    async def stream_chat(self, messages, tools):
        self.seen.append([dict(message) for message in messages])
        yield StreamEvent(type="token", data={"text": "I have read the request."})
        yield StreamEvent(type="done", data={})

    async def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("THOMAS_VERIFICATION_CONTRACT", "1")
    monkeypatch.setenv("THOMAS_TASK_CHECKLISTS", "0")
    monkeypatch.setattr(acceptance_runtime, "load_learned", lambda *_: [])
    monkeypatch.setattr(acceptance_runtime, "record_misses", lambda *_: None)
    monkeypatch.setattr(
        loop_completion,
        "evaluate_rules",
        lambda **kwargs: {"passed": True, "job_type": "coding", "checks": []},
    )
    cfg = AppConfig(
        models={
            "offline": ModelConfig(
                name="offline",
                model="offline",
                reasoning_effort="low",
                context_window=100000,
            )
        },
        default_model="offline",
    )
    cfg.memory.root = str(tmp_path / "memory")
    monkeypatch.setattr(config_module, "load_config", lambda *_: cfg)
    monkeypatch.setattr(llm_client, "LLMClient", OfflineModel)
    OfflineModel.instances.clear()
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)


@pytest.mark.parametrize("user_request", [REQUEST, REQUEST + " Do NOT create branches or commit."])
def test_direct_build_contract_excludes_internal_policy_but_model_keeps_it(tmp_path, user_request):
    events = []
    result = dispatch.dispatch_via_agent_loop(
        user_request,
        cwd=tmp_path,
        profile="offline",
        dry_run=False,
        verify=False,
        token_check=lambda: True,
        emit=events.append,
        guardrails="guarded",
        file_access="workspace",
        history=[{"role": "user", "text": "Write an unrelated old-report.csv."}],
        definition="Internal planner says to inspect audit-only.txt.",
        plan="Use check.run and preserve internal planning notes.",
    )
    assert OfflineModel.instances and OfflineModel.instances[0].seen, result.reason
    assert OfflineModel.instances[0].closed
    acceptance = next(event for event in events if event.get("fc") == "acceptance")
    requirements = [item["description"] for item in acceptance["items"] if item["kind"] == "requirement"]
    assert requirements, "the fix must retain the user's requirements"
    assert all(requirement in user_request for requirement in requirements), requirements
    assert any("four stops" in requirement for requirement in requirements), requirements
    assert any("no external dependencies" in requirement for requirement in requirements), requirements
    if "Do NOT create branches or commit." in user_request:
        assert "Do NOT create branches or commit." in requirements
    all_items = str(acceptance["items"])
    assert "old-report.csv" not in all_items and "audit-only.txt" not in all_items
    for internal in (
        "Use your file tools",
        "Enforced Code execution policy",
        "check.run",
        "scratch",
    ):
        assert internal not in all_items
    model_context = "\n".join(str(message.get("content", "")) for message in OfflineModel.instances[0].seen[0])
    assert user_request in model_context
    assert "Enforced Code execution policy" in model_context
    assert "File access = workspace" in model_context
    assert "Direct shell is unavailable" in model_context
    assert "check.run" in model_context
    assert "Do not modify protected files or gate scripts" in model_context


@pytest.mark.asyncio
async def test_call_without_separate_intent_keeps_its_request(tmp_path):
    # Existing non-enriched AgentLoop callers do not pass intent_text.
    from thomas.agent.loop import AgentLoop
    from thomas.tools.registry import ToolRegistry

    cfg = config_module.load_config(None)
    cfg.tools.sandbox_root = str(tmp_path)
    model = OfflineModel(cfg.get_model("offline"))
    loop = AgentLoop(cfg, model, ToolRegistry(), conversation=[], memory=None)
    prompt = "Create `fallback.txt` with the text READY."
    events = [event async for event in loop.run(prompt, tools_policy="never", job_type="coding")]
    assert events and model.seen
    report = next(
        event.data["token_report"]["acceptance_contract"] for event in events if event.type.value == "agent_done"
    )
    assert any("fallback.txt" in str(item) for item in report["items"])
    assert any(message.get("role") == "user" and message.get("content") == prompt for message in model.seen[0])
