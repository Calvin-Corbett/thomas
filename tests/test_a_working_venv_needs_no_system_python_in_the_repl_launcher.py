"""run-repl.ps1 looks for a system Python only when ``.venv`` has to be made.

A machine can have a working ``.venv`` and no Python on PATH (the venv carries its own
interpreter). The launcher used to refuse such a machine; a probe for a system Python
that runs first would do so again. run-ui.ps1's version of this is tested next door
through ``Ensure-ThomasVenv``; run-repl.ps1 keeps the step at the top level of the
script, so these tests run just those statements, with ``Find-SystemPython`` replaced
by a function that says it was asked and finds nothing. The REPL is never started.
"""

from __future__ import annotations

from pathlib import Path

from tests.launcher_powershell_support import RUN_REPL, needs_windows_powershell, ps_path, run_functions

pytestmark = needs_windows_powershell

_BODY = """
$Root = {root}
$NoInstall = $true
function Find-SystemPython {{ Write-Host 'ASKED FOR A SYSTEM PYTHON'; return $null }}
'statements: ' + $topLevel.Count
foreach ($s in $topLevel) {{ . ([scriptblock]::Create($s)) }}
'went on'
"""


def _run(root: Path, tmp_path: Path) -> str:
    return run_functions(
        RUN_REPL,
        [],
        _BODY.format(root=ps_path(root)),
        tmp_path,
        # The venv step only: the statements after it install packages and start the REPL. Any
        # other top-level statement that looks for a Python is part of the step and is run too.
        top_level=("$VenvPy = Join-Path", "Test-Path $VenvPy", "Find-SystemPython"),
    )


def test_a_working_venv_never_asks_for_a_system_python(tmp_path: Path) -> None:
    root = tmp_path / "with venv"
    (root / ".venv" / "Scripts").mkdir(parents=True)
    (root / ".venv" / "Scripts" / "python.exe").write_bytes(b"")

    out = _run(root, tmp_path)

    assert "statements: 2" in out and "went on" in out, out
    assert "ASKED FOR A SYSTEM PYTHON" not in out and "ERROR" not in out, out


def test_no_venv_asks_once_and_says_what_to_install_when_there_is_none(tmp_path: Path) -> None:
    root = tmp_path / "without venv"
    root.mkdir()

    out = _run(root, tmp_path)

    assert out.count("ASKED FOR A SYSTEM PYTHON") == 1, out
    assert "Python 3.10 or newer was not found" in out and "went on" not in out, out
