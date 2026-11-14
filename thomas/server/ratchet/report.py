"""What the ratchet has found and done, read from its files alone: for GET /api/ratchet and for Chat.

No git runs here: the census is the last discovery, the ledger says what happened
to each candidate since, and the halt says whether every run is stopped.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from thomas.server import self_change_status
from thomas.server.ratchet.candidates import read_census
from thomas.server.ratchet.ledger import WITHDRAWN, Ledger, ratchet_root


def _row(sha: str, ref: str, refs: Any, files: int, state: str, reason: str, event: dict[str, Any]) -> dict[str, Any]:
    sid = str(event.get("submission") or "")
    if (
        state == "awaiting_card"
        and sid
        and (self_change_status.read_hand_in_state(sid) or {}).get("status") == "withdrawn"
    ):
        state, reason = "queued", WITHDRAWN
    return {
        "sha": sha,
        "ref": ref,
        "refs": list(refs or [ref]),
        "files": files,
        "state": state,
        "reason": reason,
        "at": str(event.get("at") or ""),
        "landed_commit": str(event.get("landed_commit") or ""),
    }


def read_report(root: Path | None = None) -> dict[str, Any]:
    folder = root or ratchet_root()
    census = read_census(folder)
    book = Ledger(folder / "ledger.jsonl")
    latest = book.latest()
    rows: list[dict[str, Any]] = []
    listed: set[str] = set()
    for cand in census.get("candidates") or []:
        sha = str(cand.get("sha") or "")
        event = latest.get(sha, {})
        state = str(event.get("state") or "queued")
        reason = str(event.get("reason") or "not proven yet")
        ref, refs = str(cand.get("ref") or ""), cand.get("refs")
        rows.append(_row(sha, ref, refs, len(cand.get("files") or []), state, reason, event))
        listed.add(sha)
    for skip in census.get("skipped") or []:
        sha = str(skip.get("sha") or "")
        refs = skip.get("refs") or [""]
        state = str(skip.get("status") or "not_for_ratchet")
        rows.append(_row(sha, str(refs[0]), refs, 0, state, str(skip.get("reason") or ""), latest.get(sha, {})))
        listed.add(sha)
    for sha, event in latest.items():
        if sha not in listed:
            files = len(event.get("files") or [])
            state, reason = str(event.get("state") or ""), str(event.get("reason") or "")
            ref = str(event.get("candidate_ref") or "")
            rows.append(_row(sha, ref, event.get("refs"), files, state, reason, event))
    return {
        "dev_sha": str(census.get("dev_sha") or ""),
        "discovered_at": str(census.get("discovered_at") or ""),
        "counts": dict(Counter(row["state"] for row in rows)),
        "candidates": rows,
        "halted": book.halted() or {},
    }


__all__ = ["read_report"]
