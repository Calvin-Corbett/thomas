"""The run timeline measures dependency overlap from observed activity only."""

import asyncio

import pytest

from thomas.core.praxis.timelines import build_report, dependency_overlap, sanitize_tools
from thomas.server.praxis.run_channel import RunChannel


def test_queued_time_and_finished_dependencies_do_not_count_as_overlap():
    rows = [
        {
            "agent_id": "base",
            "state": "completed",
            "activity_intervals": [(2.0, 5.0)],
            "dependencies": [],
            "attempts": 1,
        },
        {
            "agent_id": "dependent",
            "state": "completed",
            "activity_intervals": [(4.0, 7.0)],
            "dependencies": ["base"],
            "attempts": 1,
        },
    ]
    report = build_report(rows)
    assert report["dependency_overlap"] == {
        "integral_builder_seconds": 1.0,
        "span_s": 5.0,
        "mean_concurrent": 0.2,
        "peak": 1,
        "time_with_any_overlap_s": 1.0,
        "fraction_time_at_least_10": 0.0,
        "segments": 3,
    }
    assert report["agents"][1]["active_s"] == 3.0


def test_live_interval_and_tool_arguments_are_not_exposed():
    report = build_report(
        [{"agent_id": "live", "state": "running", "attempt_started_at": 10.0, "activity_intervals": []}],
        now=12.5,
    )
    assert report["agents"][0]["active_s"] == 2.5
    assert sanitize_tools([{"tool": "read", "start": 1, "end": 2, "outcome": "ok", "arguments": "SECRET"}]) == [
        {"tool": "read", "start": 1, "end": 2, "outcome": "ok"}
    ]
    assert dependency_overlap({}, {})["peak"] == 0


@pytest.mark.asyncio
async def test_live_run_status_reports_observed_active_time():
    release = asyncio.Event()

    async def child(_agent_id, _kind, _title, _brief):
        await release.wait()
        yield {"type": "done", "text": "read"}

    channel = RunChannel("timeline-test", child)
    handles = await channel.spawn([{"kind": "review", "title": "Read", "brief": "Inspect"}])
    await asyncio.sleep(0.01)
    report = channel.status()
    assert report["agents"][0]["agent_id"] == handles[0]["agent_id"]
    assert report["agents"][0]["active_s"] > 0
    assert report["metrics"]["dependency_overlap"]["peak"] == 0
    release.set()
    await asyncio.gather(*channel._tasks.values())
    assert channel.status()["agents"][0]["active_s"] > 0
