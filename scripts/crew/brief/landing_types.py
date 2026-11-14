"""Plain values shared by the landing lane, its store and its entry script. Stdlib only."""

from __future__ import annotations

from dataclasses import dataclass

TERMINAL = frozenset({"released", "refused", "skipped", "abandoned", "recovered"})
LANE_PREFIX = "lane:"  # who wrote an event: the ticket's own agent, or "lane:<agent that noticed>"
# Verdicts that say the owning process is dead: false whenever that same process is still running.
OWNER_GONE = frozenset({"waiter_dead", "holder_dead"})
# Reasons a lane verdict can honestly give about an owner that is still alive (hung, silent, never asked about, never took the slot).
LIVE_OWNER_REASONS = (
    "lease_expired",
    "heartbeat_stale",
    "nobody_resumed",
    "never_took_slot",
    "unledgered_ticket",
    "torn_ticket",
)
# Holds that wasted the shared slot through the holder's own doing: they count toward the strict cap.
SLOT_WASTE_REASONS = frozenset({"lease_expired", "heartbeat_stale"})
# How much of a refusal the agent sees in the ledger and in land.py's answer; the whole output is in a file.
MESSAGE_KEEP = 4000


@dataclass(frozen=True)
class Config:
    max_hold: float = 900.0  # lease: the reaper's own value is the only one used, never a holder's
    max_hold_ceiling: float = 1800.0  # no setting and no ledger line can ask for more than this
    poll: float = 2.0
    beat_every: float = 5.0  # at most one heartbeat write per waiter per this many seconds
    waiter_hb_timeout: float = 90.0
    holder_hb_timeout: float = 120.0
    unreadable_grace: float = 10.0  # an unreadable heartbeat file counts as alive only while its mtime is this fresh
    torn_after: float = 30.0
    unledgered_grace: float = 60.0
    head_grant_grace: float = 60.0  # the head waiter must take the slot within this, or it is dropped
    resume_grace: float = 600.0  # a submitted ticket survives this long without a --wait/--resume call
    max_wait: float = 2700.0
    attempt_cap: int = 3  # per identity per window: holds that wasted the slot (lease overrun, went silent)
    refusal_cap: int = 10  # per identity per window: honest refusals by the commit tool inside the slot
    attempt_window: float = 3600.0
    say_every: float = 20.0
    jump_tolerance: float = 30.0  # wall clock vs monotonic clock disagreement that means "the clock was set"
    suspend_gap: float = 30.0  # a poller's own gap between polls longer than this means the machine slept
    warn_hold: float = 300.0  # a landing that holds the slot this long is reported as "hold overran" once
    precheck_timeout: float = 120.0  # the pre-check dry run is bounded by this
    window_commits: int = 400  # how far back dev history is searched for a landing key
    keep_closed: int = 500  # finished tickets kept before the lane prunes the oldest
    lock_tries: int = 5


@dataclass(frozen=True)
class Outcome:  # what the injected commit function returns
    ok: bool
    sha: str | None = None
    blocker: str | None = None
    message: str = ""
    gate: str | None = None
    output_file: str | None = None  # the commit tool's whole output for a refusal, under the queue root


class AttemptCapReached(Exception):
    def __init__(self, retry_in: float, what: str = "slot-wasting"):
        super().__init__(f"{what} attempt cap reached; the oldest one ages out in {int(retry_in // 60) + 1} min")
        self.retry_in = retry_in
