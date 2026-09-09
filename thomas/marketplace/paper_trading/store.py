"""Local-first persistence for proposals and the trade journal.

State lives in a single JSON file under the plugin data dir, written atomically
(tmp + fsync + os.replace). This mirrors the persistence pattern used by the
Life Manager plugin and the core scheduler.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from thomas.marketplace.paper_trading._exceptions import ProposalNotFound
from thomas.marketplace.paper_trading._types import (
    JournalEntry,
    Proposal,
    ProposalStatus,
)

_STATE_VERSION = 1


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _today_utc() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


class PaperTradingStore:
    """JSON-backed store for proposals and journal entries.

    Not designed for high concurrency; the workload is one human + one agent on a
    local desktop. Reads reload from disk so the route and the agent tools (which
    construct independent stores over the same path) stay consistent.
    """

    def __init__(self, state_path: Path) -> None:
        self._path = Path(state_path)

    # --- low-level ----------------------------------------------------------
    def _default(self) -> dict[str, Any]:
        return {
            "version": _STATE_VERSION,
            "updated_at": _now_iso(),
            "proposals": [],
            "journal": [],
        }

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return self._default()
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return self._default()
        if not isinstance(payload, dict):
            return self._default()
        state = self._default()
        if isinstance(payload.get("proposals"), list):
            state["proposals"] = payload["proposals"]
        if isinstance(payload.get("journal"), list):
            state["journal"] = payload["journal"]
        return state

    def _save(self, state: dict[str, Any]) -> None:
        state["version"] = _STATE_VERSION
        state["updated_at"] = _now_iso()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        body = json.dumps(state, ensure_ascii=False, indent=2)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._path)

    # --- proposals ----------------------------------------------------------
    def add_proposal(self, proposal: Proposal) -> Proposal:
        state = self._load()
        state["proposals"].append(proposal.to_dict())
        self._save(state)
        return proposal

    def list_proposals(self, status: str | None = None) -> list[Proposal]:
        state = self._load()
        rows = [Proposal(**row) for row in state["proposals"]]
        if status:
            rows = [p for p in rows if p.status == status]
        return rows

    def get_proposal(self, proposal_id: str) -> Proposal:
        state = self._load()
        for row in state["proposals"]:
            if row.get("id") == proposal_id:
                return Proposal(**row)
        raise ProposalNotFound(proposal_id)

    def update_proposal(self, proposal: Proposal) -> Proposal:
        state = self._load()
        found = False
        for idx, row in enumerate(state["proposals"]):
            if row.get("id") == proposal.id:
                state["proposals"][idx] = proposal.to_dict()
                found = True
                break
        if not found:
            raise ProposalNotFound(proposal.id)
        self._save(state)
        return proposal

    def count_trades_today(self) -> int:
        """Number of proposals that reached the broker today (UTC).

        Used by the risk engine to enforce ``max_trades_per_day``. Counts
        submitted/filled proposals whose decision happened today.
        """
        state = self._load()
        today = _today_utc()
        counted = 0
        terminal = {
            ProposalStatus.SUBMITTED.value,
            ProposalStatus.FILLED.value,
        }
        for row in state["proposals"]:
            if row.get("status") in terminal:
                stamp = str(row.get("submitted_at") or row.get("decided_at") or "")
                if stamp.startswith(today):
                    counted += 1
        return counted

    # --- journal ------------------------------------------------------------
    def append_journal(self, entry: JournalEntry) -> JournalEntry:
        state = self._load()
        state["journal"].append(entry.to_dict())
        self._save(state)
        return entry

    def list_journal(self) -> list[JournalEntry]:
        state = self._load()
        return [JournalEntry(**row) for row in state["journal"]]

    def update_journal(self, entry: JournalEntry) -> JournalEntry:
        state = self._load()
        for idx, row in enumerate(state["journal"]):
            if row.get("id") == entry.id:
                state["journal"][idx] = entry.to_dict()
                break
        self._save(state)
        return entry
