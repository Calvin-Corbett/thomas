"""CAP-077 L2: host supervisor with restart SLA, missed-work reports, and
accumulating role memory.

Every test drives an injected fake clock and injected health/restart callables
-- no real processes, sleeps, or network -- so behaviour is deterministic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.tools.automation_supervisor import (
    MEMORY_PATH_ENV,
    AutomationSupervisor,
    ScheduledWork,
    _default_memory_path,
)


class FakeClock:
    """A controllable monotonic clock: ``now`` is read and advanced explicitly."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Automation:
    """A fake persistent automation with a flip-able health flag.

    ``restart`` advances the injected clock by ``restart_cost`` to model how
    long the restart took, then marks the automation healthy again.
    """

    def __init__(self, clock: FakeClock, *, restart_cost: float) -> None:
        self._clock = clock
        self._restart_cost = restart_cost
        self.up = True
        self.restart_calls = 0

    def probe(self) -> bool:
        return self.up

    def restart(self) -> None:
        self.restart_calls += 1
        self._clock.advance(self._restart_cost)
        self.up = True


def test_down_automation_restarted_with_latency_within_sla(tmp_path: Path) -> None:
    clock = FakeClock(start=100.0)
    auto = Automation(clock, restart_cost=2.0)
    sup = AutomationSupervisor(clock=clock, memory_path=tmp_path / "mem.json")
    sup.register("worker", sla_seconds=5.0, health_probe=auto.probe, restart_action=auto.restart)

    # Confirm healthy first.
    assert sup.tick("worker").healthy is True

    # Automation dies; a tick observes it down and restarts it.
    auto.up = False
    clock.advance(1.0)
    result = sup.tick("worker")

    assert result.healthy is False
    assert result.restart is not None
    assert auto.restart_calls == 1
    assert auto.up is True  # restored
    # Latency = restart cost = 2.0s, comfortably inside the 5s SLA.
    assert result.restart.latency_seconds == pytest.approx(2.0)
    assert result.restart.sla_breach is False
    assert sup.sla_breaches("worker") == []


def test_restart_slower_than_sla_is_flagged_as_breach(tmp_path: Path) -> None:
    clock = FakeClock(start=0.0)
    auto = Automation(clock, restart_cost=10.0)  # slow restart
    sup = AutomationSupervisor(clock=clock, memory_path=tmp_path / "mem.json")
    sup.register("slowpoke", sla_seconds=5.0, health_probe=auto.probe, restart_action=auto.restart)

    auto.up = False
    result = sup.tick("slowpoke")

    assert result.restart is not None
    assert result.restart.latency_seconds == pytest.approx(10.0)
    assert result.restart.sla_breach is True
    breaches = sup.sla_breaches("slowpoke")
    assert len(breaches) == 1
    assert breaches[0].latency_seconds == pytest.approx(10.0)


def test_missed_work_reported_on_recovery(tmp_path: Path) -> None:
    clock = FakeClock(start=0.0)
    auto = Automation(clock, restart_cost=1.0)
    sup = AutomationSupervisor(clock=clock, memory_path=tmp_path / "mem.json")
    schedule = [
        ScheduledWork("cron", run_at=10.0, label="nightly-sync"),
        ScheduledWork("cron", run_at=20.0, label="hourly-report"),
        ScheduledWork("cron", run_at=99.0, label="future-job"),  # after recovery
    ]
    sup.register(
        "cron",
        sla_seconds=30.0,
        health_probe=auto.probe,
        restart_action=auto.restart,
        schedule=schedule,
    )

    # Seen healthy at t=5, so downtime starts there.
    clock.advance(5.0)
    assert sup.tick("cron").healthy is True

    # Goes down; discovered at t=25. Restart costs 1s -> recovered at t=26.
    auto.up = False
    clock.advance(20.0)  # now t=25
    result = sup.tick("cron")

    report = result.missed_report
    assert report is not None
    assert report.down_since == pytest.approx(5.0)
    assert report.recovered_at == pytest.approx(26.0)
    labels = [w.label for w in report.missed]
    # Work at t=10 and t=20 fell in the [5, 26] downtime window; t=99 did not.
    assert labels == ["nightly-sync", "hourly-report"]
    assert report.missed_count == 2


def test_role_memory_accumulates_across_two_restarts(tmp_path: Path) -> None:
    clock = FakeClock(start=0.0)
    auto = Automation(clock, restart_cost=1.0)
    sup = AutomationSupervisor(clock=clock, memory_path=tmp_path / "mem.json")
    sup.register("agent", sla_seconds=5.0, health_probe=auto.probe, restart_action=auto.restart)

    sup.remember("agent", "learned: prefers batch mode")

    # First restart.
    auto.up = False
    clock.advance(1.0)
    sup.tick("agent")

    sup.remember("agent", "learned: db host is db-1")

    # Second restart.
    auto.up = False
    clock.advance(1.0)
    sup.tick("agent")

    texts = [f.text for f in sup.role_memory("agent")]
    # Pre-restart facts survive both restarts; new facts append; each restart
    # also contributed its own auto-fact -> memory strictly accumulates.
    assert "learned: prefers batch mode" in texts
    assert "learned: db host is db-1" in texts
    restart_facts = [f for f in sup.role_memory("agent") if f.source == "restart"]
    assert len(restart_facts) == 2
    # Nothing was wiped: at least the 2 manual + 2 restart facts remain.
    assert len(texts) >= 4
    # The earliest manual fact still precedes the later ones (append order).
    assert texts.index("learned: prefers batch mode") < texts.index("learned: db host is db-1")


def test_role_memory_survives_supervisor_restart(tmp_path: Path) -> None:
    mem_path = tmp_path / "mem.json"
    clock = FakeClock(start=0.0)
    auto = Automation(clock, restart_cost=1.0)

    sup = AutomationSupervisor(clock=clock, memory_path=mem_path)
    sup.register("persist", sla_seconds=5.0, health_probe=auto.probe, restart_action=auto.restart)
    sup.remember("persist", "fact-one")
    auto.up = False
    sup.tick("persist")  # appends a restart fact too

    before = [f.text for f in sup.role_memory("persist")]
    assert "fact-one" in before

    # Simulate a full supervisor process restart: brand-new instance, same path.
    clock2 = FakeClock(start=500.0)
    sup2 = AutomationSupervisor(clock=clock2, memory_path=mem_path)
    reloaded = [f.text for f in sup2.role_memory("persist")]

    assert reloaded == before  # durable store round-tripped exactly

    # And it keeps accumulating from the reloaded baseline.
    sup2.register(
        "persist",
        sla_seconds=5.0,
        health_probe=auto.probe,
        restart_action=auto.restart,
    )
    sup2.remember("persist", "fact-two")
    assert [f.text for f in sup2.role_memory("persist")] == before + ["fact-two"]


def test_memory_path_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "env" / "role_memory.json"
    monkeypatch.setenv(MEMORY_PATH_ENV, str(target))
    assert _default_memory_path() == target

    clock = FakeClock()
    sup = AutomationSupervisor(clock=clock)  # no explicit path -> uses env
    sup.register("x", sla_seconds=1.0, health_probe=lambda: True, restart_action=lambda: None)
    sup.remember("x", "hello")
    assert target.exists()


def test_determinism_via_injected_clock(tmp_path: Path) -> None:
    def run() -> list[float]:
        clock = FakeClock(start=0.0)
        auto = Automation(clock, restart_cost=3.0)
        sup = AutomationSupervisor(clock=clock, memory_path=tmp_path / f"mem-{clock.now}.json")
        sup.register("d", sla_seconds=5.0, health_probe=auto.probe, restart_action=auto.restart)
        clock.advance(2.0)
        sup.tick("d")
        auto.up = False
        clock.advance(4.0)
        sup.tick("d")
        return [r.latency_seconds for r in sup.restart_history("d")]

    # Same injected clock trajectory -> identical latencies, run after run.
    assert run() == run()
    assert run() == [pytest.approx(3.0)]


def test_unregistered_automation_raises(tmp_path: Path) -> None:
    sup = AutomationSupervisor(clock=FakeClock(), memory_path=tmp_path / "mem.json")
    with pytest.raises(KeyError):
        sup.tick("nope")
