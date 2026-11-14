"""The GPT Build shell prompt describes cmd.exe without changing other dispatch prompts."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from thomas.core import cage_account
from thomas.forge.anvil import dispatch_agent_loop, dispatch_claude_cli
from thomas.forge.anvil.bridge_prompts import CAGED_SHELL_SYNTAX, compose_headless_prompt
from thomas.forge.anvil.dispatch_claude_cli import dispatch_via_claude_cli


def _caged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cage_account, "running_as_cage_account", lambda: True)


def test_caged_gpt_prompt_explains_the_shell_once(monkeypatch: pytest.MonkeyPatch) -> None:
    _caged(monkeypatch)
    prompt = compose_headless_prompt(
        "fix the bug", guardrails="guarded", file_access="project", autonomy_level=3, check_run_available=True
    )
    assert prompt.count(CAGED_SHELL_SYNTAX) == 1
    for detail in ("cmd.exe", "';'", "&&", "double quotes"):
        assert detail in CAGED_SHELL_SYNTAX


def test_gpt_dispatch_sends_the_guidance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _caged(monkeypatch)
    result = dispatch_agent_loop.dispatch_via_agent_loop(
        "fix the bug", cwd=tmp_path, dry_run=True, guardrails="guarded", file_access="project", autonomy_level=3
    )
    assert CAGED_SHELL_SYNTAX in result.prompt


def test_claude_cli_does_not_get_cmd_guidance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _caged(monkeypatch)
    monkeypatch.setattr(dispatch_claude_cli, "repo_context_for", lambda goal: "")
    result = dispatch_via_claude_cli(
        "fix the bug", cwd=tmp_path, dry_run=True, guardrails="guarded", file_access="project", autonomy_level=3
    )
    assert "cage account" in result.prompt
    assert CAGED_SHELL_SYNTAX not in result.prompt
    assert "cmd.exe" not in result.prompt


def test_prompts_without_the_caged_shell_do_not_get_cmd_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cage_account, "running_as_cage_account", lambda: False)
    for guardrails in ("guarded", "open"):
        prompt = compose_headless_prompt(
            "fix the bug", guardrails=guardrails, file_access="project", autonomy_level=3, check_run_available=True
        )
        assert "cmd.exe" not in prompt
        if guardrails == "open":
            assert "unsandboxed host process" in prompt
    _caged(monkeypatch)
    fortress = compose_headless_prompt(
        "fix the bug", guardrails="fortress", file_access="project", autonomy_level=3, check_run_available=True
    )
    assert "cmd.exe" not in fortress


@pytest.mark.parametrize("check_run_available", [False, True])
def test_build_prompt_catches_common_second_look_repairs_before_hand_in(check_run_available: bool) -> None:
    prompt = compose_headless_prompt("fix the bug", check_run_available=check_run_available)
    for requirement in (
        "tests that import the changed modules",
        "every test file you edited",
        "architecture tests",
        "ruff check and ruff format --check",
        "size gate",
        "applies to its tip",
        "unchanged target branch",
        "removing the fix",
        "unverified",
    ):
        assert requirement in prompt
    if not check_run_available:
        assert "You DO have the check.run tool" not in prompt


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe exists only on Windows")
def test_windows_cmd_interprets_the_syntax_as_described(tmp_path: Path) -> None:
    executable = f'"{sys.executable}"'
    # Child interpreters inherit a pytest audit hook; pin persistence to the test
    # folder even if the parent shell supplies a real THOMAS_STATE_FILE.
    env = os.environ.copy()
    env["THOMAS_STATE_FILE"] = str(tmp_path / "thomas_state.json")

    def command(arguments: str, *, code: str = "import sys; print(sys.argv[1:])") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            f'{executable} -c "{code}" {arguments}', shell=True, capture_output=True, text=True, check=False, env=env
        )

    semicolon = command("--short; echo next")
    assert semicolon.returncode == 0
    assert ast.literal_eval(semicolon.stdout.strip()) == ["--short;", "echo", "next"]

    single_quotes = command("--grep='project list'")
    assert single_quotes.returncode == 0
    assert ast.literal_eval(single_quotes.stdout.strip()) == ["--grep='project", "list'"]

    double_quotes = command('--grep="project list"')
    assert double_quotes.returncode == 0
    assert ast.literal_eval(double_quotes.stdout.strip()) == ["--grep=project list"]

    success = command("&& echo next", code="import sys; sys.exit(0)")
    assert success.returncode == 0
    assert success.stdout.strip() == "next"
    failure = command("&& echo next", code="import sys; sys.exit(3)")
    assert failure.returncode == 3
    assert "next" not in failure.stdout
