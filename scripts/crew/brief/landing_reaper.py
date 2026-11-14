"""The lane's reading and recovery half: fold the ledger into ticket states, finish tickets whose owners are gone.

Mixed into ``Lane``. Reaping only ever APPENDS events (and kills a commit child that outlived its lease); it is safe to
run from any waiter, any number of times. A holder's own words never extend its lease: the length comes from the
reaper's configuration, clamped to a ceiling, whatever a ``granted`` line says. Events written by anyone but the
ticket's own agent or a ``lane:`` writer are ignored (and reported by ``--verify``), not honoured.
"""

from __future__ import annotations

import statistics
from typing import Any

from scripts.crew.brief.landing_liveness import judge
from scripts.crew.brief.landing_types import LANE_PREFIX, LIVE_OWNER_REASONS, OWNER_GONE, TERMINAL


def _num(value: Any) -> float:
    return float(value) if isinstance(value, int | float) else 0.0


class ReaperMixin:
    # ---- state: folded from the ledger, one place
    def _lease(self, declared: Any) -> float:
        try:
            asked = float(declared or self.cfg.max_hold)
        except (TypeError, ValueError):
            asked = self.cfg.max_hold
        return min(asked, self.cfg.max_hold, self.cfg.max_hold_ceiling)

    def _honoured(self, s: dict[str, Any], e: dict[str, Any]) -> bool:
        """An event counts when the ticket's own agent wrote it, or a lane writer did. A lane verdict that finishes a ticket is
        checked against the ticket's owning process: while that same process runs, only the reasons that can honestly be given about a LIVE
        owner stand, and a lease verdict stands only if the lease really was over. Authorship itself is the ``by`` text any
        agent can write: a forger who copies a believable reason gets through (S1 cannot stop it)."""
        who = str(e.get("by") or "")
        if who == s["ticket"].get("agent"):
            return True
        if not who.startswith(LANE_PREFIX):
            return False
        if e.get("kind") in ("abandoned", "skipped") and e.get("seq") not in self._verdicts:
            t, reason = s["ticket"], str(e.get("reason") or "")
            if self.same_process(s.get("owner_pid") or t.get("pid"), s.get("owner_start") or t.get("pid_start")):
                if not reason.startswith(LIVE_OWNER_REASONS):
                    return False
                if reason.startswith("lease_expired") and not self._lease_was_over(s, e):
                    return False
            self._verdicts.add(e.get("seq"))
        return True

    @staticmethod
    def _lease_was_over(s: dict[str, Any], e: dict[str, Any]) -> bool:
        if "granted_at" not in s:
            return False
        if _num(e.get("ran")) > s.get("max_hold", 0):  # the holder's own run-time count passed the lease
            return True
        return float(e.get("at") or 0) - s["granted_at"] >= 0.9 * s.get("max_hold", 0)

    def states(self) -> dict[int, dict[str, Any]]:
        now = self.clock()
        events = self.store.events()
        self.blind = any(
            e.get("kind") == "unreadable" and now - float(e.get("at") or 0) < self.cfg.unreadable_grace for e in events
        )
        out: dict[int, dict[str, Any]] = {
            n: {
                "ticket": t,
                "state": "torn" if t.get("torn") else "waiting",
                "sha": None,
                "events": [],
                "ignored": [],
                "ledgered": False,
            }
            for n, t in self.store.tickets().items()
        }
        for e in events:
            s = out.get(int(e.get("ticket") or 0))
            kind = e.get("kind")
            if s is None or kind in ("unreadable", "pruned", "invalid"):
                continue
            if not self._honoured(s, e):
                s["ignored"].append(e)
                continue
            s["events"].append(e)
            s["ledgered"] = s["ledgered"] or kind == "taken"
            s["sha"] = e.get("sha_landed") or s["sha"]
            if kind in ("overran", "unbounded"):
                s[kind] = e.get("reason") or True
            if kind == "adopted":
                s["owner_pid"], s["owner_start"] = e.get("owner_pid"), e.get("owner_start")
                s["owner_breakaway"] = e.get("breakaway")
            if s["state"] in TERMINAL:
                continue  # first finish wins; a late "landed" from a skipped hung holder only adds the sha
            if (
                kind == "granted" and s["state"] == "waiting"
            ):  # the FIRST grant counts: a repeat never restarts the lease
                s.update(state="holding", granted_at=float(e["at"]), max_hold=self._lease(e.get("max_hold")))
            elif kind == "landed":
                s["state"] = "landed"
            elif kind in TERMINAL:
                s.update(state=kind, reason=e.get("reason", ""), notice=e.get("notice", ""), finished=float(e["at"]))
        for s in out.values():
            s["open"] = s["state"] not in TERMINAL
        return out

    def _finish(self, kind: str, n: int, *, by: str | None = None, **fields: Any) -> None:
        self.store.append(kind, n, by=by or self.agent, now=self.clock(), **fields)
        self.store.drop_live(n)
        for key in ("beat", "lease", "touch", "born", "torn"):
            self.clocks.forget((key, n))

    def _still_open(self, n: int) -> bool:
        return self.states().get(n, {}).get("open", False)

    def same_process(self, pid: int | None, start: float | None) -> bool:
        if not self.pid_alive(pid):
            return False
        if not start:
            return True
        seen = self.proc_start(pid)
        return seen is None or abs(seen - float(start)) <= 2.0

    # ---- recovery
    def reap(self, states: dict[int, dict[str, Any]] | None = None) -> list[int]:
        """Finish every open ticket whose owner is gone. Safe to call from any waiter, any number of times."""
        now, done = self.clock(), []
        self.clocks.check()
        states = states if states is not None else self.states()
        open_ns = sorted(n for n, s in states.items() if s["open"])
        beats, touches = self.store.beats(open_ns), self.store.touches()
        by = LANE_PREFIX + (self.agent or "unknown")
        self.clocks.note_queue_silence(self._others_stamps(states, open_ns, beats), now)
        for n in open_ns:
            s = states[n]
            alive, why = judge(
                s, beats.get(n), touches.get(n), now, self.cfg, self.same_process, self.clocks, blind=self.blind
            )
            if alive or not self._still_open(n):
                continue
            done.append(n)
            self._finish_dead(n, s, why, beats.get(n) or {}, by)
        if not done:
            self._drop_idle_head(states, by, done)
        return done

    def _others_stamps(
        self, states: dict[int, dict[str, Any]], open_ns: list[int], beats: dict[int, dict[str, Any]]
    ) -> list[float]:
        """The newest sign of life of every open ticket that is not mine: all of them old means nobody else was awake."""
        stamps = []
        for n in open_ns:
            t = states[n]["ticket"]
            if t.get("pid") == self.pid or states[n].get("owner_pid") == self.pid:
                continue
            beat = beats.get(n) or {}
            stamps.append(
                float(beat.get("mtime") if beat.get("unreadable") else beat.get("t") or t.get("created") or 0)
            )
        return stamps

    def touch(self, num: int, *, throttle: bool = True) -> None:
        """Called by every --wait / --resume / foreground poll: the sign that someone still wants this ticket."""
        mono = self.mono()
        if throttle and mono - self._beat_at.get(("t", num), float("-inf")) < self.cfg.beat_every:
            return
        self._beat_at[("t", num)] = mono
        self.store.touch(num, now=self.clock())

    def lease_left(self, num: int) -> float:
        s = self.states().get(num) or {}
        if "granted_at" not in s:
            return self.cfg.max_hold
        return max(1.0, s["max_hold"] - (self.clock() - s["granted_at"]))

    def note_overran(self, num: int, seconds: float) -> None:
        """Said once per ticket: the landing has held the slot longer than ``warn_hold`` (it is killed only at the lease)."""
        if not self.states().get(num, {}).get("overran"):
            self.store.append("overran", num, by=self.agent, now=self.clock(), reason=f"{int(seconds)}s")
            self.say(
                f"hold overran: this landing has held the slot {int(seconds)} s (warned at {int(self.cfg.warn_hold)} s, stopped at the {int(self.cfg.max_hold)} s lease)"
            )

    def mark_unbounded(self, num: int, why: str) -> None:
        """The OS would not put the commit tool in a job: the lease cannot reach orphaned grandchildren on this ticket."""
        if not self.states().get(num, {}).get("unbounded"):
            self.store.append("unbounded", num, by=self.agent, now=self.clock(), reason=why)
            self.say(
                f"WARNING: the commit tool is not in a job object ({why}); falling back to a tree kill, orphans may survive the lease"
            )

    def _finish_dead(self, n: int, s: dict[str, Any], why: str, beat: dict[str, Any], by: str) -> None:
        key, includes = s["ticket"].get("key", ""), s["ticket"].get("includes") or []
        child, child_start = int(beat.get("child") or 0), float(beat.get("child_start") or 0)
        script, killed, ignored = str(beat.get("child_script") or ""), None, ""
        if s["state"] in ("holding", "landed") and child and why.startswith("lease_expired"):
            # Only the commit tool's own recorded child, with its recorded start time AND running the commit tool, and only
            # after the lease. A pid named by a heartbeat file anyone can write is otherwise left alone and reported.
            if not child_start or not script:
                ignored = f"the heartbeat names pid {child} without a recorded start time and commit tool"
            elif self.same_process(child, child_start):
                if script in self.proc_cmd(child):
                    self.kill_child(child, child_start)
                    killed = not self.same_process(child, child_start)
                else:
                    ignored = f"the heartbeat names pid {child}, which is not running the commit tool"
        sha = self.find_landed(key, includes) if s["state"] in ("holding", "landed") and key else None
        if s["state"] == "landed" or sha:
            note = f"your change already landed as {sha or s['sha']}; nothing to re-run"
            self._finish("recovered", n, by=by, sha_landed=sha or s["sha"], reason=why, notice=note)
        elif s["state"] == "holding":
            note = (
                f"you held the landing slot and it was taken back ({why}); nothing landed. "
                "Run land.py again (the retry goes to the back of the line)"
            )
            extra = {"child_pid": child, "child_start": child_start, "killed": killed} if child and not ignored else {}
            extra = {**extra, "child_ignored": ignored} if ignored else extra
            self._finish("skipped", n, by=by, reason=why, notice=note, ran=beat.get("ran"), **extra)
        else:
            note = f"your queue ticket was dropped ({why}); run land.py again"
            if why == "nobody_resumed":
                note = "nobody asked about your submitted ticket for too long, so it left the line; run land.py again"
            self._finish("abandoned", n, by=by, reason=why, notice=note)

    def _drop_idle_head(self, states: dict[int, dict[str, Any]], by: str, done: list[int]) -> None:
        """A head waiter that never takes the slot (hand-made ticket, wedged process) must not block everyone."""
        opens = sorted(n for n, s in states.items() if s["open"])
        head = opens[0] if opens else None
        if head is None or states[head]["state"] != "waiting" or states[head]["ticket"].get("agent") == self.agent:
            self._head = (None, 0.0)
            return
        if self.blocked_by_orphan(states) or self._head[0] != head:
            self._head = (head, self.mono())
            return
        if self.mono() - self._head[1] > self.cfg.head_grant_grace and self._still_open(head):
            note = "you were first in line but did not take the landing slot in time; run land.py again"
            self._finish("abandoned", head, by=by, reason="never_took_slot", notice=note)
            done.append(head)

    def blocked_by_orphan(self, states: dict[int, dict[str, Any]]) -> bool:
        """A commit tool left running by a skipped holder still owns the branch: never start a second one beside it."""
        now = self.clock()
        for s in states.values():
            for e in s["events"]:
                if (
                    e.get("kind") == "skipped"
                    and e.get("child_pid")
                    and now - float(e.get("at") or 0) < self.cfg.max_hold
                ):
                    if self.same_process(int(e["child_pid"]), e.get("child_start")):
                        return True
        return False

    # ---- numbers for humans
    def durations(self) -> list[float]:
        rows = []
        for s in self.states().values():
            g = next((e for e in s["events"] if e["kind"] == "granted"), None)
            f = next((e for e in s["events"] if e["kind"] == "landed"), None)
            if g and f:
                rows.append(float(f["at"]) - float(g["at"]))
        return rows

    def eta(self, ahead: int) -> float:
        rows = self.durations()[-20:]
        return (statistics.median(rows) if rows else 30.0) * (ahead + 1)

    def _holder_text(self, states: dict[int, dict[str, Any]]) -> str:
        h = next((s for s in states.values() if s["open"] and s["state"] in ("holding", "landed")), None)
        if not h:
            return "none yet"
        return f"{h['ticket'].get('agent')} for {int(self.clock() - h['granted_at'])}s"
