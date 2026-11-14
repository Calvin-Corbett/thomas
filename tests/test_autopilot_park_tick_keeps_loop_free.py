"""Park maintenance must not stall other teams while it reads stored conversations."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.core.event_loop_offload import reset_offload_receipts, slowest_offloads
from thomas.server import autopilot_park as parks
from thomas.server import thomas_project


@pytest.mark.asyncio
async def test_twenty_five_parked_conversations_do_not_block_the_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop_thread = threading.get_ident()
    read_threads: list[int] = []
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    live = tmp_path / "live.json"
    live.touch()
    rows = {f"team-{i}": {"project_root": str(tmp_path)} for i in range(25)}
    monkeypatch.setattr(parks, "_snapshot_parks", lambda _catalog: (time.sleep(0.12), rows)[1])
    monkeypatch.setattr(parks, "_run_active", lambda *_args: False)

    def live_file(_root: Path, _cid: str) -> Path:
        return live  # an existing path; no actual conversation contents needed

    def read_live(_root: Path, _catalog: Path, _cid: str) -> dict:
        read_threads.append(threading.get_ident())
        time.sleep(0.12)
        return {"turns": []}

    monkeypatch.setattr(thomas_project, "_live_file", live_file)
    monkeypatch.setattr(thomas_project, "_read_live", read_live)
    from thomas.server.routes import evolve_agent_autopilot as ap

    monkeypatch.setattr(ap, "decide", lambda _: SimpleNamespace(action="wait", retry_at=time.time() + 3600))
    reset_offload_receipts()
    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    task = asyncio.create_task(heartbeat())
    try:
        assert await parks.resume_due({}, catalog) == []
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    assert ticks >= 30, f"the loop missed turns while reading 25 parked conversations: {ticks}"
    assert len(read_threads) == 25 and all(t != loop_thread for t in read_threads)
    labels = {entry["label"] for entry in slowest_offloads()}
    assert {"autopilot.read_parks", "autopilot.read_live"} <= labels
