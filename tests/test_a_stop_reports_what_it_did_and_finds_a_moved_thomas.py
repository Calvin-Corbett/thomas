"""``-Stop`` has to say what it did, and look where the Thomas is.

The server has no window, so ``-Stop`` (the shortcut's ``/stop``) is the only off switch. It exits 0 only
when it ended a Thomas, 5 when it found none, 6 when one is still there afterwards, 3 while a Build runs.
When the port you asked for was busy, Thomas started on the next one and the launcher recorded where:
``-Stop`` and the next launch look there too. Everything the gate calls is replaced by a stand-in that
records the call (see ``launcher_gate_support``), so nothing is asked of a server, opened or stopped.
"""

from __future__ import annotations

import pytest

from tests.launcher_gate_support import PORT, gate_cases
from tests.launcher_powershell_support import needs_windows_powershell

pytestmark = needs_windows_powershell

_CASES = """
Case 'stop with nothing running' 'start' @{ Stop = $true }
Case 'stop that left it running' 'replace' @{ Stop = $true; StopWorked = $true; Listening = @(22001) }
Case 'stop that could not find the process' 'replace' @{ Stop = $true; Listening = @(22001); Answering = @(22001) }
Case 'stop beside another program' 'start' @{ Stop = $true; Listening = @(22001) }
Case 'moved: found there' 'start' @{ Moved = 22002; Plans = @{ 22002 = 'attach' } }
Case 'moved: not asked when this port answers' 'attach' @{ Moved = 22002; Plans = @{ 22002 = 'attach' } }
Case 'moved: nothing there either' 'start' @{ Moved = 22002 }
Case 'moved: restart replaces it there' 'start' @{ Restart = $true; Moved = 22002; Plans = @{ 22002 = 'replace' } }
Case 'moved: restart refused while it builds' 'start' @{ Restart = $true; Moved = 22002; Plans = @{ 22002 = 'refuse' } }
Case 'moved: stop finds nothing on either' 'start' @{ Stop = $true; Moved = 22002 }
Case 'moved: stop ends both' 'start' @{ Stop = $true; Moved = 22002; StopPorts = @(22001, 22002) }
Case 'moved: stop ends the one there' 'start' @{ Stop = $true; Moved = 22002; StopPorts = @(22002) }
Case 'moved: stop refused while it builds' 'start' @{ Stop = $true; Moved = 22002; Plans = @{ 22002 = 'refuse' } }
Case 'moved: stop leaves one running' 'start' @{ Stop = $true; Moved = 22002; StopPorts = @(22001, 22002); Listening = @(22002); Plans = @{ 22002 = 'replace' } }
Case 'moved: stop leaves another copy there' 'start' @{ Stop = $true; Moved = 22002; StopPorts = @(22002); Plans = @{ 22002 = 'replace' }; Other = $true }
Case 'moved: stop leaves a listener that did not answer' 'start' @{ Stop = $true; Moved = 22002; StopPorts = @(22002); Listening = @(22002) }
Case 'moved: another copy there is not attached to' 'start' @{ Moved = 22002; Plans = @{ 22002 = 'attach' }; Other = $true }
Case 'moved: restart leaves another copy there' 'start' @{ Restart = $true; Moved = 22002; Plans = @{ 22002 = 'refuse' }; Other = $true }
"""


@pytest.fixture(scope="module")
def cases(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    return gate_cases(_CASES, tmp_path_factory.mktemp("stop"))


def test_a_stop_that_found_nothing_does_not_exit_as_a_success(cases: dict[str, str]) -> None:
    """``-Stop`` exits 0 only when it ended a Thomas; 5 is "none found", so a shortcut cannot say it stopped one."""
    for name in ("stop with nothing running", "stop beside another program"):
        assert "|code=5|" in cases[name] and f"No Thomas was found on port {PORT}." in cases[name], cases["raw"]
        assert "Stopped Thomas" not in cases[name], cases["raw"]
    # With a recorded port there are two places it looked, and the log says both.
    both = cases["moved: stop finds nothing on either"]
    assert "|code=5|" in both and "No Thomas was found on port 22001 or 22002." in both, cases["raw"]
    # A listener that is not Thomas is not Thomas, so it is no reason to call the stop a failure.
    assert "could not be stopped" not in cases["stop beside another program"], cases["raw"]


def test_a_stop_that_left_a_thomas_running_exits_6_and_says_so(cases: dict[str, str]) -> None:
    """Ending a process reports nothing when it fails, so the port is looked at again after the stop."""
    for name in ("stop that left it running", "stop that could not find the process"):
        assert "|code=6|" in cases[name] and f"Thomas on port {PORT} could not be stopped." in cases[name], cases["raw"]
        assert "Stopped Thomas" not in cases[name], cases["raw"]


def test_a_thomas_that_moved_up_is_found_where_it_is_not_started_twice(cases: dict[str, str]) -> None:
    """With the port busy, Thomas starts on the next one; the launcher records it and finds it there again."""
    found = cases["moved: found there"]
    assert "|code=0|" in found and "|opened=http://127.0.0.1:22002/|" in found and "|port=22002|" in found, cases["raw"]
    assert "port=22001 " in found and "port=22002 " in found, "both ports should have been asked about"
    assert (
        "|code=null|" in cases["moved: nothing there either"] and "|port=22001|" in cases["moved: nothing there either"]
    )
    # A Thomas that answers on the port asked for ends the question: the recorded port is not probed.
    assert "port=22002 " not in cases["moved: not asked when this port answers"], cases["raw"]
    assert "|opened=http://127.0.0.1:22001/|" in cases["moved: not asked when this port answers"], cases["raw"]


def test_a_restart_goes_where_the_thomas_is(cases: dict[str, str]) -> None:
    replaced = cases["moved: restart replaces it there"]
    assert "|code=null|" in replaced and "|port=22002|" in replaced and "replace=True" in replaced, cases["raw"]
    refused = cases["moved: restart refused while it builds"]
    assert "|code=3|" in refused and "|opened=http://127.0.0.1:22002/|" in refused, cases["raw"]


def test_a_stop_ends_the_thomas_on_the_recorded_port_too(cases: dict[str, str]) -> None:
    both = cases["moved: stop ends both"]
    assert "|code=0|" in both and "|stopped=22001,22002|" in both, cases["raw"]
    assert "Stopped Thomas on port 22001 and 22002." in both, cases["raw"]
    there = cases["moved: stop ends the one there"]
    assert "|code=0|" in there and "Stopped Thomas on port 22002." in there and "22001." not in there, cases["raw"]
    # A Build on either one keeps both running; the message is the one for that port.
    refused = cases["moved: stop refused while it builds"]
    assert "|code=3|" in refused and "|stopped=|" in refused and "plan message for 22002" in refused, cases["raw"]
    left = cases["moved: stop leaves one running"]
    assert "|code=6|" in left and "Thomas on port 22002 could not be stopped." in left, cases["raw"]


def test_the_recorded_port_is_acted_on_only_when_the_thomas_there_is_this_copy(cases: dict[str, str]) -> None:
    """The record says where this copy's Thomas was; another copy's Thomas, or a listener that did not answer as one, is left alone."""
    for name in ("moved: stop leaves another copy there", "moved: stop leaves a listener that did not answer"):
        # Only the port asked for is stopped; the recorded one is not even tried, and nothing is said about it.
        assert "|stopped=22001|" in cases[name] and "|code=5|" in cases[name], cases["raw"]
        assert f"No Thomas was found on port {PORT}." in cases[name], cases["raw"]
    # Without -Stop, a Thomas of another copy there is neither attached to nor replaced: the launch starts on the port it asked for.
    for name in ("moved: another copy there is not attached to", "moved: restart leaves another copy there"):
        assert "|code=null|" in cases[name] and "|port=22001|" in cases[name] and "|opened=|" in cases[name], cases[
            "raw"
        ]
