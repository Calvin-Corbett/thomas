"""In the cage, Build has a shell: it runs as the cage account, which a firewall rule keeps off the internet.

You said on 2026-09-25: "If the other frontier agents have a cage shell, then he needs a cage shell. He has to be
able to do shit... If he can't run shell, that's like literally not having hands for AI." Until now Build handed a
shell only to a run that selected Open (a dial that asks for your Windows Hello), because that shell ran as you. In
the cage it runs as ``thomas-agent``: it cannot write Thomas's code, and "Thomas cage: no direct connections out"
blocks everything but loopback, so its only way out is the proxy's pinned hosts. A Thomas project's team said it
plainly that night: "I did not run pytest myself -- direct shell is unavailable."
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from thomas.core import cage_account
from thomas.forge.anvil.bridge_prompts import compose_headless_prompt
from thomas.forge.anvil.dispatch_claude_cli import _claude_cli_tools
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings, direct_shell_allowed


def _caged(monkeypatch: pytest.MonkeyPatch, value: bool) -> None:
    monkeypatch.setattr(cage_account, "running_as_cage_account", lambda: value)


@pytest.mark.parametrize(
    ("guardrails", "caged", "shell"),
    [
        ("guarded", True, True),  # the cage is the sandbox: its default preset gets hands
        ("guarded", False, False),  # outside the cage a shell would run as you
        ("open", False, True),
        ("open", True, True),
        ("fortress", True, False),  # the strict preset you choose keeps its promise
    ],
)
def test_an_editing_run_gets_a_shell_in_the_cage(monkeypatch, guardrails, caged, shell) -> None:
    _caged(monkeypatch, caged)
    assert direct_shell_allowed(autonomy_level=5, file_access="project", guardrails=guardrails) is shell


def test_a_run_that_may_not_edit_never_gets_one(monkeypatch) -> None:
    _caged(monkeypatch, True)
    assert not direct_shell_allowed(autonomy_level=2, file_access="project", guardrails="guarded")
    assert not direct_shell_allowed(autonomy_level=5, file_access="read_only", guardrails="guarded")


def test_claude_build_is_offered_bash_only_in_the_cage(monkeypatch) -> None:
    _caged(monkeypatch, True)
    tools, deny_bash = _claude_cli_tools((), "guarded", autonomy_level=5, file_access="project")
    assert "Bash" in tools and not deny_bash
    _caged(monkeypatch, False)
    tools, deny_bash = _claude_cli_tools((), "guarded", autonomy_level=5, file_access="project")
    assert "Bash" not in tools and deny_bash


def _account_windows_reports() -> str:
    """This process's account as Windows' own ``whoami`` reports it from the token, not
    through cage_account's code; "" off Windows, where there is no cage account."""
    if sys.platform != "win32":
        return ""
    whoami = Path(os.environ.get("SYSTEMROOT") or r"C:\Windows") / "System32" / "whoami.exe"
    answer = subprocess.run([str(whoami)], capture_output=True, text=True, timeout=60, check=True)
    return answer.stdout.strip().rsplit("\\", 1)[-1]


@pytest.mark.real_cage_account  # tests/conftest.py replaces the reader for every other test
def test_the_account_is_read_from_windows_not_from_the_environment(monkeypatch) -> None:
    """A variable anyone can set must never hand your own account a shell, nor take the cage's away.

    The environment is set to the OPPOSITE of what Windows says, whichever account
    runs the suite, so a reader that trusts USERNAME gives the wrong answer here: it
    fails as you (the variables claim the cage) and in the cage (they deny it).
    """
    truth = _account_windows_reports()
    caged = truth.casefold() == cage_account.CAGE_ACCOUNT
    lie = "not-the-cage-account" if caged else cage_account.CAGE_ACCOUNT
    for name in ("USERNAME", "USER", "LOGNAME"):
        monkeypatch.setenv(name, lie)
    assert cage_account.running_as_cage_account() is caged
    if sys.platform == "win32":
        assert cage_account.process_account().casefold() == truth.casefold()


def test_the_run_and_the_report_say_what_the_shell_is(monkeypatch) -> None:
    _caged(monkeypatch, True)
    prompt = compose_headless_prompt(
        "Fix the flaky test", autonomy_level=5, file_access="project", guardrails="guarded"
    )
    assert "cage account" in prompt and "unsandboxed host process" not in prompt
    report = ForgeCodeSettings.from_payload(
        {"model": "claude:opus", "autonomy_level": 5, "file_access": "project", "guardrails": "guarded"}
    ).capability_report()
    guard = report["support"]["guardrails"]
    assert guard["terminal"] == "enabled_in_selected_project"
    assert "cage account" in guard["terminal_boundary"] and "Open was selected" not in guard["terminal_boundary"]
