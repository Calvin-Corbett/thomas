"""Claude CLI descendants must not survive a completed or timed-out Build pass."""

from __future__ import annotations

import ctypes
import os
import signal
import sys
import time

import pytest

from thomas.forge.anvil.forge_event_stream import _stream_cli

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Job Object contract")


def _child_alive(pid: int) -> bool:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle(handle)


def _child_gone(pid: int) -> bool:
    for _ in range(40):
        if not _child_alive(pid):
            return True
        time.sleep(0.05)
    return False


@pytest.mark.parametrize("parent_stays", [False, True])
def test_claude_pass_owns_child_process_tree(tmp_path, parent_stays):
    script = (
        "import subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); "
        "print(child.pid,flush=True); " + ("time.sleep(20)" if parent_stays else "sys.exit(0)")
    )
    events = []
    rc, tail = _stream_cli(
        [sys.executable, "-c", script],
        str(tmp_path),
        1,
        lambda _line: [],
        events.append,
    )
    child_pid = int(tail.splitlines()[0])
    try:
        assert _child_gone(child_pid), "closing the Claude job must terminate its MCP-style child"
        assert (rc != 0) is parent_stays
        assert any("timed out" in event.get("text", "") for event in events) is parent_stays
    finally:
        if _child_alive(child_pid):
            os.kill(child_pid, signal.SIGTERM)
