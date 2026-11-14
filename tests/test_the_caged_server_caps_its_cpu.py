"""The caged server and everything it starts stay under their share of this PC's processor time (2026-10-25).

You asked: "make sure thomas doesnt ever max out the pc always 90%". Waiting for room left the PC at 98% with ten teams
running their tests, so the server joins a job with a hard CPU rate cap before it starts anything.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from scripts.cage import cpu_cap


class FakeKernel:
    def __init__(self, *, rate_ok: bool = True, join_ok: bool = True) -> None:
        self.rate_ok, self.join_ok = rate_ok, join_ok
        self.rates: list[tuple[int, int, int]] = []
        self.joined: list[tuple[int, str]] = []
        self.closed: list[int] = []

    def CreateJobObjectW(self, _attrs: Any, _name: Any) -> int:  # noqa: N802 -- the Windows names
        return 7

    def SetInformationJobObject(self, job: int, kind: int, rate: Any, size: int) -> bool:  # noqa: N802
        info = rate._obj
        self.rates.append((kind, info.ControlFlags, info.CpuRate))
        return self.rate_ok

    def GetCurrentProcess(self) -> str:  # noqa: N802
        return "this process"

    def AssignProcessToJobObject(self, job: int, process: str) -> bool:  # noqa: N802
        self.joined.append((job, process))
        return self.join_ok

    def CloseHandle(self, job: int) -> None:  # noqa: N802
        self.closed.append(job)


@pytest.fixture(autouse=True)
def _no_job_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cpu_cap, "_job", None)
    monkeypatch.delenv(cpu_cap.LIMIT_ENV, raising=False)
    monkeypatch.delenv(cpu_cap.CAPPED_ENV, raising=False)  # restored after each test, whatever the cap set


def test_the_server_joins_a_job_that_starts_with_the_whole_pc() -> None:
    kernel = FakeKernel()
    said = cpu_cap.cap_this_process_tree(kernel, follow=False)
    assert kernel.rates == [(15, 0x1 | 0x4, 10_000)], "enabled, and all 10,000 of every 10,000 cycles to start"
    assert kernel.joined == [(7, "this process")] and kernel.closed == [], "the job stays open for the server's life"
    assert said.startswith("CPU soft limit: this server and everything it starts are slowed only while this PC")
    assert "averages 90% or more over 5 minutes" in said
    assert os.environ[cpu_cap.CAPPED_ENV] == "90", "its children's CPU waits for room stand down"


def test_the_cap_and_the_waits_name_the_same_setting() -> None:
    from thomas.core import machine_load

    assert (cpu_cap.LIMIT_ENV, cpu_cap.CAPPED_ENV) == (machine_load.LIMIT_ENV, machine_load.CAPPED_ENV)


def test_the_limit_follows_the_same_setting_as_the_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cpu_cap.LIMIT_ENV, "75")
    kernel = FakeKernel()
    assert "averages 75% or more" in cpu_cap.cap_this_process_tree(kernel, follow=False)
    assert kernel.rates[0][2] == 10_000 and os.environ[cpu_cap.CAPPED_ENV] == "75"
    monkeypatch.setenv(cpu_cap.LIMIT_ENV, "0")
    off = FakeKernel()
    assert cpu_cap.cap_this_process_tree(off, follow=False).startswith("no CPU cap") and off.rates == off.joined == []


@pytest.mark.parametrize("broken", ["rate", "join"])
def test_a_cap_that_cannot_be_set_is_said_and_the_server_starts_anyway(broken: str) -> None:
    kernel = FakeKernel(rate_ok=broken != "rate", join_ok=broken != "join")
    said = cpu_cap.cap_this_process_tree(kernel, follow=False)
    assert said.startswith("no CPU cap:") and kernel.closed == [7]
    assert cpu_cap._job is None and cpu_cap.CAPPED_ENV not in os.environ, "without the cap the CPU waits stay on"


def test_a_test_that_runs_the_server_entry_never_caps_the_test_run() -> None:
    assert cpu_cap.cap_this_process_tree() in {"no CPU cap (under pytest)", "no CPU cap (not Windows)"}
    assert cpu_cap._job is None


@pytest.mark.parametrize(
    ("share", "average", "expected"),
    [(100, 95, 90), (40, 95, 30), (30, 99, 30), (70, 88, 70), (70, 80, 80), (95, 50, 100)],
    ids=["busy: a step down", "busy: down to the floor", "never under the floor", "between: held", "calm: a step back",
         "never over all of it"],
)  # fmt: skip
def test_thomas_is_slowed_only_on_a_busy_average_and_given_it_back_on_a_calm_one(
    share: float, average: float, expected: float
) -> None:
    assert cpu_cap.next_share(share, average, 90.0) == expected


class FakePC(FakeKernel):
    """A PC with ten processors whose readings are fed in: the job's processor time and the PC's busy time."""

    def __init__(self) -> None:
        super().__init__()
        self.job_ticks, self.busy, self.whole = 0, 0, 0

    def tick(self, seconds: float, ours: float, total: float) -> None:
        capacity = int(seconds * 1e7 * 10)
        self.job_ticks += int(capacity * ours / 100)
        self.busy += int(capacity * total / 100)
        self.whole += capacity

    def QueryInformationJobObject(self, job: int, kind: int, spent: Any, size: int, _length: Any) -> bool:  # noqa: N802
        spent._obj.TotalUserTime, spent._obj.TotalKernelTime = self.job_ticks, 0
        return kind == 1

    def GetSystemTimes(self, idle: Any, kernel: Any, user: Any) -> bool:  # noqa: N802
        for target, value in ((idle, self.whole - self.busy), (kernel, self.whole), (user, 0)):
            target._obj.dwHighDateTime, target._obj.dwLowDateTime = value >> 32, value & 0xFFFFFFFF
        return True


def test_a_short_spike_slows_nothing_and_a_busy_five_minutes_slows_thomas_a_step_a_minute() -> None:
    pc, now = FakePC(), [0.0]
    follower = cpu_cap.Follower(pc, 7, 90.0, clock=lambda: now[0])
    follower.cpus = 10
    assert follower.step() is None and follower.share == 100.0, "no interval measured yet; Thomas has all of it"
    moves: list[tuple[float, int]] = []

    def run_for(seconds: int, total: float) -> None:
        for _ in range(seconds // 10):
            now[0] += 10
            before = len(pc.rates)
            pc.tick(10, ours=50.0, total=total)
            follower.step()
            moves.extend((now[0], rate) for _kind, _flags, rate in pc.rates[before:])

    run_for(270, total=99.0)
    assert moves == [], "under 5 minutes busy: nothing is slowed"
    run_for(150, total=99.0)
    assert [rate for _, rate in moves] == [9000, 8000, 7000], "a step a minute while the average stays busy"
    run_for(600, total=40.0)
    assert [rate for _, rate in moves] == [9000, 8000, 7000, 8000, 9000, 10_000], "given back once it is calm"
    assert all(b - a >= cpu_cap.SETTLE_S for (a, _), (b, _) in zip(moves, moves[1:])), "a minute between moves"
    assert follower.share == 100.0
