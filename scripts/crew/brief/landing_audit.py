"""Tamper evidence for the landing queue: what ``land.py --status --verify`` reports. Read-only, stdlib only.

Everything here is EVIDENCE for you to read, never a protection: agents run as your account and can write any file in the
queue folder, so an agent that forges a ticket and the ledger line that vouches for it passes every check below.
"""

from __future__ import annotations

import hashlib
from typing import Any

from scripts.crew.brief.landing_files import digest, numbers
from scripts.crew.brief.landing_types import LANE_PREFIX, LIVE_OWNER_REASONS


def pruned_floor(events: list[dict[str, Any]]) -> tuple[int, list[tuple[int, int]]]:
    """(tickets below this number were pruned on purpose, seq ranges pruned on purpose) from the lane's own prune lines."""
    below, ranges = 1, []
    for e in events:
        if e.get("kind") == "pruned":
            below = max(below, int(e.get("ticket_below") or 1))
            ranges += [(int(a), int(b)) for a, b in e.get("ranges") or []]
    return below, ranges


def verify_store(store: Any, *, now: float, grace: float) -> list[str]:
    out: list[str] = []
    store._seen.clear()  # judge the files as they are now, not as they were when first read
    tickets, events = store.tickets(), store.events()
    below, ranges = pruned_floor(events)
    top_ticket = max(tickets, default=0)
    out += [f"ticket T{n:06d} is missing (deleted?)" for n in range(below, top_ticket + 1) if n not in tickets]
    seqs = {e.get("seq") for e in events}
    top = max((s for s in seqs if isinstance(s, int)), default=0)
    pruned = lambda s: any(a <= s <= b for a, b in ranges)  # noqa: E731
    out += [
        f"ledger event E{s:06d} is missing (deleted?)" for s in range(1, top + 1) if s not in seqs and not pruned(s)
    ]
    taken: dict[int, dict[str, Any]] = {}
    for e in events:
        seq = int(e.get("seq") or 0)
        if e.get("kind") == "invalid":
            out.append(f"ledger file {e.get('file')} is not a valid event file (no kind, seq or ticket): ignored")
            continue
        if e.get("kind") == "unreadable":
            if now - float(e.get("at") or 0) > 10:
                out.append(
                    f"ledger event E{seq:06d} is empty or unreadable (a crash while writing, or edited): ignored"
                )
            continue
        if e.get("sha") != digest({k: v for k, v in e.items() if k != "sha"}):
            out.append(f"ledger event E{seq:06d} does not match its own hash (edited or forged)")
        if e.get("kind") == "taken":
            n = int(e["ticket"])
            if n in taken:
                out.append(f"ticket number T{n:06d} was taken twice (a deleted ticket's number was reused)")
            taken[n] = e
    for n, body in tickets.items():
        path = store.dirs["tickets"] / f"T{n:06d}.json"
        line = taken.get(n)
        if body.get("torn"):
            out.append(f"ticket T{n:06d} is empty or unreadable (crash while writing, or edited)")
        elif line is None and now - float(body.get("created") or 0) > grace:
            out.append(f"ticket T{n:06d} has no ledger line (written by hand or by a crash)")
        elif line is not None and hashlib.sha256(path.read_bytes()).hexdigest() != line.get("ticket_sha"):
            out.append(f"ticket T{n:06d} no longer matches its ledger hash (rewritten by someone)")
    out += [
        f"ledger says ticket T{n:06d} was taken but its file is gone" for n in taken if n not in tickets and n >= below
    ]
    for e in events:
        n = int(e.get("ticket") or 0)
        ticket = tickets.get(n)
        if not ticket or e.get("kind") in ("unreadable", "pruned"):
            continue
        who, owner = str(e.get("by") or ""), ticket.get("agent")
        if who != owner and not who.startswith(LANE_PREFIX):
            out.append(
                f"event E{int(e['seq']):06d} '{e['kind']}' for T{n:06d} was written by {who}, not {owner} or a lane"
            )
        if e.get("kind") != "taken" and float(e.get("at") or 0) < float(ticket.get("created") or 0) - 1:
            out.append(f"event E{int(e['seq']):06d} for T{n:06d} is older than the ticket (the number was reused)")
    return out


def lane_findings(lane: Any, *, now: float) -> list[str]:
    """What only the lane can judge: a lease longer than the reaper allows, and 'owner gone' verdicts about owners that live."""
    out: list[str] = []
    for n, s in lane.states().items():
        ticket = s["ticket"]
        for e in s["events"] + s["ignored"]:
            if e.get("child_ignored"):
                out.append(
                    f"T{n:06d}: {e['child_ignored']}; the process was left alone (a forged or damaged heartbeat)"
                )
            if e.get("kind") == "granted" and not _plausible_lease(e.get("max_hold"), lane.cfg):
                out.append(
                    f"T{n:06d} was granted a lease of {e.get('max_hold')} s; the reaper allows at most "
                    f"{min(lane.cfg.max_hold, lane.cfg.max_hold_ceiling):.0f} s, so it was clamped (typo or forged line)"
                )
            if (
                str(e.get("by") or "").startswith(LANE_PREFIX)
                and e.get("kind") in ("abandoned", "skipped")
                and not str(e.get("reason") or "").startswith(LIVE_OWNER_REASONS)
            ):
                pid = s.get("owner_pid") or ticket.get("pid")
                if pid and lane.same_process(int(pid), s.get("owner_start") or ticket.get("pid_start")):
                    out.append(
                        f"T{n:06d} was finished as '{e.get('reason')}' by {e.get('by')}, but its owner (pid {pid}) is alive "
                        f"and is the same process: a forged or mistaken verdict"
                    )
    return out


def _plausible_lease(value: Any, cfg: Any) -> bool:
    try:
        return float(value or cfg.max_hold) <= min(cfg.max_hold, cfg.max_hold_ceiling)
    except (TypeError, ValueError):
        return False


def folder_counts(store: Any) -> dict[str, int]:
    return {name: len(numbers(path, "T" if name != "ledger" else "E")) for name, path in store.dirs.items()}
