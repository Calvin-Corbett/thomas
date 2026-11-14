"""The window setup gives the test-runner account no way to write an answer (review B1, static).

``enable_window.ps1`` is never run here; these read its text and assert the shape of the isolation it sets up: a
separate ``thomas-runner`` account that may read the repo and write only inside a job's copy, and that is refused any
write on ``jobs``, ``results`` and ``state`` -- the folders whose contents the promoter trusts. A real ACL change
needs the owner's one elevated run; this only proves the script asks for the right one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cage" / "enable_window.ps1"


@pytest.fixture(scope="module")
def text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _grant_line(text: str, folder: str) -> str:
    """The Set-FolderAcl call for ``Join-Path $CheckRoot "<folder>"``."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Set-FolderAcl") and f'"{folder}"' in stripped:
            return stripped
    raise AssertionError(f"no Set-FolderAcl line for {folder}")


def test_a_separate_runner_account_is_provisioned(text: str) -> None:
    assert 'RunnerUser = "thomas-runner"' in text, "the setup names a separate test-runner account"
    assert re.search(r"New-LocalUser\s+-Name\s+\$RunnerUser", text), "it creates thomas-runner"
    assert re.search(r"Administrators.*-Member\s+\$RunnerUser", text), "and never leaves it an administrator"


def test_the_runner_can_write_only_a_jobs_copy(text: str) -> None:
    copies = _grant_line(text, "copies")
    assert "${runner}" in copies and "M" in copies, "the runner writes a job's copy to run the tests there"
    # Read the repo so it can run the tests in the copy; no write anywhere in the repo (one grant line, read only).
    live = next(line for line in text.splitlines() if "$LiveRoot" in line and "/grant" in line)
    assert '"${runner}:(OI)(CI)RX"' in live, live
    assert ":(OI)(CI)M" not in live, f"the runner must not modify your checkout: {live}"


@pytest.mark.parametrize("folder", ["jobs", "results", "state"])
def test_the_runner_and_the_agent_cannot_write_the_answer_folders(text: str, folder: str) -> None:
    grant = _grant_line(text, folder)
    assert "${runner}" not in grant, f"the runner must have no grant on {folder}: {grant}"
    assert "${agent}" not in grant, f"the Build teams' account must have no grant on {folder}: {grant}"


def test_the_isolation_is_read_back_and_proven(text: str) -> None:
    # Assert-Writers proves only SYSTEM, Administrators and the checker may write results and state; the runner and
    # the agent are not among the allowed writers.
    for folder in ("results", "state"):
        assert re.search(rf'Assert-Writers \(Join-Path \$CheckRoot "{folder}"\) @\(\$checkerSid\)', text), folder
    assert re.search(r'Assert-Writers \(Join-Path \$CheckRoot "jobs"\) @\(\$ownerSid\)', text)


def test_the_runner_identity_is_recorded_for_the_checker(text: str) -> None:
    # The service reads scripts/cage/checker_runner.py's config to learn which account to launch tests as.
    assert "runner.json" in text, "the setup writes the runner identity the checker reads"
    assert "thomas-runner" in text and "credential" in text.lower()
