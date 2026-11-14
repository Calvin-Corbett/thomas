"""Ticket store for the landing queue: the files, the counters and the ledger. Stdlib only.

The lane logic (who may take the slot, lease, recovery) lives in ``landing_queue`` and only talks to the ``TicketStore``
interface below, so a later stage can put the folder under a locked-down channel directory or behind a service without
touching the lane or the agent-facing ``land.py``.

Layout under the queue root (one file per fact; only heartbeats are ever replaced):
  tickets/T000001.json   created whole (temp file + hard link): the number IS the place in line, no clock involved
  ledger/E000001.json    one file per event, numbered the same way, each carrying its own content hash
  beats/T000001.json     liveness of an OPEN ticket's owner; deleted when the ticket finishes
  touch/T000001.json     the last time an agent asked about a submitted ticket (--wait / --resume); deleted likewise

Tamper-EVIDENT only: every agent runs as the same account, so any agent can write any file here. ``verify`` reports a
deleted ticket, a rewritten ticket, a missing or reused number, a forged event and an event written for someone
else's ticket. It cannot stop any of it, and it is not a protection.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Protocol

from scripts.crew.brief import landing_audit, landing_proc, landing_prune
from scripts.crew.brief.landing_files import (
    READ_TRIES,
    atomic_write,
    create_numbered,
    numbers,
    read_json,
    read_state,
)
from scripts.crew.brief.landing_files import digest as digest  # re-exported for the audit and the tests

ENV_ROOT = "THOMAS_LANDING_QUEUE_DIR"


def canonical_coordination_dir(start: Path | None = None) -> Path:
    """The shared ``runtime/coordination`` of the primary checkout, like the board and the presence files."""
    here = Path(start) if start else Path(__file__).resolve().parents[3]
    try:
        out = landing_proc.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=str(here),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        common = Path(out.stdout.strip())
        if out.returncode == 0 and common.name == ".git" and common.parent.exists():
            return common.parent / "runtime" / "coordination"
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return here / "runtime" / "coordination"


def resolve_queue_root(env: dict[str, str] | None = None, start: Path | None = None) -> Path:
    """The single setting for where tickets live: ``THOMAS_LANDING_QUEUE_DIR``, else the shared coordination folder."""
    override = str((env if env is not None else os.environ).get(ENV_ROOT) or "").strip()
    return Path(override) if override else canonical_coordination_dir(start) / "landing_queue"


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _valid_event(row: dict[str, Any]) -> bool:
    return isinstance(row.get("kind"), str) and all(isinstance(row.get(k), int) for k in ("seq", "ticket"))


class TicketStore(Protocol):
    """What the lane needs. A service-owned store implements the same calls over its own transport."""

    root: Path

    def take(self, *, now: float, **ticket: Any) -> int: ...
    def tickets(self) -> dict[int, dict[str, Any]]: ...
    def events(self) -> list[dict[str, Any]]: ...
    def append(self, kind: str, ticket: int, *, by: str, now: float, **fields: Any) -> dict[str, Any]: ...
    def beat(self, ticket: int, *, now: float, **fields: Any) -> None: ...
    def beats(self, only: Any = None) -> dict[int, dict[str, Any]]: ...
    def touch(self, ticket: int, *, now: float) -> None: ...
    def touches(self) -> dict[int, float]: ...
    def drop_live(self, ticket: int) -> None: ...
    def prune(self, below: int, *, now: float) -> int: ...
    def verify(self, *, now: float, grace: float) -> list[str]: ...


class FileTicketStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.dirs = {name: self.root / name for name in ("tickets", "ledger", "beats", "touch")}
        self._seen: dict[
            tuple[str, int], dict[str, Any]
        ] = {}  # tickets and events are never rewritten, so parse each once
        self._max_ref = 0  # highest ticket number any ledger line has ever named

    # ---- numbering: counters that never go backwards, even if a ticket file is deleted
    def _next_ticket(self) -> int:
        top = max(numbers(self.dirs["tickets"], "T"), default=0)
        top = max(
            top, max(numbers(self.dirs["beats"], "T"), default=0), max(numbers(self.dirs["touch"], "T"), default=0)
        )
        self.events()
        return max(top, self._max_ref) + 1

    def take(self, *, now: float, **ticket: Any) -> int:
        def build(n: int) -> bytes:
            return json.dumps({"num": n, "created": now, **ticket}, sort_keys=True).encode("utf-8")

        num, payload = create_numbered(self.dirs["tickets"], "T", build, self._next_ticket())
        self.append(
            "taken", num, by=str(ticket.get("agent") or ""), now=now, ticket_sha=hashlib.sha256(payload).hexdigest()
        )
        return num

    def append(self, kind: str, ticket: int, *, by: str, now: float, **fields: Any) -> dict[str, Any]:
        def build(seq: int) -> bytes:
            body = {"seq": seq, "kind": kind, "ticket": ticket, "by": by, "pid": os.getpid(), "at": now, **fields}
            return json.dumps({**body, "sha": digest(body)}, sort_keys=True).encode("utf-8")

        start = max(numbers(self.dirs["ledger"], "E"), default=0) + 1
        _, payload = create_numbered(self.dirs["ledger"], "E", build, start)
        self._max_ref = max(self._max_ref, int(ticket))
        return json.loads(payload)

    # ---- reads
    def tickets(self) -> dict[int, dict[str, Any]]:
        found: dict[int, dict[str, Any]] = {}
        for n in numbers(self.dirs["tickets"], "T"):
            body = self._seen.get(("T", n))
            if body is None:
                path = self.dirs["tickets"] / f"T{n:06d}.json"
                state, body = read_state(path, READ_TRIES)
                if state == "missing":
                    continue
                if body is None:  # numbered but unreadable: a crash while writing, or an edit
                    try:
                        body = {"num": n, "torn": True, "mtime": path.stat().st_mtime}
                    except OSError:
                        continue
                else:
                    self._seen[("T", n)] = body
            found[n] = body
        return found

    def events(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for n in numbers(self.dirs["ledger"], "E"):
            row = self._seen.get(("E", n))
            if row is None:
                path = self.dirs["ledger"] / f"E{n:06d}.json"
                state, row = read_state(path, READ_TRIES)
                if state == "missing":
                    continue
                if row is None:  # present but unreadable: keep a placeholder carrying its mtime so the lane can age it
                    try:
                        mtime = path.stat().st_mtime
                    except OSError:
                        continue
                    rows.append({"seq": n, "kind": "unreadable", "ticket": 0, "at": mtime})
                    continue
                self._seen[("E", n)] = row
            if not _valid_event(
                row
            ):  # a numbered file that is not an event: kept as a marker, ignored by the lane, named by verify
                rows.append({"seq": n, "kind": "invalid", "ticket": 0, "at": 0, "file": f"E{n:06d}.json"})
                continue
            self._max_ref = max(self._max_ref, int(row.get("ticket") or 0), _as_int(row.get("ticket_below"), 1) - 1)
            rows.append(row)
        return rows

    # ---- liveness files (best effort: a missed write is not fatal, the next poll writes another)
    def beat(self, ticket: int, *, now: float, **fields: Any) -> None:
        try:
            atomic_write(self.dirs["beats"] / f"T{ticket:06d}.json", json.dumps({"t": now, **fields}))
        except OSError:
            pass

    def beats(self, only: Any = None) -> dict[int, dict[str, Any]]:
        """Beat files of the wanted (open) tickets. One that cannot be read says so, with its mtime, instead of vanishing."""
        wanted = numbers(self.dirs["beats"], "T") if only is None else sorted(set(only))
        out: dict[int, dict[str, Any]] = {}
        for n in wanted:
            path = self.dirs["beats"] / f"T{n:06d}.json"
            state, row = read_state(path, READ_TRIES)
            if state == "missing":
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0.0
            out[n] = row if row is not None else {"unreadable": True, "mtime": mtime}
        return out

    def touch(self, ticket: int, *, now: float) -> None:
        try:
            atomic_write(self.dirs["touch"] / f"T{ticket:06d}.json", json.dumps({"t": now}))
        except OSError:
            pass

    def touches(self) -> dict[int, float]:
        rows = {n: read_json(self.dirs["touch"] / f"T{n:06d}.json", 2) for n in numbers(self.dirs["touch"], "T")}
        return {n: float(r.get("t") or 0) for n, r in rows.items() if r}

    def drop_live(self, ticket: int) -> None:
        for name in ("beats", "touch"):
            try:
                (self.dirs[name] / f"T{ticket:06d}.json").unlink()
            except OSError:
                pass

    # ---- housekeeping and checks, in their own modules
    def prune(self, below: int, *, now: float) -> int:
        return landing_prune.prune_below(self, below, now=now)

    def verify(self, *, now: float, grace: float) -> list[str]:
        return landing_audit.verify_store(self, now=now, grace=grace)
