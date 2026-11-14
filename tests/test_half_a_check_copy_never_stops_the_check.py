"""Half a check copy left by an earlier try never stops the next check.

A check copy is two folders: its files and its git folder. A try that died while making or removing one can leave
only one of them, or a git folder with no record of what it is. Such a half is not found as a copy, so nothing
removed it, and making the new copy under the same name was refused. On 2026-11-10 one finished change was stopped
before your card three times in under a minute each with "a scratch copy of dev could not be made: a green for
precard-thomas-85f46985dfc8-change already exists"; the half it tripped on was almost four days old.

Now the retry removes the half and makes the copy under its own name, and when Windows still holds the half open
it checks in a fresh copy beside it, never under a name another half already has.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.server import green_checkout, green_handoff
from thomas.server.precard import scratch


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for part in ("work", "git"):
        (tmp_path / part).mkdir()
    monkeypatch.setattr(green_checkout, "green_root", lambda: tmp_path)
    monkeypatch.setattr(green_handoff, "end_green_processes", lambda name: None)

    def create_green(*, blue: Path, execution_id: str, checkout_tip: str):
        if (tmp_path / "work" / execution_id).exists() or (tmp_path / "git" / execution_id).exists():
            raise green_checkout.GreenUnavailable(f"a green for {execution_id} already exists")
        return SimpleNamespace(execution_id=execution_id)

    monkeypatch.setattr(green_checkout, "create_green", create_green)
    return tmp_path


@pytest.mark.parametrize("part", ["work", "git"])
def test_half_a_copy_is_removed_and_the_check_uses_its_own_name(root: Path, part: str) -> None:
    name = scratch.scratch_id("thomas-x", scratch.WITH_CHANGE)
    half = root / part / name
    half.mkdir()
    (half / "leftover.txt").write_text("x", encoding="utf-8")
    assert green_checkout.find_green(name) is None, "half a copy is not found as a copy"

    copy = scratch.copy_of_dev(Path("blue"), "tip", "thomas-x", scratch.WITH_CHANGE)

    assert copy.execution_id == name
    assert not half.exists()


def test_a_held_half_is_left_and_the_fresh_copy_takes_a_name_no_half_has(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = scratch.scratch_id("thomas-x", scratch.WITH_CHANGE)
    second = scratch.scratch_id("thomas-x", f"{scratch.WITH_CHANGE}2")
    (root / "git" / name).mkdir()
    (root / "work" / second).mkdir()  # an earlier fresh copy, itself left as a half

    def held(green, **_: object) -> None:
        raise PermissionError(32, "The process cannot access the file because it is being used by another process")

    monkeypatch.setattr(green_checkout, "remove_green", held)

    copy = scratch.copy_of_dev(Path("blue"), "tip", "thomas-x", scratch.WITH_CHANGE)

    assert copy.execution_id == scratch.scratch_id("thomas-x", f"{scratch.WITH_CHANGE}3")
    assert (root / "git" / name).is_dir(), "the held half is left for the sweep"
