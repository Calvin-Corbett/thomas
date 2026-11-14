"""The shell a Build run gets finds python, pytest and ruff.

On 2026-09-25 the caged Build teams got a shell (85a8f823) and still could not run a single test: "python: command
not found". The runner itself runs on Thomas's own environment (the running copy's .venv, which the cage account can
run), but nothing put that environment on PATH for the shell it hands the agent, so one team made 124 shell calls
hunting for a Python and handed in saying "once the tests run somewhere Python is available". The runner now puts its
own environment's scripts folder on PATH -- last, so a project's own Python still comes first where there is one.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from thomas.forge.anvil import forge_code_runner


def test_the_runners_own_scripts_folder_is_on_path_last(monkeypatch, tmp_path: Path) -> None:
    scripts = tmp_path / "venv" / "Scripts"
    scripts.mkdir(parents=True)
    monkeypatch.setattr(sys, "executable", str(scripts / "python.exe"))
    monkeypatch.setenv("PATH", os.pathsep.join([r"C:\first", r"C:\second"]))
    forge_code_runner.python_tools_on_path()
    parts = os.environ["PATH"].split(os.pathsep)
    assert parts[:2] == [r"C:\first", r"C:\second"] and parts[-1] == str(scripts)
    forge_code_runner.python_tools_on_path()  # a second call never adds it twice
    assert os.environ["PATH"].split(os.pathsep).count(str(scripts)) == 1


def test_the_runner_does_it_before_any_agent_tool_exists(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(forge_code_runner, "python_tools_on_path", lambda: calls.append("path"))
    monkeypatch.setattr(forge_code_runner, "handle_console_ctrl_c", lambda: calls.append("ctrl_c") or True)
    monkeypatch.setattr(forge_code_runner, "record_stacks_while_running", lambda: None)
    monkeypatch.setattr("thomas.tools.filesystem.anchor_runtime_protection", lambda _root: None)
    forge_code_runner.prepare_runner_process()
    assert calls == ["ctrl_c", "path"]
