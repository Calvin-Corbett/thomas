"""The grant: Express's permission to land, held in this process's memory and nowhere else.

A grant is bound to the logon session it was given in and to this referee run. It is never written down as authority:
a ``lane_switch`` line in the ledger is a record for you to read, and nothing reads it back. So a restart of the
referee, a sign-out or a reboot ends Express, and a forged file or ledger line cannot create one. The end time is
clamped to the pinned ceiling when the grant is made and again every time it is checked, so lowering the ceiling in the
pin shortens a grant already running. Expiry uses both the wall clock and the monotonic clock and takes the sooner, so
setting the wall clock back never gives time back. Standard library only.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from typing import Protocol


class Clock(Protocol):
    def time(self) -> float: ...

    def monotonic(self) -> float: ...


class EventSink(Protocol):
    def event(self, name: str, sid: str | None = None, **fields: object) -> dict: ...


@dataclass(frozen=True)
class Grant:
    session: str
    run_id: str
    granted_wall: float
    granted_mono: float
    seconds: float  # as granted, already clamped to the ceiling of that moment

    def remaining(self, wall: float, mono: float, ceiling_minutes: int) -> float:
        """Seconds left; zero or less means expired. The sooner of the wall and monotonic ends, under today's ceiling."""
        seconds = min(self.seconds, ceiling_minutes * 60)
        return min(self.granted_wall + seconds - wall, self.granted_mono + seconds - mono)


class GrantHolder:
    """The one in-memory grant. ``open`` and ``revoke`` are called only from the elevated command handler and the switch."""

    def __init__(self, clock: Clock, ledger: EventSink | None = None) -> None:
        self._clock, self._ledger, self._lock = clock, ledger, threading.Lock()
        self.run_id = secrets.token_hex(8)
        self._grant: Grant | None = None

    @property
    def current(self) -> Grant | None:
        return self._grant

    def open(self, session: str, minutes: int, ceiling_minutes: int) -> Grant:
        """Start a grant of ``minutes`` (clamped to ``ceiling_minutes``) for ``session``. Replaces any earlier grant."""
        if not (isinstance(session, str) and session) or type(minutes) is not int or minutes < 1:
            raise ValueError("a grant needs a logon session and a whole number of minutes")
        seconds = float(min(minutes, ceiling_minutes) * 60)
        grant = Grant(session, self.run_id, self._clock.time(), self._clock.monotonic(), seconds)
        recorded = False
        try:
            self._record("express", minutes=int(seconds // 60))  # the record first: if it fails there is no grant
            recorded = True
        finally:
            with self._lock:  # a failed ON leaves nothing behind, not even an earlier grant
                self._grant = grant if recorded else None
        return grant

    def revoke(self, why: str) -> bool:
        """End the grant. True when there was one."""
        with self._lock:
            had, self._grant = self._grant is not None, None
        if had:
            self._record("standard", why=why)
        return had

    def _record(self, lane: str, **fields: object) -> None:
        if self._ledger is not None:
            self._ledger.event("lane_switch", to=lane, **fields)
