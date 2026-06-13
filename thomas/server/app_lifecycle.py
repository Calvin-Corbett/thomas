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
import time as _time
from typing import Any

from thomas.core.config import AppConfig
from thomas.server.app_keys import APP_CRASH_COUNT, APP_DIAGNOSTICS, APP_RESTART_REQUESTED, APP_SHUTDOWN_EVENT

log = logging.getLogger(__name__)


class _ServerRestartRequested(Exception):
    """Sentinel: supervisor loop should restart the server cleanly."""

    pass


async def serve_async(
    config: AppConfig,
    *,
    host: str = "127.0.0.1",
    port: int = 8899,
    crash_count: int = 0,
) -> None:
    from aiohttp import web

    from .app_core import create_app

    app = create_app(config)
    app[APP_CRASH_COUNT] = crash_count

    # Shutdown event -- set by restart endpoint or signal handler
    shutdown_event = asyncio.Event()
    app[APP_SHUTDOWN_EVENT] = shutdown_event
    app[APP_RESTART_REQUESTED] = False

    runner = web.AppRunner(app)
    await runner.setup()

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
                await runner.cleanup()
                raise
            delay = attempt * 1.0
            print(
                f"[thomas] Port {port} busy ({bind_err}), retrying in {delay:.0f}s ({attempt}/{max_bind_attempts})..."
            )
            await asyncio.sleep(delay)

    # ── Startup summary ──
    diag = app.get(APP_DIAGNOSTICS, {})
    boot_dur = app.get("APP_BOOT_DURATION", 0)
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
        await runner.cleanup()
        if app.get(APP_RESTART_REQUESTED):
            raise _ServerRestartRequested()


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


def _pids_listening_on_port(target_port: int) -> set[int] | None:
    """PIDs bound to ``target_port`` in LISTEN state; None if unknowable."""
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


def _check_single_instance(config: AppConfig, host: str, port: int) -> None:
    """Ensure only one Thomas server runs at a time.

    Uses a PID lock file. If another instance is alive, kills it first so the
    newest launch always wins. This prevents zombie accumulation when the user
    clicks "run UI" repeatedly.
    """

    def _terminate_pid(pid: int, *, why: str, known_port: Any = "?") -> None:
        if pid == os.getpid():
            return
        try:
            os.kill(pid, 0)  # process exists
        except OSError:
            return

        print(f"[thomas] Stopping previous instance (PID {pid}, port {known_port}, {why})...")
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return

        # Wait up to 3s for graceful shutdown.
        for _ in range(30):
            _time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except OSError:
                break  # dead
        else:
            # Still alive -- force kill.
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL if hasattr(signal, "SIGKILL") else signal.SIGTERM)
        print("[thomas] Previous instance stopped.")

    def _list_duplicate_thomas_server_processes() -> list[tuple[int, str]]:
        """Best-effort process sweep for legacy/lockless server processes."""
        current_pid = os.getpid()
        # (pid, ppid, name, cmdline) for every visible process.
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

        return _filter_duplicate_server_candidates(rows, current_pid)

    lock_dir = pathlib.Path(config.memory.root_path) / ".thomas"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = lock_dir / "serve.lock"

    lock_pid_to_kill: int | None = None
    lock_port_to_kill: Any = "?"
    if lock_file.exists():
        try:
            data = json.loads(lock_file.read_text(encoding="utf-8"))
            old_pid = data.get("pid")
            old_port = data.get("port", "?")
            if old_pid is not None:
                try:
                    lock_pid_to_kill = int(old_pid)
                except (ValueError, TypeError):
                    lock_pid_to_kill = None
                lock_port_to_kill = old_port
        except (json.JSONDecodeError, KeyError, OSError):
            pass  # corrupt lock file, overwrite it

    if lock_pid_to_kill is not None:
        _terminate_pid(lock_pid_to_kill, why="serve.lock owner", known_port=lock_port_to_kill)

    # Extra safeguard: terminate other Thomas server entrypoints that actually
    # conflict with THIS launch. A name match alone is not a conflict — other
    # installs/worktrees may legitimately run their own servers on other ports
    # — so only kill processes listening on our port or explicitly configured
    # for it via --port.
    listeners = _pids_listening_on_port(port)
    for pid, cmdline in _list_duplicate_thomas_server_processes():
        if not _is_conflicting_duplicate(pid, cmdline, port, listeners):
            continue
        _terminate_pid(pid, why="duplicate thomas server process", known_port=port)
        log.debug("Stopped duplicate Thomas server PID %s (%s)", pid, cmdline)

    # Write our lock
    lock_file.write_text(
        json.dumps({"pid": os.getpid(), "host": host, "port": port}),
        encoding="utf-8",
    )


def _release_lock(config: AppConfig) -> None:
    """Remove the lock file on clean shutdown."""
    lock_file = pathlib.Path(config.memory.root_path) / ".thomas" / "serve.lock"
    with contextlib.suppress(OSError):
        lock_file.unlink(missing_ok=True)


def serve(config: AppConfig, *, host: str = "127.0.0.1", port: int = 8899) -> None:
    """Run the server with a supervisor loop that auto-restarts on crashes.

    - Clean exits (Ctrl+C, SystemExit) stop immediately.
    - ``_ServerRestartRequested`` (from /api/server/restart) restarts with no
      crash count / backoff.
    - Unhandled exceptions trigger restart with exponential backoff.
    - After 5 crashes in 5 minutes, the supervisor gives up.
    """

    _check_single_instance(config, host, port)

    max_crashes = 5
    crash_window_s = 300  # 5 minutes
    crash_times: list = []
    crash_count = 0

    try:
        while True:
            try:
                asyncio.run(serve_async(config, host=host, port=port, crash_count=crash_count))
                break  # clean exit (e.g. Ctrl+C handled inside the event loop)
            except KeyboardInterrupt:
                print("\n[thomas] Stopped by user.")
                break
            except SystemExit:
                break
            except _ServerRestartRequested:
                print("[thomas] Restart requested. Rebooting...")
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
