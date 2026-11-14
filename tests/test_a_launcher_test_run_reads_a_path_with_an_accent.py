"""The launcher tests write a PowerShell script that holds the paths they use.

Windows PowerShell 5.1 reads a script with no byte-order mark as the ANSI code page,
not UTF-8, so a path with an accent in it (a Windows user name, say) reached the body
of the test as other characters and every test built on ``run_functions`` failed on
that machine. The harness is written with a byte-order mark. The launchers are not
run: the body only asks whether a folder exists.
"""

from __future__ import annotations

from pathlib import Path

from tests.launcher_powershell_support import RUN_UI, needs_windows_powershell, ps_path, run_functions


@needs_windows_powershell
def test_a_test_folder_with_an_accent_in_its_name_reaches_powershell_intact(tmp_path: Path) -> None:
    work = tmp_path / "Zoë Muñoz"
    work.mkdir()

    out = run_functions(RUN_UI, [], f"'found: ' + (Test-Path -LiteralPath {ps_path(work)})", work)

    assert "found: True" in out, out
