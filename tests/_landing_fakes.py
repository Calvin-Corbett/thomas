"""Fakes for the landing queue tests: a clock the test moves, a world of live pids, a fake dev branch."""

from __future__ import annotations

import time
from pathlib import Path

from scripts.crew.brief import landing_proc
from scripts.crew.brief.landing_queue import Config, Lane, Outcome
from scripts.crew.brief.landing_store import FileTicketStore


class FakeClock:
    def __init__(self) -> None:
        self.now = time.time()  # real epoch, so file mtimes and the fake clock agree
        self.tick = 1000.0  # the monotonic clock

    def __call__(self) -> float:
        return self.now

    def mono(self) -> float:
        return self.tick

    def advance(self, seconds: float) -> None:
        self.now += seconds
        self.tick += seconds

    def jump(self, seconds: float) -> None:
        """The wall clock is set (laptop resume): the monotonic clock does not move."""
        self.now += seconds


class World:
    """Which pids are alive, the shared clock, the fake dev branch, and a presence-heartbeat counter."""

    def __init__(self, tmp: Path, cfg: Config | None = None) -> None:
        self.clock = FakeClock()
        self.alive: set[int] = set()
        self.starts: dict[int, float] = {}
        self.killed: list[int] = []
        self.cmds: dict[int, str] = {}
        self.locks: tuple[list[str], list[str]] = ([], [])
        self.dev: list[tuple[str, str]] = []  # (sha, message)
        self.cfg = cfg or Config(poll=2.0, say_every=1e9)
        self.store = FileTicketStore(tmp / "queue")
        self.presence_calls = 0
        self.commit_calls = 0
        self.said: list[str] = []

    def find_landed(self, key: str, includes=(), own=False) -> str | None:  # noqa: ANN001
        return next((sha for sha, message in self.dev if f"Landing-Ticket: {key}" in message), None)

    def land_on_dev(self, key: str) -> str:
        sha = f"sha{len(self.dev) + 1:04d}"
        self.dev.append((sha, f"change\n\nLanding-Ticket: {key}"))
        return sha

    def lane(self, agent: str, pid: int, sleep=None, cfg: Config | None = None) -> Lane:  # noqa: ANN001
        self.alive.add(pid)

        def presence() -> None:
            self.presence_calls += 1

        return Lane(
            self.store,
            agent=agent,
            session=f"s-{agent}",
            pid=pid,
            clock=self.clock,
            mono=self.clock.mono,
            proc_start=self.starts.get,
            proc_cmd=lambda pid: self.cmds.get(pid, ""),
            kill_child=lambda pid, start: (self.killed.append(pid), self.alive.discard(pid)),
            git_cleanup=lambda: self.locks,
            sleep=sleep or self.clock.advance,
            pid_alive=lambda p: p in self.alive,
            find_landed=self.find_landed,
            presence=presence,
            say=self.said.append,
            cfg=cfg or self.cfg,
        )

    def life(self, seconds: float, observer, *beaters, step: float = 2.0) -> None:  # noqa: ANN001, ANN002
        """Time passes as a live queue lives it: every step each (lane, ticket, phase) beats and the observer polls."""
        for _ in range(int(seconds // step)):
            self.clock.advance(step)
            for lane, num, phase, *extra in beaters:  # an optional fourth item is the beat's extra keyword arguments
                lane.beat(num, phase, throttle=True, **(extra[0] if extra else {}))
            observer.reap()

    def bystander(self, name: str = "z", pid: int = 900):  # noqa: ANN201
        """A live waiter at the back of the line: proof that someone else is awake, which a sleeping machine never has."""
        lane = self.lane(name, pid)
        return lane, lane.enqueue(f"k-{name}", "s")

    def committer(self, key: str):  # noqa: ANN201
        def commit() -> Outcome:
            self.commit_calls += 1
            return Outcome(True, sha=self.land_on_dev(key))

        return commit


def holder_numbers(lane: Lane) -> list[int]:
    return [n for n, s in lane.states().items() if s["open"] and s["state"] in ("holding", "landed")]


class sp:  # noqa: N801 - reads like the subprocess module at the call site
    """The subprocess calls the tests make themselves, started without a console window (as the product's are)."""

    run = staticmethod(landing_proc.run)
    Popen = staticmethod(landing_proc.popen)
