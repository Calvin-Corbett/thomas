"""The landing lane: FIFO tickets, one landing in flight, lease, liveness and crash recovery. Stdlib only.

An agent that wants to land takes a numbered ticket, waits WITHOUT running gates, and when every lower ticket is
finished it is the holder: it runs the real commit tool once. The place in line is the ticket number (a counter slot in
the store), never a clock. A holder that dies, hangs past its lease or goes quiet is skipped by whoever is next, its commit
child is killed if it outlived the lease, and a notice is written for its agent. Before any holder lands, and when a holder
is skipped, dev's recent history is searched for the change's idempotency key AND its content (``find_landed``), so a
holder that died after the compare-and-swap is never landed twice and a different change with the same words never reads
as landed. Everything time-, process- and git-shaped is injected, so the tests run it with fake clocks and a fake commit.
This is a queue in front of the commit tool, not protection: tamper-evident only.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Sequence
from typing import Any

from scripts.crew.brief import landing_audit, landing_proc
from scripts.crew.brief.landing_liveness import Clocks
from scripts.crew.brief.landing_reaper import ReaperMixin
from scripts.crew.brief.landing_store import TicketStore
from scripts.crew.brief.landing_types import MESSAGE_KEEP, SLOT_WASTE_REASONS, AttemptCapReached, Config, Outcome

__all__ = ["AttemptCapReached", "Config", "Lane", "Outcome"]


def _default_alive(pid: int | None) -> bool:
    from thomas.core.process_alive import process_alive  # never os.kill(pid, 0): that is Ctrl+C on Windows

    return process_alive(pid)


class Lane(ReaperMixin):
    def __init__(
        self,
        store: TicketStore,
        *,
        agent: str = "",
        session: str = "",
        pid: int | None = None,
        clock: Callable[[], float] = time.time,
        mono: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        pid_alive: Callable[[int | None], bool] = _default_alive,
        proc_start: Callable[[int | None], float | None] = landing_proc.start_time,
        kill_child: Callable[[int, Any], None] = lambda pid, start: landing_proc.kill_tree(pid),
        proc_cmd: Callable[[int | None], str] = landing_proc.proc_cmdline,
        find_landed: Callable[..., str | None] = lambda key, includes=(), own=False: None,
        git_cleanup: Callable[[], tuple[list[str], list[str]]] = lambda: ([], []),
        presence: Callable[[], None] = lambda: None,
        say: Callable[[str], None] = lambda text: None,
        cfg: Config = Config(),
    ):
        self.store, self.agent, self.session = store, agent, session
        self.pid = pid if pid is not None else os.getpid()
        self.clock, self.mono, self.sleep = clock, mono, sleep
        self.pid_alive, self.proc_start, self.kill_child, self.proc_cmd = pid_alive, proc_start, kill_child, proc_cmd
        self.find_landed, self.git_cleanup, self.presence, self.say, self.cfg = (
            find_landed,
            git_cleanup,
            presence,
            say,
            cfg,
        )
        self.clocks = Clocks(clock, mono, cfg.jump_tolerance, cfg.max_hold_ceiling + 60, cfg.suspend_gap)
        self.blind, self._head, self._beat_at, self._lock_tries = False, (None, 0.0), {}, 0
        self._verdicts: set[Any] = set()
        self.stop_if: Callable[[], str | None] = lambda: None  # e.g. the process that started this wait is gone
        self.on_wait: Callable[[int, int], None] = lambda num, ahead: (
            None
        )  # (ticket, open tickets ahead): the pre-check
        self._locks_cleaned: list[str] = []

    @property
    def ident(self) -> str:
        """Who a ticket belongs to for caps and attaching: the bound session, else the agent id."""
        return self.session or self.agent

    # ---- the agent side
    def open_count(self) -> int:
        return sum(1 for s in self.states().values() if s["open"])

    def find_open(self, key: str) -> int | None:
        """This identity's own open ticket for this exact change, so a second run attaches instead of queueing again."""
        for n, s in sorted(self.states().items()):
            t = s["ticket"]
            if s["open"] and t.get("key") == key and (t.get("session") or t.get("agent")) == self.ident:
                return n
        return None

    def recent_ends(self, now: float) -> tuple[list[float], list[float]]:
        """(slot-wasting ends, in-slot refusals) of this identity inside the window, as ticket creation times.

        Rule: only what cost the shared slot counts. A hold that overran its lease or went silent counts toward the strict
        cap (attempt_cap); an honest refusal by the commit tool inside the slot counts toward the looser refusal_cap.
        A wait that timed out, a withdrawal, a killed or silent WAITER, a killed holder and a lane skip never count."""
        waste, refused = [], []
        for s in self.states().values():
            t = s["ticket"]
            created = float(t.get("created") or 0)
            if (t.get("session") or t.get("agent")) != self.ident or now - created >= self.cfg.attempt_window:
                continue
            refusal = next((e for e in s["events"] if e["kind"] == "refused"), {})
            blocker = refusal.get("blocker")
            if s["state"] == "skipped" and s.get("reason", "").split(" ")[0] in SLOT_WASTE_REASONS:
                waste.append(created)
            elif s["state"] == "refused" and refusal.get("stage") != "precheck":  # a pre-check never used the slot
                (waste if blocker in ("lane_error", "lease_expired") else refused).append(created)
        return sorted(waste), sorted(refused)

    def enqueue(
        self,
        key: str,
        subject: str,
        *,
        includes: Sequence[str] = (),
        request: dict[str, Any] | None = None,
        mode: str = "foreground",
    ) -> int:
        self.reap()
        if (existing := self.find_open(key)) is not None:
            return existing
        try:
            self.maybe_prune()
        except OSError:  # housekeeping never stops a landing
            pass
        now = self.clock()
        waste, refused = self.recent_ends(now)
        if len(waste) >= self.cfg.attempt_cap:
            raise AttemptCapReached(waste[0] + self.cfg.attempt_window - now, "slot-wasting")
        if len(refused) >= self.cfg.refusal_cap:
            raise AttemptCapReached(refused[0] + self.cfg.attempt_window - now, "refused-in-slot")
        return self.store.take(
            now=now,
            agent=self.agent,
            session=self.session,
            pid=self.pid,
            pid_start=self.proc_start(self.pid),
            ppid=os.getppid(),
            mode=mode,
            key=key,
            includes=list(includes),
            subject=subject[:120],
            attempt=len(waste) + len(refused) + 1,
            request=request or {},
        )

    def adopt(self, num: int, **fields: Any) -> None:
        """A detached worker takes over a ticket that the submitting process created, so liveness follows the worker."""
        self.store.append(
            "adopted",
            num,
            by=self.agent,
            now=self.clock(),
            owner_pid=self.pid,
            owner_start=self.proc_start(self.pid),
            **fields,
        )

    def beat(
        self,
        num: int,
        phase: str,
        child_pid: int = 0,
        child_start: float | None = None,
        *,
        throttle: bool = False,
        child_script: str = "",
        ran: float = -1.0,
    ) -> None:
        mono = self.mono()
        if throttle and mono - self._beat_at.get(num, float("-inf")) < self.cfg.beat_every:
            return
        self._beat_at[num] = mono
        self.store.beat(
            num,
            now=self.clock(),
            pid=self.pid,
            child=child_pid,
            child_start=child_start or 0,
            child_script=child_script,
            ran=ran,
            phase=phase,
        )
        self.presence()  # keeps the agent's session, and so its claim, from looking idle to the dead-claim sweep

    def wait_turn(self, num: int, *, max_wait: float | None = None) -> str:
        """Returns granted, timeout or lost. Runs no gates; only reads, heartbeats and sleeps."""
        start, last_say = self.clock(), float("-inf")
        limit = self.cfg.max_wait if max_wait is None else max_wait
        while True:
            self.beat(num, "waiting", throttle=True)
            states = self.states()
            if self.reap(states):
                states = self.states()
            if num not in states or not states[num]["open"] or states[num]["state"] in ("holding", "landed"):
                return "lost"  # finished, or already held by another process: never a second commit tool for one ticket
            if (why := self.stop_if()) is not None:
                self.withdraw(num, why)
                return "lost"
            ahead = [n for n, s in states.items() if s["open"] and n < num]
            if not ahead and self._may_grant(states):
                locks = self._locks_cleaned
                self.store.append(
                    "granted", num, by=self.agent, now=self.clock(), max_hold=self.cfg.max_hold, locks_cleaned=locks
                )
                if locks:
                    self.say(f"removed abandoned git lock file(s) left by a killed landing: {', '.join(locks)}")
                self.beat(num, "holding")
                return "granted"
            if self.clock() - start > limit:
                note = "you waited past your limit and left the line; run land.py again"
                self._finish("abandoned", num, reason="wait_timeout", notice=note)
                return "timeout"
            if ahead and self.clock() - last_say >= self.cfg.say_every:
                last_say = self.clock()
                self.say(
                    f"queued as T{num:06d}: {len(ahead)} ahead, est. wait {int(self.eta(len(ahead)))}s "
                    f"(holder: {self._holder_text(states)})"
                )
            if ahead:
                self.on_wait(num, len(ahead))  # may finish the ticket (a pre-check refusal): the next poll sees it
            self.sleep(self.cfg.poll)

    def _may_grant(self, states: dict[int, dict[str, Any]]) -> bool:
        """No orphaned commit tool, no abandoned git lock file: only then may the next holder start."""
        self._locks_cleaned = []
        if self.blocked_by_orphan(states):
            return False
        removed, left = self.git_cleanup()
        self._locks_cleaned = removed
        if left and self._lock_tries < self.cfg.lock_tries:
            self._lock_tries += 1  # git is running right now; try again next poll, but never wait for ever
            return False
        self._lock_tries = 0
        return True

    def hold(self, num: int, commit: Callable[[], Outcome]) -> tuple[str, Outcome]:
        """Run the one landing. Returns (landed | already_landed | refused | lost, outcome). Never keeps the slot."""
        s = self.states()[num]
        if not s["open"]:
            return "lost", Outcome(
                False, blocker="ticket_skipped", message=s.get("notice") or "your ticket was skipped"
            )
        key, includes = s["ticket"].get("key", ""), s["ticket"].get("includes") or []
        prior = self.find_landed(key, includes) if key else None  # no dry run inside the slot: land.py ran it already
        if prior:
            self._finish("released", num, sha_landed=prior, note="already landed")
            return "already_landed", Outcome(True, sha=prior, message=f"already landed as {prior}")
        if not self._still_open(num):  # skipped while the check above ran: never start a second commit tool
            return "lost", Outcome(
                False, blocker="ticket_skipped", message="your ticket was skipped while it was being checked"
            )
        out = None
        try:
            out = commit()
        finally:
            if out is None:  # the commit step raised or was interrupted: the slot is released either way
                self._finish("refused", num, blocker="lane_error", message="commit step raised")
        if not out.ok:
            self._finish(
                "refused",
                num,
                blocker=out.blocker or "refused",
                message=out.message[:MESSAGE_KEEP],
                output_file=out.output_file,
            )
            return "refused", out
        self.store.append("landed", num, by=self.agent, now=self.clock(), sha_landed=out.sha)
        self._finish("released", num)
        return "landed", out

    def refuse_early(self, num: int, out: Outcome) -> None:
        """The pre-check refused while the ticket waited: it finishes before it ever used the slot."""
        if self.states().get(num, {}).get("state") == "waiting":
            fields = {"message": out.message[:MESSAGE_KEEP], "output_file": out.output_file, "stage": "precheck"}
            self._finish("refused", num, blocker=out.blocker or "refused", **fields)

    def withdraw(self, num: int, reason: str = "agent_cancelled") -> None:
        if self._still_open(num):
            self._finish("abandoned", num, reason=reason, notice=f"you left the line ({reason})")

    # ---- housekeeping and checks
    def maybe_prune(self) -> int:
        states = self.states()
        closed = sorted(n for n, s in states.items() if not s["open"])
        keep = self.cfg.keep_closed
        if len(closed) <= keep + max(10, keep // 5):
            return 0
        lowest_open = min((n for n, s in states.items() if s["open"]), default=max(states) + 1)
        return self.store.prune(min(closed[-keep], lowest_open), now=self.clock())

    def audit(self) -> list[str]:
        now = self.clock()
        return self.store.verify(now=now, grace=self.cfg.unledgered_grace) + landing_audit.lane_findings(self, now=now)
