"""A Windows machine with no Python still has a ``python.exe``: the Microsoft Store alias.

It is a stub. Run with any arguments it prints an install hint and exits 9009. The
launcher took the first ``python`` on PATH as Python, so on a machine with none it
never reached the winget install and died creating the venv, in a hidden window,
with nothing on screen. These tests put a stub like that first on PATH and ask the
launcher's own functions what they make of it; nothing is installed and neither
launcher script runs. A Python is then taken at the version the project declares
(``requires-python = ">=3.10"``, no upper bound) and the launcher only looks for
one when ``.venv`` has to be made.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.launcher_powershell_support import (
    RUN_REPL,
    RUN_UI,
    needs_windows_powershell,
    ps_path,
    run_functions,
)

pytestmark = needs_windows_powershell

STUB = "@echo Python was not found; run without arguments to install from the Microsoft Store 1>&2\r\n@exit /b 9009\r\n"
PYTHON_312 = "@exit /b 0\r\n"
PYTHON_39 = "@exit /b 1\r\n"  # what the version probe exits when the interpreter is too old
# "py -3.12" and "py -3" answer; every other version flag is "No suitable Python runtime" (103).
PY_WITH_312 = '@if "%1"=="-3.12" exit /b 0\r\n@if "%1"=="-3" exit /b 0\r\n@exit /b 103\r\n'
PY_WITH_ONLY_THE_NEWEST = '@if "%1"=="-3" exit /b 0\r\n@exit /b 103\r\n'

RUN_UI_FUNCTIONS = [
    "Invoke-NativeCore",
    "Invoke-NativeQuiet",
    "Test-PythonRuns",
    "Find-SystemPython",
    "Ensure-SystemPython",
]
RUN_REPL_FUNCTIONS = ["Invoke-NativeQuiet", "Test-PythonRuns", "Find-SystemPython"]
# A real py launcher reachable from System32 would answer instead of the stand-ins.
PY_ON_PATH = "py-on-path"

_SEARCH = """
function Search([string]$name, [string[]]$dirs) {{
  $env:Path = ($dirs -join ';') + ';' + $env:SystemRoot + '\\System32'
  $found = Find-SystemPython
  $name + ': ' + $(if ($found) {{ $found.Kind + ' ' + $found.Path + ' ' + $found.Flag }} else {{ 'nothing' }})
}}
$env:Path = $env:SystemRoot + '\\System32'
if (Get-Command py -ErrorAction SilentlyContinue) {{ '{py_on_path}'; exit 0 }}
Search 'stub only' @({stub})
Search 'python behind the stub' @({stub}, {real})
Search 'python 3.9 only' @({old})
Search 'py with 3.12 and something newer' @({py_312})
Search 'py with only something newer' @({py_newest})
Search 'python behind a python.exe that will not start' @({broken}, {real})
"""

_ENSURE = """
$env:Path = {stub} + ';' + $env:SystemRoot + '\\System32'
$script:asked = @()
function Install-WithWinget {{
  param([string]$PackageId, [string]$DisplayName)
  $script:asked += $PackageId
  return $false
}}
$result = Ensure-SystemPython
'asked: ' + ($script:asked -join ',')
'result: ' + $(if ($result) {{ 'python' }} else {{ 'nothing' }})
"""


def _bin(root: Path, name: str, python_bat: str, exe: str = "python.bat") -> Path:
    folder = root / name
    folder.mkdir()
    (folder / exe).write_bytes(python_bat.encode("ascii"))
    return folder


@pytest.fixture(scope="module")
def searches(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    root = tmp_path_factory.mktemp("store_alias")
    stub = _bin(root, "WindowsApps", STUB)
    real = _bin(root, "Python312", PYTHON_312)
    old = _bin(root, "Python39", PYTHON_39)
    py_312 = _bin(root, "Launcher312", PY_WITH_312, "py.bat")
    py_newest = _bin(root, "LauncherNewest", PY_WITH_ONLY_THE_NEWEST, "py.bat")
    # A python.exe Windows refuses to run at all (here an empty file): starting it throws rather than exiting 1.
    broken = _bin(root, "Broken", "", "python.exe")
    search = _SEARCH.format(
        py_on_path=PY_ON_PATH,
        stub=ps_path(stub),
        broken=ps_path(broken),
        real=ps_path(real),
        old=ps_path(old),
        py_312=ps_path(py_312),
        py_newest=ps_path(py_newest),
    )

    got: dict[str, str] = {"real": str(real), "py_312": str(py_312), "py_newest": str(py_newest)}
    for script, names in ((RUN_UI, RUN_UI_FUNCTIONS), (RUN_REPL, RUN_REPL_FUNCTIONS)):
        out = run_functions(script, names, search, root)
        if PY_ON_PATH in out:
            pytest.skip("a real py launcher is reachable from System32 here; the stand-ins would not be consulted")
        got[script.stem] = out
    got["ensure"] = run_functions(RUN_UI, RUN_UI_FUNCTIONS, _ENSURE.format(stub=ps_path(stub)), root)
    return got


@pytest.mark.parametrize("script", ["run-ui", "run-repl"])
def test_the_store_stub_alone_is_not_python(searches: dict[str, str], script: str) -> None:
    assert "stub only: nothing" in searches[script], searches[script]


@pytest.mark.parametrize("script", ["run-ui", "run-repl"])
def test_a_working_python_behind_the_stub_is_found(searches: dict[str, str], script: str) -> None:
    assert f"python behind the stub: python {searches['real']}\\python.bat" in searches[script], searches[script]


@pytest.mark.parametrize("script", ["run-ui", "run-repl"])
def test_a_python_exe_that_will_not_even_start_is_skipped_not_fatal(searches: dict[str, str], script: str) -> None:
    """Starting it throws; the search has to treat that as "not Python" and carry on to the one behind it."""
    expected = f"python behind a python.exe that will not start: python {searches['real']}\\python.bat"
    assert expected in searches[script], searches[script]


@pytest.mark.parametrize("script", ["run-ui", "run-repl"])
def test_the_py_launcher_is_asked_for_a_tested_version_before_the_newest(searches: dict[str, str], script: str) -> None:
    # py -3 alone is whatever is newest, so 3.12 next to 3.14 must not come back as 3.14.
    assert f"py with 3.12 and something newer: py {searches['py_312']}\\py.bat -3.12" in searches[script], searches[
        script
    ]
    # With nothing else installed the newest is used rather than concluding there is no Python.
    assert f"py with only something newer: py {searches['py_newest']}\\py.bat -3\n" in searches[script] + "\n", (
        searches[script]
    )


def test_a_python_older_than_thomas_supports_is_not_taken(searches: dict[str, str]) -> None:
    assert "python 3.9 only: nothing" in searches["run-ui"], searches["run-ui"]


def test_with_only_the_stub_the_launcher_reaches_the_winget_install(searches: dict[str, str]) -> None:
    assert "asked: Python.Python.3.11,Python.Python.3.12" in searches["ensure"], searches["ensure"]
    assert "result: nothing" in searches["ensure"], searches["ensure"]


@pytest.mark.parametrize(
    ("script", "names"), [(RUN_UI, RUN_UI_FUNCTIONS), (RUN_REPL, RUN_REPL_FUNCTIONS)], ids=["run-ui", "run-repl"]
)
def test_looking_for_a_python_never_lets_the_py_launcher_install_one(
    tmp_path: Path, script: Path, names: list[str]
) -> None:
    """The Python install manager's py.exe installs a runtime it is asked for and lacks, when its switches allow.

    PYTHON_MANAGER_AUTOMATIC_INSTALL=0 is the off switch. PYTHON_MANAGER_CONFIRM=0 only
    skips the confirmation, so with install on it would install without asking: the probe
    must leave it exactly as it found it.
    """
    seen = tmp_path / "seen.txt"
    folder = tmp_path / "launcher"
    folder.mkdir()
    (folder / "py.bat").write_bytes(
        # The space before ">>" matters: "0>>" would redirect handle 0 instead of writing the file.
        f'@echo AUTO=%PYTHON_MANAGER_AUTOMATIC_INSTALL% CONFIRM=%PYTHON_MANAGER_CONFIRM% >> "{seen}"\r\n@exit /b 0\r\n'.encode()
    )
    probe = f"'probe ran: ' + (Test-PythonRuns -Path {ps_path(folder / 'py.bat')} -LauncherArgs @('-3.13'))\n"
    out = run_functions(
        script,
        names,
        "$env:PYTHON_MANAGER_AUTOMATIC_INSTALL = 'yes'\n"
        "$env:PYTHON_MANAGER_CONFIRM = 'ask'\n" + probe + f"'py saw: ' + (Get-Content -Raw {ps_path(seen)}).Trim()\n"
        "'after: ' + $env:PYTHON_MANAGER_AUTOMATIC_INSTALL + ' [' + $env:PYTHON_MANAGER_CONFIRM + ']'\n"
        "Remove-Item Env:PYTHON_MANAGER_AUTOMATIC_INSTALL\n"
        "Remove-Item Env:PYTHON_MANAGER_CONFIRM\n"
        + probe
        + "'left behind: [' + $env:PYTHON_MANAGER_AUTOMATIC_INSTALL + '] [' + $env:PYTHON_MANAGER_CONFIRM + ']'\n",
        tmp_path,
    )

    assert "probe ran: True" in out, out
    # The one switch is turned off for the probe; the other is not touched.
    assert "py saw: AUTO=0 CONFIRM=ask" in out, out
    # What was set before is put back, and what was not set is not left behind.
    assert "after: yes [ask]" in out, out
    assert "left behind: [] []" in out, out


def _version_probe(script: Path) -> str:
    match = re.search(r"\$probe = '([^']*)'", script.read_text(encoding="utf-8"))
    assert match, f"no version probe in {script.name}"
    return match.group(1)


@pytest.mark.parametrize("script", [RUN_UI, RUN_REPL], ids=["run-ui", "run-repl"])
@pytest.mark.parametrize(
    ("version", "accepted"),
    [((3, 9, 13), False), ((3, 10, 0), True), ((3, 13, 5), True), ((3, 14, 0), True), ((3, 15, 1), True)],
)
def test_the_version_check_follows_requires_python_with_no_upper_bound(
    script: Path, version: tuple[int, int, int], accepted: bool
) -> None:
    """Runs the launcher's own probe text under a pretended interpreter version."""
    probe = _version_probe(script)
    pretend = f"import sys; sys.version_info = {(*version, 'final', 0)!r}; "
    done = subprocess.run([sys.executable, "-c", probe.replace("import sys; ", pretend, 1)], capture_output=True)

    assert (done.returncode == 0) is accepted, (version, done.returncode, probe)


_VENV_SETUP = """
$Root = {root}
Set-Location $Root
$VenvRoot = Join-Path $Root '.venv'
function Ensure-SystemPython {{ $script:asked++; return $script:found }}
function Case([string]$name, $found) {{
  $script:found = $found; $script:asked = 0
  $result = Ensure-ThomasVenv
  $name + ': asked=' + $script:asked + ' result=' + $(if ($null -eq $result) {{ 'null' }} else {{ $result }})
}}
"""
# Stand-ins for "python -m venv .venv": they make the files that mean a venv exists, and print, as the real one can.
_MAKE_VENV = (
    "@echo made it %*\r\n"
    "@mkdir .venv\\Scripts >nul 2>&1\r\n"
    "@echo # > .venv\\pyvenv.cfg\r\n"
    "@echo # > .venv\\Scripts\\python.exe\r\n"
)


def _venv_run(tmp_path: Path, cases: str) -> str:
    (tmp_path / "python.bat").write_bytes(_MAKE_VENV.encode("ascii"))
    (tmp_path / "py.bat").write_bytes(_MAKE_VENV.encode("ascii"))
    body = _VENV_SETUP.format(root=ps_path(tmp_path)) + cases.format(
        python=ps_path(tmp_path / "python.bat"), py=ps_path(tmp_path / "py.bat")
    )
    return run_functions(RUN_UI, ["Test-VenvValid", "Ensure-ThomasVenv"], body, tmp_path)


def test_a_working_venv_never_asks_for_a_python_and_a_missing_one_asks_once(tmp_path: Path) -> None:
    out = _venv_run(
        tmp_path,
        "Case 'no venv and no python' $null\n"
        "Case 'python found' @{{ Kind = 'python'; Path = {python} }}\n"
        "Case 'already a venv' $null\n",
    )

    assert "no venv and no python: asked=1 result=2" in out, out
    assert "Python 3.10 or newer was not found" in out, out
    # What the venv tool prints stays out of the returned exit code.
    assert "python found: asked=1 result=null" in out, out
    assert "already a venv: asked=0 result=null" in out, out


def test_the_py_launcher_makes_the_venv_with_the_version_it_was_found_for(tmp_path: Path) -> None:
    out = _venv_run(tmp_path, "Case 'py found' @{{ Kind = 'py'; Path = {py}; Flag = '-3.12' }}\n")

    # The flag the launcher was found with, not a fixed -3.
    assert "made it -3.12 -m venv .venv" in out, out
    assert "py found: asked=1 result=null" in out, out


@pytest.mark.parametrize("script", [RUN_UI, RUN_REPL], ids=["run-ui", "run-repl"])
def test_neither_launcher_makes_a_venv_with_a_fixed_py_version_flag(script: Path) -> None:
    text = script.read_text(encoding="utf-8")

    assert "$SysPy.Flag -m venv .venv" in text
    assert "-3 -m venv" not in text
