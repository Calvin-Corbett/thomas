"""Keep a completed run's automatic handoff pending until it is resolved."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

_sleep = asyncio.sleep
RETRY_DELAY_S = 30.0


async def start_repair_handoff(app: Any, project_root: Path, catalog_root: Path, cid: str) -> Any:
    from thomas.server.routes import evolve_agent_autopilot as ap

    decision = await ap.continue_after_turn(app, project_root, catalog_root, cid)
    if decision is not None and decision.start_pending:

        async def retry() -> None:
            await _sleep(RETRY_DELAY_S)
            await finish_handoff(app, project_root, catalog_root, cid)

        asyncio.create_task(retry())
    return decision


async def finish_handoff(app: Any, project_root: Path, catalog_root: Path, cid: str) -> None:
    while True:
        try:
            await _finish_handoff(app, project_root, catalog_root, cid)
            return
        except (OSError, RuntimeError):
            await _sleep(RETRY_DELAY_S)


async def _finish_handoff(app: Any, project_root: Path, catalog_root: Path, cid: str) -> None:
    from thomas.server.autopilot_restart import defer_until_reload
    from thomas.server.routes import evolve_agent_autopilot as ap
    from thomas.server.routes.evolve_agent_receipts import _action_receipt, _save_action_receipt

    conversation = ap._load_joined_conversation(project_root, catalog_root, cid)
    if conversation is None:
        return
    user = next((turn for turn in reversed(conversation.get("turns") or []) if turn.get("role") == "user"), {})
    request_id = str(user.get("request_id") or "")
    if request_id:
        await asyncio.to_thread(defer_until_reload, catalog_root, conversation, cid)
    while True:
        decision = await ap.after_run(app, project_root, catalog_root, cid)
        if decision is not None and not decision.start_pending:
            if request_id:
                receipt = await asyncio.to_thread(_action_receipt, catalog_root, "run", request_id)
                if receipt and receipt.get("state") == "after_run_pending":
                    await asyncio.to_thread(
                        _save_action_receipt, catalog_root, "run", request_id, {**receipt, "state": "finished"}
                    )
            return
        await _sleep(RETRY_DELAY_S)
        fresh = ap._load_joined_conversation(project_root, catalog_root, cid)
        if fresh is None or fresh.get("turns") != conversation.get("turns"):
            return
        conversation = fresh
