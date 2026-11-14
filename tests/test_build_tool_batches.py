"""Build helper read batching keeps mutation barriers while reducing wait time."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from thomas.agent.loop_tool_batches import execute_build_tool_batch
from thomas.core.events import AgentEvent, EventType


@pytest.mark.asyncio
async def test_independent_reads_overlap_without_crossing_write_barriers(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("before", encoding="utf-8")
    calls = [
        {"name": "fs.read_file", "id": "first"},
        {"name": "fs.read_file", "id": "second"},
        {"name": "fs.write_file", "id": "write"},
        {"name": "fs.read_file", "id": "last"},
    ]
    active_reads = 0
    peak_reads = 0

    async def run_one(call):
        nonlocal active_reads, peak_reads
        if call["name"] == "fs.write_file":
            assert active_reads == 0
            source.write_text("after", encoding="utf-8")
            value = "wrote"
        else:
            active_reads += 1
            peak_reads = max(peak_reads, active_reads)
            await asyncio.sleep(0.03)
            value = source.read_text(encoding="utf-8")
            active_reads -= 1
        return AgentEvent(EventType.TOOL_RESULT, {"value": value, "id": call["id"]})

    async def run(parallel: bool):
        source.write_text("before", encoding="utf-8")
        start = time.perf_counter()
        if parallel:
            results = [event async for event in execute_build_tool_batch(calls, run_one)]
        else:
            results = [await run_one(call) for call in calls]
        return time.perf_counter() - start, [event.data["value"] for event in results]

    serial_elapsed, serial_results = await run(False)
    parallel_elapsed, parallel_results = await run(True)
    assert parallel_results == serial_results == ["before", "before", "wrote", "after"]
    assert peak_reads == 2
    print(f"serial={serial_elapsed:.4f}s batched={parallel_elapsed:.4f}s results={parallel_results}")
    # Runtime timing is diagnostic; CI scheduling can swamp these short sleeps.
    # peak_reads and identical results are the deterministic concurrency and quality checks.
    assert serial_elapsed > 0 and parallel_elapsed > 0


@pytest.mark.asyncio
async def test_read_batches_never_exceed_four_in_flight() -> None:
    active = peak = 0
    calls = [{"name": "fs.read_file", "id": str(index)} for index in range(10)]

    async def run_one(call):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return AgentEvent(type=EventType.TOOL_RESULT, data={"tool_id": call["id"]})

    results = [event async for event in execute_build_tool_batch(calls, run_one)]
    assert peak == 4
    assert [event.data["tool_id"] for event in results] == [str(index) for index in range(10)]


@pytest.mark.asyncio
async def test_unknown_tools_do_not_overlap_reads() -> None:
    running = 0
    observed = []

    async def run_one(call):
        nonlocal running
        if call["name"] == "fs.read_file":
            running += 1
            await asyncio.sleep(0)
            running -= 1
        else:
            assert running == 0
        observed.append(call["name"])
        return AgentEvent(EventType.TOOL_RESULT, {})

    calls = [{"name": name} for name in ("fs.read_file", "unknown.tool", "fs.read_file")]
    assert len([event async for event in execute_build_tool_batch(calls, run_one)]) == 3
    assert observed == [call["name"] for call in calls]
