"""run-ui.ps1 wrote the ``thomas://`` handler into HKCU on every launch, and said nothing.

That re-pointed the handler at whichever checkout launched last and would replace
a handler some other program had registered. These tests run the launcher's own
registration function with the registry cmdlets replaced by functions that record
what they were asked to write, so nothing here reads or writes your registry.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.launcher_powershell_support import RUN_UI, needs_windows_powershell, ps_path, run_functions

pytestmark = needs_windows_powershell

FUNCTIONS = ["Get-CommandPathAny", "Ensure-ThomasProtocolRegistration"]

_PRELUDE = """
$script:writes = @()
$script:registered = $null
function New-Item { $script:writes += 'New-Item' }
function Set-Item { $script:writes += 'Set-Item' }
function Set-ItemProperty { $script:writes += 'Set-ItemProperty' }
# Every other way into the registry, so a later edit of the function under test cannot reach yours from here.
function New-ItemProperty { $script:writes += 'New-ItemProperty' }
function Remove-Item { $script:writes += 'Remove-Item' }
function Remove-ItemProperty { $script:writes += 'Remove-ItemProperty' }
function reg { $script:writes += 'reg' }
function Get-Item {
  if ($null -eq $script:registered) { return $null }
  $value = $script:registered
  $key = New-Object psobject
  $key | Add-Member -MemberType ScriptMethod -Name GetValue -Value ({ param($name) $value }.GetNewClosure())
  return $key
}
foreach ($name in 'New-Item', 'Set-Item', 'Set-ItemProperty', 'New-ItemProperty', 'Remove-Item', 'Remove-ItemProperty', 'reg', 'Get-Item') {
  if ((Get-Command $name).CommandType -ne 'Function') { throw ('the registry stand-in for ' + $name + ' is not in place') }
}
function Case([string]$name, $registered, [bool]$register, [bool]$skip) {
  $script:writes = @()
  $script:registered = $registered
  $script:RegisterProtocol = $register
  $script:NoProtocolHandler = $skip
  $said = Ensure-ThomasProtocolRegistration 6>&1 | Out-String
  $name + ': writes=' + $script:writes.Count + ' said=' + [int]($said -match 'thomas://')
}
"""


@pytest.fixture(scope="module")
def cases(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, str], str]:
    tmp_path = tmp_path_factory.mktemp("handler")
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "run-ui.ps1").write_text("# stand-in\n", encoding="utf-8")
    other = tmp_path / "other checkout" / "scripts"
    other.mkdir(parents=True)
    (other / "run-ui.ps1").write_text("# stand-in\n", encoding="utf-8")

    working = f'"powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "{other / "run-ui.ps1"}" -DeepLink "%1"'
    gone = '"powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "C:\\gone\\scripts\\run-ui.ps1" -DeepLink "%1"'
    foreign = '"C:\\Tools\\linkhandler.exe" "%1"'
    cases = [
        ("none registered", None, False, False),
        ("working copy registered", working, False, False),
        ("copy that no longer exists registered", gone, False, False),
        ("another program registered", foreign, False, False),
        ("working copy, -RegisterProtocol", working, True, False),
        ("none registered, -NoProtocolHandler", None, False, True),
    ]
    body = f"$Root = {ps_path(root)}\n" + _PRELUDE
    for name, registered, register, skip in cases:
        # The registered command holds quotes and backslashes: a here-string carries it as is.
        value = "$null" if registered is None else f"@'\n{registered}\n'@"
        body += f"Case '{name}' {value} ${str(register).lower()} ${str(skip).lower()}\n"
    out = run_functions(RUN_UI, FUNCTIONS, body, tmp_path)
    return {line.split(":", 1)[0]: line for line in out.splitlines() if ": writes=" in line}, out


def test_a_launch_writes_the_handler_only_when_it_is_missing_or_dangling(cases: tuple[dict[str, str], str]) -> None:
    got, out = cases

    # Missing, or registered to a copy whose script is gone: written, and the launcher says so.
    for name in ("none registered", "copy that no longer exists registered"):
        assert got[name].endswith("said=1") and "writes=0" not in got[name], out
    # A copy that still works, and another program's handler, are left alone, silently.
    for name in ("working copy registered", "another program registered"):
        assert got[name].endswith("writes=0 said=0"), out


def test_register_protocol_repoints_it_and_no_protocol_handler_never_writes(cases: tuple[dict[str, str], str]) -> None:
    got, out = cases

    assert got["working copy, -RegisterProtocol"].endswith("said=1"), out
    assert "writes=0" not in got["working copy, -RegisterProtocol"], out
    assert got["none registered, -NoProtocolHandler"].endswith("writes=0 said=0"), out
