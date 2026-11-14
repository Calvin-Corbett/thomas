"""A non-elevated window setup plan catches missing rights and unreadable runtime paths."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SETUP = REPO / "scripts" / "cage" / "enable_window.ps1"
HELPERS = REPO / "scripts" / "cage" / "window_setup_steps.ps1"


def _plan(tmp_path: Path) -> str:
    shell = shutil.which("powershell.exe") or shutil.which("pwsh")
    if not shell:
        pytest.skip("PowerShell is required for the Windows window-setup plan")
    home = Path(sys.base_prefix)
    if not (home / "python.exe").is_file():
        pytest.skip("base Python has no python.exe for the plan")
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text(f"home = {home}\n", encoding="utf-8")
    result = subprocess.run(
        [
            shell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SETUP),
            "-Plan",
            "-RepoRoot",
            str(REPO),
            "-LiveRoot",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RESULT: failed" not in result.stdout, result.stdout
    return result.stdout


def test_runner_description_fits_local_user_limit() -> None:
    source = SETUP.read_text(encoding="utf-8")
    match = re.search(r'New-LocalUser -Name \$RunnerUser\b.*?-Description "([^"]+)"', source, re.S)
    assert match, "runner's New-LocalUser must have a literal description"
    assert len(match.group(1)) <= 48


def test_checker_batch_logon_precedes_credential_task_and_service_task(tmp_path: Path) -> None:
    output = _plan(tmp_path)
    batch = output.index("PLAN: grant SeBatchLogonRight to thomas-checker")
    credential = output.index("PLAN: store the runner logon")
    task = output.index("PLAN: scheduled task ThomasChecker")
    assert batch < credential < task
    helpers = HELPERS.read_text(encoding="utf-8")
    source = SETUP.read_text(encoding="utf-8")
    assert "LsaAddAccountRights" in helpers
    assert "Grant-CheckerBatchLogon $checkerSid" in source


def test_plan_grants_both_accounts_python_and_noninheriting_service_paths(tmp_path: Path) -> None:
    output = _plan(tmp_path)
    python_home = str(Path(sys.base_prefix))
    grants = [line for line in output.splitlines() if line.startswith("PLAN: icacls ")]
    for path in (str(tmp_path / "scripts" / "cage"), str(tmp_path / "scripts" / "forge" / "gates"), python_home):
        grant = next((line for line in grants if path.casefold() in line.casefold()), None)
        assert grant, f"missing explicit read grant for {path}"
        assert "*<thomas-checker>:(OI)(CI)RX" in grant
        assert "*<thomas-runner>:(OI)(CI)RX" in grant
        assert "/T" in grant, f"grant must reach non-inheriting descendants: {grant}"
    helpers = HELPERS.read_text(encoding="utf-8")
    assert "pyvenv.cfg" in helpers
    assert "Invoke-Acl (@($pythonHome, '/grant')" in helpers
