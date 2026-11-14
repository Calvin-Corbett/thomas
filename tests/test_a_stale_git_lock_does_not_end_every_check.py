"""A copy's git lock left by a killed git no longer ends every check "unavailable" (2026-11-13).

Copy thomas-7d997486ee9a failed every try within a minute: "could not read green's changes: fatal: Unable to create
'...\\git\\thomas-7d997486ee9a/index.lock': File exists". The git that made the lock was gone and nothing removed it.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from tests.ratchet_support import make_repo
from thomas.server import green_checkout, green_git_lock


@pytest.fixture
def green(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> green_checkout.Green:
    repo = make_repo(tmp_path)
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(tmp_path / "greens"))
    made = green_checkout.create_green(repo, "stale-lock-test")
    (made.work / "thomas/core/widget.py").write_text("VALUE = 2\n", encoding="utf-8")
    return made


def _lock(green: green_checkout.Green, age_s: float) -> Path:
    lock = green.git_dir / "index.lock"
    lock.write_text("", encoding="utf-8")
    then = time.time() - age_s
    os.utime(lock, (then, then))
    return lock


def test_an_abandoned_lock_is_removed_and_the_change_is_read(
    green: green_checkout.Green, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(green_git_lock, "git_holds", lambda _git_dir, _work: False)
    lock = _lock(green, green_git_lock.STALE_AFTER_S + 60)

    assert green_checkout.changed_paths(green) == ["thomas/core/widget.py"]
    assert not lock.exists()


def test_a_young_lock_is_kept_and_the_failure_says_why(green: green_checkout.Green) -> None:
    lock = _lock(green, 5)

    with pytest.raises(green_checkout.GreenUnavailable, match="left in place"):
        green_checkout.changed_paths(green)
    assert lock.exists()


def test_an_old_lock_a_git_may_still_hold_is_kept(green: green_checkout.Green, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(green_git_lock, "git_holds", lambda _git_dir, _work: True)
    lock = _lock(green, green_git_lock.STALE_AFTER_S + 60)

    with pytest.raises(green_checkout.GreenUnavailable, match="may still hold it"):
        green_checkout.changed_paths(green)
    assert lock.exists()


def test_no_git_running_on_a_fresh_copy_holds_its_lock(green: green_checkout.Green) -> None:
    assert green_git_lock.git_holds(green.git_dir, green.work) is False
