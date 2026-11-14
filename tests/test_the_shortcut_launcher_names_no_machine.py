"""The Thomas.vbs launcher names no machine, and on the default port starts Thomas when its port refuses a connection.

Thomas.vbs is tracked in git and ships in the installer, but it used to be written
with the folder of whoever ran ``scripts/thomas_app.py`` (a Windows user name and
its path layout). On any other machine every ``FileExists`` check failed, no server
was started, and the browser fallback opened Edge on Thomas's local address with
nothing listening: "This site can't be reached".

It also treated a shell that would not start as a shell that started. electron.exe
is unsigned; where Windows refuses to run it (Smart App Control), ``Run`` raises an
error and the old launcher quit anyway, so clicking the icon did nothing.

These tests read the generated text and, on Windows, compile it. They never run a
launcher: the compile check puts ``WScript.Quit`` first, so nothing after it executes.
The order in which a launcher acts is in test_the_shortcut_launcher_flow.py and
test_the_shortcut_launcher_start_asks_first.py; the probes it calls, run for real, are
in test_the_shortcut_launcher_probes.py.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from scripts import thomas_app

from tests.launcher_script_host_support import CSCRIPT, cscript

ROOT = Path(__file__).resolve().parents[1]
needs_cscript = pytest.mark.skipif(CSCRIPT is None, reason="needs Windows Script Host")


def _variants() -> dict[str, str]:
    return {
        "ordinary": thomas_app.render_launcher(thomas_app.DEFAULT_PORT),
        "caged": thomas_app.render_launcher(thomas_app.CAGED_PORT, caged=True),
        "caged on the everyday port": thomas_app.render_launcher(thomas_app.DEFAULT_PORT, caged=True),
        "other port": thomas_app.render_launcher(9001),
    }


def _committed_launcher() -> str | None:
    """Thomas.vbs as git holds it, or None when this is not a checkout with it tracked.

    Not the file on disk: ``python scripts/thomas_app.py --caged`` (or --port) rewrites
    that copy for this machine, and a test of the tracked file must not turn red
    because you installed the caged icon.
    """
    git = shutil.which("git")
    if git is None:
        return None
    done = subprocess.run(  # noqa: S603 - read-only git on this checkout
        [git, "-C", str(ROOT), "show", ":Thomas.vbs"], capture_output=True, check=False, timeout=30
    )
    if done.returncode != 0:
        return None
    return done.stdout.decode("ascii").replace("\r\n", "\n")


def test_no_launcher_names_a_folder_a_drive_or_a_person() -> None:
    for name, text in _variants().items():
        assert not re.search(r"[A-Za-z]:\\", text), f"{name}: a drive-letter path is baked in"
        assert "\\Users\\" not in text, f"{name}: a user profile path is baked in"
        assert str(thomas_app.REPO_ROOT) not in text, f"{name}: the folder it was generated in is baked in"
        assert "WScript.ScriptFullName" in text, f"{name}: paths must come from where the file sits"


def test_the_tracked_launcher_is_exactly_what_the_generator_writes() -> None:
    """So an install rewrites it to the same bytes and dirties nothing in git."""
    tracked = _committed_launcher()
    if tracked is None:
        pytest.skip("Thomas.vbs is not tracked in a git checkout here")

    assert tracked == thomas_app.render_launcher(thomas_app.DEFAULT_PORT)


def test_the_files_it_reaches_for_exist_at_the_places_it_computes() -> None:
    text = thomas_app.render_launcher(thomas_app.DEFAULT_PORT)

    assert 'appDir & "\\desktop"' in text and (ROOT / "desktop" / "main.js").is_file()
    assert 'appDir & "\\scripts\\run-desktop.ps1"' in text and (ROOT / "scripts" / "run-desktop.ps1").is_file()
    assert 'appDir & "\\launch-thomas.vbs"' in text and (ROOT / "launch-thomas.vbs").is_file()
    assert "run-ui.ps1" in (ROOT / "launch-thomas.vbs").read_text(encoding="utf-8")


def test_a_shell_windows_refuses_to_start_falls_through_to_the_browser_window() -> None:
    text = thomas_app.render_launcher(thomas_app.DEFAULT_PORT)
    run = text.index("shell.Run Chr(34) & electronExe")

    assert text.rindex("On Error Resume Next", 0, run) > text.index("If fso.FileExists(electronExe)")
    assert text[run:].split("\n")[1].strip() == "If Err.Number = 0 Then WScript.Quit 0"
    assert "shellFailed = True" in text[run : text.index('shell.Run "msedge"')]
    # Re-installing cannot unblock an unsigned exe, so the install offer is skipped.
    assert "If (Not shellFailed) And fso.FileExists(runDesktopPs1)" in text


def test_the_browser_fallback_starts_a_server_when_nothing_answers_and_only_then() -> None:
    text = thomas_app.render_launcher(thomas_app.DEFAULT_PORT)
    guard = text.index("If (Not ServerIsUp(appUrl)) And fso.FileExists(launchVbs)")
    block = text[guard : text.index("\nEnd If\n", guard)]

    assert 'shell.Run "wscript.exe //nologo " & Chr(34) & launchVbs & Chr(34), 0' in block
    assert block.rstrip().endswith("WScript.Quit 0"), "the launcher opens Thomas itself; nothing more is opened here"
    assert guard < text.index('shell.Run "msedge"'), "the server has to be started before the app window opens"
    assert '"api/health"' in text, "the probe asks the same health URL the desktop shell asks"


def test_the_health_probe_calls_only_a_refused_connection_down() -> None:
    """A timeout means something accepted and is too busy to answer: starting another server stops it."""
    probe = thomas_app._SERVER_PROBE
    down = re.findall(r"Err\.Number\s*=\s*(&H[0-9A-Fa-f]+)", probe)

    assert [d.upper() for d in down] == ["&H80072EFD"], "only 'cannot connect' may mean nothing is there"
    assert "ServerIsUp = True\n" in probe.split("On Error Resume Next")[0], "unknown is up, never down"
    # A machine-wide proxy that is unreachable reports 'cannot connect' for a server that is running.
    assert "http.setProxy 1" in probe, "the probe must go to the loopback address directly, not through a proxy"


def test_the_start_guard_counts_only_a_young_invocation_of_this_script() -> None:
    guard = thomas_app._START_GUARD
    text = thomas_app.render_launcher(thomas_app.DEFAULT_PORT)

    assert "Name = 'powershell.exe' OR Name = 'pwsh.exe'" in guard, "both shells can run run-ui.ps1"
    assert "CreationDate" in guard and "age < maxSeconds" in guard, "an old console must not count"
    assert '"-File " & Chr(34) & scriptPath & Chr(34)' in guard, "a shell that only mentions the path must not count"
    assert "StartIsRunning(runUiPs1, 30 * 60)" in text, "a start counts for half an hour"


def test_the_caged_launcher_never_starts_a_server_as_you() -> None:
    for port in (thomas_app.CAGED_PORT, thomas_app.DEFAULT_PORT):
        text = thomas_app.render_launcher(port, caged=True)

        assert "launch-thomas" not in text and "run-ui" not in text and "ServerIsUp" not in text, port
        assert "StartIsRunning" not in text and "schtasks /Run /TN ThomasCagedServer" in text, port


def test_a_port_the_everyday_launcher_does_not_serve_gets_no_automatic_start() -> None:
    assert "launch-thomas" not in thomas_app.render_launcher(9001)


def _compile_only(text: str, path: Path) -> Path:
    """The same text with Quit as the first statement: it compiles, then exits."""
    head, rest = text.split("\n", 1)
    assert head == "Option Explicit"
    path.write_bytes((head + "\nWScript.Quit 0\n" + rest).replace("\n", "\r\n").encode("ascii"))
    return path


@needs_cscript
def test_every_launcher_variant_compiles_and_a_broken_one_does_not(tmp_path: Path) -> None:
    for name, text in _variants().items():
        done = cscript(_compile_only(text, tmp_path / f"{name.replace(' ', '_')}.vbs"))
        assert done.returncode == 0, f"{name}: {done.stdout}{done.stderr}"

    broken = thomas_app.render_launcher(thomas_app.DEFAULT_PORT).replace("End Function", "")
    assert cscript(_compile_only(broken, tmp_path / "broken.vbs")).returncode != 0
