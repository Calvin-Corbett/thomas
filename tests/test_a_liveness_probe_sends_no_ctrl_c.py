"""Asking whether an agent's process is alive never sends it, or its console, a Ctrl+C.

``agent_presence._is_pid_alive`` asked with ``os.kill(pid, 0)``. On Windows signal 0 is ``CTRL_C_EVENT``, sent through
``GenerateConsoleCtrlEvent``, which can interrupt every process on the console; every startup router's presence check
made that call. On 2026-09-27 Thomas projects sharing a console kept dying with KeyboardInterrupt, and a Thomas
project's own team found the cause while doing other work. Windows is now asked through ``OpenProcess`` and
``GetExitCodeProcess`` (``thomas.core.process_alive``), and still tells a running process from a finished one.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from thomas.core import agent_presence, process_alive

windows_only = pytest.mark.skipif(os.name != "nt", reason="the Windows probe")


def _never_signal(*_args: object) -> None:
    pytest.fail("os.kill was called: on Windows signal 0 is CTRL_C_EVENT")


@windows_only
def test_a_running_process_is_alive_and_nothing_is_signalled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "kill", _never_signal)

    assert process_alive.process_alive(os.getpid()) is True
    assert agent_presence._is_pid_alive(os.getpid()) is True


@windows_only
def test_a_finished_process_is_not_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    finished = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
    monkeypatch.setattr(os, "kill", _never_signal)

    assert process_alive.process_alive(int(finished.stdout.strip())) is False
    assert agent_presence._is_pid_alive(None) is False
    assert agent_presence._is_pid_alive(-3) is False
