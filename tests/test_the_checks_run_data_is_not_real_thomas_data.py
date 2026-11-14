"""A check keeps its runs' data outside your real Thomas data folder (2026-10-27).

tests/conftest.py fails a session that opens anything in your real Thomas data folder. The cage's greens live in it
(LOCALAPPDATA/Thomas/green), and each check kept its runs' reports and selection files under green_root()/precard, so
in the cage every shard failed its session with all tests passed: 3603b9 and 4b24de, "pytest exit 1 contradicts its
report" on all 16 shards, after fad9eda7 had already moved the tests' own folders apart from the reports.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from thomas.core.config import resolve_thomas_data_dir
from thomas.server import green_checkout
from thomas.server.precard import slot


def test_the_default_data_root_is_outside_the_real_data_folder_and_the_greens(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(slot.DATA_ROOT_ENV, raising=False)
    monkeypatch.setattr(green_checkout, "green_root", lambda: tmp_path / "LocalAppData" / "Thomas" / "green")
    root = slot.data_root().resolve()
    real = resolve_thomas_data_dir(env={}).resolve()
    assert real not in root.parents and root != real
    greens = green_checkout.green_root().resolve()
    assert greens not in root.parents and root != greens


def test_leftovers_are_swept_from_the_new_place_and_the_old_one(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(slot.DATA_ROOT_ENV, str(tmp_path / "data-root"))
    monkeypatch.setattr(green_checkout, "green_root", lambda: tmp_path / "greens")
    old = time.time() - 10_000
    for folder in (tmp_path / "data-root" / "green-a", tmp_path / "greens" / "precard" / "green-b"):
        folder.mkdir(parents=True)
        os.utime(folder, (old, old))
    fresh = tmp_path / "data-root" / "green-c"
    fresh.mkdir()
    removed = slot.clear_leftovers(3600)
    assert sorted(removed) == ["precard/green-a", "precard/green-b"] and fresh.is_dir()


@pytest.mark.parametrize("named", ["", "  "])
def test_an_empty_setting_falls_back_to_the_temporary_folder(monkeypatch, named: str) -> None:
    monkeypatch.setenv(slot.DATA_ROOT_ENV, named)
    assert slot.data_root().name == "thomas-precard"
