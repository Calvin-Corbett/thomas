"""The machine-wide gate slots (scripts/crew/brief/gate_slots.py): a limit on how many commit gates run at once.

A slot is a byte-range lock on a small file, so the operating system drops it when the holder ends, however it ends. These
tests use real locks, including one held by a second process that is then killed.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest
from scripts.crew.brief import gate_slots
from scripts.crew.brief.gate_slots import SlotPool

PY = sys.executable
HOLDER = """
import sys, time
from pathlib import Path
from scripts.crew.brief import gate_slots
pool = gate_slots.SlotPool(Path(sys.argv[1]), int(sys.argv[2]), wait_seconds=30)
with pool.hold() as got:
    print("held" if got else "not held", flush=True)
    time.sleep(120)
"""


def test_the_default_is_half_the_cores_and_never_fewer_than_four() -> None:
    assert gate_slots.slot_count({}, cpus=16) == 8
    assert gate_slots.slot_count({}, cpus=4) == 4
    assert gate_slots.slot_count({}, cpus=1) == 4
    assert gate_slots.slot_count({}, cpus=128) == 64


def test_the_slot_count_can_be_set_and_zero_turns_the_limit_off() -> None:
    assert gate_slots.slot_count({gate_slots.SLOTS_ENV: "3"}) == 3
    assert gate_slots.slot_count({gate_slots.SLOTS_ENV: "0"}) == 0
    assert gate_slots.slot_count({gate_slots.SLOTS_ENV: "-2"}) == 0
    assert gate_slots.slot_count({gate_slots.SLOTS_ENV: "5000"}) == gate_slots.MAX_SLOTS
    assert gate_slots.slot_count({gate_slots.SLOTS_ENV: "many"}, cpus=16) == 8


def test_the_slot_files_live_in_the_configured_directory_or_the_temporary_one(tmp_path: Path) -> None:
    assert gate_slots.slot_dir({gate_slots.DIR_ENV: str(tmp_path)}) == tmp_path / "thomas-gate-slots"
    assert gate_slots.slot_dir({}).name == "thomas-gate-slots"


def test_slots_are_handed_out_one_per_holder_and_taken_back(tmp_path: Path) -> None:
    pool = SlotPool(tmp_path, 2, wait_seconds=0.3)
    with pool.hold() as first, pool.hold() as second:
        assert (first, second) == (True, True)
        with pool.hold() as third:  # both taken: waits the limit, then goes ahead without one
            assert third is False
        assert pool.gave_up == 1
    with pool.hold() as again, pool.hold() as again_too:  # both were given back
        assert (again, again_too) == (True, True)
    assert pool.gave_up == 1


def test_a_slot_is_given_back_when_the_block_raises(tmp_path: Path) -> None:
    pool = SlotPool(tmp_path, 1, wait_seconds=0.2)
    with pytest.raises(RuntimeError), pool.hold():
        raise RuntimeError("the gate blew up")
    with pool.hold() as got:
        assert got is True


def test_a_directory_that_cannot_be_used_means_no_limit_and_no_wait(tmp_path: Path) -> None:
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory")
    pool = SlotPool(blocker / "slots", 1, wait_seconds=30)
    started = time.monotonic()
    with pool.hold() as got:
        assert got is False
    assert time.monotonic() - started < 2.0 and pool.gave_up == 0


def test_a_slot_held_by_another_process_is_not_available_and_dies_with_that_process(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    holder = subprocess.Popen(
        [PY, "-c", HOLDER, str(tmp_path), "1"],
        cwd=root,
        stdout=subprocess.PIPE,
        text=True,
        creationflags=0x08000000 if sys.platform == "win32" else 0,
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "held"
        with SlotPool(tmp_path, 1, wait_seconds=0.4).hold() as got:
            assert got is False, "a slot held by another process was handed out"
        holder.kill()  # no cleanup runs: the operating system must drop the lock
        holder.wait(timeout=20)
        with SlotPool(tmp_path, 1, wait_seconds=10).hold() as got_after:
            assert got_after is True, "a killed holder left its slot taken"
    finally:
        if holder.poll() is None:
            holder.kill()
        if holder.stdout is not None:
            holder.stdout.close()


def test_a_waiting_gate_gets_the_slot_as_soon_as_it_is_given_back(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    holder = subprocess.Popen(
        [PY, "-c", HOLDER, str(tmp_path), "1"],
        cwd=root,
        stdout=subprocess.PIPE,
        text=True,
        creationflags=0x08000000 if sys.platform == "win32" else 0,
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "held"
        waiter = SlotPool(tmp_path, 1, wait_seconds=60)
        started = time.monotonic()
        killer = _after(1.0, holder.kill)
        with waiter.hold() as got:
            waited = time.monotonic() - started
            assert got is True and 0.8 < waited < 30
        killer.join()
    finally:
        if holder.poll() is None:
            holder.kill()
        if holder.stdout is not None:
            holder.stdout.close()


def _after(seconds: float, action):
    import threading

    timer = threading.Timer(seconds, action)
    timer.start()
    return timer


def test_every_file_a_slot_opens_is_closed_again(tmp_path: Path, monkeypatch) -> None:
    opened: list[int] = []
    closed: list[int] = []
    real_open, real_close = os.open, os.close

    def spy_open(*args, **kwargs) -> int:
        opened.append(real_open(*args, **kwargs))
        return opened[-1]

    def spy_close(fd: int) -> None:
        closed.append(fd)
        real_close(fd)

    # only this module sees the spies: a copy of os with two functions swapped
    names = {name: getattr(os, name) for name in dir(os)}
    names.update(open=spy_open, close=spy_close)
    monkeypatch.setattr(gate_slots, "os", types.SimpleNamespace(**names))
    pool = SlotPool(tmp_path, 2, wait_seconds=0.2)
    with pool.hold(), pool.hold():
        pass
    with pool.hold():
        pass
    assert opened and sorted(opened) == sorted(closed), "a slot left a file open"
