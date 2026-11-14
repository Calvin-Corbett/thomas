"""Fakes shared by the evolve bridge tests: a scripted driver, configs, a funnel model, a clean git repo, a GPT translator runner."""

from __future__ import annotations

import pytest

from thomas.forge.anvil.evolve_claude_bridge import (
    BridgeConfig,
)


class FakeDriver:
    def __init__(self, window: str | None = "Claude Code - VS Code"):
        self.window = window
        self.typed: list[str] = []
        self.enters = 0

    def find_window(self, match: str):
        return self.window if (self.window and match in self.window) else None

    def type_text(self, text: str) -> None:
        self.typed.append(text)

    def press_enter(self) -> None:
        self.enters += 1


def _enabled_cfg(**kw):
    return BridgeConfig(enabled=True, require_confirmation=True, **kw)


def _funnel_fake_model_call(system, user, profile=""):
    import json

    if "reading of what SUCCESS" in system:
        return json.dumps({"items": [{"text": "module has a clear docstring", "rationale": "the goal"}]})
    if "CHECKS that would prove" in system:
        return json.dumps(
            {"items": [{"text": "ast.get_docstring is non-empty", "how_to_test": "pytest -q", "essential": True}]}
        )
    if "implementation PLAN" in system:
        return json.dumps(
            {"plan": "add a triple-quoted module docstring at the top", "items": [{"text": "write the docstring"}]}
        )
    if "Adversarially grade" in system:
        return json.dumps({"score": 0.9, "pass": True, "weaknesses": [], "reason": "ok"})
    if "synthesizer bound to the goal" in system:
        return json.dumps(
            {
                "merged": "MERGED PLAN: add a top-of-file module docstring",
                "kept_items": ["x"],
                "contradictions": [],
                "dropped": [],
            }
        )
    if "needless weight" in system:
        return json.dumps({"cuts": []})
    if "INDEPENDENT evaluator" in system:
        return json.dumps({"broke_it": False, "verdict": "pass", "findings": [], "reason": "ok"})
    return "{}"


def _init_repo(root):
    """A throwaway git repo with deterministic identity/signing."""
    from thomas.forge.anvil.forge_code_git import _run_git

    _run_git(root, ["init"])
    _run_git(root, ["config", "user.email", "test@example.com"])
    _run_git(root, ["config", "user.name", "Forge Test"])
    _run_git(root, ["config", "commit.gpgsign", "false"])


def _commit_all(root):
    from thomas.forge.anvil.forge_code_git import _run_git

    _run_git(root, ["add", "-A"])
    _run_git(root, ["commit", "-m", "base"])


@pytest.fixture
def clean_git_repo(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    _commit_all(tmp_path)
    return tmp_path


def _run_gpt_translator(events):
    """Drive a simulated GPT-engine ``AgentEvent`` stream through the in-process
    translator, returning ``(emitted_forge_events, translator)``.

    Each item is ``(EventType, data)`` — exactly what ``_agent_loop_pass_async``
    feeds the translator for every event the loop yields.
    """
    from thomas.forge.anvil.evolve_claude_bridge import _AgentLoopForgeTranslator

    out: list[dict] = []
    tr = _AgentLoopForgeTranslator(out.append)
    for et, data in events:
        tr.feed(et.value if hasattr(et, "value") else et, data)
    tr.close()
    return out, tr
