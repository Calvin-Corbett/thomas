"""The pre-check: one dry run of the commit tool while a ticket waits near the head of the line. Stdlib only.

It runs inside the process that waits for the ticket (the detached worker, or land.py with ``--no-detach``), never before
the ticket exists, so ``--submit`` returns once the ticket exists. It is plugged into ``Lane.wait_turn`` as ``on_wait``
and runs:

* only when at most ``NEAR_HEAD`` open tickets are ahead, so a hundred waiters do not all run dry runs;
* only when one of ``MAX_PRECHECKS`` queue-wide slots is free right now. It never waits for one: no free slot means
  "try again at the next poll", and a ticket that reaches its turn without one simply lands (the real run runs every gate);
* at low priority, at most once per ticket, beating the ticket's heartbeat while it runs;
* never in the way of a turn: when the ticket's turn comes while the dry run runs, the dry run is stopped.

A refusal that only reflects a branch others keep moving (retried once), a timeout and a stop are advisory: the ticket
stays in line. Any other refusal finishes the ticket as refused before it ever used the slot (exit 1, not counted toward
the refusal cap), with the commit tool's whole output in a file under the queue root.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from scripts.crew.brief import land_commit
from scripts.crew.brief.landing_queue import Lane, Outcome

MAX_PRECHECKS = 2  # dry runs at a time, queue-wide
NEAR_HEAD = 2  # a pre-check runs only with at most this many open tickets ahead
STALE_SLOT = 600.0  # a slot file older than this was left by a killed pre-check
RACE_GATES = frozenset({"workboard_agent_claim", "workboard_changed_files"})  # judge a HEAD that others keep moving
ADVISORY = frozenset({"precheck_timeout", "precheck_stopped"})


def try_slot(folder: Path) -> Path | None:
    """One of the queue-wide slots if one is free right now, else None. Never waits."""
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(MAX_PRECHECKS):
        path = folder / f"S{i}.lock"
        try:
            if time.time() - path.stat().st_mtime > STALE_SLOT:
                path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return path
        except OSError:
            continue
    return None


def race_only(out: Outcome) -> bool:
    return out.blocker == "branch_race" or out.gate in RACE_GATES


class Precheck:
    """``lane.on_wait`` for one ticket: called on every poll while others are ahead."""

    def __init__(self, lane: Lane, num: int, cmd: list[str], root: Path, pause: float = 2.0):
        self.lane, self.num, self.cmd, self.root, self.pause = lane, num, cmd, root, pause
        self.done = False

    def __call__(self, num: int, ahead: int) -> None:
        if self.done or num != self.num or ahead > NEAR_HEAD:
            return
        slot = try_slot(self.lane.store.root / "prechecks")
        if slot is None:
            return  # every slot is busy: try again at the next poll, never pile onto the holder
        self.done = True
        try:
            verdict = self.run()
        except (OSError, ValueError, subprocess.SubprocessError) as exc:  # an advisory step never costs the ticket
            self.lane.say(f"pre-check could not run ({type(exc).__name__}: {exc}); queueing anyway")
            return
        finally:
            slot.unlink(missing_ok=True)
        if verdict.ok or verdict.blocker == "precheck_stopped":
            return
        if verdict.blocker in ADVISORY or race_only(verdict):
            self.lane.say(f"pre-check: {verdict.message[:300]}; queueing anyway (the real run still runs every gate)")
            return
        self.lane.refuse_early(self.num, verdict)

    def turn_came(self) -> bool:
        states = self.lane.states()
        mine = states.get(self.num)
        return not mine or not mine["open"] or not any(s["open"] and n < self.num for n, s in states.items())

    def run(self) -> Outcome:
        """At most two dry runs: a race-class refusal is retried once, anything else is the answer."""

        def tick(ran: float) -> bool:
            self.lane.beat(self.num, "waiting", throttle=True)  # a dry run is no reason to look dead
            return self.turn_came()

        def save(text: str) -> str | None:
            return land_commit.save_output(self.lane.store.root, self.num, "precheck", text)

        last = Outcome(True)
        for attempt in range(2):
            last, _paths, stopped = land_commit.dry_run(self.cmd, self.root, self.lane.cfg.precheck_timeout, tick, save)
            if stopped or last.ok or not race_only(last):
                return last
            if attempt == 0:
                time.sleep(self.pause)
        return last
