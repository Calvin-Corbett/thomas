"""First launch ran setup with ``-AutoInstallTools``: winget installs of Node.js and Ollama, and ``npm i -g @openai/codex``.

Nothing asked for that, the default profile (openai_codex) needs none of the three,
and from the installer's Thomas shortcut it ran in a hidden window. Now setup
runs without the flag unless ``-InstallTools`` or THOMAS_AUTO_INSTALL_TOOLS=1
asks for it, and the launcher says which it chose. These tests run the launcher's
own first-run function with ``powershell`` replaced by a function that records
its arguments, so no setup runs and nothing is installed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.launcher_powershell_support import RUN_UI, needs_windows_powershell, ps_path, run_functions

pytestmark = needs_windows_powershell

BASE_ARGS = ["-Easy", "-NoPrompt", "-SkipInstall", "-SkipDoctor"]

_BODY = """
$Root = {root}
$script:calls = @()
function powershell {{ $script:calls += ($args -join ' '); $global:LASTEXITCODE = 0 }}
function Case([string]$name, [bool]$tools, [string]$envValue, [bool]$noInstall, [bool]$done) {{
  $script:calls = @()
  $script:InstallTools = $tools
  $script:NoInstall = $noInstall
  $env:THOMAS_AUTO_INSTALL_TOOLS = $envValue
  $marker = Join-Path $Root 'runtime\\setup\\last_setup.txt'
  if ($done) {{ New-Item -ItemType Directory -Force -Path (Split-Path $marker) | Out-Null; 'x' | Out-File $marker }}
  elseif (Test-Path $marker) {{ Remove-Item $marker }}
  $said = Invoke-FirstRunQuickSetup 6>&1 | Out-String
  $name + '|calls=' + $script:calls.Count + '|' + ($script:calls -join ';') + '|' + ($said -replace '\\s+', ' ')
}}
Case 'default' $false '' $false $false
Case 'flag' $true '' $false $false
Case 'env' $false '1' $false $false
Case 'env off' $false '0' $false $false
Case 'already set up' $true '' $false $true
Case 'already set up, no flag' $false '' $false $true
Case 'no install' $true '' $true $false
"""


@pytest.fixture(scope="module")
def cases(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    work = tmp_path_factory.mktemp("first_run")
    (work / "scripts").mkdir()
    (work / "scripts" / "setup.ps1").write_text("# stand-in\n", encoding="utf-8")
    out = run_functions(RUN_UI, ["Invoke-FirstRunQuickSetup"], _BODY.format(root=ps_path(work)), work)
    got = {line.split("|", 1)[0]: line for line in out.splitlines() if "|calls=" in line}
    got["raw"] = out
    return got


def test_setup_is_not_given_the_tool_install_flag_by_default(cases: dict[str, str]) -> None:
    for name in ("default", "env off"):
        line = cases[name]
        assert "|calls=1|" in line, cases["raw"]
        assert "-AutoInstallTools" not in line, line
        assert all(arg in line for arg in BASE_ARGS), line
        assert "Not installing Node.js, the Codex CLI or Ollama" in line, line
        # What not installing costs: no Node.js means no desktop shell, and web tabs go blank on sites that refuse framing.
        assert "desktop shell is not installed, so web tabs stay blank" in line, line
        assert "run-ui with -InstallTools on a first launch" in line, line
        # And what setup still does without the flag when Node.js is already there.
        assert "runs npm install for the desktop shell if Node.js is already installed" in line, line


def test_the_flag_or_the_environment_variable_turns_tool_installs_on_and_says_so(cases: dict[str, str]) -> None:
    for name in ("flag", "env"):
        line = cases[name]
        assert "|calls=1|" in line, cases["raw"]
        assert "-AutoInstallTools" in line, line
        assert all(arg in line for arg in BASE_ARGS), line
        assert "Tool installs are on" in line, line


def test_setup_does_not_run_again_once_done_or_when_installs_are_skipped(cases: dict[str, str]) -> None:
    assert "|calls=0|" in cases["already set up"], cases["raw"]
    assert "|calls=0|" in cases["no install"], cases["raw"]


def test_the_flag_says_so_when_it_is_ignored_because_setup_already_ran(cases: dict[str, str]) -> None:
    assert "-InstallTools only applies to a first launch" in cases["already set up"], cases["raw"]
    assert "Run setup.cmd to install Node.js, the Codex CLI or Ollama" in cases["already set up"], cases["raw"]
    # No flag, nothing to explain.
    assert "InstallTools" not in cases["already set up, no flag"], cases["raw"]
