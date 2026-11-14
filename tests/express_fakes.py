"""Offline stand-ins for the four things the Express referee asks the machine about.

The referee (plan B1 to B5) reads a clock, receives a grant over an elevated channel, asks whether you are at the
PC, and lists who can write a folder. Each of those is an injectable seam; these fakes are what the offline tests
inject (the ACL lister is in ``express_acl``). None of them touches the real machine, the network or a model.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone

START_EPOCH = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc).timestamp()


class FakeClock:
    """A clock that only moves when a test moves it. ``time`` is wall time, ``monotonic`` never jumps back."""

    def __init__(self, wall: float = START_EPOCH, mono: float = 1000.0) -> None:
        self.wall = float(wall)
        self.mono = float(mono)

    def time(self) -> float:
        return self.wall

    def monotonic(self) -> float:
        return self.mono

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("a clock in a test only moves forward")
        self.wall += seconds
        self.mono += seconds

    def git_date(self) -> str:
        return f"{int(self.wall)} +0000"


class PipeRefused(PermissionError):
    """The elevated channel turned the caller away."""


@dataclass(frozen=True)
class GrantCall:
    message: Mapping[str, object]
    elevated: bool


@dataclass
class FakeGrantTransport:
    """The named pipe the switch helper talks to. It admits an elevated caller only and records every call.

    ``handler`` may compute the reply for an admitted call; by default the reply is ``{"ok": True}``.
    """

    elevated_only: bool = True
    handler: Callable[[Mapping[str, object]], dict] | None = None
    calls: list[GrantCall] = field(default_factory=list)

    def send(self, message: Mapping[str, object], *, elevated: bool) -> dict:
        self.calls.append(GrantCall(dict(message), elevated))
        if self.elevated_only and not elevated:
            raise PipeRefused("the pipe admits only an elevated administrator token")
        return self.handler(message) if self.handler else {"ok": True, "op": message.get("op")}

    def admitted(self, op: str | None = None) -> list[GrantCall]:
        return [c for c in self.calls if c.elevated and (op is None or c.message.get("op") == op)]

    def refused(self) -> list[GrantCall]:
        return [c for c in self.calls if self.elevated_only and not c.elevated]


@dataclass(frozen=True)
class PresenceState:
    locked: bool
    idle_seconds: float
    logon_session: str


class FakePresence:
    """Whether you are at the PC: lock state, seconds since your last input, and the logon session."""

    def __init__(self, clock: FakeClock, *, logon_session: str = "session-1") -> None:
        self._clock = clock
        self._locked = False
        self._session = logon_session
        self._last_input = clock.monotonic()

    def state(self) -> PresenceState:
        return PresenceState(self._locked, self._clock.monotonic() - self._last_input, self._session)

    def touch(self) -> None:
        self._last_input = self._clock.monotonic()

    def lock(self) -> None:
        self._locked = True

    def unlock(self) -> None:
        self._locked = False
        self.touch()

    def new_logon_session(self, session: str) -> None:
        self._session = session
        self.touch()
