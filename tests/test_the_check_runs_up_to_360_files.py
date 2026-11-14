"""The check runs up to 360 covering test files (spec 2026-10-12 Part 1 item 8); off, it keeps the 120 it had.

At one process per copy a 60-file check took 1,321 s, so the cap was 120. With one run of the change across the
machine-wide pool, the speed is spent on running more tests, not fewer. A wide check that runs out of its hour because
its shards spent most of it waiting for places in a busy pool is held without a strike: the machine was busy, the
change's tests were not slow.
"""

from __future__ import annotations

import contextlib
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.server import capacity_ledger, proof
from thomas.server.precard import check, pool
from thomas.server.proof import ProofRun, Selection, selection


def test_the_check_runs_up_to_360_covering_test_files() -> None:
    assert selection.CAP == proof.CAP == 360
    texts = {
        "tests/test_architecture.py": "",
        **{f"tests/test_w{n:03}.py": "from pkg import widget\n" for n in range(400)},
    }

    chosen = selection.select_from(texts, ["pkg/widget.py"])

    assert len(chosen.files) == 360 and len(chosen.left_out) == 41
    assert chosen.files[0] == "tests/test_architecture.py"


@pytest.mark.parametrize(("off", "cap"), [(True, 120), (False, 360)])
def test_with_parallel_off_the_check_keeps_the_120_file_cap(
    monkeypatch: pytest.MonkeyPatch, off: bool, cap: int
) -> None:
    if off:
        monkeypatch.setenv(pool.PARALLEL_ENV, "off")
    else:
        monkeypatch.delenv(pool.PARALLEL_ENV, raising=False)

    assert check._cap() == cap


@pytest.mark.parametrize(("waited_min", "first"), [(14, "small"), (15, "big")])
def test_a_360_file_checks_shards_let_a_smaller_checks_go_first_for_at_most_15_minutes(
    waited_min: int, first: str
) -> None:
    """Every shard of a check waits in line by its check's selected files: a 360-file check never starves a smaller
    one of pool places, and the 15-minute rule keeps it from being starved in turn."""
    now = 1_000_000.0
    big = {"key": "big", "kind": pool.SHARD_KIND, "state": "waiting", "files": 360, "since": now - 60 * waited_min}
    small = {"key": "small", "kind": pool.SHARD_KIND, "state": "waiting", "files": 20, "since": now}

    assert capacity_ledger.order([big, small], now)[0]["key"] == first


@pytest.mark.parametrize(
    ("off", "waited_min", "ran_min", "cause", "costly"),
    [
        (False, 50, 10, "busy", False),  # its shards mostly waited for places: the machine was busy
        (False, 0, 60, "deadline", True),  # its tests really took the hour
        (False, 25, 35, "deadline", True),  # more of it ran than waited
        (True, 50, 10, "deadline", True),  # with the pool off nothing waits for a place
    ],
)
def test_a_check_out_of_time_is_a_strike_only_when_its_tests_had_the_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    off: bool,
    waited_min: int,
    ran_min: int,
    cause: str,
    costly: bool,
) -> None:
    if off:
        monkeypatch.setenv(pool.PARALLEL_ENV, "off")
    else:
        monkeypatch.delenv(pool.PARALLEL_ENV, raising=False)
    spent = pool.Waits()
    spent.add(waited=60 * waited_min, ran=60 * ran_min)
    monkeypatch.setattr(check.pool, "Waits", lambda: spent)
    monkeypatch.setattr(check.scratch, "apply_change", lambda *_: "")
    monkeypatch.setattr(check.green_handoff, "size_problems", lambda *_: [])
    monkeypatch.setattr(check.proofs, "select", lambda *_a, **_k: Selection(("tests/test_ok.py",), ()))
    out_of_time = ProofRun(False, "it ran out of time", (), 0, 30, True)
    monkeypatch.setattr(check.proofs, "run_tests", lambda *_a, **_k: out_of_time)
    monkeypatch.setattr(check.machine_capacity, "_memory", lambda: (32 * 1024**3, 20 * 1024**3))
    work = (SimpleNamespace(work=tmp_path / "base"), SimpleNamespace(work=tmp_path / "change"), tmp_path / "data")
    deadline = check.proofs.Deadline(0.0)

    checked = check._steps(SimpleNamespace(execution_id="wide"), "abc123", "patch", ["pkg/w.py"], sys.executable,
                           *work, deadline)  # fmt: skip

    assert (checked.state, checked.cause, checked.costly) == (check.UNAVAILABLE, cause, costly)


def test_a_shards_wait_for_a_place_is_counted_apart_from_its_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    @contextlib.contextmanager
    def slow_place(_job_id: str, **_kwargs: object) -> Iterator[dict[str, object]]:
        time.sleep(0.3)  # another check's shards hold every place
        yield {}

    def refused(_job_id: str, **_kwargs: object) -> None:
        time.sleep(0.2)
        raise capacity_ledger.NotAdmitted("all 12 places are in use", waited=True)

    monkeypatch.setattr(pool.capacity_ledger, "pool_size", lambda own, **_k: own)
    monkeypatch.setattr(pool, "run_measured", lambda *_a, **_k: (time.sleep(0.1), (0, "ran", 0.0, 0.0))[1])
    waits = pool.Waits()

    monkeypatch.setattr(pool.capacity_ledger, "admitted", slow_place)
    assert pool.runner(None, files=1, record_peaks=False, waits=waits)(["t"], cwd=tmp_path, env={}, timeout_s=5)[0] == 0
    assert waits.waited_s >= 0.25 and 0.05 <= waits.ran_s < 0.25, (waits.waited_s, waits.ran_s)

    monkeypatch.setattr(pool.capacity_ledger, "admitted", refused)
    pool.runner(None, files=1, record_peaks=False, waits=waits)(["t"], cwd=tmp_path, env={}, timeout_s=5)
    assert waits.waited_s >= 0.4 and waits.ran_s < 0.25, "a place never given is all wait"
