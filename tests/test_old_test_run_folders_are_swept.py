"""A test session that ends removes a few data folders earlier runs left behind, and never a live one.

On 2026-11-06 one account's temp folder held 1,992 ``thomas-test-data-*`` folders that sessions could not remove (a
shard stopped for time, or a file Defender or Windows Search held open), each one more for Windows Search to index.
Regression for tests/run_folder_sweep.py, which tests/conftest.py calls from pytest_unconfigure.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from tests import run_folder_sweep

HOUR = 3600.0


def _folder(parent: Path, name: str, age_s: float, now: float) -> Path:
    folder = parent / name
    (folder / "shared").mkdir(parents=True)
    (folder / "shared" / "secrets.json").write_text("{}", encoding="utf-8")
    os.utime(folder, (now - age_s, now - age_s))
    return folder


def test_only_old_run_folders_go_and_never_the_runs_own(tmp_path: Path) -> None:
    now = time.time()
    old = _folder(tmp_path, "thomas-test-data-old", 7 * HOUR, now)
    fresh = _folder(tmp_path, "thomas-test-data-fresh", 1 * HOUR, now)
    own = _folder(tmp_path, "thomas-test-data-own", 9 * HOUR, now)
    other = _folder(tmp_path, "someone-elses-folder", 30 * HOUR, now)

    assert run_folder_sweep.sweep(tmp_path, own=own, now=now) == 1
    assert not old.exists()
    assert fresh.exists() and own.exists() and other.exists()


def test_one_session_removes_at_most_its_limit(tmp_path: Path) -> None:
    now = time.time()
    for i in range(5):
        _folder(tmp_path, f"thomas-test-data-{i}", 8 * HOUR, now)
    assert run_folder_sweep.sweep(tmp_path, own=tmp_path / "none", now=now, limit=3) == 3
    assert len(list(tmp_path.glob("thomas-test-data-*"))) == 2


def test_the_session_end_calls_the_sweep() -> None:
    conftest = (Path(__file__).resolve().parent / "conftest.py").read_text(encoding="utf-8")
    end = conftest[conftest.index("def pytest_unconfigure") :]
    assert "sweep(TEST_DATA_ROOT.parent, own=TEST_DATA_ROOT)" in end.split("\ndef ", 1)[0]
