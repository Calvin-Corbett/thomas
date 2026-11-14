"""The caged server, and every process it starts, ignores a console Ctrl+C.

On 2026-09-26 the caged server's log read "[thomas] Stopped by user." at 22:19:08 with nobody at its console: it runs
as a background task. Every Build runner and every test run of the check before your card is its child on that one
console, and a Ctrl+C sent to "this console" by any of them reaches all of them. The keepalive had restarted it six
times over 2026-09-25 and 26, cutting off every Build run it hosted.

These run a real host process in a separate, hidden console (so nothing here can reach pytest's own console): it
starts a child, a third process sends CTRL_C_EVENT to the whole console, and each says whether it survived. The
control case shows the test can see a Ctrl+C at all; the fixed case uses ``caged_server.ignore_console_ctrl_c``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="a console Ctrl+C is a Windows console event")

ROOT = Path(__file__).resolve().parents[1]
CHILD = (
    "import time\n"
    "try:\n"
    "    time.sleep(3.0); print('child survived', flush=True)\n"
    "except KeyboardInterrupt:\n"
    "    print('child interrupted', flush=True)\n"
)
SENDER = "import ctypes, time; ctypes.windll.kernel32.GenerateConsoleCtrlEvent(0, 0); time.sleep(0.5)"
HOST = """
import ctypes, subprocess, sys, time
sys.path.insert(0, {root!r})
# Ctrl+C handled, whatever this process inherited: a parent that already ignores it passes that on, and then
# the fixed case would pass without the function under test doing anything.
ctypes.windll.kernel32.SetConsoleCtrlHandler(None, False)
if {fixed!r}:
    from scripts.cage import caged_server
    print("ignored", caged_server.ignore_console_ctrl_c(), flush=True)
child =subprocess.Popen([sys.executable, "-c", {child!r}])
time.sleep(1.0)
subprocess.run([sys.executable, "-c", {sender!r}])
try:
    time.sleep(2.0); print("host survived", flush=True)
except KeyboardInterrupt:
    print("host interrupted", flush=True)
child.wait(timeout=10)
"""


def _host(fixed: bool) -> str:
    script = HOST.format(root=str(ROOT), fixed=fixed, child=CHILD, sender=SENDER)
    hidden = subprocess.STARTUPINFO()
    hidden.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    hidden.wShowWindow = 0  # SW_HIDE
    done = subprocess.run(
        [sys.executable, "-c", script],
        creationflags=subprocess.CREATE_NEW_CONSOLE,  # its own console: the Ctrl+C below cannot reach this one
        startupinfo=hidden,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return done.stdout + done.stderr


def test_without_it_a_console_ctrl_c_stops_the_host_and_its_child() -> None:
    said = _host(fixed=False)
    assert "host interrupted" in said or "KeyboardInterrupt" in said, said
    assert "child interrupted" in said, said


def test_with_it_the_host_and_the_child_it_started_both_keep_running() -> None:
    said = _host(fixed=True)
    assert "ignored True" in said, said
    assert "host survived" in said and "child survived" in said, said
