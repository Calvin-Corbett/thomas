"""repair.ps1 asks before it moves a database, and leaves everything alone on a no.

The script cannot be run in a test: it installs tools and rewrites the venv. Its consent, data-check and final-verdict
functions can. This test parses scripts/repair.ps1 with PowerShell's own parser, pulls out Read-Consent,
Resolve-InstallTools, Test-RepairOk, Invoke-VenvPython and Invoke-DataCheck, and runs them in a real powershell.exe
against scratch folders. A stub stands in for the venv python; it runs the real `bootdoctor check` code without
probing any port.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
REPAIR = ROOT / "scripts" / "repair.ps1"
POWERSHELL = shutil.which("powershell")

pytestmark = pytest.mark.skipif(
    os.name != "nt" or POWERSHELL is None, reason="repair.ps1 is a Windows PowerShell script"
)

HARNESS = r"""
param([string]$Repair, [string]$Spec, [string]$Out, [switch]$RealReadHost)
$ErrorActionPreference = "Stop"
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Repair, [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) { throw "repair.ps1 does not parse" }
$isFunction = [Func[System.Management.Automation.Language.Ast, bool]]{
  param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $script:want
}
foreach ($script:want in "Read-Consent", "Resolve-InstallTools", "Test-RepairOk", "Invoke-VenvPython", "Invoke-DataCheck") {
  $fn = $ast.Find($isFunction, $true)
  if (-not $fn) { throw "repair.ps1 has no function $script:want" }
  Invoke-Expression $fn.Extent.Text
}
if (-not $RealReadHost) {
  # What the person types. Read-Host is a cmdlet, so a function of the same name takes its place.
  function Read-Host { param($Prompt) $script:asked += $Prompt; return $script:answer }
}
$results = @()
$cases = Get-Content $Spec -Raw | ConvertFrom-Json
foreach ($case in $cases) {
  $script:asked = @()
  $script:answer = [string]$case.answer
  $NoPrompt = [bool]$case.no_prompt
  $QuarantineCorrupt = [bool]$case.quarantine
  $Root = [string]$case.root
  $venvPy = [string]$case.py
  $script:lines = @()
  $script:DataExit = 0
  Write-Host ("### " + $case.name)
  $consent = $null
  $verdict = $null
  if ($case.kind -eq "consent") {
    $consent = Read-Consent "Question?"
  } elseif ($case.kind -eq "install") {
    $consent = Resolve-InstallTools -Never ([bool]$case.never) -Always ([bool]$case.always) -Unattended $NoPrompt
  } elseif ($case.kind -eq "ok") {
    $verdict = Test-RepairOk -SetupExit $case.setup -DataExit $case.data -DoctorExit $case.doctor -SkipDoctor ([bool]$case.skip_doctor)
  } else {
    Invoke-DataCheck
  }
  $results += [pscustomobject]@{
    name = $case.name; consent = $consent; ok = $verdict; data_exit = $script:DataExit; asked = @($script:asked).Count
  }
}
$json = ConvertTo-Json -InputObject @($results) -Depth 4
[System.IO.File]::WriteAllText($Out, $json, (New-Object System.Text.UTF8Encoding $false))
"""

STUB = """
import os, sys
from pathlib import Path
sys.path.insert(0, {repo!r})
from thomas.bootdoctor.check_command import run_check

args = sys.argv[1:]
assert args[:3] == ["-m", "thomas.bootdoctor", "check"], args
root = Path(args[args.index("--root") + 1])
quarantine = "--quarantine" in args
if quarantine and os.environ.get("STUB_THOMAS_RUNNING") == "1":
    print("[bootdoctor] runtime detected on 127.0.0.1:22057; refusing activation without --force.")
    raise SystemExit(2)
raise SystemExit(run_check(root=root, memory_root=root, quarantine=quarantine))
"""


def _database(root: Path, *, damaged: bool) -> Path:
    path = root / ".thomas" / "runs.sqlite3"
    path.parent.mkdir(parents=True)
    if damaged:
        path.write_bytes(b"not a database, only text padding" * 4)
    else:
        con = sqlite3.connect(path)
        con.execute("create table t (x)")
        con.commit()
        con.close()
    return path


def _cmd(path: Path, stub: Path, *, running: bool = False) -> Path:
    lines = ["@echo off", "set STUB_THOMAS_RUNNING=1" if running else "rem", f'"{sys.executable}" "{stub}" %*']
    path.write_text("\r\n".join([*lines, "exit /b %ERRORLEVEL%", ""]), encoding="ascii")
    return path


def _run_harness(tmp_path: Path, cases: list[dict], *, headless: bool = False) -> tuple[dict[str, dict], str]:
    harness = tmp_path / "harness.ps1"
    harness.write_text(HARNESS, encoding="ascii")
    spec, out = tmp_path / "spec.json", tmp_path / "out.json"
    spec.write_text(json.dumps(cases), encoding="utf-8")
    out.unlink(missing_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("THOMAS_")}
    env["THOMAS_DATA_DIR"] = str(tmp_path / "data")
    env["PYTHONPATH"] = str(ROOT)
    # Headless: PowerShell itself is non-interactive, so the real Read-Host throws instead of asking.
    shell_flags = ["-NonInteractive"] if headless else []
    script_flags = ["-RealReadHost"] if headless else []
    done = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", *shell_flags, "-File", str(harness)]
        + ["-Repair", str(REPAIR), "-Spec", str(spec), "-Out", str(out), *script_flags],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        env=env,
        cwd=tmp_path,
    )
    assert out.exists(), done.stdout + done.stderr
    return {row["name"]: row for row in json.loads(out.read_text(encoding="utf-8-sig"))}, done.stdout


def _case(name: str, **fields) -> dict:
    base = {"name": name, "kind": "data", "answer": "", "no_prompt": False, "quarantine": False}
    return {**base, "never": False, "always": False, **fields}


# (switches and answer typed) -> (tools get installed, questions asked). The in-app Auto Repair button passes
# -NoPrompt and has always installed tools; a console run asks; -NoAutoInstallTools wins over every other switch.
INSTALL_CASES = {
    "console-yes": ({"answer": "y"}, True, 1),
    "console-no": ({"answer": "n"}, False, 1),
    "console-enter": ({"answer": ""}, False, 1),
    "no-prompt": ({"no_prompt": True, "answer": "n"}, True, 0),
    "auto-install": ({"always": True, "answer": "n"}, True, 0),
    "never": ({"never": True, "answer": "y"}, False, 0),
    "never-and-auto-install": ({"never": True, "always": True, "answer": "y"}, False, 0),
    "never-and-no-prompt": ({"never": True, "no_prompt": True, "answer": "y"}, False, 0),
}


# (setup exit, data check exit, doctor exit, doctor skipped) -> the repair ends ok. Exit 3 is a damaged database left in
# place, 2 a move refused because Thomas is running, 1 a config no move can fix; none of them may end "ok". A setup
# exit that never got a value (None) is not a 0.
OK_CASES = {
    "all-clean": ((0, 0, 0, False), True),
    "setup-failed-data-clean": ((1, 0, 0, False), False),
    "setup-never-reported": ((None, 0, 0, False), False),
    "config-will-not-parse": ((0, 1, 0, False), False),
    "damaged-database-left-in-place": ((0, 3, 0, False), False),
    "move-refused-thomas-running": ((0, 2, 0, False), False),
    "doctor-failed": ((0, 0, 1, False), False),
    "doctor-skipped": ((0, 0, 1, True), True),
    "doctor-skipped-data-bad": ((0, 1, 1, True), False),
    "doctor-skipped-setup-failed": ((1, 0, 0, True), False),
    "everything-failed": ((1, 3, 1, False), False),
}


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> dict:
    tmp_path = tmp_path_factory.mktemp("repair")
    stub = tmp_path / "stub.py"
    stub.write_text(STUB.format(repo=str(ROOT)), encoding="utf-8")
    py = str(_cmd(tmp_path / "stub.cmd", stub))
    running_py = str(_cmd(tmp_path / "stub_running.cmd", stub, running=True))

    answers = {"y": True, "yes": True, "YES": True, " y ": True}
    answers.update({"": False, "n": False, "no": False, "maybe": False, "yep": False, "yes please": False})
    cases = [_case(f"consent[{a}]", kind="consent", answer=a) for a in answers]
    cases.append(_case("consent-no-prompt", kind="consent", answer="y", no_prompt=True))
    cases += [_case(f"install[{name}]", kind="install", **fields) for name, (fields, _i, _a) in INSTALL_CASES.items()]
    for name, ((setup, data, doctor, skipped), _expected) in OK_CASES.items():
        cases.append(_case(f"ok[{name}]", kind="ok", setup=setup, data=data, doctor=doctor, skip_doctor=skipped))

    roots: dict[str, Path] = {}
    for name, damaged in (("no-consent", True), ("declined", True), ("accepted", True), ("switch", True)):
        roots[name] = tmp_path / name
        _database(roots[name], damaged=damaged)
    roots["clean"] = tmp_path / "clean"
    _database(roots["clean"], damaged=False)
    roots["bad-config"] = tmp_path / "bad-config"
    roots["bad-config"].mkdir()
    (roots["bad-config"] / "thomas.toml").write_text("[server\nport = = 1\n", encoding="utf-8")
    roots["running"] = tmp_path / "running"
    _database(roots["running"], damaged=True)

    def at(name: str, **fields) -> dict:
        return _case(f"data-{name}", root=str(roots[name]), py=fields.pop("py", py), **fields)

    cases += [
        at("no-consent", no_prompt=True, answer="y"),
        at("declined", answer="n"),
        at("accepted", answer="y"),
        at("switch", quarantine=True, no_prompt=True),
        at("clean"),
        at("bad-config"),
        at("running", quarantine=True, py=running_py),
    ]
    results, stdout = _run_harness(tmp_path, cases)
    return {"results": results, "stdout": stdout, "roots": roots, "answers": answers, "tmp": tmp_path, "py": py}


def test_yes_and_y_agree_and_everything_else_is_a_no(run: dict) -> None:
    for answer, expected in run["answers"].items():
        assert run["results"][f"consent[{answer}]"]["consent"] is expected, repr(answer)


def test_tools_are_installed_only_after_a_yes_or_a_switch_and_never_against_no_auto_install(run: dict) -> None:
    for name, (_fields, installs, asked) in INSTALL_CASES.items():
        row = run["results"][f"install[{name}]"]
        assert (row["consent"], row["asked"]) == (installs, asked), name


def test_the_repair_ends_ok_only_when_setup_the_data_check_and_doctor_all_passed(run: dict) -> None:
    for name, (_exits, expected) in OK_CASES.items():
        assert run["results"][f"ok[{name}]"]["ok"] is expected, name


def test_no_prompt_answers_no_without_asking(run: dict) -> None:
    row = run["results"]["consent-no-prompt"]
    assert row["consent"] is False
    assert row["asked"] == 0


def test_a_damaged_database_stays_put_when_nobody_said_yes(run: dict) -> None:
    for name, asked in (("no-consent", 0), ("declined", 1)):
        row = run["results"][f"data-{name}"]
        assert (run["roots"][name] / ".thomas" / "runs.sqlite3").exists(), name
        assert list((run["roots"][name] / ".thomas").glob("*.corrupt-*")) == [], name
        assert row["data_exit"] == 3, name  # reaches ok=False in the report
        assert row["asked"] == asked, name


def test_a_yes_or_the_switch_moves_the_database_aside_and_keeps_its_bytes(run: dict) -> None:
    for name, asked in (("accepted", 1), ("switch", 0)):
        folder = run["roots"][name] / ".thomas"
        moved = list(folder.glob("runs.sqlite3.corrupt-*"))
        assert len(moved) == 1, name
        assert moved[0].read_bytes() == b"not a database, only text padding" * 4
        assert not (folder / "runs.sqlite3").exists(), name
        assert run["results"][f"data-{name}"]["data_exit"] == 0, name
        assert run["results"][f"data-{name}"]["asked"] == asked, name


def test_a_healthy_folder_is_not_asked_about(run: dict) -> None:
    row = run["results"]["data-clean"]
    assert (row["data_exit"], row["asked"]) == (0, 0)
    assert (run["roots"]["clean"] / ".thomas" / "runs.sqlite3").exists()


def test_a_config_no_move_can_fix_fails_the_check_and_is_left_alone(run: dict) -> None:
    row = run["results"]["data-bad-config"]
    assert (row["data_exit"], row["asked"]) == (1, 0)
    assert (run["roots"]["bad-config"] / "thomas.toml").read_text(encoding="utf-8") == "[server\nport = = 1\n"


def test_a_running_thomas_blocks_the_move_and_the_message_says_what_to_do(run: dict) -> None:
    row = run["results"]["data-running"]
    assert row["data_exit"] == 2
    assert (run["roots"]["running"] / ".thomas" / "runs.sqlite3").exists()
    assert "Close Thomas, then run repair.cmd again." in run["stdout"]
    assert "--force" not in run["stdout"]


def test_with_no_console_to_ask_at_the_answer_is_no_and_the_repair_carries_on(run: dict) -> None:
    cases = [_case("consent-headless", kind="consent", answer="y")]
    results, stdout = _run_harness(run["tmp"], cases, headless=True)

    assert results["consent-headless"]["consent"] is False
    assert "No answer was possible here, so the answer is no." in stdout
