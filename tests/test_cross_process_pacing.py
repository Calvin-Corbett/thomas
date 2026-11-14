"""Real process contention and crash recovery for account request admission."""

from __future__ import annotations

import asyncio
import multiprocessing
import os
from pathlib import Path

import thomas.core.cross_process_pacing as pacing
from thomas.core.cross_process_pacing import CrossProcessProviderPacer
from thomas.core.provider_pacing import parse_retry_after


def _compete(path: str, go, ready, results) -> None:
    pacer = CrossProcessProviderPacer(Path(path), provider="shared", ceiling=3, reserved_interactive=0)
    ready.put(os.getpid())
    go.wait(15)

    async def run() -> None:
        async def one(index: int) -> None:
            row = await pacer.acquire(f"{os.getpid()}:{index}")
            assert row["slot"]
            await asyncio.sleep(0.08)
            pacer.release(f"{os.getpid()}:{index}", ticket=row["ticket"], kind="clean")

        await asyncio.gather(*(one(index) for index in range(5)))

    asyncio.run(run())
    results.put(pacer.report())


def _die_holding_lease(path: str, ready) -> None:
    pacer = CrossProcessProviderPacer(Path(path), provider="crash", ceiling=1, reserved_interactive=0)
    row = asyncio.run(pacer.acquire("doomed"))
    ready.put(row["ticket"])
    ready.close()
    ready.join_thread()
    os._exit(0)


def test_two_processes_share_one_provider_cap(tmp_path):
    context = multiprocessing.get_context("spawn")
    go, ready, results = context.Event(), context.Queue(), context.Queue()
    path = str(tmp_path / "provider.sqlite3")
    processes = [context.Process(target=_compete, args=(path, go, ready, results)) for _ in range(2)]
    for process in processes:
        process.start()
    try:
        assert ready.get(timeout=20) != ready.get(timeout=20)
        go.set()
        reports = [results.get(timeout=30) for _ in processes]
        assert all(report["peak_inflight"] == 3 for report in reports)
    finally:
        go.set()
        for process in processes:
            process.join(15)
            if process.is_alive():
                process.terminate()
                process.join(5)
        assert all(process.exitcode == 0 for process in processes)
    final = CrossProcessProviderPacer(Path(path), provider="shared", ceiling=3, reserved_interactive=0).report()
    assert final["inflight_now"] == final["waiting_now"] == 0


def test_crashed_process_lease_is_reaped(tmp_path):
    context = multiprocessing.get_context("spawn")
    path = str(tmp_path / "provider.sqlite3")
    ready = context.Queue()
    process = context.Process(target=_die_holding_lease, args=(path, ready))
    process.start()
    ready.get(timeout=20)
    process.join(15)
    assert process.exitcode == 0
    pacer = CrossProcessProviderPacer(Path(path), provider="crash", ceiling=1, reserved_interactive=0)

    async def recover() -> None:
        row = await asyncio.wait_for(pacer.acquire("replacement"), timeout=5)
        assert row["slot"] and pacer.report()["inflight_now"] == 1
        pacer.release("replacement", ticket=row["ticket"], kind="clean")

    asyncio.run(recover())
    assert pacer.report()["inflight_now"] == 0


def test_refusal_window_is_shared_across_pacer_instances(tmp_path):
    path = tmp_path / "provider.sqlite3"
    first = CrossProcessProviderPacer(path, provider="rate", ceiling=4, reserved_interactive=0)
    second = CrossProcessProviderPacer(path, provider="rate", ceiling=4, reserved_interactive=0)

    async def run() -> None:
        old_a = await first.acquire("old-a")
        old_b = await second.acquire("old-b")
        first.release("old-a", ticket=old_a["ticket"], kind="provider_refusal", retry_after_raw=0)
        assert second.report()["cap_now"] == 2
        second.release("old-b", ticket=old_b["ticket"], kind="provider_refusal", retry_after_raw=0)
        assert first.report()["cap_now"] == 2
        for index in range(8):
            row = await second.acquire(f"clean-{index}")
            second.release(f"clean-{index}", ticket=row["ticket"], kind="clean")
        assert first.report()["cap_now"] == 3

    asyncio.run(run())


def test_process_identity_without_optional_psutil(monkeypatch):
    monkeypatch.setattr(pacing, "psutil", None)
    assert pacing._process_started(os.getpid()) is not None


def test_zero_retry_after_is_a_real_zero_not_missing_header():
    assert parse_retry_after(0.0) == 0.0
    assert parse_retry_after("0") == 0.0
    assert parse_retry_after(None) is None
