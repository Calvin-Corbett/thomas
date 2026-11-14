"""Your one elevated setup step gives each account only its part (spec 2026-10-12, sections 8.1, 8.4, 8.7).

Run with -Plan: it prints every action and changes nothing, so this needs no elevation and touches no real folder,
account, task, firewall rule or pin.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cage" / "enable_window.ps1"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
pytestmark = pytest.mark.skipif(not POWERSHELL, reason="needs Windows PowerShell")


@pytest.fixture(scope="module")
def plan(tmp_path_factory: pytest.TempPathFactory) -> list[str]:
    root = tmp_path_factory.mktemp("window-setup")
    status = root / "status.txt"
    subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), "-Plan",
         "-LiveRoot", str(root / "Thomas"), "-CheckRoot", str(root / "Check"), "-RecordRoot", str(root / "Window"),
         "-PinRoot", str(root / "Pins"), "-StatusFile", str(status)],
        capture_output=True, text=True, timeout=180, check=False,
    )  # fmt: skip
    lines = status.read_text(encoding="utf-8").splitlines()
    assert not any(line.startswith("RESULT: failed") for line in lines), lines
    return lines


def _acl(plan: list[str], folder: str) -> str:
    found = [line for line in plan if line.startswith("PLAN: icacls ") and line.split()[2].endswith(folder)]
    assert len(found) == 1, (folder, found)
    return found[0]


def test_the_checker_writes_answers_and_you_write_jobs_and_neither_writes_the_others(plan: list[str]) -> None:
    jobs, results = _acl(plan, "jobs"), _acl(plan, "results")
    assert "<your account>:(OI)(CI)M" in jobs and "<thomas-checker>:(OI)(CI)RX" in jobs
    assert "<thomas-checker>:(OI)(CI)M" in results and "<your account>:(OI)(CI)RX" in results
    for folder in ("copies", "state"):
        assert "<thomas-checker>:(OI)(CI)M" in _acl(plan, folder)


def test_the_build_teams_account_has_no_entry_in_the_checkers_folders(plan: list[str]) -> None:
    for folder in ("Check", "jobs", "results", "copies", "state"):
        line = _acl(plan, folder)
        assert "/inheritance:r" in line
        assert "<thomas-agent>" not in line.split("/grant:r", 1)[1]


def test_the_record_lets_you_add_a_file_and_never_change_one(plan: list[str]) -> None:
    line = _acl(plan, "Window")
    assert "<your account>:(CI)(RX,WD,AD)" in line and "<your account>:(OI)(IO)(R)" in line
    assert "*S-1-3-4:(OI)(CI)(R)" in line, "OWNER RIGHTS: the file you made is not yours to rewrite"
    assert "<thomas-agent>:(OI)(CI)(RX)" in line


def test_the_checker_reads_your_checkout_is_fenced_and_runs_limited_from_it(plan: list[str]) -> None:
    text = "\n".join(plan)
    assert "<thomas-checker>:(OI)(CI)RX" in _acl(plan, "Thomas")
    assert "block every connection out for thomas-checker" in text
    assert "checker_service.py" in text and "as thomas-checker, Limited" in text


def test_the_cards_are_pinned_from_the_reviewed_copy_and_no_password_is_shown(plan: list[str]) -> None:
    text = "\n".join(plan)
    assert "PLAN: pin catalogue.sha256" in text and "card_catalogue.py" in text
    assert "password not shown, not stored" in text
    assert "restart ThomasCagedServer and ThomasSelfChangePromoter" in text
