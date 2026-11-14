"""The Build run limit is this computer's, measured -- not a fixed 8.

You asked: "make it estimate the most the hardware can do and set that as
the limit. this will need to happen to everyone who installs as part of the
first start up." Regression for thomas.core.machine_capacity: the three
worked examples from the brief, the profile's recompute-only-when-hardware-
changed rule, the env override, admission refusals, peak-based refinement,
startup registration, and the read-only capacity route.

A running server reaches that registration through
thomas.server.rows.machine_capacity, which nothing imports, so that dotted
name, here, is how a check of the row finds this file. These tests call it on
an app of their own, where the hooks wait for that app to start and stop.

Every test patches the machine (CPU/memory) and the data-dir resolver; none
of them ever reads this real machine or writes to its real Thomas data dir.
"""

from __future__ import annotations

import asyncio
import json
import math
import sys
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.core import machine_capacity as mc


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv(mc.ENV_OVERRIDE, raising=False)
    monkeypatch.setattr(mc, "_default_data_dir", lambda: tmp_path)
    monkeypatch.setattr(mc.os, "cpu_count", lambda: 4)
    monkeypatch.setattr(mc, "_memory", lambda: (None, None))
    return tmp_path


def test_run_registry_key_matches_the_real_app_key() -> None:
    """`_RUN_REGISTRY_KEY` duplicates this constant rather than importing it (thomas/core/
    must not import thomas/server/); nothing else keeps the two in step, so a rename on
    either side would silently blind the sampler. This test may import thomas.server --
    only thomas/core/machine_capacity.py itself may not."""
    from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_RUNS

    assert mc._RUN_REGISTRY_KEY == APP_EVOLVE_AGENT_RUNS


# ── estimate(): the worked examples ─────────────────────────────────────────


def test_estimate_16cpu_32gib_768mb_budget() -> None:
    assert mc.estimate(cpus=16, total_ram_bytes=32 * 1024**3, run_budget_mb=768) == 32


def test_estimate_4cpu_8gib_768mb_budget() -> None:
    assert mc.estimate(cpus=4, total_ram_bytes=8 * 1024**3, run_budget_mb=768) == 5


def test_estimate_128cpu_512gib_hits_the_runaway_cap() -> None:
    assert mc.estimate(cpus=128, total_ram_bytes=512 * 1024**3, run_budget_mb=768) == 100


def test_estimate_unknown_ram_uses_the_cpu_term_alone() -> None:
    assert mc.estimate(cpus=6, total_ram_bytes=None, run_budget_mb=768) == 6 * mc.CPU_FACTOR


def test_estimate_never_goes_below_one() -> None:
    assert mc.estimate(cpus=0, total_ram_bytes=0, run_budget_mb=768) == 1


# ── profile(): recompute only when the hardware moved ───────────────────────


def test_profile_is_written_on_first_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mc, "_memory", lambda: (16 * 1024**3, 8 * 1024**3))
    prof = mc.profile()
    saved = json.loads((tmp_path / "machine_capacity.json").read_text(encoding="utf-8"))
    assert saved["cpus"] == 4
    assert saved["limit"] == prof["limit"]
    assert saved["source"] == "measured"


def test_profile_not_recomputed_when_hardware_matches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mc, "_memory", lambda: (16 * 1024**3, 8 * 1024**3))
    first = mc.profile()
    # Hand-edit the saved file the way record_run_peak would, to prove a second
    # call on the SAME hardware returns it untouched rather than overwriting it.
    edited = {**first, "run_budget_mb": 999}
    (tmp_path / "machine_capacity.json").write_text(json.dumps(edited), encoding="utf-8")
    second = mc.profile()
    assert second["run_budget_mb"] == 999


def test_profile_recomputed_when_cpus_differ(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mc, "_memory", lambda: (16 * 1024**3, 8 * 1024**3))
    mc.profile()
    monkeypatch.setattr(mc.os, "cpu_count", lambda: 16)
    second = mc.profile()
    assert second["cpus"] == 16
    assert second["limit"] == mc.estimate(cpus=16, total_ram_bytes=16 * 1024**3, run_budget_mb=mc.DEFAULT_RUN_BUDGET_MB)


# ── max_concurrent_runs(): the env override ─────────────────────────────────


def test_env_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(mc.ENV_OVERRIDE, "37")
    assert mc.max_concurrent_runs() == 37


def test_env_override_is_clamped_to_the_runaway_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(mc.ENV_OVERRIDE, "100000")
    assert mc.max_concurrent_runs() == mc.RUNAWAY_LIMIT


@pytest.mark.parametrize("bad", ["", "  ", "abc", "0", "-4", "3.5"])
def test_invalid_env_override_falls_back_to_the_profile(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv(mc.ENV_OVERRIDE, bad)
    assert mc.max_concurrent_runs() == mc.estimate(cpus=4, total_ram_bytes=None, run_budget_mb=mc.DEFAULT_RUN_BUDGET_MB)


# ── admission_refusal() ──────────────────────────────────────────────────────


def test_admission_refusal_at_the_limit_names_processors_and_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mc, "_memory", lambda: (8 * 1024**3, 8 * 1024**3))
    limit = mc.max_concurrent_runs()
    message = mc.admission_refusal(limit)
    assert message is not None
    assert message.startswith(f"All {limit} runs this computer can hold at once are busy")
    assert "4 processors" in message
    assert "GB memory" in message


def test_admission_refusal_low_memory_names_free_and_needed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mc, "_memory", lambda: (32 * 1024**3, 100 * 1024 * 1024))  # 100 MB free
    message = mc.admission_refusal(0)
    assert message is not None
    assert "memory free" in message
    assert "GB" in message


def test_admission_refusal_none_when_there_is_room(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mc.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(mc, "_memory", lambda: (32 * 1024**3, 16 * 1024**3))
    assert mc.admission_refusal(0) is None


# ── record_run_peak(): refinement from real runs ────────────────────────────


def test_record_run_peak_needs_five_samples_before_refining(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mc.os, "cpu_count", lambda: 32)
    monkeypatch.setattr(mc, "_memory", lambda: (16 * 1024**3, 16 * 1024**3))
    before = mc.profile()
    for peak in (400.0, 420.0, 440.0, 460.0):
        mc.record_run_peak(peak)
    after = mc.profile()
    assert after["run_budget_mb"] == before["run_budget_mb"]
    assert after["limit"] == before["limit"]
    assert after["observed_peaks_mb"] == [400.0, 420.0, 440.0, 460.0]


def test_record_run_peak_fifth_sample_refines_budget_and_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mc.os, "cpu_count", lambda: 32)
    monkeypatch.setattr(mc, "_memory", lambda: (16 * 1024**3, 16 * 1024**3))
    before = mc.profile()
    for peak in (400.0, 420.0, 440.0, 460.0, 480.0):
        mc.record_run_peak(peak)
    after = mc.profile()
    expected_budget = max(mc._MIN_RUN_BUDGET_MB, math.ceil(480.0 * mc._PEAK_SAFETY_FACTOR))
    assert after["run_budget_mb"] == expected_budget
    assert after["limit"] == mc.estimate(cpus=32, total_ram_bytes=16 * 1024**3, run_budget_mb=expected_budget)
    assert after["limit"] != before["limit"]


# ── Wiring into the app ──────────────────────────────────────────────────────


class _FakeRouter:
    def __init__(self) -> None:
        self.routes: dict[str, Any] = {}

    def add_get(self, path: str, handler: Any) -> None:
        self.routes[path] = handler


class _FakeApp(dict):
    def __init__(self) -> None:
        super().__init__()
        self.on_startup: list[Any] = []
        self.on_cleanup: list[Any] = []
        self.router = _FakeRouter()


def test_register_machine_capacity_creates_the_profile_on_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mc, "_memory", lambda: (8 * 1024**3, 8 * 1024**3))
    app = _FakeApp()
    mc.register_machine_capacity(app)
    assert len(app.on_startup) == 1
    assert len(app.on_cleanup) == 1
    assert "/api/machine/capacity" in app.router.routes

    async def _run() -> None:
        await app.on_startup[0](app)
        try:
            assert (tmp_path / "machine_capacity.json").is_file()
        finally:
            await app.on_cleanup[0](app)

    asyncio.run(_run())


def test_capacity_route_returns_limit_and_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mc, "_memory", lambda: (8 * 1024**3, 8 * 1024**3))
    app = _FakeApp()
    mc.register_machine_capacity(app)
    handler = app.router.routes["/api/machine/capacity"]

    async def _run() -> dict[str, Any]:
        response = await handler(None)
        return json.loads(response.body.decode("utf-8"))

    payload = asyncio.run(_run())
    assert "limit" in payload
    assert "source" in payload
    assert payload["max_concurrent_runs"] == mc.max_concurrent_runs()


# ── GET /api/machine/capacity: the same access guard as its siblings ────────


def test_capacity_route_refuses_like_metrics_does_in_remote_mode_without_a_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mirrors `_require_api_access` in "remote" mode with no token, which is exactly what
    `/api/metrics` and `/api/landing-health` answer with (401), unauthenticated."""
    monkeypatch.setattr(mc, "_memory", lambda: (8 * 1024**3, 8 * 1024**3))

    def _guard_like_metrics_in_remote_mode(request: Any) -> None:
        raise web.HTTPUnauthorized(text="API token required")

    async def _run() -> int:
        app = web.Application()
        mc.register_machine_capacity(app, require_api_access=_guard_like_metrics_in_remote_mode)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            resp = await client.get("/api/machine/capacity")
            return resp.status
        finally:
            await client.close()

    assert asyncio.run(_run()) == 401


def test_capacity_route_answers_when_the_guard_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mc, "_memory", lambda: (8 * 1024**3, 8 * 1024**3))

    async def _run() -> tuple[int, dict[str, Any]]:
        app = web.Application()
        mc.register_machine_capacity(app, require_api_access=lambda _request: None)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            resp = await client.get("/api/machine/capacity")
            return resp.status, await resp.json()
        finally:
            await client.close()

    status, payload = asyncio.run(_run())
    assert status == 200
    assert "limit" in payload


def test_capacity_route_stays_unguarded_when_no_guard_is_given(monkeypatch: pytest.MonkeyPatch) -> None:
    """Back-compat: existing callers (and the tests above `register_machine_capacity`
    without a guard) still get a working, unguarded route."""
    monkeypatch.setattr(mc, "_memory", lambda: (8 * 1024**3, 8 * 1024**3))
    app = _FakeApp()
    mc.register_machine_capacity(app)
    handler = app.router.routes["/api/machine/capacity"]
    response = asyncio.run(handler(None))
    assert response.status == 200


# ── The sampler ──────────────────────────────────────────────────────────────


def _stub_psutil(procs: dict[int, int]) -> Any:
    """A minimal fake psutil module: `Process(pid).memory_info().rss` in bytes, no children."""

    class _StubProc:
        def __init__(self, rss_bytes: int) -> None:
            self._rss = rss_bytes

        def memory_info(self) -> Any:
            return type("MemInfo", (), {"rss": self._rss})()

        def children(self, recursive: bool = True) -> list[Any]:
            return []

    class _StubPsutil:
        Error = RuntimeError

        def __init__(self, by_pid: dict[int, Any]) -> None:
            self._by_pid = by_pid

        def Process(self, pid: int) -> Any:
            return self._by_pid[pid]

    return _StubPsutil({pid: _StubProc(rss_bytes) for pid, rss_bytes in procs.items()})


def test_collect_active_run_pids_reads_the_registry_on_the_loop() -> None:
    proc_handle = type("ProcHandle", (), {"pid": 111})()
    app: dict[str, Any] = {mc._RUN_REGISTRY_KEY: {"cid-1": {"session": {"proc": proc_handle, "run_id": "run-1"}}}}
    assert mc._collect_active_run_pids(app) == {"run-1": 111}


def test_collect_active_run_pids_empty_without_a_registry() -> None:
    assert mc._collect_active_run_pids({}) == {}


def test_sample_active_runs_takes_plain_pids_not_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """`sample_active_runs` is the function handed to `asyncio.to_thread` (I2): it must
    take only plain data, never the app itself."""
    monkeypatch.setitem(sys.modules, "psutil", _stub_psutil({111: 300 * 1024 * 1024}))
    assert mc.sample_active_runs({"run-1": 111}) == {"run-1": pytest.approx(300.0)}


def test_sample_active_runs_returns_empty_without_psutil(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "psutil", None)  # None in sys.modules forces ImportError
    assert mc.sample_active_runs({"run-1": 111}) == {}


def test_sampler_loop_dispatches_the_walk_through_asyncio_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """I2: the loop must not run the psutil walk on the event loop itself."""
    calls: list[tuple[Any, tuple[Any, ...]]] = []

    async def _fake_to_thread(fn: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append((fn, args))
        return {}

    monkeypatch.setattr(mc.asyncio, "to_thread", _fake_to_thread)
    app: dict[str, Any] = {mc._RUN_REGISTRY_KEY: {}}
    asyncio.run(mc._sampler_tick(app))
    assert len(calls) == 1
    assert calls[0][0] is mc.sample_active_runs


def test_sampler_tick_records_a_peak_once_a_run_leaves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mc, "_memory", lambda: (8 * 1024**3, 8 * 1024**3))
    monkeypatch.setitem(sys.modules, "psutil", _stub_psutil({111: 300 * 1024 * 1024}))

    live_proc_handle = type("ProcHandle", (), {"pid": 111})()
    app: dict[str, Any] = {mc._RUN_REGISTRY_KEY: {"cid-1": {"session": {"proc": live_proc_handle, "run_id": "run-1"}}}}

    asyncio.run(mc._sampler_tick(app))
    assert app[mc._APP_SAMPLER_PEAKS]["run-1"] == pytest.approx(300.0)
    assert mc._read_profile(tmp_path / "machine_capacity.json") is None  # not recorded yet: still running

    # The run leaves the registry (finished): the next tick records its peak.
    app[mc._RUN_REGISTRY_KEY] = {}
    asyncio.run(mc._sampler_tick(app))
    saved = mc.profile()
    assert saved["observed_peaks_mb"] == [pytest.approx(300.0)]


def test_the_sampler_adds_no_key_to_a_running_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """Its first tick comes ten seconds in, and a key written then read as a leak in a plugin that happened to be counted."""
    monkeypatch.setattr(mc, "_SAMPLE_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(mc, "_psutil_importable", lambda: True)
    tick = mc._sampler_tick
    app = web.Application()
    mc.register_machine_capacity(app)

    async def scenario() -> tuple[set[Any], set[Any]]:
        counted, ticked = asyncio.Event(), asyncio.Event()

        async def tick_after_the_count(app_ref: Any) -> None:
            await counted.wait()
            await tick(app_ref)
            ticked.set()

        monkeypatch.setattr(mc, "_sampler_tick", tick_after_the_count)
        async with TestClient(TestServer(app)):
            at_start = set(app)
            counted.set()
            await asyncio.wait_for(ticked.wait(), 30)
            return at_start, set(app)

    at_start, after_a_tick = asyncio.run(scenario())
    assert mc._APP_SAMPLER_TASK in at_start  # an empty compare would pass
    assert after_a_tick == at_start
