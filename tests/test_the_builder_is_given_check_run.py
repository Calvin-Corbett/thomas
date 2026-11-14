"""Who gets `check.run`, and what the Build agent is told about it.

Split from test_the_builder_can_check_its_own_work.py, which covers what the tool
runs and refuses. This file covers registration (any live-edit run, at every
guardrail) and the prompt, which may only name the tool when the run has it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from thomas.forge.anvil import dispatch_agent_loop
from thomas.forge.anvil.bridge_prompts import compose_headless_prompt
from thomas.forge.anvil.dispatch_claude_cli import dispatch_via_claude_cli
from thomas.forge.anvil.forge_code_settings import live_edit_allowed


class _ToolsetSeen(Exception):
    def __init__(self, names: set[str]) -> None:
        super().__init__("toolset captured")
        self.names = names


def _pass_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    autonomy_level: int,
    file_access: str,
    guardrails: str = "guarded",
    allow_shell: bool = False,
) -> set[str]:
    """Run the real GPT pass up to the point it hands its toolset to the loop."""
    import thomas.agent.kernel_wiring as kernel_wiring

    def _capture(_config: Any, _llm: Any, tools: Any, **_kwargs: Any) -> Any:
        raise _ToolsetSeen({tool.name for tool in tools.list_tools()})

    monkeypatch.setattr(kernel_wiring, "build_agent_loop", _capture)
    with pytest.raises(_ToolsetSeen) as seen:
        asyncio.run(
            dispatch_agent_loop._agent_loop_pass_async(
                "fix the bug",
                str(tmp_path),
                60,
                lambda _event: None,
                allow_shell=allow_shell,
                file_access=file_access,
                guardrails=guardrails,
                autonomy_level=autonomy_level,
            )
        )
    return seen.value.names


@pytest.mark.parametrize("guardrails", ["guarded", "fortress", "open"])
def test_a_live_edit_run_gets_check_run_at_every_guardrail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, guardrails: str
) -> None:
    names = _pass_tools(tmp_path, monkeypatch, autonomy_level=3, file_access="project", guardrails=guardrails)
    assert "check.run" in names
    assert "shell.exec" not in names, "check.run must not bring a shell with it"


def test_a_read_only_run_does_not_get_check_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert "check.run" not in _pass_tools(tmp_path, monkeypatch, autonomy_level=3, file_access="read_only")


def test_a_low_autonomy_run_does_not_get_check_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert "check.run" not in _pass_tools(tmp_path, monkeypatch, autonomy_level=2, file_access="project")


def test_the_gate_is_the_existing_live_edit_rule() -> None:
    assert live_edit_allowed(autonomy_level=3, file_access="project")
    assert not live_edit_allowed(autonomy_level=3, file_access="read_only")
    assert not live_edit_allowed(autonomy_level=2, file_access="project")


# -- the prompt names check.run only when it exists --------------------------


def test_the_prompt_tells_the_agent_to_use_check_run_when_it_has_it() -> None:
    prompt = compose_headless_prompt(
        "fix the bug", guardrails="guarded", file_access="project", autonomy_level=3, check_run_available=True
    )
    assert "check.run" in prompt
    assert "Before you say you are done, use check.run" in prompt
    assert "shell.exec" in prompt, "it must say arbitrary commands still need shell.exec"


def test_the_prompt_never_claims_check_run_it_does_not_have() -> None:
    prompt = compose_headless_prompt("fix the bug", guardrails="guarded", file_access="project", autonomy_level=3)
    assert "check.run" not in prompt


@pytest.mark.parametrize(
    ("autonomy", "file_access", "expected"),
    [(3, "project", True), (4, "full", True), (3, "read_only", False), (2, "project", False)],
)
def test_the_gpt_dispatch_prompt_matches_its_toolset(
    tmp_path: Path, autonomy: int, file_access: str, expected: bool
) -> None:
    result = dispatch_agent_loop.dispatch_via_agent_loop(
        "fix the bug",
        cwd=tmp_path,
        dry_run=True,
        guardrails="guarded",
        file_access=file_access,
        autonomy_level=autonomy,
    )
    assert ("check.run" in result.prompt) is expected


def test_the_claude_dispatch_prompt_never_names_check_run(tmp_path: Path) -> None:
    result = dispatch_via_claude_cli(
        "fix the bug", cwd=tmp_path, dry_run=True, guardrails="guarded", file_access="project", autonomy_level=3
    )
    assert "check.run" not in result.prompt


def test_the_open_prompt_also_names_check_run_when_it_has_it() -> None:
    prompt = compose_headless_prompt(
        "fix the bug", guardrails="open", file_access="project", autonomy_level=3, check_run_available=True
    )
    assert "unsandboxed host process" in prompt
    assert "You also have check.run" in prompt


@pytest.mark.parametrize("guardrails", ["guarded", "fortress", "open"])
def test_build_checks_follow_the_project_language(guardrails: str) -> None:
    prompt = compose_headless_prompt(
        "build a static HTML app",
        guardrails=guardrails,
        file_access="project",
        autonomy_level=3,
        check_run_available=True,
    )
    assert "Ruff checks Python files only" in prompt
    assert "never pass HTML, CSS, JavaScript, or other non-Python files to Ruff" in prompt
    assert "Run pytest only when the project has Python tests" in prompt
    assert "browser" in prompt or "web.playtest" in prompt
