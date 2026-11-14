"""Every shard's memory watcher reads one shared list of processes, not one of its own every half second.

Measured 2026-11-06 for your "cpu is still capped at 100%": each shard's watcher called ``children(recursive=True)``
every half second, and on Windows each call lists every process on the machine (~25 ms of CPU). With 16 shards the
watchers took 12.36 CPU-seconds every 15 seconds; with one list per half second shared by all, 1.12, finding the same
processes. Regression for thomas.server.precard.pool._ProcessTable and _tree, with a stand-in psutil.
"""

from __future__ import annotations

import types

import psutil
import pytest

from thomas.server.precard import pool


class _Proc:
    def __init__(self, pid: int, born: float, table: dict) -> None:
        self.pid, self._born, self._table = pid, born, table

    def create_time(self) -> float:
        return self._born

    def is_running(self) -> bool:
        return self.pid in self._table["alive"]

    def children(self, recursive: bool = False) -> list:
        self._table["walks"] += 1
        return [_Proc(pid, self._table["born"][pid], self._table) for pid in self._table["under"].get(self.pid, [])]

    def memory_info(self) -> types.SimpleNamespace:
        return types.SimpleNamespace(peak_pagefile=10 * 1024**2, peak_wset=5 * 1024**2, rss=1)


def _fake(
    parents: dict[int, int], born: dict[int, float], *, can_list: bool = True
) -> tuple[types.SimpleNamespace, dict]:
    table = {"lists": 0, "walks": 0, "born": born, "alive": set(born), "under": {}}
    for child, parent in parents.items():
        table["under"].setdefault(parent, []).append(child)

    def ppid_map() -> dict[int, int]:
        table["lists"] += 1
        return dict(parents)

    module = types.SimpleNamespace(
        Error=psutil.Error,
        Process=lambda pid: _Proc(pid, born[pid], table),
        _psplatform=types.SimpleNamespace(ppid_map=ppid_map) if can_list else types.SimpleNamespace(),
    )
    return module, table


@pytest.fixture(autouse=True)
def _fresh_table(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pool, "_TABLE", pool._ProcessTable(60.0))


def test_many_shards_share_one_list_of_processes() -> None:
    parents = {10: 1, 11: 10, 12: 11, 20: 1, 21: 20}
    module, table = _fake(parents, {1: 0.0, 10: 5.0, 11: 6.0, 12: 7.0, 20: 5.0, 21: 6.0})
    for _ in range(3):
        for root in (10, 20):
            peaks, seen = {"committed": 0.0, "working_set": 0.0}, {}
            pool._sample(module, root, peaks, seen)
            assert set(seen) == ({10, 11, 12} if root == 10 else {20, 21})
            assert peaks["committed"] == 10.0 * len(seen) and peaks["working_set"] == 5.0 * len(seen)
    assert table["lists"] == 1, "six looks by two shards inside one half second read one list"
    assert table["walks"] == 0


def test_a_process_older_than_the_shard_is_not_counted() -> None:
    module, _table = _fake({10: 1, 11: 10}, {1: 0.0, 10: 5.0, 11: 4.0})  # 11 holds a reused id: it predates 10
    seen: dict = {}
    pool._sample(module, 10, {"committed": 0.0, "working_set": 0.0}, seen)
    assert set(seen) == {10}


def test_without_a_list_of_parents_each_shard_walks_its_own_tree() -> None:
    module, table = _fake({10: 1, 11: 10}, {1: 0.0, 10: 5.0, 11: 6.0}, can_list=False)
    seen: dict = {}
    pool._sample(module, 10, {"committed": 0.0, "working_set": 0.0}, seen)
    assert set(seen) == {10, 11} and table["walks"] == 1


def test_the_real_psutil_can_list_parents() -> None:
    found = pool._ProcessTable(0.0).descendants(psutil, 0)
    assert found is not None, "psutil lost ppid_map: every shard would walk the whole process table again"
