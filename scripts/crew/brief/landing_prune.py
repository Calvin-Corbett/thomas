"""Pruning for the landing queue: drop finished tickets and their ledger lines below a number, safely while others poll.

The lane decides WHICH tickets may go (every one below ``below`` is finished). This module writes one ``pruned`` ledger
line that says what was removed on purpose (a ticket floor and the removed event numbers), then removes the files, so
``verify`` and the number counters keep working and nothing about a prune looks like tampering. Readers that list the
folder while files vanish skip the missing file; a second pruner is kept out by a lock file.
"""

from __future__ import annotations

import os
import time
from typing import Any

from scripts.crew.brief.landing_files import numbers

LOCK_STALE = 60.0
PER_TICKET = ("output", "logs")  # folders of files named T<ticket>-<stage>.txt or T<ticket>.log, one ticket each


def _merge(pairs: list[list[int]]) -> list[list[int]]:
    out: list[list[int]] = []
    for lo, hi in sorted(pairs):
        if out and lo <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return out


def _drop(path: Any) -> bool:
    """Delete a file; False when the OS refuses (on Windows a reader holds it open): skipped, never fatal."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return False
    return True


def _drop_per_ticket(root: Any, removed: set[int]) -> None:
    """A pruned ticket's refusal output and worker log go with it."""
    for folder in PER_TICKET:
        try:
            names = os.listdir(root / folder)
        except OSError:
            continue
        for name in names:
            digits = name[1:].split("-")[0].split(".")[0]
            if name.startswith("T") and digits.isascii() and digits.isdecimal() and int(digits) in removed:
                _drop(root / folder / name)


def _lock(store: Any) -> bool:
    path = store.root / "prune.lock"
    try:
        if time.time() - path.stat().st_mtime > LOCK_STALE:
            path.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        return True
    except OSError:
        return False


def prune_below(store: Any, below: int, *, now: float) -> int:
    """Remove every ticket numbered below ``below`` (the caller guarantees they are finished). Returns tickets removed."""
    store.root.mkdir(parents=True, exist_ok=True)
    if not _lock(store):
        return 0
    try:
        events = store.events()
        old = [e for e in events if e.get("kind") == "pruned"]
        gone = [
            e for e in events if e.get("kind") not in ("pruned", "unreadable") and 0 < int(e.get("ticket") or 0) < below
        ]
        tickets = [n for n in numbers(store.dirs["tickets"], "T") if n < below]
        if not tickets and not gone:
            return 0
        ranges = [list(r) for e in old for r in e.get("ranges") or []]
        floor = max([below] + [int(e.get("ticket_below") or 1) for e in old])
        removed_seqs = [int(e["seq"]) for e in gone] + [int(e["seq"]) for e in old]
        # Recorded first: a crash half way leaves a line that over-claims, which is harmless, never a gap that looks forged.
        merged = _merge(ranges + [[x, x] for x in removed_seqs])
        store.append(
            "pruned", 0, by="lane:prune", now=now, ticket_below=floor, ranges=merged, removed_tickets=len(tickets)
        )
        removed = {
            n for n in tickets if _drop(store.dirs["tickets"] / f"T{n:06d}.json")
        }  # tickets first: never a ghost
        for n in tickets:
            store._seen.pop(("T", n), None)
            store.drop_live(n)
        _drop_per_ticket(store.root, removed)
        for e in gone + old:  # a ledger file a reader has open is skipped and found again by the next prune
            if e.get("kind") == "pruned" or int(e["ticket"]) in removed:
                store._seen.pop(("E", int(e["seq"])), None)
                _drop(store.dirs["ledger"] / f"E{int(e['seq']):06d}.json")
        return len(tickets)
    finally:
        (store.root / "prune.lock").unlink(missing_ok=True)
