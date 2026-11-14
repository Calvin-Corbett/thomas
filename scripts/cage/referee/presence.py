"""Owner presence: is your workstation unlocked and in use?

New landings are held as ``owner_away`` while the workstation is locked or you have not touched it for longer than the
pinned idle limit (default 15 minutes, never more), and resume when you return. The same reading, with a one minute
limit, is how the referee checks that you are at the PC before it honours an ON command. ``PresenceSource`` is the
seam: the Windows reader is in ``presence_win``; tests inject a fake. A reading that cannot be had, or that does not
make sense (an idle time that is negative or not a number, a lock flag that is not a bool), counts as not present.
Standard library only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from .authstate import StateError

TOUCH_SECONDS = 60  # "you touched the machine in the last minute", for ON


class PresenceSource(Protocol):
    def state(self) -> object:
        """An object with ``locked`` (bool), ``idle_seconds`` (float) and ``logon_session`` (str)."""


@dataclass(frozen=True)
class Presence:
    locked: bool
    idle_seconds: float
    logon_session: str


def read_presence(source: PresenceSource) -> Presence:
    """The current reading, or ``StateError('presence_unreadable')``."""
    try:
        raw = source.state()
        locked, idle, session = raw.locked, raw.idle_seconds, raw.logon_session  # type: ignore[attr-defined]
    except (OSError, AttributeError, RuntimeError) as exc:
        raise StateError("presence_unreadable", str(exc)[:80]) from exc
    ok = type(locked) is bool and isinstance(session, str) and bool(session)
    ok = ok and isinstance(idle, (int, float)) and not isinstance(idle, bool) and math.isfinite(idle) and idle >= 0
    if not ok:
        raise StateError("presence_unreadable", "the reading makes no sense")
    return Presence(locked, float(idle), session)


def away(seen: Presence, idle_limit_minutes: int) -> bool:
    """True when the workstation is locked or you have been idle for longer than the limit."""
    return seen.locked or seen.idle_seconds > idle_limit_minutes * 60


def touched_recently(seen: Presence) -> bool:
    return not seen.locked and seen.idle_seconds <= TOUCH_SECONDS
