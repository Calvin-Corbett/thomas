"""The acceptance contract's source walk stays out of runtime trees (2026-09-06).

Every loop pass that wrote code sat ~30 s between the answer and the verdict.
A stack dump twenty seconds in landed in ``acceptance_contract._source_files``:
it walks the whole workspace to find source files, and in Thomas's own
checkout ``runtime/`` (a doppelganger with its venvs) holds 566,161 files
that the skip list never mentioned. Two such walks per pass, on every test
that drives the loop and on every self-edit run.

The walk now prunes the same runtime trees the orphan scan prunes, and it
carries a wall-clock budget: a tree it has never seen cannot stall a pass,
and a scan cut short says so (``SourceScanIncomplete``) instead of handing
back a partial list that a check could mistake for a clean one.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from thomas.core import acceptance_contract as ac


def _py(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x = 1\n", encoding="utf-8")


def test_runtime_and_data_trees_are_never_walked(tmp_path: Path) -> None:
    _py(tmp_path / "app.py")
    for i in range(20):
        _py(tmp_path / "runtime" / "doppelganger" / "green" / f"m{i}.py")
        _py(tmp_path / ".thomas" / "sessions" / f"s{i}.py")
        _py(tmp_path / "venvs" / "green" / "lib" / f"v{i}.py")
        _py(tmp_path / "node_modules" / "pkg" / f"n{i}.js")
    found = ac._source_files(tmp_path, exclude=set())
    assert [p.name for p in found] == ["app.py"], found


def test_the_walk_stops_at_its_time_budget(tmp_path: Path, monkeypatch) -> None:
    for i in range(400):
        _py(tmp_path / f"d{i:03d}" / "m.py")
    monkeypatch.setattr(ac, "_WALK_BUDGET_SECONDS", 0.0)
    started = time.monotonic()
    with pytest.raises(ac.SourceScanIncomplete):
        ac._source_files(tmp_path, exclude=set())
    assert time.monotonic() - started < 2.0
