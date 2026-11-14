"""A check before a card waits for its turn in the same line as the Builds' own test runs.

On 2026-11-13 a check's shards ran beside thirteen test runs of Builds on a PC at its limit: they timed out at 1800 s
and per test, and the check ended 'unavailable' after 92 minutes. The wait is not taken from a shard's own time.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import pytest

from thomas.server.precard import pool


class _Line:
    def __init__(self, waits: int) -> None:
        self.waits, self.joined, self.gave_back, self.looks = waits, [], [], 0

    def join(self, label: str) -> int:
        self.joined.append(label)
        return 7

    def look(self, ticket: int) -> tuple[bool, int]:
        self.looks += 1
        return self.looks > self.waits, 0

    def leave(self, ticket: int) -> None:
        self.gave_back.append(ticket)


@pytest.fixture
def shard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    line, ran = _Line(waits=3), []

    @contextlib.contextmanager
    def admitted(*_a: Any, **_k: Any):
        yield {}

    def run_measured(command: Any, *, cwd: Path, env: Any, timeout_s: float) -> tuple[int, str, int, int]:
        ran.append((line.looks, timeout_s))
        return 0, "1 passed", 0, 0

    monkeypatch.setattr(pool.machine_capacity, "check_shard_mb", lambda *_a: 100)
    monkeypatch.setattr(pool, "size", lambda **_k: 4)
    monkeypatch.setattr(pool.green_checkout, "green_root", lambda: tmp_path)
    monkeypatch.setattr(pool.machine_load, "wait_for_room", lambda **_k: (0.0, ""))
    monkeypatch.setattr(pool.capacity_ledger, "admitted", admitted)
    monkeypatch.setattr(pool.capacity_ledger, "pool_size", lambda own, **_k: own)
    monkeypatch.setattr(pool, "run_measured", run_measured)
    monkeypatch.setattr(pool.machine_load, "line", lambda: line)
    monkeypatch.setattr(pool, "LINE_POLL_S", 0.0)
    return pool.runner(None, files=3, record_peaks=False), line, ran


def test_a_shard_starts_only_when_its_turn_in_the_line_comes_and_gives_its_place_back(shard, tmp_path: Path) -> None:
    run, line, ran = shard
    assert run(["pytest"], cwd=tmp_path, env={}, timeout_s=1800) == (0, "1 passed")
    assert line.joined == ["check shard"] and line.gave_back == [7]
    assert ran == [(4, 1800)], "it ran after its fourth look, with all of its own time"


def test_a_line_that_cannot_be_used_does_not_stop_a_shard(shard, tmp_path: Path) -> None:
    run, line, ran = shard

    def broken(_label: str) -> int:
        raise OSError("the line file is locked")

    line.join = broken
    assert run(["pytest"], cwd=tmp_path, env={}, timeout_s=1800) == (0, "1 passed") and len(ran) == 1
