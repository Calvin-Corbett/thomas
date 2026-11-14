"""How many Build runs this computer can hold at once, measured, not fixed.

You asked: "make it estimate the most the hardware can do and set that as
the limit. this will need to happen to everyone who installs as part of the
first start up." Before this, evolve_agent_routes.py capped every install at
the same DEFAULT_MAX_CONCURRENT_CODE_RUNS of 8 (raisable to a ceiling of 64
via an env var), no matter whether the machine had 4 cores or 128. This
module estimates a ceiling from the machine actually running it, refines that
estimate from what runs really use, and recomputes whenever the hardware
itself looks different (a reinstall on new metal, a resized VM).

thomas/core/ is the bottom of the dependency tree (see thomas/_architecture.py)
and must not gain a new import from thomas/server/. The Code-run registry this
module's sampler reads lives in thomas.server.routes.evolve_agent_run_state,
whose keys are deliberately plain strings rather than an importable AppKey --
"so a sibling can read the same run state without importing this module back"
is that module's own reasoning, and it applies here too. `_RUN_REGISTRY_KEY`
below duplicates that string rather than importing the module that owns it.
"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import json
import logging
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from thomas.core import machine_load
from thomas.core.task_bot_lock import _PathLock

log = logging.getLogger(__name__)

# A runaway cap: no machine, however large, offers more than this many slots.
RUNAWAY_LIMIT = 100
# A Build subprocess, its model streams, and a headless browser playtest.
DEFAULT_RUN_BUDGET_MB = 768
# Runs mostly wait on models, so more of them fit per CPU than a compute-bound
# workload would allow.
CPU_FACTOR = 2

# What jobs leave for Windows and you: a quarter of the memory, never less than 4 GiB and never more than 8 GiB.
# You asked: "it needs to work on 16 GB of RAM. But at the same time ... I have 64, so you can do a lot more on
# mine ... it should automatically be set to [the] computer's RAM." A flat quarter held 16 GiB back on a 64 GiB
# PC; the cap gives a 64 GiB PC 56 GiB of room while a 16 GiB PC keeps its 4 GiB. What a game or anything else
# you open takes is still counted live: every admission also reads free memory and free commit (_memory).
_RESERVE_FLOOR_BYTES = 4 * 1024 * 1024 * 1024
_RESERVE_CEILING_BYTES = 8 * 1024 * 1024 * 1024
_RESERVE_FRACTION = 0.25

_PROFILE_SCHEMA = 1
_PROFILE_FILENAME = "machine_capacity.json"
_PEAK_HISTORY_LIMIT = 50
_MIN_PEAKS_FOR_REFINEMENT = 5
_PEAK_PERCENTILE = 0.90
_PEAK_SAFETY_FACTOR = 1.25
_MIN_RUN_BUDGET_MB = 256

# A check shard is not a Build run: its peaks live under their own key and size only the check's pool (spec
# 2026-10-12 Part 1 item 1). ``observed_peaks_mb``, which sizes Build runs and the cage shell runner, is not touched.
CHECK_SHARD_PEAKS_KEY = "check_shard_peaks_mb"
DEFAULT_CHECK_SHARD_MB = DEFAULT_RUN_BUDGET_MB
# One writer of the profile at a time, in this process and in every other: ``task_bot_lock._PathLock`` on the file (a
# lock per path in this process, re-entrant for the thread holding it, then ``machine_capacity.json.lock`` beside the
# file). A shard's peak and a Build run's peak each read the file and wrote back a copy without the other's sample.
# On Windows a read, or the rename that replaces the file, fails while another process is replacing or reading it at
# that instant; both are tried again a few times, and a file that stays busy is never taken for a missing one.
_BUSY_TRIES = 5
_BUSY_WAIT_S = 0.02

ENV_OVERRIDE = "THOMAS_MAX_CONCURRENT_CODE_RUNS"

_SAMPLE_INTERVAL_SECONDS = 10
# thomas.server.routes.evolve_agent_run_state.APP_EVOLVE_AGENT_RUNS, duplicated
# rather than imported (see module docstring).
_RUN_REGISTRY_KEY = "evolve_agent_runs"
_APP_PROFILE_SNAPSHOT = "machine_capacity_profile"
_APP_SAMPLER_TASK = "machine_capacity_sampler_task"
_APP_SAMPLER_PEAKS = "machine_capacity_sampler_peaks_mb"


def _memory() -> tuple[int | None, int | None]:
    """(total, available) bytes for this machine, or (None, None) if nothing could tell us.

    On Windows *available* is the smaller of free memory and free commit. Commit is what runs out first there:
    on 2026-11-06 this PC had 26 GB of memory free but its commit charge stood at 62.6 of 90.9 GB, and a full
    commit charge stops new processes from starting however much memory looks free.
    """
    try:
        import psutil
    except ImportError:
        psutil = None  # type: ignore[assignment]
    if psutil is not None:
        try:
            vm = psutil.virtual_memory()
            total, available = int(vm.total), int(vm.available)
        except (AttributeError, OSError, ValueError):
            pass
        else:
            if os.name == "nt":
                measured = _windows_memory()
                if measured is not None:
                    available = min(available, measured[1])
            return total, available
    if os.name == "nt":
        measured = _windows_memory()
        if measured is not None:
            return measured
    elif sys.platform == "darwin":
        total = _macos_total_memory()
        if total is not None:
            return total, None
    else:
        measured = _linux_memory()
        if measured is not None:
            return measured
    return None, None


def _windows_memory() -> tuple[int, int] | None:
    try:

        class _MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
            return None
        # ullAvailPageFile is the commit still free (the commit limit less the commit charge), not the page file.
        return int(status.ullTotalPhys), min(int(status.ullAvailPhys), int(status.ullAvailPageFile))
    except (AttributeError, OSError, ValueError):
        return None


def _linux_memory() -> tuple[int, int] | None:
    try:
        fields: dict[str, int] = {}
        with open("/proc/meminfo", encoding="ascii") as handle:
            for line in handle:
                key, _, rest = line.partition(":")
                if key in ("MemTotal", "MemAvailable"):
                    fields[key] = int(rest.strip().split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    if "MemTotal" not in fields:
        return None
    return fields["MemTotal"], fields.get("MemAvailable")


def _macos_total_memory() -> int | None:
    try:
        result = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def _reserve_bytes(total_ram_bytes: int) -> int:
    return max(_RESERVE_FLOOR_BYTES, min(_RESERVE_CEILING_BYTES, int(total_ram_bytes * _RESERVE_FRACTION)))


def usable_memory_bytes(total_ram_bytes: int | None, available_bytes: int | None) -> int | None:
    """Memory jobs may use, with the reserve counted once: ``min(available, total - reserve)``."""
    if total_ram_bytes is None:
        return None if available_bytes is None else int(available_bytes)
    ceiling = max(0, int(total_ram_bytes) - _reserve_bytes(int(total_ram_bytes)))
    return ceiling if available_bytes is None else min(int(available_bytes), ceiling)


def estimate(*, cpus: int, total_ram_bytes: int | None, run_budget_mb: int) -> int:
    """The most concurrent runs this machine can plausibly hold, at least 1."""
    cpu_term = max(1, int(cpus)) * CPU_FACTOR
    if total_ram_bytes is None:
        return max(1, min(RUNAWAY_LIMIT, cpu_term))
    usable = max(0, int(total_ram_bytes) - _reserve_bytes(int(total_ram_bytes)))
    budget_bytes = max(1, int(run_budget_mb)) * 1024 * 1024
    memory_term = usable // budget_bytes
    return max(1, min(RUNAWAY_LIMIT, cpu_term, memory_term))


def _default_data_dir() -> Path:
    from thomas.core.config import resolve_thomas_data_dir

    return resolve_thomas_data_dir()


def _profile_path(data_dir: Path | None) -> Path:
    resolved = Path(data_dir) if data_dir is not None else _default_data_dir()
    return resolved / _PROFILE_FILENAME


def _read_profile(path: Path) -> dict[str, Any] | None:
    """The saved profile; None when the file is missing or is not a profile.

    A file another process is replacing this instant cannot be opened on Windows (``PermissionError``): it is read
    again a few times, and then the error is raised, so a busy file is never taken for a missing one and written over.
    """
    for attempt in range(_BUSY_TRIES):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except ValueError:
            return None
        except PermissionError:
            if attempt == _BUSY_TRIES - 1:
                raise
            time.sleep(_BUSY_WAIT_S * (attempt + 1))
            continue
        return data if isinstance(data, dict) else None
    return None


def _write_profile(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".machine_capacity-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        for attempt in range(_BUSY_TRIES):
            try:
                os.replace(tmp_name, path)
                break
            except PermissionError:  # a reader has the file open this instant (Windows): wait, then try again
                if attempt == _BUSY_TRIES - 1:
                    raise
                time.sleep(_BUSY_WAIT_S * (attempt + 1))
    except OSError:
        with contextlib.suppress(OSError):
            os.remove(tmp_name)
        raise


def _compute_profile(
    *, cpus: int, total_ram_bytes: int | None, run_budget_mb: int = DEFAULT_RUN_BUDGET_MB
) -> dict[str, Any]:
    return {
        "schema": _PROFILE_SCHEMA,
        "cpus": cpus,
        "total_ram_bytes": total_ram_bytes,
        "run_budget_mb": run_budget_mb,
        "observed_peaks_mb": [],
        "limit": estimate(cpus=cpus, total_ram_bytes=total_ram_bytes, run_budget_mb=run_budget_mb),
        "computed_at": time.time(),
        "source": "measured" if total_ram_bytes is not None else "cpu_only",
    }


def profile(*, data_dir: Path | None = None, memory: tuple[int | None, int | None] | None = None) -> dict[str, Any]:
    """This machine's saved capacity profile, recomputed only when the hardware moved.

    Recomputes and saves when the file is missing, unreadable, or its
    `cpus`/`total_ram_bytes` no longer match this machine. Otherwise returns
    the saved profile untouched, so refinements from `record_run_peak` survive.

    `memory` lets a caller that already read `_memory()` this call (e.g.
    `admission_refusal`) hand the reading in rather than pay for a second one.

    A file that cannot be read just now (another process is replacing it) is
    never written over: this call returns an estimate built in memory instead.
    """
    path = _profile_path(data_dir)
    try:
        return _saved_profile(path, memory)
    except OSError:
        log.warning("%s could not be read or saved just now; using an estimate it does not keep", path, exc_info=True)
        total_ram_bytes, _available = memory if memory is not None else _memory()
        return _compute_profile(cpus=max(1, os.cpu_count() or 1), total_ram_bytes=total_ram_bytes)


def _saved_profile(path: Path, memory: tuple[int | None, int | None] | None = None) -> dict[str, Any]:
    """The saved profile; rebuilt and saved, under the file's lock, only when it is missing or from other hardware.

    Raises ``OSError`` when the file is there but cannot be read now, so no caller writes over it.
    """
    cpus = max(1, os.cpu_count() or 1)
    total_ram_bytes, _available = memory if memory is not None else _memory()

    def current(found: dict[str, Any] | None) -> bool:
        return found is not None and found.get("cpus") == cpus and found.get("total_ram_bytes") == total_ram_bytes

    existing = _read_profile(path)
    if existing is not None and current(existing):
        return existing
    with _PathLock(path):
        existing = _read_profile(path)  # another writer may have saved it while this one waited for the lock
        if existing is not None and current(existing):
            return existing
        computed = _compute_profile(cpus=cpus, total_ram_bytes=total_ram_bytes)
        _write_profile(path, computed)
        return computed


def _resolve_limit(prof: dict[str, Any]) -> int:
    """An env override wins (clamped to RUNAWAY_LIMIT), else the given profile's limit."""
    raw = str(os.environ.get(ENV_OVERRIDE, "")).strip()
    if raw:
        try:
            requested = int(raw)
        except ValueError:
            requested = 0
        if requested > 0:
            return min(requested, RUNAWAY_LIMIT)
    return int(prof.get("limit") or 1)


def max_concurrent_runs() -> int:
    """The live ceiling: an env override wins (clamped to RUNAWAY_LIMIT), else the profile's."""
    return _resolve_limit(profile())


def _gb(byte_count: float) -> str:
    return f"{byte_count / (1024**3):.1f}"


def admission_refusal(active: int) -> str | None:
    """The one sentence `_start_run` returns when a new run cannot start, else None."""
    memory_reading = _memory()  # read once; shared with `profile()` below
    prof = profile(memory=memory_reading)
    limit = _resolve_limit(prof)
    if active >= limit:
        cpus = prof.get("cpus")
        total_ram_bytes = prof.get("total_ram_bytes")
        ram = _gb(total_ram_bytes) if isinstance(total_ram_bytes, (int, float)) else "unknown"
        return (
            f"All {limit} runs this computer can hold at once are busy "
            f"({cpus} processors, {ram} GB memory). Wait for one to finish."
        )
    _total, available = memory_reading
    run_budget_mb = int(prof.get("run_budget_mb") or DEFAULT_RUN_BUDGET_MB)
    needed_bytes = run_budget_mb * 1024 * 1024
    if available is not None and available < needed_bytes:
        return (
            f"This computer has {_gb(available)} GB of memory free and a run needs about "
            f"{_gb(needed_bytes)} GB. Close something or wait for a run to finish."
        )
    return None


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def record_run_peak(peak_mb: float) -> None:
    """Fold one run's peak memory into the profile; refine the budget at 5+ samples.

    Under the file's lock; a profile that cannot be read just now is left as it is (``OSError``).
    """
    path = _profile_path(None)
    with _PathLock(path):
        prof = _saved_profile(path)
        peaks = [*prof.get("observed_peaks_mb", []), float(peak_mb)][-_PEAK_HISTORY_LIMIT:]
        prof["observed_peaks_mb"] = peaks
        if len(peaks) >= _MIN_PEAKS_FOR_REFINEMENT:
            p90 = _percentile(peaks, _PEAK_PERCENTILE)
            run_budget_mb = max(_MIN_RUN_BUDGET_MB, math.ceil(p90 * _PEAK_SAFETY_FACTOR))
            prof["run_budget_mb"] = run_budget_mb
            prof["limit"] = estimate(
                cpus=int(prof.get("cpus") or 1),
                total_ram_bytes=prof.get("total_ram_bytes"),
                run_budget_mb=run_budget_mb,
            )
            prof["computed_at"] = time.time()
        _write_profile(path, prof)


def record_check_shard_peak(committed_mb: float, working_set_mb: float) -> None:
    """Keep one check shard's peak committed memory and working set (the last 50); Build's sizing is not touched.

    Under the file's lock; a profile that cannot be read just now is left as it is (``OSError``).
    """
    path = _profile_path(None)
    with _PathLock(path):
        prof = _saved_profile(path)
        sample = {"committed": float(committed_mb), "working_set": float(working_set_mb)}
        prof[CHECK_SHARD_PEAKS_KEY] = [*prof.get(CHECK_SHARD_PEAKS_KEY, []), sample][-_PEAK_HISTORY_LIMIT:]
        _write_profile(path, prof)


def check_shard_mb(prof: dict[str, Any] | None = None) -> int:
    """One check shard's memory: 1.25 times the p90 of measured committed memory once 5 are known, else 768 MiB."""
    samples = (prof if prof is not None else profile()).get(CHECK_SHARD_PEAKS_KEY) or []
    committed = [
        float(sample["committed"])
        for sample in samples
        if isinstance(sample, dict) and isinstance(sample.get("committed"), (int, float))
    ]
    if len(committed) < _MIN_PEAKS_FOR_REFINEMENT:
        return DEFAULT_CHECK_SHARD_MB
    return max(_MIN_RUN_BUDGET_MB, math.ceil(_percentile(committed, _PEAK_PERCENTILE) * _PEAK_SAFETY_FACTOR))


def _process_tree_rss_mb(psutil_mod: Any, pid: int) -> float | None:
    process_error = getattr(psutil_mod, "Error", OSError)
    try:
        proc = psutil_mod.Process(pid)
        total = proc.memory_info().rss
        for child in proc.children(recursive=True):
            try:
                total += child.memory_info().rss
            except process_error:
                continue
        return total / (1024 * 1024)
    except process_error:
        return None


def _psutil_importable() -> bool:
    try:
        import psutil  # noqa: F401
    except ImportError:
        return False
    return True


def _collect_active_run_pids(app: Any) -> dict[str, int]:
    """On the loop: cheap dict reads only, no psutil call, no blocking I/O.

    Returns plain data (run_id -> pid) -- the only thing the blocking walk in
    `sample_active_runs` needs, so the app itself never crosses into a thread.
    """
    registry = app.get(_RUN_REGISTRY_KEY)
    if not isinstance(registry, dict):
        return {}
    pids: dict[str, int] = {}
    for cid, slot in registry.items():
        if not isinstance(slot, dict):
            continue
        session = slot.get("session") if isinstance(slot.get("session"), dict) else {}
        proc = session.get("proc")
        pid = getattr(proc, "pid", None)
        if pid is None:
            continue
        pids[str(session.get("run_id") or cid)] = pid
    return pids


def sample_active_runs(pids: dict[str, int]) -> dict[str, float]:
    """Off the loop (run via `asyncio.to_thread`): the blocking psutil process-tree walk.

    Takes plain pid data rather than the app, so the thread only ever makes OS
    calls. Returns `{run_id: rss_mb}` for every pid whose tree could be
    measured; a pid that failed is simply absent from the result.
    """
    try:
        import psutil
    except ImportError:
        return {}
    measured: dict[str, float] = {}
    for run_id, pid in pids.items():
        rss_mb = _process_tree_rss_mb(psutil, pid)
        if rss_mb is not None:
            measured[run_id] = rss_mb
    return measured


async def _sampler_tick(app: Any) -> None:
    """One tick: registry read and bookkeeping on the loop, the psutil walk off it."""
    pids = _collect_active_run_pids(app)
    measured = await asyncio.to_thread(sample_active_runs, pids)
    peaks_by_run: dict[str, float] = app.setdefault(_APP_SAMPLER_PEAKS, {})
    for run_id, rss_mb in measured.items():
        if rss_mb > peaks_by_run.get(run_id, 0.0):
            peaks_by_run[run_id] = rss_mb
    for run_id in [rid for rid in peaks_by_run if rid not in pids]:
        peak = peaks_by_run.pop(run_id)
        if peak > 0:
            await asyncio.to_thread(record_run_peak, peak)


async def _sampler_loop(app: Any) -> None:
    while True:
        await asyncio.sleep(_SAMPLE_INTERVAL_SECONDS)
        try:
            await _sampler_tick(app)
        except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError):
            log.warning("machine capacity sampler tick failed", exc_info=True)


def register_machine_capacity(app: Any, *, require_api_access: Any = None, own_task: Any = None) -> None:
    """Measure this machine on every start, refine from real runs, and expose it read-only.

    `on_startup` computes/loads the profile -- so every install measures its
    own machine on its first start, and every start after -- and, only when
    psutil actually imports, launches a light sampler that watches Code runs'
    real memory use. `on_cleanup` cancels the sampler if it ran. `GET
    /api/machine/capacity` reports the profile, the live limit, and current
    free memory: read-only, for a person or Settings to see the number and
    why -- guarded by `require_api_access` the same way its sibling status
    routes are (`thomas.server.routes.observability`,
    `app_routes_task_ledger.py`), when the caller supplies one; the app's own
    `register_machine_capacity(app, require_api_access=_require_api_access)`
    call always does.

    `thomas.server.rows.machine_capacity` calls this with a view of the app,
    so these hooks run when that row starts and stops, and `own_task` is the
    row's `ctx.task`, so a stop owns the sampler. Called on a real app, with
    no `own_task`, it is a plain task that `on_cleanup` ends.
    """
    from aiohttp import web

    def _start_sampler(app_ref: Any) -> Any:
        if own_task is None:
            return asyncio.ensure_future(_sampler_loop(app_ref))
        return own_task(lambda: _sampler_loop(app_ref), name="memory sampler")

    async def _on_startup(app_ref: Any) -> None:
        app_ref[_APP_PROFILE_SNAPSHOT] = await asyncio.to_thread(profile)
        if _psutil_importable():
            app_ref[_APP_SAMPLER_PEAKS] = {}  # here, so a tick ten seconds in does not change a running app's keys
            app_ref[_APP_SAMPLER_TASK] = _start_sampler(app_ref)

    async def _on_cleanup(app_ref: Any) -> None:
        task = app_ref.get(_APP_SAMPLER_TASK)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def api_machine_capacity(request: Any) -> Any:
        if require_api_access is not None:
            require_api_access(request)
        prof = profile()
        _total, available = _memory()
        now = await asyncio.to_thread(machine_load.reading)
        load = {"limit_percent": machine_load.limit(), "over_limit": machine_load.over_limit(now)}
        if now is not None:
            load.update(cpu_percent=round(now.cpu, 1), memory_percent=round(now.memory, 1))
        return web.json_response(
            {**prof, "max_concurrent_runs": max_concurrent_runs(), "available_ram_bytes": available, "load": load}
        )

    async def api_metrics_steps(request: Any) -> Any:
        """Where the time went over the last ``days`` (default 1, at most 30): :mod:`thomas.core.step_report`."""
        if require_api_access is not None:
            require_api_access(request)
        try:
            asked = float(request.query.get("days") or 1)
        except ValueError:
            asked = 1.0
        days = min(max(asked, 0.01), 30.0) if math.isfinite(asked) else 1.0
        from thomas.core import step_log, step_report

        summary = await asyncio.to_thread(lambda: step_report.summarize(step_log.read(days)))
        return web.json_response({"days": days, **summary})

    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    app.router.add_get("/api/machine/capacity", api_machine_capacity)
    app.router.add_get("/api/metrics/steps", api_metrics_steps)


RUN_LOAD_WAIT_S = 600.0  # the longest a new Build run waits for this PC to drop under the load limit


async def await_room_for_run(others_running: bool) -> None:
    """A new Build run waits while this PC is over the load limit, at most RUN_LOAD_WAIT_S, but only while another run
    is going: with none running, nothing of Thomas's is filling the PC, and waiting would only stop him."""
    if others_running:
        await machine_load.await_room(max_wait_s=RUN_LOAD_WAIT_S, label="build run")


__all__ = [
    "CHECK_SHARD_PEAKS_KEY",
    "CPU_FACTOR",
    "DEFAULT_CHECK_SHARD_MB",
    "DEFAULT_RUN_BUDGET_MB",
    "ENV_OVERRIDE",
    "RUNAWAY_LIMIT",
    "RUN_LOAD_WAIT_S",
    "admission_refusal",
    "await_room_for_run",
    "check_shard_mb",
    "estimate",
    "max_concurrent_runs",
    "profile",
    "record_check_shard_peak",
    "record_run_peak",
    "register_machine_capacity",
    "sample_active_runs",
    "usable_memory_bytes",
]
