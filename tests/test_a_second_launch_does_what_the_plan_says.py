"""The launcher's decision about a Thomas that is already running has to reach the browser and the exit code.

The decision itself is tested against stand-in servers next door. This file
covers what the launcher does with it: a reused Thomas opens in the browser (at
the ``thomas://`` link when there is one) and ends the launch with exit code 0, one
left running that is not this copy opens too and exits 4, a refused restart opens it
too and exits 3, a replacement or a fresh start opens
nothing and goes on. ``Get-ExistingServerPlan`` is replaced by a function that
records how it was asked, and ``Start-Process`` and the function that stops a
server by ones that record the call, so nothing is opened or stopped.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.launcher_gate_support import PORT, gate_cases
from tests.launcher_powershell_support import RUN_UI, needs_windows_powershell, run_functions

pytestmark = needs_windows_powershell

DEEP_LINK = "thomas://install/demo"

_CASES = """
Case 'attach' 'attach'
Case 'attach with a link' 'attach' @{ DeepLink = 'thomas://install/demo' }
Case 'attach without a browser' 'attach' @{ NoBrowser = $true }
Case 'attach to one that is not this copy' 'attach' @{ Left = $true }
Case 'attach to a degraded one' 'attach' @{ Degraded = $true }
Case 'attach to a degraded one without a browser' 'attach' @{ Degraded = $true; NoBrowser = $true }
Case 'attach to a degraded one that is also left' 'attach' @{ Degraded = $true; Left = $true }
Case 'refuse' 'refuse'
Case 'replace' 'replace'
Case 'start' 'start'
Case 'restart asked' 'replace' @{ Restart = $true }
Case 'tray asked' 'attach' @{ Tray = $true }
Case 'stop a server' 'replace' @{ Stop = $true; StopWorked = $true }
Case 'stop during a build' 'refuse' @{ Stop = $true }
Case 'stop a server that does not answer' 'start' @{ Stop = $true; StopWorked = $true }
Case 'again, still to replace' 'replace' @{ Again = $true }
Case 'again, nothing there' 'start' @{ Again = $true }
Case 'again, a build started' 'attach' @{ Again = $true; Left = $true }
Case 'again, a build started and a restart was asked' 'refuse' @{ Again = $true; Restart = $true }
Case 'again, now current' 'attach' @{ Again = $true }
"""


@pytest.fixture(scope="module")
def cases(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    work = tmp_path_factory.mktemp("gate")
    return gate_cases(_CASES, work)


def test_a_reused_thomas_opens_in_the_browser_and_ends_the_launch(cases: dict[str, str]) -> None:
    line = cases["attach"]

    assert "|code=0|" in line, cases["raw"]
    assert f"|opened=http://127.0.0.1:{PORT}/|" in line, cases["raw"]
    assert "|stopped=|" in line and "plan message" in line


def test_a_marketplace_link_lands_on_the_thomas_that_is_running(cases: dict[str, str]) -> None:
    line = cases["attach with a link"]

    assert "|code=0|" in line, cases["raw"]
    assert (
        f"|opened=http://127.0.0.1:{PORT}/?nav=marketplace&thomas_deep_link=thomas%3A%2F%2Finstall%2Fdemo|" in line
    ), cases["raw"]


def test_no_browser_means_none_is_opened(cases: dict[str, str]) -> None:
    assert "|code=0|" in cases["attach without a browser"], cases["raw"]
    assert "|opened=|" in cases["attach without a browser"], cases["raw"]


def test_a_thomas_left_running_that_is_not_this_copy_opens_and_exits_4(cases: dict[str, str]) -> None:
    """Exit 4 is what lets the Start Menu shortcut tell you the window that opened is not the copy you launched."""
    line = cases["attach to one that is not this copy"]

    assert "|code=4|" in line, cases["raw"]
    assert f"|opened=http://127.0.0.1:{PORT}/|" in line and "|stopped=|" in line, cases["raw"]


def test_a_degraded_thomas_opens_and_exits_7_so_the_shortcut_can_say_so(cases: dict[str, str]) -> None:
    """A Thomas that reports degraded is used, not stopped, but a hidden shortcut must not say nothing."""
    line = cases["attach to a degraded one"]

    assert "|code=7|" in line, cases["raw"]
    assert f"|opened=http://127.0.0.1:{PORT}/|" in line and "|stopped=|" in line, cases["raw"]
    assert "|code=7|" in cases["attach to a degraded one without a browser"], cases["raw"]
    # A Thomas left running mid-Build keeps its own, more urgent, message.
    assert "|code=4|" in cases["attach to a degraded one that is also left"], cases["raw"]
    assert "|code=0|" in cases["attach"], cases["raw"]


def test_a_refused_restart_exits_3_and_still_shows_the_thomas_that_is_busy(cases: dict[str, str]) -> None:
    line = cases["refuse"]

    assert "|code=3|" in line, cases["raw"]
    assert f"|opened=http://127.0.0.1:{PORT}/|" in line, cases["raw"]
    assert "|stopped=|" in line


def test_a_replacement_or_a_fresh_start_opens_nothing_and_carries_on(cases: dict[str, str]) -> None:
    for name in ("replace", "start"):
        assert f"{name}|code=null|" in cases[name], cases["raw"]
        assert "|opened=|" in cases[name] and "|stopped=|" in cases[name], cases[name]


def test_the_plan_is_asked_for_this_copy_and_a_restart_reaches_it(cases: dict[str, str]) -> None:
    assert f"port={PORT} version=9.9.9 root=C:\\Apps\\Thomas replace=False" in cases["attach"], cases["raw"]
    assert f"port={PORT} version=9.9.9 root=C:\\Apps\\Thomas replace=True" in cases["restart asked"], cases["raw"]


def test_a_tray_that_was_asked_for_but_not_started_is_said(cases: dict[str, str]) -> None:
    assert "-Tray was not started" in cases["tray asked"], cases["raw"]
    assert "-Tray was not started" not in cases["attach"]


def test_stop_ends_the_server_and_asks_the_plan_as_a_replacement(cases: dict[str, str]) -> None:
    line = cases["stop a server"]

    assert "|code=0|" in line and "replace=True" in line, cases["raw"]
    assert f"|stopped={PORT}|" in line and "Stopped Thomas" in line and "|opened=|" in line, cases["raw"]
    # A server that did not answer is still stopped if it is a Thomas process on the port.
    assert f"|stopped={PORT}|" in cases["stop a server that does not answer"], cases["raw"]


def test_stop_leaves_a_build_running_and_says_when_nothing_was_there(cases: dict[str, str]) -> None:
    assert "|code=3|" in cases["stop during a build"], cases["raw"]
    assert f"|stopped={PORT}|" not in cases["stop during a build"], cases["raw"]


@pytest.mark.parametrize(
    ("gate", "falls_through"),
    [("3", False), ("0", False), ("$null", True)],
)
def test_the_launch_ends_where_the_gate_says_and_goes_on_when_it_says_nothing(
    tmp_path: Path, gate: str, falls_through: bool
) -> None:
    out = run_functions(
        RUN_UI,
        [],
        f"function Invoke-ExistingServerGate {{ return {gate} }}\n"
        "'statements: ' + $topLevel.Count\n"
        "foreach ($s in $topLevel) { . ([scriptblock]::Create($s)) }\n"
        "'fell through'",
        tmp_path,
        top_level=("$gateExit",),
    )

    assert "statements: 2" in out, out
    assert ("fell through" in out) is falls_through, out


def test_asking_again_does_not_announce_a_replacement_twice_but_does_announce_what_changed(
    cases: dict[str, str],
) -> None:
    for name in ("again, still to replace", "again, nothing there"):
        assert f"{name}|code=null|" in cases[name] and "plan message" not in cases[name], cases["raw"]
    # A Build that started since is news: it is said, and the running Thomas opens and is left alone.
    started = cases["again, a build started"]
    assert "|code=4|" in started and "plan message" in started, cases["raw"]
    assert f"|opened=http://127.0.0.1:{PORT}/|" in started and "|stopped=|" in started, cases["raw"]
    refused = cases["again, a build started and a restart was asked"]
    assert "|code=3|" in refused and "plan message" in refused and "|stopped=|" in refused, cases["raw"]
    assert "|code=0|" in cases["again, now current"] and "plan message" in cases["again, now current"], cases["raw"]


@pytest.mark.parametrize("restart", ["$false", "$true"])
@pytest.mark.parametrize(("gate", "stops"), [("4", False), ("3", False), ("0", False), ("$null", True)])
def test_the_old_server_is_stopped_only_if_the_gate_still_says_so_just_before(
    tmp_path: Path, gate: str, stops: bool, restart: str
) -> None:
    """Installing and first-run setup can take minutes; a Build started on the old server meanwhile must survive.

    With ``-Restart`` too: that is the launch that replaces a server on purpose, so it is the one most likely
    to be wired around the second look.
    """
    out = run_functions(
        RUN_UI,
        [],
        f"$Port = 22001; $Restart = {restart}\n"
        f"function Invoke-ExistingServerGate {{ param([switch]$Again) Write-Host ('again=' + $Again.IsPresent); return {gate} }}\n"
        "function Stop-ThomasServerOnPort { param($P) Write-Host 'STOPPED'; return $true }\n"
        "'statements: ' + $topLevel.Count\n"
        "foreach ($s in $topLevel) { . ([scriptblock]::Create($s)) }\n",
        tmp_path,
        top_level=("$lastGate", "Stop-ThomasServerOnPort $Port | Out-Null"),
    )

    assert "statements: 3" in out and "again=True" in out, out
    assert ("STOPPED" in out) is stops, out


def _statements_after(text: str, start: str) -> list[str]:
    """The non-blank, non-comment lines after the line that begins with *start*."""
    tail = text[text.index(start) :].splitlines()[1:]
    return [line.strip() for line in tail if line.strip() and not line.strip().startswith("#")]


def test_the_second_look_comes_after_the_slow_steps_and_right_before_the_stop() -> None:
    """Moving the second look up to the first, or to just after the venv, leaves the minutes of setup unguarded.

    The behaviour tests above pass whichever place it sits in, so this reads where it is: after the slow
    steps (the venv, the pip install, first-run setup), then nothing but the exit it decides and the stop.
    """
    text = RUN_UI.read_text(encoding="utf-8")
    second = "\n$lastGate = Invoke-ExistingServerGate -Again\n"
    steps = [
        "\n$gateExit =",
        "\n$venvExit = Ensure-ThomasVenv\n",
        "\nEnsure-Installed\n",
        "\nInvoke-FirstRunQuickSetup\n",
    ]

    assert text.count(second) == 1
    where = [text.index(step) for step in [*steps, second]]
    assert where == sorted(where), "the second look is not after the first look and every slow step"
    assert _statements_after(text, second.strip())[:2] == [
        "if ($null -ne $lastGate) { exit $lastGate }",
        "Stop-ThomasServerOnPort $Port | Out-Null",
    ]


@pytest.mark.parametrize(("stop", "locks"), [("$false", 1), ("$true", 0)])
def test_a_stop_does_not_wait_for_a_launch_that_is_going_on(tmp_path: Path, stop: str, locks: int) -> None:
    out = run_functions(
        RUN_UI,
        [],
        f"$Stop = {stop}\n$script:locks = 0\n"
        "function Enter-LaunchLock { $script:locks++; return $null }\n"
        "foreach ($s in $topLevel) { . ([scriptblock]::Create($s)) }\n"
        "'locks: ' + $script:locks",
        tmp_path,
        # Not "$LaunchLock" alone: the block that starts the server also names it.
        top_level=("$LaunchLock = Enter-LaunchLock",),
    )

    assert f"locks: {locks}" in out, out
