"""The Thomas project list stays responsive during a slow full scan."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from thomas.server.routes.self_project_listing_cache import read_listing


@pytest.mark.asyncio
async def test_full_listing_refresh_keeps_last_complete_cards_and_never_blocks_start() -> None:
    entered = threading.Event()
    release = threading.Event()
    slot: dict = {}
    calls = 0

    def reader(_catalog: Path, _running: set[str]) -> dict:
        nonlocal calls
        calls += 1
        if calls == 2:
            entered.set()
            release.wait(5)
        return {
            "ok": True,
            "projects": [{"title": f"project {calls}", "changed_files": ["file.py"]}],
            "unreadable": ["unreadable green"],
        }

    try:
        first = await read_listing(slot, Path("catalog"), set(), reader)
        assert first["projects"][0]["title"] == "project 1"
        assert first["unreadable"] == ["unreadable green"]
        assert not first["refreshing"]

        slot["updated"] = 0  # force a refresh even though the snapshot is recent
        stale = await asyncio.wait_for(read_listing(slot, Path("catalog"), set(), reader), 1)
        assert stale["refreshing"]
        assert stale["projects"] == first["projects"]
        assert stale["unreadable"] == first["unreadable"]
        started = asyncio.Event()
        await asyncio.wait_for(started.set() or started.wait(), 1)
        release.set()
        await asyncio.wait_for(slot["task"], 2)
        fresh = await read_listing(slot, Path("catalog"), set(), reader)
        assert fresh["projects"][0]["title"] == "project 2"
    finally:
        release.set()
        if slot.get("task"):
            await asyncio.wait_for(slot["task"], 6)


@pytest.mark.asyncio
async def test_cold_listing_returns_quickly_and_later_includes_complete_scan() -> None:
    entered = threading.Event()
    release = threading.Event()
    slot: dict = {}

    def reader(_catalog: Path, _running: set[str]) -> dict:
        entered.set()
        release.wait(5)
        return {"ok": True, "projects": [{"title": "live"}], "unreadable": ["one inaccessible copy"]}

    try:
        cold = await asyncio.wait_for(read_listing(slot, Path("catalog"), set(), reader), 1)
        assert entered.is_set() and cold == {"ok": True, "projects": [], "unreadable": [], "refreshing": True}
        release.set()
        await asyncio.wait_for(slot["task"], 2)
        fresh = await read_listing(slot, Path("catalog"), set(), reader)
        assert fresh["projects"] == [{"title": "live"}]
        assert fresh["unreadable"] == ["one inaccessible copy"]
    finally:
        release.set()
        if slot.get("task"):
            await asyncio.wait_for(slot["task"], 6)


@pytest.mark.asyncio
async def test_start_during_scan_requires_a_post_start_scan_before_listing_is_complete() -> None:
    entered = threading.Event()
    release = threading.Event()
    slot: dict = {}
    names = ["first"]
    scans: list[list[str]] = []

    def reader(_catalog: Path, _running: set[str]) -> dict:
        seen = list(names)
        scans.append(seen)
        if len(scans) == 2:
            entered.set()
            release.wait(5)
        return {"ok": True, "projects": [{"title": name} for name in seen], "unreadable": []}

    try:
        first = await read_listing(slot, Path("catalog"), set(), reader)
        assert first["projects"] == [{"title": "first"}]
        slot["updated"] = 0
        await read_listing(slot, Path("catalog"), set(), reader)
        assert await asyncio.to_thread(entered.wait, 1)
        names.append("second")
        slot["dirty"] = True  # POST succeeded while an older scan was in flight
        during = await read_listing(slot, Path("catalog"), set(), reader)
        assert during["refreshing"] and during["projects"] == first["projects"]
        release.set()
        await asyncio.wait_for(slot["task"], 2)
        after = await read_listing(slot, Path("catalog"), set(), reader)
        assert scans == [["first"], ["first"], ["first", "second"]]
        assert not after["refreshing"]
        assert after["projects"] == [{"title": "first"}, {"title": "second"}]
    finally:
        release.set()
        if slot.get("task"):
            await asyncio.wait_for(slot["task"], 6)


@pytest.mark.asyncio
async def test_start_just_after_scan_invalidates_even_a_recent_complete_listing() -> None:
    slot: dict = {}
    names = ["first"]

    def reader(_catalog: Path, _running: set[str]) -> dict:
        return {"ok": True, "projects": list(names), "unreadable": []}

    await read_listing(slot, Path("catalog"), set(), reader)
    names.append("second")
    slot["dirty"] = True
    pending = await read_listing(slot, Path("catalog"), set(), reader)
    assert pending["refreshing"]
    await asyncio.wait_for(slot["task"], 2)
    fresh = await read_listing(slot, Path("catalog"), set(), reader)
    assert fresh["projects"] == ["first", "second"] and not fresh["refreshing"]


@pytest.mark.asyncio
async def test_failed_cold_scan_is_not_reported_as_an_empty_complete_list() -> None:
    def broken(_catalog: Path, _running: set[str]) -> dict:
        raise OSError("unreadable catalogue")

    report = await read_listing({}, Path("catalog"), set(), broken)
    assert report["ok"] is False
    assert report["error"] and not report["refreshing"]
    assert "projects" not in report


@pytest.mark.asyncio
async def test_failed_refresh_preserves_old_cards_but_marks_them_stale() -> None:
    slot: dict = {}
    calls = 0

    def reader(_catalog: Path, _running: set[str]) -> dict:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("unreadable catalogue")
        return {"ok": True, "projects": ["still visible"], "unreadable": []}

    await read_listing(slot, Path("catalog"), set(), reader)
    slot["updated"] = 0
    await read_listing(slot, Path("catalog"), set(), reader)
    await asyncio.wait_for(slot["task"], 2)
    stale = await read_listing(slot, Path("catalog"), set(), reader)
    assert stale["projects"] == ["still visible"]
    assert stale["refreshing"] and slot["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [{"ok": False}, {"incomplete": True}, {"unreadable": ["green"]}])
async def test_partial_refresh_keeps_complete_cards_and_blocks_capacity(failure) -> None:
    from thomas.server.self_project_queue_tick import queue_status

    slot: dict = {}
    complete = {"ok": True, "projects": [{"conversation_id": "live", "state": "running"}], "unreadable": []}
    partial = {"ok": True, "projects": [], "unreadable": [], **failure}
    result = complete

    def reader(_catalog: Path, _running: set[str]) -> dict:
        return result

    await read_listing(slot, Path("catalog"), set(), reader)
    captured_at = slot["captured_at"]
    result = partial
    slot["updated"] = 0
    await read_listing(slot, Path("catalog"), set(), reader)
    await asyncio.wait_for(slot["task"], 2)
    stale = await read_listing(slot, Path("catalog"), set(), reader)
    assert stale["projects"] == complete["projects"]
    assert stale["refreshing"] and stale["incomplete"]
    assert slot["captured_at"] == captured_at
    capacity = queue_status({"self_project_listing_slot": slot}, {"queued": []})
    assert capacity["running"] is None and capacity["blocked_by"]

    result = {**complete, "projects": [{"conversation_id": "new", "state": "running"}]}
    slot["updated"] = 0
    await read_listing(slot, Path("catalog"), set(), reader)
    await asyncio.wait_for(slot["task"], 2)
    fresh = await read_listing(slot, Path("catalog"), set(), reader)
    assert fresh["projects"] == result["projects"]
    assert not fresh["refreshing"] and not fresh.get("incomplete")
    assert not slot.get("error")
