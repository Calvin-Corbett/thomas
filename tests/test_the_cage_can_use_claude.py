"""The caged Thomas runs on your Claude plan, through a Claude sign-in of its own (Task 2j).

You chose on a card: "Switch Thomas to Claude now", then "Yes, set it up". The
setup script (scripts/cage/enable_cage_claude.ps1) makes the cage's Claude folder and
copies the CLI and the sign-in wrapper (scripts/cage/cage_claude_sign_in.ps1) beside
it; caged_server.py finds them at start. These tests use a temp folder in place of
C:\\ProgramData\\ThomasCage, never run either script and never start the CLI: its
process is a stub that records what it was given.
"""

from __future__ import annotations

import asyncio
import importlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator
from functools import partial
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import mock

import pytest
from scripts.cage import caged_server, egress_proxy

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "cage" / "enable_cage_claude.ps1"
WRAPPER = REPO / "scripts" / "cage" / "cage_claude_sign_in.ps1"
ICACLS = r"C:\Windows\System32\icacls.exe"
# Everything caged_server.main writes into the environment, so each test gets it back.
_SET_BY_MAIN = (
    "THOMAS_OWNER_DESK",
    "CODEX_HOME",
    "THOMAS_OWNED_ROOT",
    "THOMAS_MEMORY_ROOT",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
    "THOMAS_SEARCH_BROKER",
    "CLAUDE_CONFIG_DIR",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
    "THOMAS_RUN_CHANNEL_URL",
    "THOMAS_CODE_RUN_ID",
    "THOMAS_RUN_CHANNEL_TOKEN",
)


def _cage(tmp_path: Path, *, with_sign_in_folder: bool = True) -> Path:
    """A stand-in for C:\\ProgramData\\ThomasCage after the setup script ran."""
    root = tmp_path / "ProgramData" / "ThomasCage"
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "claude.exe").write_bytes(b"")
    if with_sign_in_folder:
        (root / "claude").mkdir()
    return root


@pytest.fixture
def no_claude_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A PATH with no Claude on it, as the cage account has today."""
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.chdir(empty)  # shutil.which also looks in the working folder on Windows
    return empty


@pytest.fixture
def start_caged_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_claude_path: Path
) -> Iterator[Callable[..., dict[str, str]]]:
    """Run caged_server.main with the server itself stubbed; returns the environment it started with.

    main() writes the process environment, and monkeypatch.delenv records nothing for a
    key that was absent, so the whole environment is put back when the test ends.
    """
    cli = importlib.import_module("thomas.cli.main")  # the copy caged_server.main calls, from sys.modules

    for key in _SET_BY_MAIN:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(egress_proxy, "DEFAULT_PIN_ROOT", tmp_path / "no-pins")
    monkeypatch.setattr(sys, "argv", list(sys.argv))
    monkeypatch.setattr(sys, "path", list(sys.path))
    seen: dict[str, str] = {}
    monkeypatch.setattr(cli, "main", lambda: seen.update(os.environ))

    def start(cage_root: Path, *argv: str) -> dict[str, str]:
        monkeypatch.setattr(caged_server, "CAGE_ROOT", cage_root)
        assert caged_server.main(["--port", "0", *argv]) == 0
        return dict(seen)

    with mock.patch.dict(os.environ):
        yield start


@pytest.fixture
def another_copy_of_the_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """What a test leaves that re-imports a module and puts back only sys.modules: two copies of thomas.cli.main.

    `import a.b as x` reads one and `from a.b import y` the other, so a stub could miss and the real server start
    inside the test, measured 2026-10-31, until it was killed 15 minutes later. If it misses again, this ends it at once.
    """
    import thomas.server.app as app

    importlib.import_module("thomas.cli.main")
    copy = ModuleType("thomas.cli.main")
    copy.main = None
    monkeypatch.setattr(sys.modules["thomas.cli"], "main", copy)
    monkeypatch.setattr(app, "serve", mock.Mock(side_effect=AssertionError("the real server started")))


def test_the_stub_lands_on_the_cli_the_caged_server_calls(
    another_copy_of_the_cli: None, tmp_path: Path, start_caged_server: Callable[..., dict[str, str]]
) -> None:
    assert start_caged_server(_cage(tmp_path))


def test_the_caged_server_points_the_cli_at_the_cages_own_sign_in(
    tmp_path: Path, start_caged_server: Callable[..., dict[str, str]], no_claude_path: Path
) -> None:
    root = _cage(tmp_path)
    codex_home = tmp_path / "you" / ".codex"

    env = start_caged_server(root, "--codex-home", str(codex_home))

    assert env["CLAUDE_CONFIG_DIR"] == str(root / "claude")
    assert env["PATH"].split(os.pathsep) == [str(root / "bin"), str(no_claude_path)]
    assert env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    # The ChatGPT side is exactly as before.
    assert env["CODEX_HOME"] == str(codex_home)
    assert env["THOMAS_OWNED_ROOT"] == str(tmp_path / "you" / ".thomas")


def test_without_the_sign_in_folder_nothing_about_claude_changes(
    tmp_path: Path, start_caged_server: Callable[..., dict[str, str]], no_claude_path: Path
) -> None:
    root = _cage(tmp_path, with_sign_in_folder=False)
    codex_home = tmp_path / "you" / ".codex"

    env = start_caged_server(root, "--codex-home", str(codex_home))

    assert "CLAUDE_CONFIG_DIR" not in env
    assert "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC" not in env
    assert env["PATH"] == str(no_claude_path)
    assert env["CODEX_HOME"] == str(codex_home)
    assert env["THOMAS_OWNED_ROOT"] == str(tmp_path / "you" / ".thomas")


def test_the_model_list_finds_the_cages_claude(tmp_path: Path, no_claude_path: Path) -> None:
    from thomas.models.sources.claude_cli import list_claude_cli_models

    root = _cage(tmp_path)
    before = list_claude_cli_models(which=partial(shutil.which, path=str(no_claude_path)))
    assert not before.ok and "no Claude CLI" in before.error

    env = caged_server.claude_env(root, path=str(no_claude_path))
    answer = list_claude_cli_models(which=partial(shutil.which, path=env["PATH"]))

    assert answer.ok, answer.error
    assert [model.id for model in answer.models] == ["opus", "sonnet", "haiku"]


def test_the_anthropic_connection_lists_claude_in_the_caged_server(
    tmp_path: Path, start_caged_server: Callable[..., dict[str, str]]
) -> None:
    """The catalog's own reader, for the keyless anthropic profile, on the PATH the caged server set."""
    from thomas.core.config import ModelConfig
    from thomas.models.sources import list_profile_models

    start_caged_server(_cage(tmp_path))
    answer = asyncio.run(list_profile_models("anthropic", ModelConfig(name="anthropic", provider="anthropic")))

    assert (answer.ok, answer.source) == (True, "claude-cli"), answer.error


class _RecordedCli:
    """Stands in for the Claude CLI process: records its command and environment, answers once."""

    calls: list[tuple[list[str], dict[str, Any]]] = []

    def __init__(self, cmd: list[str], **kwargs: Any) -> None:
        _RecordedCli.calls.append((list(cmd), kwargs))
        result = {"type": "result", "subtype": "success", "is_error": False, "result": "Hello from the cage."}
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO((json.dumps(result) + "\n").encode("utf-8"))
        self.returncode = 0
        self.pid = 4242

    def poll(self) -> int:
        return 0

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        return None


class _NoJob:
    def __init__(self, proc: Any) -> None:
        self.proc = proc

    def close(self) -> None:
        return None


def test_builds_claude_run_uses_the_cages_sign_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, start_caged_server: Callable[..., dict[str, str]]
) -> None:
    from thomas.forge.anvil import dispatch_claude_cli, forge_code_git, windows_job

    root = _cage(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    start_caged_server(root)  # the environment the caged server leaves for everything it starts
    _RecordedCli.calls = []
    monkeypatch.setattr(subprocess, "Popen", _RecordedCli)
    monkeypatch.setattr(windows_job, "OwnedWindowsJob", _NoJob)
    monkeypatch.setattr(dispatch_claude_cli, "emergency_stop_active", lambda: False)
    monkeypatch.setattr(forge_code_git, "snapshot", lambda cwd, **kwargs: {})
    monkeypatch.setattr(forge_code_git, "project_delta_since", lambda cwd, snapshot: [])

    result = dispatch_claude_cli.dispatch_via_claude_cli(
        "say hello", cwd=project, definition="a greeting", dry_run=False, verify=False, model="opus"
    )

    assert result.ok, result.reason
    assert result.reply == "Hello from the cage."
    [(cmd, kwargs)] = _RecordedCli.calls
    assert Path(cmd[0]).parent == root / "bin" and Path(cmd[0]).name.lower() == "claude.exe"
    assert cmd[cmd.index("--model") + 1] == "opus"
    env = kwargs["env"]
    assert env["CLAUDE_CONFIG_DIR"] == str(root / "claude")
    assert env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"


def test_the_fence_lets_the_cli_keep_its_sign_in_fresh() -> None:
    """Measured 2026-09-24 with no real sign-in: an expired one sends the CLI to platform.claude.com."""
    allow = egress_proxy.load_allowlist(REPO / "scripts" / "cage")

    assert egress_proxy.host_allowed("platform.claude.com", allow)
    assert egress_proxy.host_allowed("api.anthropic.com", allow)
    # Only what the refresh and the model need: sign-in happens in your browser, and the
    # CLI's updates, telemetry and connectors stay outside the fence.
    for host in ("claude.ai", "downloads.claude.ai", "statsig.anthropic.com", "mcp-proxy.anthropic.com"):
        assert not egress_proxy.host_allowed(host, allow), host
    # The fence works per host: the comment says the whole host is reachable, not one path.
    text = (REPO / "scripts" / "cage" / "egress.allow").read_text(encoding="utf-8")
    assert "the whole platform.claude.com host" in text


def _ascii(path: Path) -> str:
    raw = path.read_bytes()
    assert raw.isascii(), f"{path.name}: Windows PowerShell reads a file with no BOM as ANSI"
    return raw.decode("ascii")


def _code(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.lstrip().startswith("#")]


def _line_with(text: str, needle: str) -> str:
    [line] = [line for line in _code(text) if needle in line]
    return line


def _first(text: str, needle: str) -> int:
    return next(number for number, line in enumerate(_code(text)) if needle in line)


def test_the_setup_script_never_runs_the_cli_against_the_cages_folder() -> None:
    text = _ascii(SCRIPT)
    code = "\n".join(_code(text))

    assert "[Security.Principal.WindowsBuiltInRole]::Administrator" in text and 'throw "not elevated"' in text
    assert f'[string]$CageRoot = "{caged_server.CAGE_ROOT}"' in text
    assert '$configDir = Join-Path $CageRoot "claude"' in text
    assert '$binDir = Join-Path $CageRoot "bin"' in text
    # No CLI run and no CLAUDE_CONFIG_DIR anywhere: the grant below is never followed by
    # a sign-in against the folder the cage can write.
    assert "CLAUDE_CONFIG_DIR" not in code and "auth login" not in code
    assert "& $target" not in code and "& $ClaudeExe" not in code

    # The config folder: inheritance off; you, SYSTEM and Administrators full; the cage
    # Modify, set only while the folder is new, and read back every time.
    folder = _line_with(text, 'Invoke-Icacls @($configDir, "/inheritance:r"')
    for grant in (
        '"*${ownerSid}:(OI)(CI)F"',
        '"*S-1-5-18:(OI)(CI)F"',
        '"*S-1-5-32-544:(OI)(CI)F"',
        '"*${agentSid}:(OI)(CI)M"',
    ):
        assert grant in folder, grant
    assert _first(text, "if ($configIsNew) {") + 1 == _first(text, 'Invoke-Icacls @($configDir, "/inheritance:r"')
    assert "Assert-FolderAcl $configDir @($ownerSid, $agentSid, 'S-1-5-18', 'S-1-5-32-544')" in text

    # The CLI's folder: owned by Administrators; the cage may read and run, never change
    # what it runs, and that is read back.
    binary = _line_with(text, 'Invoke-Icacls @($binDir, "/inheritance:r"')
    assert '"*${agentSid}:(OI)(CI)RX"' in binary
    assert "${agentSid}:(OI)(CI)M" not in binary and "${agentSid}:(OI)(CI)F" not in binary
    assert 'Invoke-Icacls @($binDir, "/setowner", "*S-1-5-32-544")' in text
    assert "Assert-FolderAcl $binDir @('S-1-5-18', 'S-1-5-32-544', $ownerSid, $agentSid) $agentSid" in text
    assert '-Filter "claude.exe.new-*"' in text


def test_the_setup_script_checks_links_and_the_signature_before_it_trusts_anything() -> None:
    text = _ascii(SCRIPT)

    # Links refused before the first folder is made or any permission is set.
    first_change = min(_first(text, "New-Item -ItemType Directory"), _first(text, "Invoke-Icacls @("))
    assert _first(text, "if (Test-Link $CageRoot) { throw") < first_change
    assert _first(text, "[IO.FileAttributes]::ReparsePoint }") < first_change
    # The copy: your claude.exe, byte for byte, signed by Anthropic; never your .claude folder.
    assert '$ClaudeExe = Join-Path $env:USERPROFILE ".local\\bin\\claude.exe"' in text
    assert "Copy-Item -LiteralPath $ClaudeExe -Destination $staged" in text
    assert "Get-FileHash -LiteralPath $staged" in text
    assert "Get-AuthenticodeSignature -LiteralPath $staged" in text
    assert "$signature.Status -eq 'Valid'" in text
    assert "$signature.SignerCertificate.Subject.StartsWith('CN=\"Anthropic, PBC\"')" in text
    assert "VersionInfo.ProductVersion" in text
    assert ".claude\\" not in text and '".claude"' not in text
    # The allow-list: every changed host line is shown before the pin is written.
    assert '. (Join-Path $scriptDir "pin_folder.ps1")' in text
    pin = _first(text, 'Write-PinFile -PinRoot $PinRoot -Name "egress.allow" -Value $allow')
    assert _first(text, '"  allow-list adds: $name"') < pin and _first(text, '"  allow-list removes: $name"') < pin


def test_the_setup_script_installs_the_wrapper_and_asks_for_a_sign_in_only_when_there_is_none() -> None:
    text = _ascii(SCRIPT)

    assert '$wrapperSource = Join-Path $scriptDir "cage_claude_sign_in.ps1"' in text
    assert '$wrapper = Join-Path $binDir "sign-in.ps1"' in text
    assert "Copy-Item -LiteralPath $wrapperSource -Destination $wrapper -Force" in text
    assert 'Invoke-Icacls @($wrapper, "/reset")' in text
    assert '$credentials = Join-Path $configDir ".credentials.json"' in text
    assert "$step = 'powershell -NoProfile -ExecutionPolicy Bypass -File \"{0}\"' -f $wrapper" in text
    ask = _first(text, "if (Test-Path -LiteralPath $credentials) {")
    assert "RESULT: CLI updated; no sign-in needed" in _code(text)[ask + 1]
    assert _first(text, "RESULT: ready for your sign-in") > ask


def test_the_wrapper_signs_in_in_a_folder_only_you_can_reach_and_moves_the_sign_in_across() -> None:
    text = _ascii(WRAPPER)
    code = "\n".join(_code(text))

    assert f'[string]$CageRoot = "{caged_server.CAGE_ROOT}"' in text
    # It refuses to run elevated.
    refuse = _first(text, "if ((New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole(")
    assert "[Security.Principal.WindowsBuiltInRole]::Administrator" in _code(text)[refuse + 1]
    assert 'throw "this window is elevated' in _code(text)[refuse + 2]
    # Its folder: new, under your LOCALAPPDATA\Temp, inheritance off, only your SID.
    assert '$temp = Join-Path $env:LOCALAPPDATA ("Temp\\thomas-cage-signin-" + [guid]::NewGuid().ToString("N"))' in text
    assert 'Invoke-Icacls @($temp, "/inheritance:r", "/grant:r", "*${mySid}:(OI)(CI)F")' in text
    # The sign-in runs in a child: only its environment holds CLAUDE_CONFIG_DIR, and only
    # ever pointed at that folder.
    assert "New-Object System.Diagnostics.ProcessStartInfo" in text
    assert "$start.UseShellExecute = $false" in text
    assert '$start.Arguments = "auth login --claudeai"' in text
    assert [line.strip() for line in _code(text) if "CLAUDE_CONFIG_DIR" in line] == [
        '$start.EnvironmentVariables["CLAUDE_CONFIG_DIR"] = $temp'
    ]
    assert "$env:CLAUDE_CONFIG_DIR" not in code
    # It uses the admin-owned copy, checked like the setup script checks it.
    assert '$claude = Join-Path $binDir "claude.exe"' in text
    assert "Get-AuthenticodeSignature -LiteralPath $claude" in text
    assert "[IO.FileAttributes]::ReparsePoint" in text
    # The move, the link check again, then the reset to the cage folder's permissions,
    # then the check from the ACL.
    move = _first(text, "[System.IO.File]::Move($fresh, $destination)")
    assert _code(text)[move + 1].strip() == "Assert-NotLink @($CageRoot, $configDir, $destination)"
    assert _first(text, 'Invoke-Icacls @($destination, "/reset")') == move + 2
    assert _first(text, "[Security.AccessControl.FileSystemRights]::Modify") > move
    # Its contents are never read, printed or copied, and the folder always goes.
    for reader in (
        "Get-Content",
        "ReadAll",
        "Get-FileHash",
        "Copy-Item",
        "Select-String",
        "accessToken",
        "refreshToken",
    ):
        assert reader not in code, reader
    assert _first(text, "finally {") < _first(text, "[System.IO.Directory]::Delete($temp, $true)")


# Every step that deletes, moves, overwrites or resets a file in the cage's folders:
# (pattern, the item it acts on).
_ACTS = (
    (re.compile(r"Remove-Item -LiteralPath (\S+)"), 1),
    (re.compile(r"Move-Item -LiteralPath (\S+)"), 1),
    (re.compile(r"\[System\.IO\.File\]::Delete\((\$\w+)\)"), 1),
    (re.compile(r"\[System\.IO\.File\]::Move\((\$\w+), (\$\w+)\)"), 2),
    (re.compile(r"Copy-Item -LiteralPath \$wrapperSource -Destination (\$\w+)"), 1),
    (re.compile(r'Invoke-Icacls @\((\$\w+), "/reset"\)'), 1),
)


@pytest.mark.parametrize(("script", "folder", "steps"), [(SCRIPT, "$binDir", 8), (WRAPPER, "$configDir", 4)])
def test_each_delete_move_and_reset_checks_for_links_again_right_before_it(
    script: Path, folder: str, steps: int
) -> None:
    # A check at the start proves nothing about a folder the cage can write by the
    # time the step runs: ThomasCage, the folder and the item are checked again, on
    # the line before.
    code = _code(_ascii(script))
    seen = 0
    for number, line in enumerate(code):
        for pattern, group in _ACTS:
            found = pattern.search(line)
            if not found:
                continue
            seen += 1
            check = code[number - 1].strip()
            assert check.startswith("Assert-NotLink @("), (script.name, line.strip(), check)
            for needed in ("$CageRoot", folder, found.group(group)):
                assert needed in check, (script.name, line.strip(), needed)
    assert seen == steps, (script.name, seen)


def test_both_scripts_run_icacls_by_its_full_path() -> None:
    # A folder every signed-in account can write sits on PATH on this machine.
    for script in (SCRIPT, WRAPPER):
        text = _ascii(script)
        assert '$icacls = "C:\\Windows\\System32\\icacls.exe"' in text, script.name
        assert "& $icacls @IcaclsArgs /Q 2>$null | Out-Null" in text, script.name
        bare = [line for line in _code(text) if re.search(r"(^|[&|;(]\s*)icacls(\.exe)?\s", line.strip())]
        assert bare == [], (script.name, bare)


def test_the_elevated_script_deletes_nothing_in_the_cages_folder() -> None:
    # The cage can write claude\, and elevated code never deletes through a folder the
    # cage can write: the settings clean-up is gone, and the header no longer claims it.
    text = _ascii(SCRIPT)
    code = _code(text)

    assert "settings.json" not in text and "cowork_settings.json" not in text
    assert not any("[System.IO.File]::Delete(" in line for line in code)
    acted_on = {
        found.group(1)
        for line in code
        for pattern in (re.compile(r"Remove-Item -LiteralPath (\S+)"), re.compile(r"Move-Item -LiteralPath (\S+)"))
        if (found := pattern.search(line))
    }
    assert acted_on == {"$leftover.FullName", "$staged", "$target", "$old.FullName"}  # all in bin\
    assert "Nothing inside the cage's claude\\ folder is deleted or changed here." in text


@pytest.mark.skipif(os.name != "nt", reason="junctions, ACLs and PowerShell")
def test_the_link_checks_refuse_a_junction_and_name_what_they_cannot_read(tmp_path: Path) -> None:
    """The scripts' own check functions, run by PowerShell on a temp folder; neither script is run."""
    cage = tmp_path / "ThomasCage"
    claude = cage / "claude"
    (claude / "projects").mkdir(parents=True)
    (claude / "plain.json").write_text("{}", encoding="utf-8")
    elsewhere, gone = tmp_path / "your-files", tmp_path / "gone"
    elsewhere.mkdir()
    gone.mkdir()
    junction, dangling = claude / "projects" / "escape", cage / "dangling"
    unreadable_cage = tmp_path / "ThomasCage2"
    locked = unreadable_cage / "claude" / "made-by-the-cage"
    locked.mkdir(parents=True)
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for link, target in ((junction, elsewhere), (dangling, gone)):
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    gone.rmdir()
    subprocess.run([ICACLS, str(locked), "/inheritance:r", "/Q"], check=True, capture_output=True)
    try:
        said = {}
        for script in (SCRIPT, WRAPPER):
            said[script.name] = _run_functions(
                script,
                f"""
                Try-It 'plain file and a missing one' {{ Assert-NotLink @('{claude / "plain.json"}', '{claude / "none"}') }}
                Try-It 'junction' {{ Assert-NotLink @('{cage}', '{claude}', '{junction}') }}
                Try-It 'dangling junction' {{ Assert-NotLink @('{dangling}') }}
                if (Get-Command Assert-NoLinkInside -ErrorAction SilentlyContinue) {{
                    Try-It 'scan with a junction inside' {{ Assert-NoLinkInside '{claude}' }}
                    Try-It 'scan past an unreadable folder' {{ Assert-NoLinkInside '{unreadable_cage / "claude"}' }}
                }}
                """,
            )
    finally:
        subprocess.run([ICACLS, str(locked), "/reset", "/Q"], capture_output=True, creationflags=no_window)
        for link in (junction, dangling):
            os.rmdir(link)  # the junction itself, never what it points to

    for name, out in said.items():
        assert "plain file and a missing one: passed" in out, (name, out)
        assert f"junction: refused: {junction} is a junction or link; stopping" in out, (name, out)
        assert f"dangling junction: refused: {dangling} is a junction or link; stopping" in out, (name, out)
    elevated = said[SCRIPT.name]
    assert f"scan with a junction inside: refused: links inside {claude}, nothing was changed: {junction}" in elevated
    refusal = next(
        line for line in elevated.splitlines() if line.startswith("scan past an unreadable folder: refused:")
    )
    assert f"the link check cannot read {locked}" in refusal, refusal
    assert "nothing was changed" in refusal and f'Rename-Item -LiteralPath "{unreadable_cage / "claude"}"' in refusal
    assert elsewhere.is_dir(), "a check followed the junction"


def _run_functions(script: Path, body: str) -> str:
    """Define the script's own functions from its parsed text, then run *body* with them."""
    command = (
        "$ErrorActionPreference = 'Stop'; $tokens = $null; $errors = $null; "
        f"$ast = [System.Management.Automation.Language.Parser]::ParseFile('{script}', [ref]$tokens, [ref]$errors); "
        "foreach ($fn in $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) "
        "{ . ([scriptblock]::Create($fn.Extent.Text)) }; "
        "function Try-It([string]$Label, [scriptblock]$Block) "
        '{ try { & $Block | Out-Null; "${Label}: passed" } catch { "${Label}: refused: $($_.Exception.Message)" } }; '
        + body
    )
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return out.stdout + out.stderr


@pytest.mark.skipif(os.name != "nt", reason="PowerShell's own parser")
def test_the_setup_script_and_the_wrapper_both_parse() -> None:
    """Windows PowerShell's own parser, on both files; neither is run."""
    for script in (SCRIPT, WRAPPER):
        assert script.is_file(), script
        parse = (
            "$tokens = $null; $errors = $null; "
            f"[System.Management.Automation.Language.Parser]::ParseFile('{script}', [ref]$tokens, [ref]$errors) "
            "| Out-Null; $errors | ForEach-Object { $_.Message }; 'errors:' + $errors.Count"
        )
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", parse],
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        assert out.stdout.strip().endswith("errors:0"), (script.name, out.stdout + out.stderr)
