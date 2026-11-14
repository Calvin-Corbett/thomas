"""start-tray-agent.ps1 names the right processes and packages, and the tray module's
STATUS.md says only what the code does. Source-level checks, plus copied-out functions
run under Windows PowerShell with nothing stopped or installed (the pip call fails on
purpose: --no-index). The stop-by-port and logon-task behaviour has its own files:
test_tray_launcher_stop.py and test_tray_launcher_task.py."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from tests.tray_support import ROOT, functions, needs_powershell, run_powershell, script_default_port, script_source

STATUS = ROOT / "thomas" / "tray_agent" / "STATUS.md"


def test_the_starter_only_stops_processes_bound_to_its_own_port() -> None:
    source = script_source()

    assert "function Test-ThomasProcessOnPort" in source
    assert "Test-ThomasProcessOnPort -CommandLine" in source
    # The old loop stopped anything that looked like a Thomas server, on any port.
    assert "$procCmd -match" not in source
    assert "Stopping any existing Thomas instances" not in source


@needs_powershell
def test_the_port_filter_accepts_only_this_ports_thomas_processes(tmp_path: Path) -> None:
    port, default = 22040, script_default_port()
    cases = [
        (rf"C:\x\python.exe -m thomas.tray_agent --port {port}", port, True),
        (rf"C:\x\python.exe -m thomas.server --host 127.0.0.1 --port {port}", port, True),
        (rf"python.exe -m thomas serve --port={port}", port, True),
        (rf"pythonw.exe C:\r\thomas\tray_agent\__main__.py --port {port}", port, True),
        (r"python.exe -m thomas serve --port 19110", port, False),
        (rf"python.exe -m thomas.server --port {port}0", port, False),
        (rf"python.exe -m http.server --port {port}", port, False),
        (r"python.exe -m thomas.server", port, False),  # no --port: only its socket says
        # A tray with no --port serves the tray's own default port, and only that one.
        (r"C:\x\pythonw.exe -m thomas.tray_agent", default, True),
        (r"C:\x\pythonw.exe -m thomas.tray_agent --no-tray", default, True),
        (r"pythonw.exe C:\r\thomas\tray_agent\__main__.py", default, True),
        (r"C:\x\pythonw.exe -m thomas.tray_agent", port, False),
        (rf"C:\x\pythonw.exe -m thomas.tray_agent --port {port}", default, False),
        (r"python.exe -m thomas.server", default, False),
    ]
    lines = [functions("Test-ThomasCommand", "Get-ThomasCommandPort", "Test-ThomasProcessOnPort")]
    for command_line, server_port, _expected in cases:
        lines.append(
            "Write-Output ('RESULT:' + "
            f"(Test-ThomasProcessOnPort -CommandLine '{command_line}' -ServerPort {server_port}))"
        )

    assert run_powershell(tmp_path, "\n".join(lines)) == [str(expected) for _c, _p, expected in cases]


def test_the_trays_own_default_port_is_the_one_the_launcher_assumes() -> None:
    entry = (ROOT / "thomas" / "tray_agent" / "__main__.py").read_text(encoding="utf-8")
    declared = re.search(r'"--port", type=int, default=(\d+)', entry)

    assert declared, "the tray entry point must declare a --port default"
    assert int(declared.group(1)) == script_default_port()
    # A tray command line with no --port counts as that port.
    assert re.search(rf"return {declared.group(1)}\b", functions("Get-ThomasCommandPort"))


@needs_powershell
def test_the_tray_icon_check_answers_false_instead_of_throwing_under_stop(tmp_path: Path) -> None:
    python = sys.executable.replace("'", "''")
    body = f"""
$ErrorActionPreference = 'Stop'
Write-Output ('RESULT:' + (Test-TrayIconPackages -Python '{python}' -Module 'no_such_module_for_the_tray_test'))
Write-Output ('RESULT:' + (Test-TrayIconPackages -Python '{python}' -Module 'json'))
Write-Output ('RESULT:' + $ErrorActionPreference)
"""

    # Windows PowerShell 5.1 turned the missing module's stderr into a terminating
    # error here, so the install and the "run headless" warning were never reached.
    assert run_powershell(tmp_path, functions("Test-TrayIconPackages") + body) == ["False", "True", "Stop"]


@needs_powershell
def test_a_failed_pip_install_is_reported_not_thrown(tmp_path: Path) -> None:
    python = sys.executable.replace("'", "''")
    body = f"""
$ErrorActionPreference = 'Stop'
$ok = Install-TrayIconPackages -Python '{python}' -Packages @('--no-index', 'no-such-package-for-the-tray-test')
Write-Output ('RESULT:' + $ok)
Write-Output ('RESULT:' + $ErrorActionPreference)
"""

    assert run_powershell(tmp_path, functions("Install-TrayIconPackages") + body) == ["False", "Stop"]


def test_the_starter_tells_you_when_the_tray_packages_did_not_install() -> None:
    source = script_source()

    # The inline probe (`& $VenvPy -c "import pystray..." 2>$null`) died under Stop.
    assert "import pystray; print" not in source
    assert "$TrayIconReady = Test-TrayIconPackages -Python $VenvPy" in source
    assert "Install-TrayIconPackages -Python $VenvPy" in source
    assert "run headless" in source
    # Only promise an icon when the packages are there.
    assert source.index("$TrayIconReady") < source.index("Tray icon will appear")


def test_status_md_no_longer_claims_the_tray_tools_are_registered() -> None:
    from thomas.server import tool_extensions

    status = STATUS.read_text(encoding="utf-8")

    assert not any("tray_agent" in path for path, _fn in tool_extensions._OPTIONAL_TOOL_MODULES)
    assert "tool_extensions.py:138" not in status
    assert "tray tools registered" not in status
    assert "no run-loop launcher" not in status
    assert "no entry-point launcher" not in status
    assert "retired" in status


def test_status_md_says_the_tray_is_opt_in_and_names_how_to_start_it() -> None:
    status = STATUS.read_text(encoding="utf-8")
    launcher = (ROOT / "scripts" / "run-ui.ps1").read_text(encoding="utf-8")

    # STATUS.md's "not the default" claim is only true while run-ui defaults to no tray.
    assert re.search(
        r"elseif\s*\(-not \$PSBoundParameters\.ContainsKey\('NoTray'\)\)\s*\{\s*\$NoTray\s*=\s*\$true", launcher
    )
    assert "Not the default" in status
    assert "run-ui.ps1 -Tray" in status
    assert "python -m thomas.tray_agent" in status


def test_status_md_says_what_was_never_run_live() -> None:
    status = STATUS.read_text(encoding="utf-8")
    field = re.search(r"^\| Status\s+\| (\w+)", status, re.M)

    # The status field uses the vocabulary in docs/STATUS_CONVENTION.md, where
    # "functional" means production-used and "wip" partly real, partly incomplete.
    assert field and field.group(1) in {"functional", "wip", "scaffold", "placeholder", "archived"}
    assert "have never been run here" in status  # the pystray icon and menu
    assert "only been tested against a mocked `schtasks`" in status
    if "have never been run here" in status:
        assert field.group(1) == "wip"


def test_status_md_does_not_present_the_administrator_claim_as_checked() -> None:
    status = STATUS.read_text(encoding="utf-8")
    changelog = (ROOT / "changelog.d" / "claude-tray-agent-says-what-it-did.md").read_text(encoding="utf-8")
    autostart = (ROOT / "thomas" / "tray_agent" / "autostart.py").read_text(encoding="utf-8")

    # Nothing here registered a task, so whether a logon trigger that names no user needs
    # administrator rights was expected, never seen. Public text must not assert it.
    assert "reserves for administrators" not in autostart
    assert "needs administrator rights)" not in changelog
    assert "expected" in status and "administrator" in status


def test_status_md_admits_the_tray_packages_are_undeclared_while_they_are() -> None:
    status = STATUS.read_text(encoding="utf-8").lower()
    declared = "pystray" in (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()

    assert ("not in `pyproject.toml`" in status) is (not declared)
