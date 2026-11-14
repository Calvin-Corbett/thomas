import asyncio

import pytest

from thomas.core.agent_vitals import VitalsHistory, sample_loop
from thomas.core.machine_load import Reading


def test_an_empty_history_has_no_latest():
    snap = VitalsHistory().snapshot()
    assert snap["cpu"] == [] and snap["memory"] == [] and snap["latest"] is None


def test_the_history_keeps_only_the_newest_points():
    h = VitalsHistory(size=3)
    for i in range(5):
        h.record(float(i), float(i * 10), ts=float(i))
    snap = h.snapshot()
    assert snap["cpu"] == [2.0, 3.0, 4.0]
    assert snap["memory"] == [20.0, 30.0, 40.0]
    assert snap["latest"] == {"cpu": 4.0, "memory": 40.0, "ts": 4.0}


def test_values_are_clamped_to_zero_to_one_hundred():
    h = VitalsHistory()
    h.record(150.0, -5.0, ts=1.0)
    snap = h.snapshot()
    assert snap["cpu"] == [100.0] and snap["memory"] == [0.0]


@pytest.mark.asyncio
async def test_the_loop_records_a_reading_and_skips_an_unreadable_one():
    h = VitalsHistory()
    readings = iter([Reading(10.0, 20.0, 1), None, Reading(30.0, 40.0, 2)])
    task = asyncio.create_task(sample_loop(h, read=lambda: next(readings, None), interval=0.01))
    await asyncio.sleep(0.15)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert h.snapshot()["cpu"][:2] == [10.0, 30.0]
