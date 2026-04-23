"""Server lifecycle management and restart logic."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import pathlib
import re
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


_THOMAS_SERVER_CMD_RE = re.compile(r"(?:^|\s)-m\s+thomas(?:\.server|\s+serve)(?:\s|$)")


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

    def _match_cmdline(raw: str) -> bool:
        text = str(raw or "").strip().lower()
        if not text:
            return False
        return bool(_THOMAS_SERVER_CMD_RE.search(text))

    def _get_process_cmdline(pid: int) -> str:
        if pid <= 0:
            return ""
        try:
            if os.name == "nt":
                probe = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        (
                            f"Get-CimInstance Win32_Process -Filter \"ProcessId = {pid}\" | "
                            "Select-Object -First 1 CommandLine | ConvertTo-Json -Compress"
                        ),
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
                    if isinstance(data, dict):
                        return str(data.get("CommandLine") or "")
            else:
                probe = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "args="],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5.0,
                    check=False,
                )
                if probe.returncode == 0:
                    return str(probe.stdout or "").strip()
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            log.debug("Process command line lookup unavailable for PID %s: %s", pid, exc)
        return ""

    def _find_listener_pid_for_port(port_number: int) -> int | None:
        try:
            if os.name == "nt":
                probe = subprocess.run(
                    ["netstat", "-ano", "-p", "tcp"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5.0,
                    check=False,
                )
                if probe.returncode == 0:
                    suffix = f":{int(port_number)}"
                    for raw in (probe.stdout or "").splitlines():
                        line = raw.strip()
                        if not line:
                            continue
                        parts = line.split()
                        if len(parts) < 5:
                            continue
                        proto, local_addr, _, state, pid_text = parts[:5]
                        if proto.upper() != "TCP" or state.upper() != "LISTENING":
                            continue
                        if not local_addr.endswith(suffix):
                            continue
                        try:
                            pid = int(pid_text)
                        except (ValueError, TypeError):
                            continue
                        return pid if pid > 0 else None
            else:
                probe = subprocess.run(
                    ["lsof", "-nP", f"-iTCP:{int(port_number)}", "-sTCP:LISTEN", "-t"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5.0,
                    check=False,
                )
                if probe.returncode == 0:
                    for raw in (probe.stdout or "").splitlines():
                        line = raw.strip()
                        if not line:
                            continue
                        try:
                            pid = int(line)
                        except (ValueError, TypeError):
                            continue
                        return pid if pid > 0 else None
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.debug("Port listener lookup unavailable for %s:%s: %s", host, port_number, exc)
        return None

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

    # Extra safeguard: if the target port is already owned by another Thomas
    # server process, stop only that concrete listener instead of sweeping
    # unrelated Python processes.
    listener_pid = _find_listener_pid_for_port(port)
    if listener_pid is not None and listener_pid != os.getpid():
        listener_cmdline = _get_process_cmdline(listener_pid)
        if _match_cmdline(listener_cmdline):
            _terminate_pid(listener_pid, why="existing listener on requested port", known_port=port)
            log.debug("Stopped Thomas server listener PID %s (%s)", listener_pid, listener_cmdline)

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
