"""Is the owning process of an open landing ticket still there? Pure judgement plus a clock guard; no files, no clock of its own.

A waiter is gone when its process is dead (pid AND start time, so a reused pid is not mistaken for it) or its heartbeat
is too old. A holder is gone when neither it nor its commit child runs, when it has gone quiet with no child, or when its
lease ran out while it is still running (hung). An unreadable heartbeat file is aged by its own modification time, so a
garbage file is not "alive forever". Ages come from ``Clocks``: wall-clock ages normally, but if the wall clock was set
(laptop resume, manual change) ages are measured by how long THIS observer has watched the value stay the same, so a one
hour jump cannot make every live ticket look stale.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


class Limits(Protocol):
    torn_after: float
    unledgered_grace: float
    waiter_hb_timeout: float
    holder_hb_timeout: float
    resume_grace: float
    jump_tolerance: float


class Clocks:
    """Wall and monotonic time, with guards for the two ways wall-clock ages lie.

    * The wall clock was SET (the two clocks disagree): ages then come from what this observer has watched.
    * The machine SLEPT. On Windows the monotonic clock counts the time asleep, so both clocks jump together and nothing
      disagrees. Two signs give it away: this poller's own gap since its previous poll, and a queue in which no other
      ticket's owner has beaten for longer than that gap (a fresh process after wake sees only the second).
    Either way the observation baseline is reset once (every heartbeat is forgiven) and ages are measured from the wake for
    ``suspect_for`` seconds, so nobody alive is reaped for the sleep, a really silent owner is still reaped after the normal
    allowance of observed time, and a lease restarts from the wake."""

    def __init__(
        self,
        wall: Callable[[], float],
        mono: Callable[[], float],
        tolerance: float,
        suspect_for: float = 1860.0,
        gap: float = 30.0,
    ):
        self.wall, self.mono, self.tolerance, self.suspect_for, self.gap = wall, mono, tolerance, suspect_for, gap
        self._w0: float | None = (
            None  # no baseline until the first poll: the gap is between POLLS, not from construction
        )
        self._m0 = 0.0
        self._suspect_until = float("-inf")
        self._seen: dict[Any, tuple[Any, float]] = {}

    def enter_suspect(self) -> None:
        self._suspect_until = self.mono() + self.suspect_for
        self._seen.clear()  # forgive every heartbeat once: ages restart from now

    def check(self) -> bool:
        """Call once per poll. True while ages must be measured by observation."""
        w, m = self.wall(), self.mono()
        if self._w0 is not None:
            moved = w - self._w0
            if abs(moved - (m - self._m0)) > self.tolerance or moved > self.gap or moved < -self.tolerance:
                self.enter_suspect()
        self._w0, self._m0 = w, m
        return self.suspect

    def note_queue_silence(self, stamps: list[float], now: float) -> None:
        """Other owners' newest beats. All older than the gap means no one else was alive to beat: a sleep, or all dead."""
        if stamps and not self.suspect and all(now - s > self.gap for s in stamps):
            self.enter_suspect()

    @property
    def suspect(self) -> bool:
        return self.mono() < self._suspect_until

    def age(self, key: Any, value: Any, wall_age: float) -> float:
        """How old ``value`` is. Always records the observation, so a later jump has a baseline."""
        m = self.mono()
        prev = self._seen.get(key)
        if prev is None or prev[0] != value:
            self._seen[key] = (value, m)
            prev = self._seen[key]
        return (m - prev[1]) if self.suspect else wall_age

    def forget(self, key: Any) -> None:
        self._seen.pop(key, None)


def judge(
    s: dict[str, Any],
    beat: dict[str, Any] | None,
    touch: float | None,
    now: float,
    cfg: Limits,
    same: Callable[[int | None, float | None], bool],
    clocks: Clocks,
    *,
    blind: bool = False,
) -> tuple[bool, str]:
    """Returns (alive, reason). *blind* means some ledger lines could not be read this round."""
    t, n = s["ticket"], int(s["ticket"].get("num") or 0)
    if t.get("torn"):
        return (clocks.age(("torn", n), t["mtime"], now - float(t["mtime"])) <= cfg.torn_after), "torn_ticket"
    created = float(t.get("created") or now)
    if not s["ledgered"] and not blind and clocks.age(("born", n), created, now - created) > cfg.unledgered_grace:
        return False, "unledgered_ticket"
    beat = beat or {}
    stamp = float(beat["mtime"]) if beat.get("unreadable") else float(beat.get("t") or created)
    last_age = clocks.age(("beat", n), stamp, now - stamp)
    child = int(beat.get("child") or 0)
    child_alive = bool(child) and same(child, beat.get("child_start"))
    owner = int(s.get("owner_pid") or t.get("pid") or 0)
    owner_alive = same(owner, s.get("owner_start") or t.get("pid_start")) or child_alive
    if s["state"] in ("holding", "landed"):
        lease_age = clocks.age(("lease", n), s["granted_at"], now - s["granted_at"])
        ran = beat.get("ran")  # the holder's own count of seconds its commit tool has RUN (a sleep is not charged)
        if isinstance(ran, int | float) and ran >= 0:
            lease_over = (
                ran > s["max_hold"] or lease_age > 8 * s["max_hold"]
            )  # the wall bound only catches a holder that lies
        else:
            lease_over = lease_age > s["max_hold"]
        if owner_alive and lease_over:
            return False, "lease_expired" + (" (its commit process is still running)" if child_alive else "")
        if not owner_alive:
            return False, "holder_dead"
        if last_age > cfg.holder_hb_timeout and not child_alive:
            return False, "heartbeat_stale"
        return True, ""
    if not owner_alive:
        return False, "waiter_dead"
    if t.get("mode") == "detached":
        seen = float(touch) if touch else created
        if clocks.age(("touch", n), seen, now - seen) > cfg.resume_grace:
            return False, "nobody_resumed"
    return (last_age <= cfg.waiter_hb_timeout), "heartbeat_stale"
