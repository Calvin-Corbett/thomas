"""With the port busy, Thomas starts on the next free one; ``-Stop`` and the next launch have to find it there.

The launcher records the port it started on in ``runtime\\thomas.port``. Without it, a
Thomas that moved up to the next port could not be stopped (the window that used to be the
off switch is gone, and ``-Stop`` would look only at the port it was asked about) and every
further click on the shortcut would start another one. Only a launch that names no ``-Port`` reads or
writes the record; the tests for a named one are in ``test_a_port_you_name_is_the_port_the_launcher_acts_on``. These tests run the launcher's own functions against stand-in
servers started here, on ports the operating system hands out; nothing is stopped.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.launcher_powershell_support import RUN_UI, needs_windows_powershell, ps_path, run_functions, stand_in_server
from tests.launcher_server_plan_support import FUNCTIONS, IDLE, LOCAL_COMMIT, LOCAL_VERSION, health

pytestmark = needs_windows_powershell

_RECORDED = """
$Port = 22001; $Root = __ROOT__
function Case([string]$name, [string]$text) {
  New-Item -ItemType Directory -Force -Path (Join-Path $Root 'runtime') | Out-Null
  [System.IO.File]::WriteAllText((Join-Path $Root 'runtime\\thomas.port'), $text)
  $name + '=' + (Get-RecordedPort)
}
'missing=' + (Get-RecordedPort)
Case 'valid' "22002`r`n"
Case 'the port asked for' '22001'
Case 'not a number' 'abc'
Case 'empty' ''
Case 'reserved' '80'
Case 'too big' '70000'
Case 'first line only' "22003`r`nabc"
"""


def test_the_recorded_port_is_the_one_in_runtime_or_zero(tmp_path: Path) -> None:
    out = run_functions(RUN_UI, ["Get-RecordedPort"], _RECORDED.replace("__ROOT__", ps_path(tmp_path)), tmp_path)

    # 0 is "none to look at": nothing recorded, nothing usable, or the port that is already being asked about.
    for name, expected in {
        "missing": 0,
        "valid": 22002,
        "the port asked for": 0,
        "not a number": 0,
        "empty": 0,
        "reserved": 0,
        "too big": 0,
        "first line only": 22003,
    }.items():
        assert f"{name}={expected}\n" in out + "\n", out


def _record_the_port(tmp_path: Path, tail: str) -> str:
    """Run the launcher's own statement that records the port (and only that one) with $Port = 22003."""
    return run_functions(
        RUN_UI,
        [],
        f"$Root = {ps_path(tmp_path)}\n$Port = 22003\n'statements: ' + $topLevel.Count\n"
        f"foreach ($s in $topLevel) {{ . ([scriptblock]::Create($s)) }}\n{tail}",
        tmp_path,
        top_level=("thomas.port",),
    )


def test_the_launcher_records_the_port_it_starts_on(tmp_path: Path) -> None:
    (tmp_path / "runtime").mkdir()
    out = _record_the_port(tmp_path, "")

    assert "statements: 1" in out, out
    assert (tmp_path / "runtime" / "thomas.port").read_text(encoding="ascii").strip() == "22003"


def test_a_port_that_cannot_be_recorded_does_not_stop_the_launch(tmp_path: Path) -> None:
    (tmp_path / "runtime").write_text("a file where the folder should be", encoding="ascii")

    assert "went on" in _record_the_port(tmp_path, "'went on'")


def test_the_port_is_recorded_after_it_is_chosen_and_before_the_server_starts() -> None:
    text = RUN_UI.read_text(encoding="utf-8")
    chosen = text.index("  $Port = $FreePort\n}\n")
    written = text.index("runtime\\thomas.port') -Value $Port")

    assert chosen < written < text.index("$LaunchUrl = Get-ThomasLaunchUrl")


def _gate(tmp_path: Path, record: str | None) -> tuple[str, int, int]:
    """Run the launcher's gate for a busy port that is not Thomas, a recorded port, and a Thomas on it."""
    root = tmp_path / "copy"
    (root / "runtime").mkdir(parents=True)
    thomas = stand_in_server(health(root=str(root)), IDLE)
    other = stand_in_server(None, None)  # answers 404 to everything: busy, and not Thomas
    thomas_port, busy_port = thomas.server_address[1], other.server_address[1]
    if record is not None:
        (root / "runtime" / "thomas.port").write_text(record.replace("THOMAS", str(thomas_port)), encoding="ascii")
    body = (
        f"$Port = {busy_port}; $Root = {ps_path(root)}; $Restart = $false; $Stop = $false; $Tray = $false\n"
        "$NoBrowser = $false; $DeepLink = ''\n"
        f"function Get-LocalThomasVersion {{ '{LOCAL_VERSION}' }}\n"
        f"function Get-LocalGitCommit {{ '{LOCAL_COMMIT}' }}\n"
        "function Start-Process { param($FilePath) Write-Host ('OPENED ' + $FilePath) }\n"
        "$code = Invoke-ExistingServerGate\n"
        "'code=[' + $code + '] port=' + $Port\n"
    )
    try:
        out = run_functions(
            RUN_UI, [*FUNCTIONS, "Get-RecordedPort", "Get-ThomasLaunchUrl", "Invoke-ExistingServerGate"], body, tmp_path
        )
    finally:
        for server in (thomas, other):
            server.shutdown()
            server.server_close()
    return out, thomas_port, busy_port


def test_a_launch_opens_the_thomas_that_moved_up_instead_of_starting_another(tmp_path: Path) -> None:
    out, thomas_port, _ = _gate(tmp_path, "THOMAS\r\n")

    assert f"code=[0] port={thomas_port}" in out, out
    assert f"OPENED http://127.0.0.1:{thomas_port}/" in out, out


@pytest.mark.parametrize("record", [None, "", "not a port", "1025"])
def test_with_nothing_usable_recorded_the_launch_goes_on_to_start_one(tmp_path: Path, record: str | None) -> None:
    """The busy port is not Thomas and no recorded port answers, so the launch starts a server as it always did."""
    out, _, busy_port = _gate(tmp_path, record)

    assert f"code=[] port={busy_port}" in out, out
    assert "OPENED" not in out, out
