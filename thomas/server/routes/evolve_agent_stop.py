"""Stopping a Build run on Praxis's word: Build binds it into Praxis's stop hook."""

from __future__ import annotations

from typing import Any

from . import evolve_agent_run_state, evolve_agent_runtime


async def stop_code_run(app: Any, run_id: str) -> bool:
    slot = evolve_agent_run_state.slot_for_run_id(app, run_id)
    if slot is None:
        return False
    proc = (slot.get("session") or {}).get("proc")
    if proc is None or proc.returncode is not None:
        return False
    evolve_agent_runtime._mark_stop_requested(proc)
    receipt = await evolve_agent_runtime._terminate_process(proc)
    return bool(receipt.get("termination_confirmed"))
