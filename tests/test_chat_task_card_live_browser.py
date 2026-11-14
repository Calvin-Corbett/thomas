"""Serve the real Chat shell so a task card's updates can be looked at live.

Opt-in: set ``THOMAS_TASK_CARD_BROWSER_SECONDS`` to how long you want the app
held open, then browse to the address the test prints.  Everything is the real
application -- ``create_app``, the real Chat page, the real card renderer and
the real ``/detail`` route.  Only the execution it reads is recorded, so the
card updates without calling an external model.

Without that variable the test skips.  Starting and stopping are deliberately
the same test, with the stop in ``finally``: a server started by one test and
killed by another through a PID file survives anything that ends the run in
between, and goes on holding the port with nobody left to close it.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from aiohttp import web

from thomas.core import task_bot_runtime
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app

PORT = 18973
SESSION = "visual-session"
EXECUTION = "visual-exec"


@pytest.mark.asyncio
async def test_live_thomas_serves_a_task_card_you_can_watch_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seconds = float(os.environ.get("THOMAS_TASK_CARD_BROWSER_SECONDS") or 0)
    if seconds <= 0:
        pytest.skip("set THOMAS_TASK_CARD_BROWSER_SECONDS to hold Thomas open and look at the card")
    monkeypatch.setenv("THOMAS_DB_PATH", str(tmp_path / "preferences.db"))
    config = AppConfig(
        models={
            "local": ModelConfig(
                name="local", provider="openai_compat", base_url="http://127.0.0.1:1/v1", model="offline-test"
            )
        },
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path / "memory")),
        server=ServerConfig(access_mode="local"),
    )
    row = {
        "conversation_id": SESSION,
        "state": "in_progress",
        "transitions": [
            {
                "summary": "Build update: Found the task-card update path.",
                "state": "in_progress",
                "occurred_at": "2026-08-05T12:00:00Z",
            }
        ],
    }
    original, reads = task_bot_runtime.get_execution, []

    def recorded_execution(execution_id: str, *args: object, **kwargs: object) -> dict | None:
        """The recorded task, whose history grows a step on the second read."""
        if execution_id != EXECUTION:
            return original(execution_id, *args, **kwargs)
        reads.append(execution_id)
        if len(reads) >= 2 and len(row["transitions"]) == 1:
            row["transitions"].append(
                {
                    "summary": "Build update: Ran the integration check.",
                    "state": "failed",
                    "blocker": "Pass budget exhausted after 30 passes",
                    "occurred_at": "2026-08-05T12:01:00Z",
                }
            )
        return row

    monkeypatch.setattr(task_bot_runtime, "get_execution", recorded_execution)
    runner = web.AppRunner(create_app(config))
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", PORT).start()
        print(f"\nThomas is serving at http://127.0.0.1:{PORT}/ for {seconds:g}s")
        print(f"Task card detail: /api/v2/chat/session/{SESSION}/delegations/{EXECUTION}/detail")
        await asyncio.sleep(seconds)
    finally:
        await runner.cleanup()
