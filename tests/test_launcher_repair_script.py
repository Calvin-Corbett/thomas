"""repair.cmd / scripts/repair.ps1 repair what failed starts actually leave behind, and ask before installing.

It used to reinstall dependencies and print a report: a damaged database, a thomas.toml that will not parse or an
unwritable data folder were never looked at, tools were installed with winget without a question, the declared
-NoPrompt switch was never read, and the closing `thomas doctor` step crashed on a bad config.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _param_block(text: str) -> str:
    return text.split("param(", 1)[1].split("\n)", 1)[0]


def test_repair_keeps_every_switch_the_in_app_repair_button_passes() -> None:
    # /api/setup/repair appends these by name; a script that drops one fails to bind and does nothing.
    route = _read("thomas/server/routes/setup_aiohttp.py")
    passed = set(re.findall(r'"(-(?:NoPrompt|SkipInstall|SkipDoctor|NoAutoInstallTools))"', route))
    assert passed == {"-NoPrompt", "-SkipInstall", "-SkipDoctor", "-NoAutoInstallTools"}

    declared = _param_block(_read("scripts/repair.ps1"))
    for switch in passed:
        assert f"[switch]${switch[1:]}" in declared, switch


def test_repair_reads_the_no_prompt_switch_it_declares() -> None:
    text = _read("scripts/repair.ps1")
    assert len(re.findall(r"\$NoPrompt\b", text)) >= 3  # declared, read in Read-Consent, read in the install choice


def test_a_console_run_asks_before_installing_tools_and_the_default_is_no() -> None:
    text = _read("scripts/repair.ps1")
    assert "Read-Consent" in text
    assert "Repair can install missing tools" in text
    assert "[y/N]" in text  # capital N: the default answer is no
    assert re.search(r'if \(\$installTools\) \{\s*\$setupArgs \+= "-AutoInstallTools"', text)
    # The unconditional form the old script had must not come back.
    assert 'setupArgs = @("-Easy", "-NoPrompt", "-AutoInstallTools")' not in text


def test_the_install_choice_is_made_from_the_three_switches_by_name() -> None:
    # What each answer leads to is run for real in test_a_repair_asks_before_it_moves_anything.py; this pins the wiring.
    text = _read("scripts/repair.ps1")
    call = "Resolve-InstallTools -Never ([bool]$NoAutoInstallTools) -Always ([bool]$AutoInstallTools) -Unattended ([bool]$NoPrompt)"
    assert f"$installTools = {call}" in text


def test_repair_tests_config_and_databases_and_moves_nothing_without_a_yes() -> None:
    text = _read("scripts/repair.ps1")
    assert '"-m", "thomas.bootdoctor", "check"' in text
    assert "[switch]$QuarantineCorrupt" in text
    quarantine_call = text.index('"--quarantine"')
    asked = text.index('Read-Consent "A database file is damaged')
    assert asked < quarantine_call  # the question comes before the move
    assert "$QuarantineCorrupt -or" in text


def test_the_data_check_runs_after_setup_has_repaired_the_dependencies() -> None:
    # The check imports Thomas; run before setup it fails on the very dependencies setup is there to fix.
    text = _read("scripts/repair.ps1")
    calls = [m.start() for m in re.finditer(r"^Invoke-DataCheck\s*$", text, re.M)]
    assert len(calls) == 1
    assert calls[0] > text.index("-File $setupScript")


def test_the_final_verdict_is_made_from_the_three_exit_codes_by_name() -> None:
    # Which combinations end ok is run for real in test_a_repair_asks_before_it_moves_anything.py; this pins the wiring.
    text = _read("scripts/repair.ps1")
    call = "Test-RepairOk -SetupExit $setupExit -DataExit $script:DataExit -DoctorExit $doctorExit -SkipDoctor ([bool]$SkipDoctor)"
    assert f"$ok = {call}" in text
    assert "data_check_exit=" in text


def test_repair_does_not_let_native_stderr_abort_the_doctor_step() -> None:
    text = _read("scripts/repair.ps1")
    body = text.split("function Invoke-VenvPython", 1)[1].split("\n}", 1)[0]
    assert '$ErrorActionPreference = "Continue"' in body
