"""A check shard's memory is measured and kept apart from Build's, and the reserve is counted once.

Spec 2026-10-12 Part 1 item 1: shards are sized at 1.25 times the p90 of their committed memory, under their own
profile key, written under a lock; ``observed_peaks_mb``, which sizes Build runs and the cage shell runner, is not
touched. The worker formula used to subtract the reserve from memory that was already free.
"""

from __future__ import annotations

import contextlib
import json
import math
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from thomas.core import machine_capacity as mc

GIB = 1024**3
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def profile_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(mc, "_default_data_dir", lambda: tmp_path)
    monkeypatch.setattr(mc, "_memory", lambda: (32 * GIB, 20 * GIB))
    mc.profile()
    return tmp_path


def test_a_shard_peak_is_recorded_under_its_own_key_and_never_moves_the_run_budget(profile_dir: Path) -> None:
    before = mc.profile()

    for n in range(6):
        mc.record_check_shard_peak(100.0 + n, 50.0 + n)

    after = mc.profile()
    assert after[mc.CHECK_SHARD_PEAKS_KEY] == [{"committed": 100.0 + n, "working_set": 50.0 + n} for n in range(6)]
    for key in ("observed_peaks_mb", "run_budget_mb", "limit"):
        assert after[key] == before[key], key


def test_a_shard_is_sized_at_one_and_a_quarter_times_the_p90_of_committed_memory(profile_dir: Path) -> None:
    for committed in range(100, 1001, 100):
        mc.record_check_shard_peak(float(committed), 5000.0)

    assert mc.check_shard_mb() == math.ceil(900 * 1.25) == 1125, "the working set never sizes a shard"


def test_before_five_shard_samples_a_shard_gets_the_default_size(profile_dir: Path) -> None:
    for _ in range(4):
        mc.record_check_shard_peak(3000.0, 3000.0)

    assert mc.check_shard_mb() == mc.DEFAULT_CHECK_SHARD_MB == mc.DEFAULT_RUN_BUDGET_MB


def test_shard_peaks_and_run_peaks_written_at_once_lose_nothing(
    profile_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = mc._write_profile

    def slow(path: Path, payload: dict) -> None:
        threading.Event().wait(0.01)  # widen the window between reading the profile and writing it back
        real(path, payload)

    monkeypatch.setattr(mc, "_write_profile", slow)

    def shards() -> None:
        for _ in range(10):
            mc.record_check_shard_peak(200.0, 100.0)

    def runs() -> None:
        for _ in range(5):
            mc.record_run_peak(300.0)

    threads = [threading.Thread(target=shards) for _ in range(4)] + [threading.Thread(target=runs)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)

    prof = mc.profile()
    assert len(prof[mc.CHECK_SHARD_PEAKS_KEY]) == 40
    assert len(prof["observed_peaks_mb"]) == 5


WRITER = r"""
import sys, threading
from pathlib import Path
from thomas.core import machine_capacity as mc
folder = Path(sys.argv[1])
mc._default_data_dir = lambda: folder
mc._memory = lambda: (32 * 1024**3, 20 * 1024**3)
real = mc._write_profile
def slow(path, payload):
    threading.Event().wait(0.01)
    real(path, payload)
mc._write_profile = slow
for _ in range(20):
    mc.record_check_shard_peak(200.0, 100.0)
"""


def test_two_processes_writing_shard_peaks_at_once_lose_nothing(profile_dir: Path) -> None:
    children = [subprocess.Popen([sys.executable, "-c", WRITER, str(profile_dir)], cwd=REPO) for _ in range(2)]
    for child in children:
        assert child.wait(120) == 0

    assert len(mc.profile()[mc.CHECK_SHARD_PEAKS_KEY]) == 40, "a load run and a server write one profile"


def test_a_busy_profile_is_read_again_and_never_written_over(
    profile_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mc.record_run_peak(300.0)
    mc.record_check_shard_peak(200.0, 100.0)
    path = profile_dir / "machine_capacity.json"
    real = Path.read_text
    refusals = [1]  # the next read meets a file another process is replacing at that instant

    def read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self == path and refusals:
            refusals.pop()
            raise PermissionError(13, "Access is denied")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    mc.record_check_shard_peak(201.0, 101.0)
    refusals.extend([1] * 50)  # from now on the file stays busy
    assert mc.profile()["observed_peaks_mb"] == [], "an estimate kept in memory, not the file"
    with pytest.raises(PermissionError):
        mc.record_check_shard_peak(202.0, 102.0)

    saved = json.loads(path.read_bytes())
    assert saved["observed_peaks_mb"] == [300.0]
    assert [sample["committed"] for sample in saved[mc.CHECK_SHARD_PEAKS_KEY]] == [200.0, 201.0]


def test_reads_beside_a_writer_never_shrink_the_peak_lists(profile_dir: Path) -> None:
    for n in range(5):
        mc.record_run_peak(300.0 + n)
        mc.record_check_shard_peak(400.0 + n, 100.0)
    path = profile_dir / "machine_capacity.json"
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    stop = threading.Event()

    def replace_it_again_and_again() -> None:
        while not stop.is_set():
            with contextlib.suppress(PermissionError):
                mc._write_profile(path, snapshot)

    writer = threading.Thread(target=replace_it_again_and_again)
    writer.start()
    try:
        sizes = {mc.check_shard_mb() for _ in range(200)}
    finally:
        stop.set()
        writer.join(10)
    assert sizes == {math.ceil(404.0 * 1.25)}, "a read that met the writer never fell back to a fresh profile"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert len(saved["observed_peaks_mb"]) == 5 and len(saved[mc.CHECK_SHARD_PEAKS_KEY]) == 5


def test_the_reserve_is_counted_once() -> None:
    assert mc.usable_memory_bytes(32 * GIB, 11 * GIB) == 11 * GIB
    assert mc.usable_memory_bytes(32 * GIB, 30 * GIB) == 24 * GIB
    assert mc.usable_memory_bytes(None, 5 * GIB) == 5 * GIB
    assert mc.usable_memory_bytes(None, None) is None
