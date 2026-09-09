"""The shell tool must work even on a Windows Selector event loop.

Root cause (found live 2026-06-07 while driving Thomas as a user, matching the
2026-06-06 "PowerShell failing at process setup" symptom): on Windows, asyncio
subprocesses require the Proactor event loop. The REPL/codex path sometimes
installs a Selector loop (for prompt_toolkit compatibility), and on a Selector
loop ``asyncio.create_subprocess_exec`` raises ``NotImplementedError`` -- the
command "never reaches the shell". ``ShellTool.execute`` now catches that and
falls back to a thread-run ``subprocess.run`` that works on any loop.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from thomas.tools.shell import ShellTool


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Selector-loop asyncio-subprocess limitation is Windows-specific",
)
def test_shell_exec_falls_back_on_selector_loop(tmp_path):
    # A Selector loop on Windows cannot spawn asyncio subprocesses. Before the
    # fix this raised NotImplementedError; now the tool falls back and succeeds.
    loop = asyncio.SelectorEventLoop()
    try:
        tool = ShellTool(tmp_path)
        result = loop.run_until_complete(tool.execute({"command": "echo OK"}))
    finally:
        loop.close()

    assert result.ok, f"shell tool failed on Selector loop: {result.error}"
    assert "OK" in (result.data or "")


def test_shell_exec_runs_a_basic_command(tmp_path):
    """Sanity: the normal path still works on the default event loop."""
    tool = ShellTool(tmp_path)
    result = asyncio.run(tool.execute({"command": "echo OK"}))
    assert result.ok, result.error
    assert "OK" in (result.data or "")
