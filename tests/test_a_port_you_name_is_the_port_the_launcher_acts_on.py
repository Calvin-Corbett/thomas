"""A ``-Port`` you name is the port: a Thomas on some other port is never attached to, replaced or stopped for it.

A launch records the port it started on in ``runtime\\thomas.port`` when the default port was busy and
Thomas moved up, so a later launch with no ``-Port`` finds it there. That record used to be consulted
for a named ``-Port`` too: a launch with a ``-Port`` of your own while a Thomas was recorded on another port attached to,
replaced or stopped the one on the other port and never started on the port you named. These tests run the launcher's own
functions (``Get-RecordedPort`` and the gate that uses it) against stand-in servers on ports the
operating system hands out, with ``Stop-ThomasServerOnPort`` and ``Start-Process`` replaced by
functions that record the call, so nothing is opened or stopped.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.launcher_powershell_support import (
    RUN_UI,
    closed_port,
    needs_windows_powershell,
    ps_path,
    run_functions,
    stand_in_server,
)
from tests.launcher_server_plan_support import BUSY, ELSEWHERE, FUNCTIONS, IDLE, LOCAL_COMMIT, LOCAL_VERSION, health

pytestmark = needs_windows_powershell

# What the Thomas on the recorded port is, and what the gate would do about it if it were asked.
THIS_COPY = {
    "out of date, idle (would be replaced)": (lambda root: health(root=root, dirty=True), IDLE),
    "current, idle (would be attached to)": (lambda root: health(root=root), IDLE),
    "out of date, building (would be left, exit 4)": (lambda root: health(root=root, dirty=True), BUSY),
}
ANOTHER_COPY = {
    "another copy, idle (would be replaced)": (lambda _root: health(root=ELSEWHERE), IDLE),
    "another copy, building (would be left, exit 4)": (lambda _root: health(root=ELSEWHERE), BUSY),
}
RECORDED = {**THIS_COPY, **ANOTHER_COPY}


def _gate(
    tmp_path: Path, recorded: str, *, named: bool, stop: bool = False, restart: bool = False
) -> tuple[str, int, int, list[str]]:
    """Run the gate for a port with nothing on it and a recorded port holding a Thomas.

    Returns what it printed, the port asked for, the recorded port and the requests the recorded Thomas got.
    """
    root = tmp_path / "copy"
    (root / "runtime").mkdir(parents=True)
    make_health, status = RECORDED[recorded]
    thomas = stand_in_server(make_health(str(root)), status)
    hits: list[str] = []
    handler = thomas.RequestHandlerClass

    class Counting(handler):  # type: ignore[misc, valid-type]
        def do_GET(self) -> None:
            hits.append(self.path)
            super().do_GET()

    thomas.RequestHandlerClass = Counting
    asked, recorded_port = closed_port(), thomas.server_address[1]
    (root / "runtime" / "thomas.port").write_text(str(recorded_port), encoding="ascii")
    body = (
        f"$Port = {asked}; $Root = {ps_path(root)}; $PortNamed = ${str(named).lower()}; $Restart = ${str(restart).lower()}\n"
        f"$Stop = ${str(stop).lower()}; $Tray = $false; $NoBrowser = $false; $DeepLink = ''\n"
        f"function Get-LocalThomasVersion {{ '{LOCAL_VERSION}' }}\n"
        f"function Get-LocalGitCommit {{ '{LOCAL_COMMIT}' }}\n"
        "function Start-Process { param($FilePath) Write-Host ('OPENED ' + $FilePath) }\n"
        "function Stop-ThomasServerOnPort { param($P) Write-Host ('STOPPED ' + $P); return $false }\n"
        "$code = Invoke-ExistingServerGate\n"
        "'code=[' + $code + '] port=' + $Port\n"
    )
    try:
        out = run_functions(
            RUN_UI, [*FUNCTIONS, "Get-RecordedPort", "Get-ThomasLaunchUrl", "Invoke-ExistingServerGate"], body, tmp_path
        )
    finally:
        thomas.shutdown()
        thomas.server_close()
    return out, asked, recorded_port, hits


@pytest.mark.parametrize("recorded", list(RECORDED))
def test_a_launch_with_a_named_port_never_acts_on_the_recorded_one(tmp_path: Path, recorded: str) -> None:
    out, asked, recorded_port, hits = _gate(tmp_path, recorded, named=True)

    # Nothing is on the named port, so the launch goes on to start one there (code is empty), where it was told to.
    assert f"code=[] port={asked}" in out, out
    assert "OPENED" not in out and "STOPPED" not in out and "Replacing" not in out, out
    assert str(recorded_port) not in out, out
    # The other Thomas was not even asked who it is.
    assert hits == [], hits


@pytest.mark.parametrize("recorded", list(THIS_COPY))
def test_the_same_launch_with_no_port_named_does_look_at_the_recorded_one(tmp_path: Path, recorded: str) -> None:
    """The control: without it the tests above would pass if the recorded Thomas were never reachable."""
    out, asked, recorded_port, hits = _gate(tmp_path, recorded, named=False)

    assert hits, "the recorded Thomas should have been asked"
    assert f"port={recorded_port}" in out.split("code=")[-1], out


@pytest.mark.parametrize("recorded", list(ANOTHER_COPY))
def test_a_recorded_port_holding_another_copys_thomas_is_asked_about_and_left_alone(
    tmp_path: Path, recorded: str
) -> None:
    """The record says where this copy's Thomas was, not that whatever answers there may be replaced.

    Two copies can share a record: this copy moved up to the recorded port, the other copy later took it.
    With the default port free, a launch starts there and does not touch the other copy's Thomas.
    """
    out, asked, recorded_port, hits = _gate(tmp_path, recorded, named=False)

    assert hits, "it should have been asked whose Thomas it is"
    assert f"code=[] port={asked}" in out, out
    assert "OPENED" not in out and "STOPPED" not in out and "Replacing" not in out and "not this copy" not in out, out


@pytest.mark.parametrize("recorded", list(ANOTHER_COPY))
def test_a_stop_with_no_port_named_leaves_another_copys_thomas_on_the_recorded_port(
    tmp_path: Path, recorded: str
) -> None:
    out, asked, recorded_port, hits = _gate(tmp_path, recorded, named=False, stop=True)

    assert out.count("STOPPED") == 1 and f"STOPPED {asked}" in out and str(recorded_port) not in out, out
    assert f"No Thomas was found on port {asked}." in out and "code=[5]" in out, out


@pytest.mark.parametrize("recorded", list(ANOTHER_COPY))
def test_a_restart_with_no_port_named_leaves_another_copys_thomas_on_the_recorded_port(
    tmp_path: Path, recorded: str
) -> None:
    out, asked, recorded_port, hits = _gate(tmp_path, recorded, named=False, restart=True)

    assert (
        f"code=[] port={asked}" in out and "STOPPED" not in out and str(recorded_port) not in out.split("code=")[-1]
    ), out


def test_a_restart_with_a_named_port_never_looks_at_a_build_on_the_recorded_one(tmp_path: Path) -> None:
    """-Restart is where a refusal would hurt most: it must not be refused for a Build on a port you did not name."""
    building = "out of date, building (would be left, exit 4)"
    out, asked, recorded_port, hits = _gate(tmp_path, building, named=True, restart=True)

    assert f"code=[] port={asked}" in out and hits == [] and "Build" not in out, out


def test_the_same_restart_with_no_port_named_is_refused_for_this_copys_build_on_the_recorded_port(
    tmp_path: Path,
) -> None:
    """The control for the test above: the refusal is real when the Build is this copy's and no port was named."""
    out, asked, recorded_port, hits = _gate(
        tmp_path, "out of date, building (would be left, exit 4)", named=False, restart=True
    )

    assert "code=[3]" in out and hits, out


@pytest.mark.parametrize("recorded", list(RECORDED))
def test_a_stop_with_a_named_port_stops_that_port_and_no_other(tmp_path: Path, recorded: str) -> None:
    out, asked, recorded_port, hits = _gate(tmp_path, recorded, named=True, stop=True)

    assert f"No Thomas was found on port {asked}." in out and "code=[5]" in out, out
    assert out.count("STOPPED") == 1 and f"STOPPED {asked}" in out and str(recorded_port) not in out, out
    assert hits == [], hits


def test_a_stop_with_no_port_named_also_stops_the_recorded_one(tmp_path: Path) -> None:
    out, asked, recorded_port, hits = _gate(tmp_path, "current, idle (would be attached to)", named=False, stop=True)

    assert f"STOPPED {asked}" in out and f"STOPPED {recorded_port}" in out, out
    assert hits, "the recorded Thomas should have been asked"


def _named(tmp_path: Path, statements: str) -> str:
    return run_functions(
        RUN_UI,
        [],
        statements,
        tmp_path,
        top_level=("$PSBoundParameters.ContainsKey('Port')",),
    )


def test_the_launcher_knows_whether_a_port_was_named(tmp_path: Path) -> None:
    """The launcher's own statement, run where ``$PSBoundParameters`` is what a ``-Port`` argument makes it."""
    out = _named(
        tmp_path,
        "'statements: ' + $topLevel.Count\n"
        "$probe = [scriptblock]::Create('param([int]$Port = 22001)' + [char]10 + $topLevel[0] + [char]10 + '[string]$PortNamed')\n"
        "'named=' + (& $probe -Port 22002)\n"
        "'default=' + (& $probe)\n",
    )

    assert "statements: 1" in out and "named=True" in out and "default=False" in out, out


@pytest.mark.parametrize(("named", "recorded"), [(True, False), (False, True)])
def test_only_a_launch_with_no_port_named_records_where_it_started(tmp_path: Path, named: bool, recorded: bool) -> None:
    """A scratch launch on a port of its own must not overwrite where the default Thomas is."""
    (tmp_path / "runtime").mkdir()
    out = run_functions(
        RUN_UI,
        [],
        f"$Root = {ps_path(tmp_path)}\n$Port = 22003\n$PortNamed = ${str(named).lower()}\n"
        "'statements: ' + $topLevel.Count\nforeach ($s in $topLevel) { . ([scriptblock]::Create($s)) }\n",
        tmp_path,
        top_level=("thomas.port",),
    )

    assert "statements: 1" in out, out
    assert (tmp_path / "runtime" / "thomas.port").exists() is recorded
