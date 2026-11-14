"""Listing the folders above a checkout that lives inside your real Thomas data folder is not real-data access.

The cage keeps its check copies in LOCALAPPDATA/Thomas/green/work. Importing ``coverage`` lists every folder above the
current one to learn its letter case (coverage/files.py ``actual_path``), so the first test in a shard to import it
listed ...\\Thomas, ...\\Thomas\\green and ...\\Thomas\\green\\work, and the tripwire failed the session with every
test passed. Both sides of a check broke the same way, the check blamed dev, and the change was tried again: since
2026-10-27 such checks used 65% of the checks' test time. Reproduced 2026-10-29: the same 359 files on the same dev ran
to the end outside LOCALAPPDATA/Thomas and failed inside it.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import conftest as guard
from tests.real_data_child_audit import names_above
from tests.test_no_test_touches_your_real_data import _fake_real_folder, _tripwire


def test_a_checkout_inside_the_data_folder_may_list_the_folders_above_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, _, check = _tripwire()
    root = _fake_real_folder(tmp_path)["root"].resolve()
    checkout = root / "green" / "work" / "thomas-copy"
    checkout.mkdir(parents=True)
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root,))
    monkeypatch.setattr(guard, "ROOT", checkout)
    monkeypatch.setattr(guard, "_DIRECT_REAL_DATA_ACCESS", set())
    before = snapshot([root])

    for folder in (root, root / "green", root / "green" / "work"):
        os.listdir(folder)
        with os.scandir(folder):
            pass

    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    assert check(session, before, [root], in_a_green=True) == []
    assert session.exitstatus == pytest.ExitCode.OK


def test_other_data_folders_and_files_still_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot, _, check = _tripwire()
    root = _fake_real_folder(tmp_path)["root"].resolve()
    checkout = root / "green" / "work" / "thomas-copy"
    checkout.mkdir(parents=True)
    (root / "projects").mkdir()
    monkeypatch.setattr(guard, "REAL_DATA_DIRS", (root,))
    monkeypatch.setattr(guard, "ROOT", checkout)
    monkeypatch.setattr(guard, "_DIRECT_REAL_DATA_ACCESS", set())
    before = snapshot([root])

    os.listdir(root / "projects")  # beside the way to the checkout, not on it
    with open(root / "green" / "notes.txt", "w", encoding="utf-8") as handle:  # on the way, but written
        handle.write("x")

    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)
    found = check(session, before, [root], in_a_green=True)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert any(str(root / "projects") in line for line in found)
    assert any(str(root / "green" / "notes.txt") in line for line in found)


def test_only_a_listing_of_a_folder_above_the_checkout_is_excused(tmp_path: Path) -> None:
    checkout = tmp_path / "Thomas" / "green" / "work" / "copy"
    assert names_above("os.listdir", tmp_path / "Thomas", checkout)
    assert names_above("os.scandir", tmp_path / "Thomas" / "green", checkout)
    assert not names_above("open", tmp_path / "Thomas" / "green", checkout)
    assert not names_above("os.listdir", tmp_path / "Thomas" / "json", checkout)
    assert not names_above("os.listdir", checkout, checkout)  # the checkout itself has its own rule
