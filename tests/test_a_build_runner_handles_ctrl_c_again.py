"""A Build runner's children handle a console Ctrl+C, while the runner itself ignores it.

The caged server ignores console Ctrl+C with the process-wide switch (ed7685ac), and a child inherits that. On
2026-09-26, with every Build runner inheriting it, all six runs reached their team's final reply and then never
finished. With runners handling Ctrl+C instead, on 2026-09-27 each run -- by then on a console of its own -- was
stopped with KeyboardInterrupt after its team's final reply. ``forge_code_runner.handle_console_ctrl_c`` (first thing
in ``prepare_runner_process``) turns the switch back on for the runner's children and ignores Ctrl+C in the runner
through Python's own handler, which a child does not inherit.

Real processes in a separate, hidden console, so nothing here can reach pytest's own: a host that ignores Ctrl+C
(as the caged server does) starts a runner-like child, which starts a child of its own; a third process sends
CTRL_C_EVENT to the whole console, and each says whether it was interrupted.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="a console Ctrl+C is a Windows console event")

ROOT = Path(__file__).resolve().parents[1]
GRANDCHILD = (
    "import sys\n"
    "try:\n"
    "    print('its child ready', flush=True)\n"
    "    sys.stdin.readline(); print('its child survived', flush=True)\n"
    "except KeyboardInterrupt:\n"
    "    print('its child interrupted', flush=True)\n"
)
RUNNER = """
import subprocess, sys
sys.path.insert(0, {root!r})
if {restore!r}:
    from thomas.forge.anvil import forge_code_runner
    print("runner handles ctrl-c", forge_code_runner.handle_console_ctrl_c(), flush=True)
child = subprocess.Popen([sys.executable, "-c", {grandchild!r}], stdin=subprocess.PIPE,
                         stdout=sys.stdout, stderr=sys.stderr, text=True)
try:
    sys.stdin.readline(); print("runner survived", flush=True)
except KeyboardInterrupt:
    print("runner interrupted", flush=True)
if child.poll() is None:
    child.stdin.write("\\n")
    child.stdin.flush()
child.wait(timeout=10)
"""
SENDER = "import ctypes; assert ctypes.windll.kernel32.GenerateConsoleCtrlEvent(0, 0)"
HOST = """
import ctypes, subprocess, sys
ctypes.windll.kernel32.SetConsoleCtrlHandler(None, True)  # the caged server: ignores it, and children inherit that
runner = subprocess.Popen([sys.executable, "-c", {runner!r}], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
ready = []
for line in runner.stdout:
    ready.append(line)
    if "its child ready" in line:
        break
if not any("its child ready" in line for line in ready):
    print("".join(ready), flush=True)
    raise RuntimeError("child did not reach its Ctrl+C handler")
subprocess.run([sys.executable, "-c", {sender!r}], check=True)
if runner.poll() is None:
    runner.stdin.write("\\n")
    runner.stdin.flush()
runner.wait(timeout=15)
print("host survived", flush=True)
print("".join(ready) + runner.stdout.read(), flush=True)
"""


def _run(restore: bool) -> str:
    runner = RUNNER.format(root=str(ROOT), restore=restore, grandchild=GRANDCHILD)
    hidden = subprocess.STARTUPINFO()
    hidden.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    hidden.wShowWindow = 0  # SW_HIDE
    done = subprocess.run(
        [sys.executable, "-c", HOST.format(runner=runner, sender=SENDER)],
        creationflags=subprocess.CREATE_NEW_CONSOLE,  # its own console: the Ctrl+C cannot reach pytest's
        startupinfo=hidden,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return done.stdout + done.stderr


def test_the_runner_survives_and_its_child_handles_ctrl_c() -> None:
    said = _run(restore=True)
    assert "runner handles ctrl-c True" in said, said
    assert "its child ready" in said, said
    assert "runner survived" in said and "its child interrupted" in said and "host survived" in said, said
    assert "runner interrupted" not in said, said


def test_without_it_the_runner_and_its_child_both_inherit_the_servers_ignore() -> None:
    said = _run(restore=False)
    assert "runner survived" in said and "its child survived" in said and "host survived" in said, said
    assert "runner interrupted" not in said, said
