"""Server lifecycle management and restart logic."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import threading
import time as _time
from asyncio import constants as asyncio_constants
from collections.abc import Coroutine
from typing import Any

from thomas.core.config import AppConfig
from thomas.server import serve_instance_guard as guard

log = logging.getLogger(__name__)

_PYTHON_LIMITS_THE_THREAD_JOIN = sys.version_info >= (3, 12)

# What closing went on without. Held for good, because the garbage collector would otherwise run their ``finally`` blocks
# at some moment of its own, beside the next server after a restart.
_CLOSED_AROUND: list[asyncio.Future[Any]] = []


class _ServerRestartRequested(Exception):
    """Sentinel: supervisor loop should restart the server cleanly."""

    pass


async def _log_landing_heartbeat() -> None:
    """Read the landing heartbeat once, after the port is open, and log it.

    This is the whole trigger. It is deliberately NOT a scheduler: people walk
    away from machines and hard-power them off, so anything that fires on a
    clock is exactly the thing that gets missed. Starting Thomas is the
    trigger, because starting Thomas is what actually happens.

    The reading itself is blocking git work, so it goes to a thread -- the
    event loop stays free and boot is never held up waiting for it.
    """
    try:
        from thomas.core.landing_health import collect_landing_health
    except ImportError:
        log.debug("Landing heartbeat unavailable: thomas.core.landing_health did not import")
        return

    # collect_landing_health() is contractually incapable of raising: every
    # failure comes back as severity 'unknown' with a sentence saying so.
    health = await asyncio.to_thread(collect_landing_health)
    for line in health.log_lines():
        log.info(line)


async def serve_async(
    config: AppConfig,
    *,
    host: str = "127.0.0.1",
    port: int = 8899,
    crash_count: int = 0,
) -> None:
    from thomas.server.precard import workers

    stopping = threading.Event()
    # Startup callbacks can schedule checks before the port is bound. Own their
    # generation from setup through shutdown, including failed startups.
    with workers.generation(stopping):
        try:
            await _serve_generation(config, host=host, port=port, crash_count=crash_count, stopping=stopping)
        finally:
            stopping.set()


async def _serve_generation(
    config: AppConfig, *, host: str, port: int, crash_count: int, stopping: threading.Event
) -> None:
    from aiohttp import web

    # The supervisor retains this function while re-importing application
    # modules after a restart. AppKey equality is identity-based: bind this
    # generation's keys with its factory, never the previous module's keys.
    from thomas.server.app_keys import (
        APP_BOOT_DURATION,
        APP_CRASH_COUNT,
        APP_DELIVERABLE_PREVIEW_SERVICE,
        APP_DIAGNOSTICS,
        APP_RESTART_REQUESTED,
        APP_SELF_BASE_URL,
        APP_SHUTDOWN_EVENT,
    )
    from thomas.server.precard import workers

    from .app_core import create_app

    app = create_app(config)
    app[APP_CRASH_COUNT] = crash_count
    app[APP_SELF_BASE_URL] = f"http://{host}:{port}"

    # Shutdown event -- set by restart endpoint or signal handler
    shutdown_event = asyncio.Event()
    app[APP_SHUTDOWN_EVENT] = shutdown_event
    app[APP_RESTART_REQUESTED] = False

    # Headroom above aiohttp's 8190-byte default so an oversized Cookie header
    # is a nuisance rather than a wall. Deliverable previews leave one cookie
    # each in the 127.0.0.1 jar, and cookies carry no port, so they arrive here
    # too; past the default this server rejects every request with a 400 BEFORE
    # any handler or middleware runs, and the drain that clears them can never
    # execute. Parsing the request is what makes recovery possible at all.
    # This is a ceiling for a local, loopback-bound UI, not an invitation.
    runner = web.AppRunner(app, max_field_size=32768)
    # Autopilot resumes a build paused on your usage limit by itself (autopilot_park), and a Build start needs
    # this server's own port. After a restart no request had taught it yet, so every paused build waited for
    # you to open Build or Chat. Port 0 (a free one) is learned from the socket once it is bound, below.
    from thomas.server.routes.evolve_agent_autopilot import remember_port

    remember_port(app, int(port or 0))
    await runner.setup()
    preview_service = app.get(APP_DELIVERABLE_PREVIEW_SERVICE)
    if preview_service is not None:
        preview_service.configure(main_origin=f"http://{host}:{port}")

    # ── Port binding with retry (handles TIME_WAIT from previous instance) ──
    max_bind_attempts = 5
    for attempt in range(1, max_bind_attempts + 1):
        site = web.TCPSite(runner, host=host, port=port)
        try:
            await site.start()
            break
        except OSError as bind_err:
            # aiohttp may register the site before bind succeeds; stop() ensures
            # the next retry can create a fresh site without duplicate registration.
            with contextlib.suppress(Exception):
                await site.stop()
            if attempt == max_bind_attempts:
                print(f"[thomas] Port {port} still busy after {max_bind_attempts} attempts. Giving up.")
                stopping.set()
                await runner.cleanup()
                if preview_service is not None:
                    await preview_service.stop()
                raise
            delay = attempt * 1.0
            print(
                f"[thomas] Port {port} busy ({bind_err}), retrying in {delay:.0f}s ({attempt}/{max_bind_attempts})..."
            )
            await asyncio.sleep(delay)
    if not port:
        with contextlib.suppress(IndexError, TypeError, ValueError):
            remember_port(app, int(runner.addresses[0][1]))
    from thomas.server.autopilot_restart import APP_SERVER_LISTENING

    listening = app.get(APP_SERVER_LISTENING)
    if listening is not None:
        listening.set()  # the restart survey starts now, not while the server is still starting

    # Keep the dedicated canvas LLM connection warm so design/canvas requests never
    # cold-start (an idle gpt-5.5 OAuth stream stalls on its next first token).
    with contextlib.suppress(Exception):
        from thomas.server.chat_delegation_canvas import start_canvas_keepalive

        start_canvas_keepalive()

    # Close orphaned delegated executions (workers killed by a restart leave
    # records stuck "executing" forever) at startup and every few minutes.
    stale_sweeper: asyncio.Task[None] | None = None
    with contextlib.suppress(Exception):
        from thomas.server.stale_execution_sweep import run_stale_execution_sweeper

        stale_sweeper = asyncio.create_task(run_stale_execution_sweeper())

    # Tell the owner, in plain English, whether their work is safely landed or
    # piling up. Scheduled here rather than run here: create_task only queues
    # it, so the port is already open and the startup summary still prints
    # first. It cannot delay boot.
    landing_heartbeat: asyncio.Task[None] = asyncio.create_task(_log_landing_heartbeat())
    from thomas.server import landed_code_reload

    landed_reload = (
        asyncio.create_task(landed_code_reload.watch(app)) if landed_code_reload.loop_enabled(port) else None
    )

    # ── Startup summary ──
    diag = app.get(APP_DIAGNOSTICS, {})
    # The plain string "APP_BOOT_DURATION" never matched the web.AppKey the value
    # is stored under, so this always fell back to 0 and every boot claimed 0.0s.
    boot_dur = app.get(APP_BOOT_DURATION, 0.0)
    ok_features = [k for k, v in diag.items() if v]
    bad_features = [k for k, v in diag.items() if not v]
    print(f"[thomas] Server booted in {boot_dur:.1f}s")
    if ok_features:
        print(f"[thomas]   Features OK:  {', '.join(ok_features)}")
    if bad_features:
        print(f"[thomas]   Unavailable:  {', '.join(bad_features)}")
    if crash_count > 0:
        print(f"[thomas]   Crash count:  {crash_count}")
    print(f"[thomas]   Listening:    http://{host}:{port}/")

    # Keep running until shutdown event is set or interrupted.
    try:
        while not shutdown_event.is_set():
            await asyncio.sleep(1)
    finally:
        stopping.set()  # checks still waiting for their turn leave before the drain; admitted ones run on as before
        if stale_sweeper is not None:
            stale_sweeper.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await stale_sweeper
        landing_heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await landing_heartbeat
        if landed_reload is not None:
            landed_reload.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await landed_reload
        await runner.cleanup()
        if preview_service is not None:
            await preview_service.stop()
        # Python's shutdown waits only for the default executor's work: a check or second look still running on the
        # check threads would run the old code beside the restarted server, on the same green. Wait for them as long.
        await workers.drain()
        if app.get(APP_RESTART_REQUESTED):
            raise _ServerRestartRequested()


def _retire_check_threads() -> None:
    """Let this generation's idle check threads end (``precard.workers``), once its drain has waited for their work.

    A restart re-imports every ``thomas`` module, so the next generation makes an executor of its own, and without this
    the old one's idle threads stayed for the life of the process: 24 of them after 10 restarts.
    """
    executor = getattr(sys.modules.get("thomas.server.precard.workers"), "EXECUTOR", None)
    if executor is not None:
        executor.shutdown(wait=False)  # work still queued or running finishes first; then its threads end


def _explicit_cmdline_port(cmdline: str) -> int | None:
    """Extract an explicit --port value from a command line, if present."""
    import re

    m = re.search(r"--port[=\s]+(\d{1,5})", str(cmdline or ""))
    if not m:
        return None
    try:
        return int(m.group(1))
    except (ValueError, TypeError):
        return None


def _listeners_from_the_socket_table(target_port: int) -> set[int] | None:
    """PIDs listening on ``target_port``, read straight from the OS socket table; None where that cannot be read.

    This answers in milliseconds. Asking PowerShell the same question (``Get-NetTCPConnection``) started a whole
    interpreter and took 2.2 s of every start and every restart, before the server did anything else.
    """
    try:
        import psutil
    except ImportError:
        return None
    try:
        return {
            conn.pid
            for conn in psutil.net_connections(kind="tcp")
            if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port == int(target_port) and conn.pid
        }
    except (psutil.Error, OSError) as exc:
        log.debug("Socket table unreadable, asking the shell instead: %s", exc)
        return None


def _pids_listening_on_port(target_port: int) -> set[int] | None:
    """PIDs bound to ``target_port`` in LISTEN state; None if unknowable."""
    from_table = _listeners_from_the_socket_table(target_port)
    if from_table is not None:
        return from_table
    try:
        if os.name == "nt":
            probe = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    f"Get-NetTCPConnection -State Listen -LocalPort {int(target_port)} "
                    "-ErrorAction SilentlyContinue | "
                    "Select-Object -ExpandProperty OwningProcess",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5.0,
                check=False,
            )
            if probe.returncode != 0:
                return None
            return {int(line) for line in probe.stdout.split() if line.strip().isdigit()}
        probe = subprocess.run(
            ["lsof", "-t", f"-iTCP:{int(target_port)}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5.0,
            check=False,
        )
        # lsof exits 1 when nothing matches; that is a definitive empty answer.
        if probe.returncode not in (0, 1):
            return None
        return {int(line) for line in probe.stdout.split() if line.strip().isdigit()}
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        log.debug("Port listener probe unavailable: %s", exc)
        return None


def _matches_thomas_server_cmdline(raw: str) -> bool:
    text = str(raw or "").strip().lower()
    if not text:
        return False
    return (" -m thomas serve" in text) or (" -m thomas.server" in text)


def _process_family(pid_to_ppid: dict[int, int | None], current_pid: int) -> set[int]:
    """Our own process lineage: ancestors (bounded walk) plus direct children.

    On Windows the venv ``Scripts/python.exe`` is a *launcher* that runs the
    real interpreter as a child with the same command line. The sweep must
    never treat our own launcher (or any other ancestor/child) as a duplicate
    server: killing the launcher tears the new server down with it via the
    launcher's job object — the server self-destructs on every venv launch.
    """
    family = {current_pid}
    cursor: int | None = current_pid
    for _ in range(32):  # bounded ancestor walk; cycles are possible with PID reuse
        cursor = pid_to_ppid.get(cursor) if cursor is not None else None
        if cursor is None or cursor in family or cursor <= 0:
            break
        family.add(cursor)
    for pid, ppid in pid_to_ppid.items():
        if ppid == current_pid:
            family.add(pid)
    return family


def _filter_duplicate_server_candidates(
    rows: list[tuple[int, int | None, str, str]], current_pid: int
) -> list[tuple[int, str]]:
    """Reduce a full process listing to candidate duplicate Thomas servers."""
    pid_to_ppid = {pid: ppid for pid, ppid, _name, _cmd in rows}
    family = _process_family(pid_to_ppid, current_pid)

    seen: set[int] = set()
    matches: list[tuple[int, str]] = []
    for pid, _ppid, name, cmdline in rows:
        if pid <= 0 or pid in family or pid in seen:
            continue
        lowered = str(name or "").lower()
        if lowered and not lowered.startswith("python"):
            continue
        if not _matches_thomas_server_cmdline(cmdline):
            continue
        seen.add(pid)
        matches.append((pid, cmdline))
    return matches


def _is_conflicting_duplicate(pid: int, cmdline: str, port: int, listeners: set[int] | None) -> bool:
    """Decide whether a name-matched Thomas server process conflicts with us.

    A duplicate is lethal only with positive evidence it holds OUR port:
    an explicit matching --port flag, or an OS-level listen on the port.
    Name match alone never kills — other installs/worktrees may run their
    own servers on other ports.
    """
    explicit_port = _explicit_cmdline_port(cmdline)
    if explicit_port is not None and explicit_port != port:
        return False  # definitively a different server
    if explicit_port == port:
        return True
    return listeners is not None and pid in listeners


def _terminate_pid(pid: int, *, why: str, known_port: Any = "?") -> None:
    if pid == os.getpid() or not guard.pid_alive(pid):
        return

    print(f"[thomas] Stopping previous instance (PID {pid}, port {known_port}, {why})...")
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return

    # Wait up to 3s for graceful shutdown.
    for _ in range(30):
        _time.sleep(0.1)
        if not guard.pid_alive(pid):
            break
    else:
        # Still alive -- force kill.
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL if hasattr(signal, "SIGKILL") else signal.SIGTERM)
    print("[thomas] Previous instance stopped.")


def _list_process_rows() -> list[tuple[int, int | None, str, str]]:
    """(pid, ppid, name, cmdline) for every visible process; [] if unknowable."""
    rows: list[tuple[int, int | None, str, str]] = []
    try:
        if os.name == "nt":
            probe = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "Get-CimInstance Win32_Process | "
                    "Select-Object ProcessId,ParentProcessId,Name,CommandLine | "
                    "ConvertTo-Json -Compress",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5.0,
                check=False,
            )
            if probe.returncode == 0 and probe.stdout.strip():
                data = json.loads(probe.stdout)
                raw_rows = data if isinstance(data, list) else [data]
                for row in raw_rows:
                    if not isinstance(row, dict):
                        continue
                    try:
                        pid = int(row.get("ProcessId"))
                    except (ValueError, TypeError):
                        continue
                    try:
                        ppid = int(row.get("ParentProcessId"))
                    except (ValueError, TypeError):
                        ppid = None
                    rows.append((pid, ppid, str(row.get("Name") or ""), str(row.get("CommandLine") or "")))
        else:
            probe = subprocess.run(
                ["ps", "-eo", "pid=,ppid=,args="],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5.0,
                check=False,
            )
            if probe.returncode == 0:
                for raw in (probe.stdout or "").splitlines():
                    parts = raw.strip().split(maxsplit=2)
                    if len(parts) < 2:
                        continue
                    try:
                        pid = int(parts[0])
                        ppid = int(parts[1])
                    except (ValueError, TypeError):
                        continue
                    cmdline = parts[2] if len(parts) > 2 else ""
                    rows.append((pid, ppid, "", cmdline))
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        log.debug("Duplicate process sweep unavailable: %s", exc)
        return []
    return rows


def _live_lock_owner(
    owner: guard.LockOwner, root: pathlib.Path, rows: list[tuple[int, int | None, str, str]] | None
) -> guard.LockOwner | None:
    """*owner* while its PID is still the server that wrote the lock; None when the lock is stale.

    The start time recorded in the lock decides without a process listing, so
    *rows* is read only when it cannot (a lock from before it was recorded).
    Another checkout's lock, or one with no checkout, stays a claim unless its PID
    provably belongs to another process now. This checkout's own lock stops being
    one unless the PID is proven to be its server: the restart would stop it.
    """
    started_at = guard.process_started_at(owner.pid)
    if rows is None and (owner.started_at is None or started_at is None):
        rows = _list_process_rows()
    cmdline_of = {pid: cmd for pid, _ppid, _name, cmd in rows or []}
    parent_of = {pid: ppid for pid, ppid, _name, _cmd in rows or []}
    launcher = cmdline_of.get(parent_of.get(owner.pid) or 0, "")
    identity = guard.lock_owner_identity(owner, started_at, cmdline_of.get(owner.pid, ""), launcher)
    ours = bool(owner.root) and guard.same_root(owner.root, root)
    if identity == guard.STRANGER or (identity == guard.UNKNOWN and ours):
        return None
    return owner


def _servers_to_stop(
    root: pathlib.Path, owner: guard.LockOwner | None, memory_root: pathlib.Path, host: str, port: int
) -> dict[int, tuple[str, Any]]:
    """Every server this start would stop, each proven to be this checkout's own.

    Refuses to start (SystemExit) at the first one it cannot prove, before
    anything is stopped: the rules are in serve_instance_guard.
    """
    listeners = _pids_listening_on_port(port)
    rows = _list_process_rows()
    parent_of = {pid: ppid for pid, ppid, _name, _cmd in rows}
    cmdline_of = {pid: cmd for pid, _ppid, _name, cmd in rows}

    stop: dict[int, tuple[str, Any]] = {}
    if owner is not None:
        owner = _live_lock_owner(owner, root, rows)
    if owner is not None:
        if not (owner.root and guard.same_root(owner.root, root)):
            guard.refuse(guard.lock_refusal(memory_root, owner))
        if owner.caged or guard.names_the_caged_server(cmdline_of.get(owner.pid, "")):
            guard.refuse(guard.caged_server_refusal(memory_root, owner))
        stop[owner.pid] = ("serve.lock owner", owner.port)

    # A name match alone is not a conflict: other installs/worktrees may run
    # their own servers on other ports. Only a process listening on our port,
    # or explicitly configured for it via --port, conflicts with this launch.
    for pid, cmdline in _filter_duplicate_server_candidates(rows, os.getpid()):
        if pid in stop or not _is_conflicting_duplicate(pid, cmdline, port, listeners):
            continue
        # On Windows the listening interpreter's own command line names the base
        # Python; its venv launcher parent, same arguments, names the checkout.
        launcher = cmdline_of.get(parent_of.get(pid) or 0, "")
        if not _matches_thomas_server_cmdline(launcher):
            launcher = ""
        if not (guard.cmdline_shows_root(cmdline, root) or guard.cmdline_shows_root(launcher, root)):
            other = guard.cmdline_checkout(launcher) or guard.cmdline_checkout(cmdline) or f"PID {pid}"
            guard.refuse(guard.port_refusal(host, port, other))
        stop[pid] = ("duplicate thomas server process", port)
    return stop


def _check_single_instance(config: AppConfig, host: str, port: int) -> int:
    """Stop an earlier server of this checkout, never anyone else's; return the port to use.

    The lock in the memory folder records pid, start time, port and checkout
    root. A restart of the same checkout still stops the previous instance, so
    repeated "run UI" clicks do not pile up servers, but only once its PID is
    proven to be that server: a PID now used by another process leaves the lock
    stale and stops nothing. A server from another checkout, one whose lock
    predates the root, and the caged server are left running and this start is
    refused. A server started from a green stops nothing and takes a free port.
    """
    root = guard.checkout_root()
    memory_root = pathlib.Path(config.memory.root_path)
    lock_dir = memory_root / ".thomas"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = lock_dir / "serve.lock"

    owner = guard.read_lock_owner(lock_file)
    if owner is not None and (owner.pid == os.getpid() or not guard.pid_alive(owner.pid)):
        owner = None  # its server is gone: the lock is stale, not a claim

    if guard.started_from_green(root):
        if owner is not None and _live_lock_owner(owner, root, None) is not None:
            guard.refuse(guard.lock_refusal(memory_root, owner))
        port = guard.green_port(host, port, _pids_listening_on_port(port))
        print(f"[thomas] Started from a self-fix copy, so it stops no other Thomas. Open http://{host}:{port}/")
    else:
        for pid, (why, known_port) in _servers_to_stop(root, owner, memory_root, host, port).items():
            _terminate_pid(pid, why=why, known_port=known_port)

    lock_file.write_text(json.dumps(guard.lock_record(os.getpid(), host, port, root)), encoding="utf-8")
    return port


def _awaiting(left: set[asyncio.Future[Any]], tasks: set[asyncio.Task[Any]]) -> set[asyncio.Task[Any]]:
    """The tasks that can end only when code a stop went on without does, such as the connection that code is answering.

    A cancel passes down to what a task awaits and stops at code that ignores it, so a wait for one of these is a wait for
    that code. ``_fut_waiter`` is private, but before Python 3.14 nothing public says what a task awaits.
    """
    held: set[asyncio.Task[Any]] = set()
    while found := {task for task in tasks - held if getattr(task, "_fut_waiter", None) in left | held}:
        held |= found
    return held


def _still_stuck(loop: asyncio.AbstractEventLoop) -> set[asyncio.Future[Any]]:
    """Give what a stop went on without one last cancel, and return what that did not end.

    The limit is for that code and what awaits it alone, because a stop has already given up on it. Every other task is
    cancelled and waited for with no limit, as ``asyncio.run`` would, because that wait is how a shielded save or a release
    of a budget ends.
    """
    # This generation's kernel, not the import at the top of a module a restart keeps: see ``_serve_generation``.
    from thomas.core.kernel import context

    left = asyncio.all_tasks(loop) & context.left_behind()
    if left:
        left |= _awaiting(left, asyncio.all_tasks(loop))
        others = asyncio.all_tasks(loop) - left
        for task in (*left, *others):
            task.cancel()
        if others:
            loop.run_until_complete(asyncio.wait(others))
        loop.run_until_complete(asyncio.wait(left, timeout=context.FORCED_STEP_SECONDS))
    return {task for task in left if not task.done()}


def _run_main(loop: asyncio.AbstractEventLoop, main: Coroutine[Any, Any, Any]) -> Any:
    """Run ``main`` to its end, with Ctrl+C as ``asyncio.run`` has it on Python 3.12, whichever Python this is.

    The first press cancels ``main``, so the server stops through its own ``finally`` and only then does
    ``KeyboardInterrupt`` reach the caller. Left to Python 3.10 a press lands in whatever code is running, and ``main``
    would stop inside the close, which waits for everything with no limit. A second press raises at once, and a handler
    someone else set keeps the press.
    """
    task = loop.create_task(main)
    presses = 0

    def on_press(_signal: int, _frame: Any) -> None:
        nonlocal presses
        presses += 1
        if presses > 1 or task.done():
            raise KeyboardInterrupt
        task.cancel()
        loop.call_soon_threadsafe(lambda: None)  # a loop asleep in its wait sees the cancel only once it is woken

    if signal.getsignal(signal.SIGINT) is signal.default_int_handler:
        with contextlib.suppress(ValueError):  # only the main thread may set one
            signal.signal(signal.SIGINT, on_press)
    try:
        return loop.run_until_complete(task)
    except asyncio.CancelledError:
        if presses:
            raise KeyboardInterrupt from None
        raise
    finally:
        if signal.getsignal(signal.SIGINT) is on_press:
            signal.signal(signal.SIGINT, signal.default_int_handler)


def _close_as_python_does(loop: asyncio.AbstractEventLoop) -> None:
    """What ``asyncio.run`` does once ``main`` has ended, in its order, which no Python offers on its own before 3.11."""
    try:
        tasks = asyncio.all_tasks(loop)
        for task in tasks:
            task.cancel()
        if tasks:
            loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
        for task in tasks:
            if not task.cancelled() and task.exception() is not None:
                loop.call_exception_handler(
                    {"message": "a task failed as Thomas closed", "exception": task.exception(), "task": task}
                )
        loop.run_until_complete(loop.shutdown_asyncgens())
        # Without its limit a thread that never ends would hold the close, and the lock with it, for ever.
        join_limit = (asyncio_constants.THREAD_JOIN_TIMEOUT,) if _PYTHON_LIMITS_THE_THREAD_JOIN else ()
        loop.run_until_complete(loop.shutdown_default_executor(*join_limit))
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def _run_and_close(main: Coroutine[Any, Any, Any]) -> Any:
    """``asyncio.run``, except that code a forced stop went on without cannot keep this process open.

    ``asyncio.run`` ends by cancelling every task left and waiting with no limit, so code that ignores being cancelled
    held it for ever, with the port closed, the lock kept, and a restart that had been asked for never happening. With
    nothing stuck this is ``asyncio.run``. Otherwise the loop closes around that code, and it never runs again.

    The loop is held here rather than in ``asyncio.Runner``, because pyproject says Python 3.10 and that arrived in 3.11.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return _run_main(loop, main)
    finally:
        stuck = _still_stuck(loop)
        if stuck:
            for task in stuck:
                log.error("Thomas closed with %r still running, because nothing can end it", task)
            _CLOSED_AROUND.extend(stuck)
            asyncio.set_event_loop(None)
            loop.close()
        else:
            _close_as_python_does(loop)


def _release_lock(config: AppConfig) -> None:
    """Remove the lock file on clean shutdown, if it is still this server's."""
    lock_file = pathlib.Path(config.memory.root_path) / ".thomas" / "serve.lock"
    owner = guard.read_lock_owner(lock_file)
    if owner is None or owner.pid != os.getpid():
        return  # another server's lock now, or none: not ours to remove
    with contextlib.suppress(OSError):
        lock_file.unlink(missing_ok=True)


def serve(config: AppConfig, *, host: str = "127.0.0.1", port: int = guard.DEFAULT_SERVE_PORT) -> None:
    """Run the server with a supervisor loop that auto-restarts on crashes.

    - Clean exits (Ctrl+C, SystemExit) stop immediately.
    - ``_ServerRestartRequested`` (from /api/server/restart) restarts with no
      crash count / backoff.
    - Unhandled exceptions trigger restart with exponential backoff.
    - After 5 crashes in 5 minutes, the supervisor gives up.
    """

    port = _check_single_instance(config, host, port)

    max_crashes = 5
    crash_window_s = 300  # 5 minutes
    crash_times: list = []
    crash_count = 0

    try:
        while True:
            try:
                _run_and_close(serve_async(config, host=host, port=port, crash_count=crash_count))
                break  # clean exit (e.g. Ctrl+C handled inside the event loop)
            except KeyboardInterrupt:
                print("\n[thomas] Stopped by user.")
                break
            except SystemExit:
                break
            except _ServerRestartRequested:
                print("[thomas] Restart requested. Rebooting...")
                _retire_check_threads()  # after serve_async's drain; the re-import below makes the next ones
                # Clear bytecode cache to avoid stale .pyc issues after hot-edits
                try:
                    import thomas

                    _pkg_root = os.path.dirname(thomas.__file__)
                    for _dirpath, _dirnames, _filenames in os.walk(_pkg_root):
                        if "__pycache__" in _dirnames:
                            _cache_dir = os.path.join(_dirpath, "__pycache__")
                            shutil.rmtree(_cache_dir, ignore_errors=True)
                    # Force re-import of critical modules
                    _stale = [k for k in sys.modules if k.startswith("thomas.")]
                    for k in _stale:
                        del sys.modules[k]
                    if "thomas" in sys.modules:
                        del sys.modules["thomas"]
                except (OSError, KeyError, ImportError) as _e:
                    print(f"[thomas] pycache cleanup: {_e}")
                continue  # no crash count, no backoff
            except BaseException as exc:
                # Catch most exceptions but not KeyboardInterrupt/SystemExit (handled above)
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                now = _time.time()
                crash_times.append(now)
                crash_times = [t for t in crash_times if now - t < crash_window_s]
                crash_count = len(crash_times)

                print(f"[thomas] CRASH ({crash_count}/{max_crashes}): {type(exc).__name__}: {exc}")

                if crash_count >= max_crashes:
                    print(
                        f"[thomas] {crash_count} crashes in {crash_window_s}s -- giving up. Fix the issue and restart manually."
                    )
                    break

                delay = min(2.0 * (2 ** (crash_count - 1)), 30.0)
                print(f"[thomas] Auto-restarting in {delay:.0f}s...")
                _time.sleep(delay)
    finally:
        _release_lock(config)
