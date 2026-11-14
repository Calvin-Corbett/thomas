"""A second double-click while the first launch is still installing or starting used to race it for the port.

The Start Menu shortcut runs hidden, and a first launch can take minutes (pip,
winget). Clicking again is the natural reaction, and that second launch ended
the first launch's server. Now a launch takes a lock first: a file under
``runtime`` that run-ui.ps1 holds open, so a second launch waits for the first,
finds Thomas running and uses it. These tests run the lock function on its own,
with a second process standing in for the first launch.
"""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

from tests.launcher_powershell_support import POWERSHELL, RUN_UI, needs_windows_powershell, ps_path, run_functions

pytestmark = needs_windows_powershell

# Holds the lock file like a launch in its slow part, and lets go when told to (or after two minutes).
_HOLDER = (
    "$f = [System.IO.File]::Open({lock}, 'OpenOrCreate', 'ReadWrite', 'None'); "
    "Set-Content -Path {ready} -Value 'held'; $end = (Get-Date).AddSeconds(120); "
    "while (-not (Test-Path {release}) -and (Get-Date) -lt $end) {{ Start-Sleep -Milliseconds 200 }}; $f.Dispose()"
)


def _first_launch(root: Path) -> subprocess.Popen[str]:
    """A process holding the lock until ``release.txt`` appears in *root*."""
    (root / "runtime").mkdir(exist_ok=True)
    ready = root / "holder-ready.txt"
    command = _HOLDER.format(
        lock=ps_path(root / "runtime" / "launch.lock"), ready=ps_path(ready), release=ps_path(root / "release.txt")
    )
    holder = subprocess.Popen(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", command],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    deadline = time.monotonic() + 60
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    assert ready.exists(), "the stand-in launch never took the lock"
    return holder


def _let_go_a_few_seconds_after_the_second_launch_starts_waiting(root: Path, seconds: float = 3) -> None:
    def release() -> None:
        deadline = time.monotonic() + 120
        while not (root / "waiting.txt").exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        time.sleep(seconds)
        (root / "release.txt").write_text("go", encoding="ascii")

    threading.Thread(target=release, daemon=True).start()


def _second_launch(root: Path, wait_sec: int, after: str = "") -> str:
    body = (
        f"$Root = {ps_path(root)}\n"
        f"Set-Content -Path {ps_path(root / 'waiting.txt')} -Value 'x'\n"
        "$started = Get-Date\n"
        f"$lock = Enter-LaunchLock -WaitSec {wait_sec}\n"
        "'got it: ' + [bool]$lock\n"
        "'waited ms: ' + [int]((Get-Date) - $started).TotalMilliseconds\n"
        "if ($lock) { $lock.Dispose() }\n" + after
    )
    return run_functions(RUN_UI, ["Enter-LaunchLock"], body, root)


def test_a_second_launch_waits_for_the_first_and_then_takes_over(tmp_path: Path) -> None:
    holder = _first_launch(tmp_path)
    _let_go_a_few_seconds_after_the_second_launch_starts_waiting(tmp_path)
    try:
        out = _second_launch(tmp_path, wait_sec=90)
    finally:
        holder.wait(timeout=60)

    assert "Another launch of Thomas is still starting; waiting for it to finish." in out, out
    assert "got it: True" in out, out
    # It really did wait for the first launch to let go, rather than taking the file at once.
    assert int(out.split("waited ms: ")[1].split()[0]) >= 2000, out


def test_a_launch_that_has_waited_long_enough_goes_ahead_without_the_lock(tmp_path: Path) -> None:
    holder = _first_launch(tmp_path)
    _let_go_a_few_seconds_after_the_second_launch_starts_waiting(tmp_path)
    try:
        out = _second_launch(tmp_path, wait_sec=1)
    finally:
        holder.wait(timeout=60)

    assert "got it: False" in out and "continuing without waiting for it" in out, out


def test_the_lock_is_free_again_once_the_first_launch_ends(tmp_path: Path) -> None:
    holder = _first_launch(tmp_path)
    (tmp_path / "release.txt").write_text("go", encoding="ascii")
    holder.wait(timeout=60)

    out = _second_launch(tmp_path, wait_sec=1)

    assert "got it: True" in out and "Another launch" not in out, out


def test_a_failure_that_is_not_another_launch_holding_the_lock_does_not_wait(tmp_path: Path) -> None:
    """A missing folder or a full disk would stall a hidden launch for ten minutes, blaming another launch."""
    body = f"""
$Root = {ps_path(tmp_path)}
function New-Item {{ }}
$started = Get-Date
$lock = Enter-LaunchLock -WaitSec 30
'got it: ' + [bool]$lock
'waited ms: ' + [int]((Get-Date) - $started).TotalMilliseconds
"""
    out = run_functions(RUN_UI, ["Enter-LaunchLock"], body, tmp_path)

    # With no runtime folder, opening the lock file fails with DirectoryNotFoundException (not a sharing violation).
    assert "got it: False" in out and "Another launch" not in out, out
    assert int(out.split("waited ms: ")[1].split()[0]) < 5000, out


def test_the_lock_is_not_handed_to_the_server_the_launch_starts(tmp_path: Path) -> None:
    """The server is a child of the launch and outlives it; it must not keep the lock."""
    body = f"""
$Root = {ps_path(tmp_path)}
$lock = Enter-LaunchLock -WaitSec 1
'first: ' + [bool]$lock
$child = Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile', '-Command', 'Start-Sleep -Seconds 5' -WindowStyle Hidden `
  -RedirectStandardOutput {ps_path(tmp_path / "out.log")} -RedirectStandardError {ps_path(tmp_path / "err.log")} -PassThru
$lock.Dispose()
$again = Enter-LaunchLock -WaitSec 1
'after release, child still running: ' + (-not $child.HasExited) + ', lock taken: ' + [bool]$again
if ($again) {{ $again.Dispose() }}
[void]$child.WaitForExit(30000)
"""
    out = run_functions(RUN_UI, ["Enter-LaunchLock"], body, tmp_path)

    assert "first: True" in out, out
    assert "after release, child still running: True, lock taken: True" in out, out


def test_a_launch_waits_up_to_ten_minutes_unless_told_otherwise() -> None:
    """The changelog says ten minutes; the tests above pass their own wait so they do not take that long."""
    text = RUN_UI.read_text(encoding="utf-8")

    assert "function Enter-LaunchLock {" in text and "  param([int]$WaitSec = 600)" in text


def test_the_tray_agent_is_started_after_the_lock_is_let_go() -> None:
    text = RUN_UI.read_text(encoding="utf-8")

    assert text.index("$LaunchLock = Enter-LaunchLock") < text.index("$gateExit = Invoke-ExistingServerGate")
    # The tray agent runs for as long as Thomas does, so a launch that waited on it would wait for ever.
    release = text.index("if ($LaunchLock) { $LaunchLock.Dispose() }")
    assert release < text.index('Invoke-ThomasRuntime @("-m", "thomas.tray_agent"')
