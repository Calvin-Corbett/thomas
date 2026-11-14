"""A shard never runs when the machine-wide ledger cannot be used: a ledger that fails is not an empty one.

``capacity_ledger`` raises an OSError (``TimeoutError``, ``PermissionError``, ``LedgerUnreadable``) when its file cannot
be read or written. A shard that ran anyway would not count against P for the other checks, so it answers
``REFUSED`` (the pool's own code, apart from a command that would not launch) with the reason, and the check reports
that it could not run. Sibling of
``test_checks_share_one_machine_wide_pool.py``, which stays under the 300-line cap.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from thomas.server import capacity_ledger, capacity_ledger_locks
from thomas.server.precard import pool
from thomas.server.proof import runner


@pytest.fixture
def ledger_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(capacity_ledger.ROOT_ENV, str(tmp_path / "ledger"))
    monkeypatch.setattr(pool.machine_capacity, "check_shard_mb", lambda *_a: 100)
    monkeypatch.setattr(pool.green_checkout, "green_root", lambda: tmp_path)
    monkeypatch.setattr(pool, "run_measured", Mock(side_effect=AssertionError("a shard ran without its place")))
    return tmp_path / "ledger"


@pytest.mark.parametrize("fails", ["pool_size", "admitted"])
@pytest.mark.parametrize(
    "error",
    [capacity_ledger_locks.LedgerUnreadable("torn"), PermissionError(13, "busy"), TimeoutError("stayed locked")],
    ids=["unreadable", "busy", "locked"],
)
def test_a_ledger_that_fails_leaves_the_shard_not_started(
    tmp_path: Path, ledger_root: Path, monkeypatch: pytest.MonkeyPatch, fails: str, error: OSError
) -> None:
    monkeypatch.setattr(capacity_ledger, fails, Mock(side_effect=error))

    code, output = pool.runner(None, files=1)(["x"], cwd=tmp_path, env={}, timeout_s=10)

    assert code == pool.REFUSED and "ledger" in output and str(error) in output
    pool.run_measured.assert_not_called()


def test_a_check_with_an_unreadable_ledger_could_not_run_and_did_not_run_out_of_time(
    tmp_path: Path, ledger_root: Path
) -> None:
    ledger_root.mkdir()
    (ledger_root / capacity_ledger.NAME).write_text("not a list of rows", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    capacity_ledger_locks.hold("a-running-job")  # a running job may have rows in the file: it is not moved aside
    try:
        result = runner.run_tests(
            tmp_path,
            ["tests/test_ok.py"],
            python=sys.executable,
            data_dir=tmp_path / "d",
            run=pool.runner(None, files=1),
        )
    finally:
        capacity_ledger_locks.let_go("a-running-job")

    assert not result.ran and not result.out_of_time and "ledger" in result.why
    assert (ledger_root / capacity_ledger.NAME).read_text(encoding="utf-8") == "not a list of rows"


MALFORMED = [
    pytest.param({"key": "p", "kind": "pool_size", "pool_size": 12}, id="no id or state"),
    pytest.param({"key": "p", "id": "p", "kind": "pool_size", "state": "recorded", "pool_size": "twelve"},
                 id="P is text"),
    pytest.param({"key": "w", "id": "x", "kind": "pool_size", "state": "recorded", "since": "soon", "pool_size": 12},
                 id="since is text"),
]  # fmt: skip


@pytest.mark.parametrize("fields", MALFORMED)
def test_a_malformed_row_of_a_live_owner_leaves_the_shard_not_started_never_a_crash(
    tmp_path: Path, ledger_root: Path, fields: dict
) -> None:
    """A row missing a field escaped the pool as a KeyError or ValueError: read as the change breaking the run."""
    row = {**fields, "owner": capacity_ledger_locks.owner(ledger_root)}  # this process's own row: it is not dropped
    (ledger_root / capacity_ledger.NAME).write_text(json.dumps([row]), encoding="utf-8")
    capacity_ledger_locks.hold("a-running-job")  # a running job may have rows in the file: it is not moved aside
    try:
        code, output = pool.runner(None, files=1)(["x"], cwd=tmp_path, env={}, timeout_s=10)
    finally:
        capacity_ledger_locks.let_go("a-running-job")

    assert code == pool.REFUSED and "ledger" in output and "cannot be read" in output
    pool.run_measured.assert_not_called()
    assert json.loads((ledger_root / capacity_ledger.NAME).read_text(encoding="utf-8")) == [row]
