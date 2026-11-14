"""On a PC at its load limit, a check is split into only the shards its files need, not one per pool place.

Measured 2026-11-06 for your "cpu is still capped at 100%": a 67-file check always went out as 16 shards of 4 files,
and each shard pays ~4 CPU-seconds just to start pytest. When the CPUs are idle, spreading wins time; when the PC is
already at its limit, the extra starts compete for the same CPUs. Regression for thomas.server.proof.scheduling.batches
(``spread``) and thomas.server.proof.runner._cpu_busy.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.core import machine_load
from thomas.server.proof import runner, scheduling

FILES = [f"tests/test_{i:02d}.py" for i in range(67)]


def _sizes(*, spread: bool) -> list[int]:
    shards = scheduling.batches(Path("."), FILES, size=12, workers=16, spread=spread)
    assert sorted(rel for shard in shards for rel in shard) == sorted(FILES), "a file was lost or repeated"
    return sorted(len(shard) for shard in shards)


def test_with_room_the_files_spread_over_every_pool_place() -> None:
    assert len(_sizes(spread=True)) == 16


def test_when_busy_only_the_shards_the_files_need() -> None:
    sizes = _sizes(spread=False)
    assert len(sizes) == 6 and max(sizes) <= 12


@pytest.mark.parametrize(
    ("limit", "cpu", "busy"),
    [(90.0, 95.0, True), (90.0, 90.0, True), (90.0, 40.0, False), (0.0, 100.0, False)],
)
def test_busy_means_cpu_at_or_over_the_limit(
    monkeypatch: pytest.MonkeyPatch, limit: float, cpu: float, busy: bool
) -> None:
    monkeypatch.setattr(machine_load, "limit", lambda: limit)
    monkeypatch.setattr(machine_load, "latest", lambda: machine_load.Reading(cpu, 10.0, 1))
    assert runner._cpu_busy() is busy


def test_no_reading_is_not_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(machine_load, "limit", lambda: 90.0)
    monkeypatch.setattr(machine_load, "latest", lambda: None)
    assert runner._cpu_busy() is False


def test_busy_counts_cpu_even_under_the_hard_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(machine_load.CAPPED_ENV, "1")
    monkeypatch.setattr(machine_load, "limit", lambda: 90.0)
    monkeypatch.setattr(machine_load, "latest", lambda: machine_load.Reading(99.0, 10.0, 1))
    assert runner._cpu_busy() is True
