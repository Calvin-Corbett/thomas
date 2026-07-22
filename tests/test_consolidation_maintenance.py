"""Tests for the background consolidation sweep.

The loop runs inside the server, so the properties that matter are: it actually
sweeps on a cadence, a failing sweep never escalates into an outage, and it
stops cleanly when the server shuts down.
"""

from __future__ import annotations

import asyncio

import pytest

from thomas.server.consolidation_maintenance import (
    ENABLED_ENV,
    INTERVAL_ENV,
    MAX_INTERVAL_S,
    MIN_INTERVAL_S,
    audit_interval_s,
    consolidation_maintenance_loop,
    maintenance_enabled,
    run_audit_once,
)


class Recorder:
    """Captures sweeps and sleeps so the loop needs no real time."""

    def __init__(self, *, raises: bool = False) -> None:
        self.sweeps = 0
        self.slept: list[float] = []
        self.raises = raises

    def audit(self) -> dict:
        self.sweeps += 1
        if self.raises:
            raise OSError("git exploded")
        return {"ok": True, "action": "none"}

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)


@pytest.mark.asyncio
async def test_loop_sweeps_on_a_cadence() -> None:
    rec = Recorder()
    cycles = await consolidation_maintenance_loop(
        startup_delay_s=0, interval_s=123.0, audit_fn=rec.audit, sleep_fn=rec.sleep, max_cycles=3
    )
    assert cycles == 3
    assert rec.sweeps == 3
    # sleeps between cycles, not after the last one
    assert rec.slept == [123.0, 123.0]


@pytest.mark.asyncio
async def test_startup_delay_is_awaited_before_the_first_sweep() -> None:
    rec = Recorder()
    await consolidation_maintenance_loop(
        startup_delay_s=30.0, interval_s=5.0, audit_fn=rec.audit, sleep_fn=rec.sleep, max_cycles=1
    )
    assert rec.slept[0] == 30.0  # boot finishes before the first sweep


@pytest.mark.asyncio
async def test_a_failing_sweep_never_takes_the_server_down() -> None:
    """The whole point: maintenance must not escalate into an outage."""
    rec = Recorder(raises=True)
    cycles = await consolidation_maintenance_loop(
        startup_delay_s=0, interval_s=1.0, audit_fn=rec.audit, sleep_fn=rec.sleep, max_cycles=3
    )
    assert cycles == 3  # kept its cadence despite every sweep raising
    assert rec.sweeps == 3


@pytest.mark.asyncio
async def test_cancellation_propagates_so_shutdown_is_clean() -> None:
    started = asyncio.Event()

    def audit() -> dict:
        started.set()
        return {"ok": True}

    async def forever(_seconds: float) -> None:
        await asyncio.sleep(3600)

    task = asyncio.create_task(
        consolidation_maintenance_loop(startup_delay_s=0, interval_s=1.0, audit_fn=audit, sleep_fn=forever)
    )
    await asyncio.wait_for(started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_disabled_by_env_does_not_sweep(monkeypatch) -> None:
    monkeypatch.setenv(ENABLED_ENV, "0")
    rec = Recorder()
    cycles = await consolidation_maintenance_loop(
        startup_delay_s=0, audit_fn=rec.audit, sleep_fn=rec.sleep, max_cycles=5
    )
    assert cycles == 0
    assert rec.sweeps == 0


def test_maintenance_is_on_unless_explicitly_disabled(monkeypatch) -> None:
    monkeypatch.delenv(ENABLED_ENV, raising=False)
    assert maintenance_enabled() is True
    for off in ("0", "false", "no", "off", "OFF"):
        monkeypatch.setenv(ENABLED_ENV, off)
        assert maintenance_enabled() is False


def test_interval_is_clamped_to_something_sane(monkeypatch) -> None:
    monkeypatch.setenv(INTERVAL_ENV, "1")
    assert audit_interval_s() == MIN_INTERVAL_S
    monkeypatch.setenv(INTERVAL_ENV, "99999999")
    assert audit_interval_s() == MAX_INTERVAL_S
    monkeypatch.setenv(INTERVAL_ENV, "not-a-number")
    assert MIN_INTERVAL_S <= audit_interval_s() <= MAX_INTERVAL_S
    monkeypatch.setenv(INTERVAL_ENV, "900")
    assert audit_interval_s() == 900.0


def test_run_audit_once_returns_a_result_rather_than_raising(tmp_path) -> None:
    """Even pointed at a non-repository it must degrade, not explode."""
    payload = run_audit_once(str(tmp_path))
    assert isinstance(payload, dict)
    assert "ok" in payload
