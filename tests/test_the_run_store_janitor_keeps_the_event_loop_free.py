"""The stale-run janitor sweeps the run store off the event loop (2026-10-27).

A freeze dump caught the server's event loop inside run_store.reconcile_stale_runs, called straight from the
janitor's async loop; every request waited while the disk was busy.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from tests.test_server_app_routes_init import _build_test_app, _Memory, _RunStore, _start_client


@pytest.mark.asyncio
async def test_run_store_janitor_sweeps_off_the_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_store = _RunStore()
    swept_on: list[int] = []

    def _reconcile_stale_runs(**kwargs: object) -> int:
        swept_on.append(threading.get_ident())
        return 0

    run_store.reconcile_stale_runs = _reconcile_stale_runs  # type: ignore[method-assign]
    monkeypatch.setattr("thomas.server.app_routes_init._RUN_STORE_JANITOR_INTERVAL_SECONDS", 0.01)
    app, _ = _build_test_app(tmp_path, monkeypatch, run_store_enabled=True, run_store=run_store, memory=_Memory())
    client = await _start_client(app)
    try:
        loop_thread = threading.get_ident()
        await asyncio.sleep(0.05)
    finally:
        await client.close()
    assert swept_on and loop_thread not in swept_on
