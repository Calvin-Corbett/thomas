"""Bridge durable delegation updates into the active worker's tool boundary.

The ledger is the queue of record; no in-memory queue can survive a server restart.
AgentLoop polls this adapter after each tool result, before its next model turn.
"""

from __future__ import annotations

from pathlib import Path
from queue import Empty

from thomas.core import task_bot_runtime


class DurableSteeringQueue:
    def __init__(self, execution_id: str, repo_root: Path) -> None:
        self.execution_id = execution_id
        self.repo_root = repo_root

    def get_nowait(self) -> str:
        updates = task_bot_runtime.take_pending_instructions(self.execution_id, repo_root=self.repo_root)
        if not updates:
            raise Empty
        return "\n".join(updates)
