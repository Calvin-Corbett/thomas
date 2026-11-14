"""
thomas/tray_agent/agent.py
-------------------------
Thomas System Tray Agent -- 24/7 background process with tray icon.

Features:
  - Hidden background process (no visible terminal)
  - System tray icon showing status (needs pystray + Pillow; without them the
    agent says so on start and runs headless)
  - Auto-start with Windows logon (Task Scheduler)
  - Auto-restart after a crash (a server you stopped from the menu stays stopped)
  - Friendly notifications for consumers
  - One agent per port: a second one exits instead of fighting the first

Usage:
    python -m thomas.tray_agent
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from thomas.tray_agent import autostart, background_thomas
from thomas.tray_agent.instance_lock import InstanceLock

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TRAY_APP_NAME = "Thomas"
TRAY_APP_VERSION = "1.0.0"
RESTART_DELAY_S = 10
HEALTHCHECK_INTERVAL_S = 30
SERVER_STARTUP_TIMEOUT_S = 60

# Idle self-improvement engines make background model calls while nobody is using
# Thomas. The direct launcher (run-ui.ps1, Start-DetachedThomasServer) turns them
# off unless you exported the variable yourself; a server started here gets the
# same default. Keep this list in step with that function.
_QUIET_ENGINE_ENV = (
    "THOMAS_CODE_ISSUE_ENGINE_ENABLED",
    "THOMAS_SELF_UPGRADE_ENGINE_ENABLED",
    "THOMAS_UI_WORKFLOW_ENGINE_ENABLED",
    "THOMAS_LOCAL_AGENT_ENGINE_ENABLED",
    "THOMAS_WORKSPACE_SYNC_ENGINE_ENABLED",
    "THOMAS_WORKSPACE_SYNC_AUTO_PUSH",
)

# Paths
_STATE_DIR = Path.home() / ".thomas"
_TRAY_STATE_FILE = _STATE_DIR / "tray_state.json"
_LOG_FILE = _STATE_DIR / "tray_agent.log"
_SERVER_LOG_FILE = _STATE_DIR / "server.log"


def _get_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in (current.parent, *current.parents):
        if (parent / "pyproject.toml").exists() and (parent / "thomas").exists():
            return parent
    return Path.cwd()


def _ensure_state_dir() -> Path:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    return _STATE_DIR


def _read_log_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default)).strip()))
    except ValueError:
        # "8MB" or an empty string must not stop the agent from starting.
        return default


def _module_available(name: str) -> bool:
    """True when `name` can be imported, without importing it."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _console_log_attached(root: logging.Logger) -> bool:
    """True when `root` already prints to a console (pythonw has no stderr, files do not count)."""
    return any(
        isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
        and getattr(h, "stream", None) is not None
        for h in root.handlers
    )


# ---------------------------------------------------------------------------
# Tray State
# ---------------------------------------------------------------------------


@dataclass
class TrayState:
    """Persistent state for tray agent."""

    # False until a schtasks call has actually succeeded (see toggle_auto_start).
    auto_start_enabled: bool = False
    last_notification: str = ""
    server_port: int = 8899
    notifications_enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "auto_start_enabled": self.auto_start_enabled,
            "last_notification": self.last_notification,
            "server_port": self.server_port,
            "notifications_enabled": self.notifications_enabled,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TrayState:
        return cls(
            auto_start_enabled=d.get("auto_start_enabled", False),
            last_notification=d.get("last_notification", ""),
            server_port=d.get("server_port", 8899),
            notifications_enabled=d.get("notifications_enabled", True),
        )

    def save(self) -> None:
        _ensure_state_dir()
        _TRAY_STATE_FILE.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls) -> TrayState:
        if not _TRAY_STATE_FILE.exists():
            return cls()
        try:
            return cls.from_dict(json.loads(_TRAY_STATE_FILE.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            return cls()


# ---------------------------------------------------------------------------
# Windows Task Scheduler integration
# ---------------------------------------------------------------------------


def _get_exe_path() -> str:
    """Get the path to the preferred Python interpreter for Thomas."""
    repo_root = _get_repo_root()
    candidates = [
        repo_root / ".venv" / "Scripts" / "python.exe",
        repo_root / ".venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _pip_command() -> str:
    """`<python> -m pip` for someone to copy. Never pythonw.exe: it runs silently and prints nothing."""
    exe = _get_exe_path()
    if exe.lower().endswith("pythonw.exe"):
        exe = exe[: -len("pythonw.exe")] + "python.exe"
    return f'"{exe}" -m pip' if " " in exe else f"{exe} -m pip"


def _get_windowless_exe_path() -> str:
    """pythonw.exe beside the chosen interpreter, so a logon start opens no console."""
    exe = Path(_get_exe_path())
    windowless = exe.with_name("pythonw.exe")
    return str(windowless) if windowless.exists() else str(exe)


def is_auto_start_enabled() -> bool:
    """Check if auto-start is configured in Windows Task Scheduler."""
    return autostart.is_enabled()


def enable_auto_start(port: int = 8899) -> bool:
    """Enable auto-start at Windows logon; True only when Windows accepted the task."""
    return autostart.enable(port, exe=_get_windowless_exe_path(), repo_root=str(_get_repo_root()))


def disable_auto_start() -> bool:
    """Disable auto-start."""
    return autostart.disable()


# ---------------------------------------------------------------------------
# Server Process Management
# ---------------------------------------------------------------------------


class ServerProcess:
    """Manages the Thomas server subprocess."""

    def __init__(self, port: int = 8899):
        self.port = port
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def start(self) -> bool:
        """Start the Thomas server."""
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                log.info("Server already running")
                return True

            try:
                exe = _get_exe_path()
                cwd = str(_get_repo_root())

                # An open port before we spawn means another process serves it.
                # Spawning anyway would replace that server, and a later "port is
                # live" check would then credit that other server to this child.
                if self._port_is_live(timeout=0.35):
                    log.warning(
                        "Port %d is already served by another process; not starting a second server.", self.port
                    )
                    return False

                # Start server as hidden subprocess, logging to file
                _ensure_state_dir()
                server_env = os.environ.copy()
                for engine_var in _QUIET_ENGINE_ENV:
                    server_env.setdefault(engine_var, "0")
                server_env["THOMAS_LOG_FILE"] = str(_SERVER_LOG_FILE)
                server_env["THOMAS_TRAY_SERVER_PORT"] = str(self.port)
                server_env.setdefault(
                    "THOMAS_LOG_MAX_BYTES",
                    str(os.environ.get("THOMAS_SERVER_LOG_MAX_BYTES", "8388608")),
                )
                server_env.setdefault(
                    "THOMAS_LOG_BACKUP_COUNT",
                    str(os.environ.get("THOMAS_SERVER_LOG_BACKUP_COUNT", "5")),
                )
                self._process = subprocess.Popen(
                    [exe, "-m", "thomas.server", "--host", "127.0.0.1", "--port", str(self.port)],
                    cwd=cwd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                    env=server_env,
                )
                pid = self._process.pid
                deadline = time.time() + SERVER_STARTUP_TIMEOUT_S
                while time.time() < deadline:
                    if self._process is None:
                        break
                    rc = self._process.poll()
                    if rc is not None:
                        log.error("Server exited during startup (rc=%s)", rc)
                        self._process = None
                        return False
                    if self._port_is_live(timeout=0.35):
                        log.info("Server started on port %d (pid %d)", self.port, pid)
                        return True
                    time.sleep(0.25)

                log.error("Server startup timed out on port %d; forcing restart path.", self.port)
                if self._process is not None:
                    try:
                        self._process.terminate()
                        self._process.wait(timeout=2)
                    except Exception:  # REVIEWED: broad catch
                        try:
                            self._process.kill()
                        except Exception:  # REVIEWED: broad catch
                            pass
                    self._process = None
                return False
            except Exception as e:
                log.error("Failed to start server: %s", e)
                return False

    def stop(self) -> None:
        """Stop the server."""
        with self._lock:
            if self._process is not None:
                try:
                    self._process.terminate()
                    self._process.wait(timeout=5)
                except Exception:  # REVIEWED: broad catch
                    try:
                        self._process.kill()
                    except Exception:  # REVIEWED: broad catch
                        pass
                self._process = None
                log.info("Server stopped")

    def is_running(self) -> bool:
        """Check if server is running."""
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def _port_is_live(self, timeout: float = 0.35) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", int(self.port)), timeout=timeout):
                return True
        except OSError:
            return False

    def is_healthy(self) -> bool:
        """Check that process is alive and the configured port is reachable."""
        with self._lock:
            running = self._process is not None and self._process.poll() is None
        if not running:
            return False
        return self._port_is_live(timeout=0.35)

    def restart(self) -> bool:
        """Restart the server."""
        self.stop()
        time.sleep(1)
        return self.start()


# ---------------------------------------------------------------------------
# Tray Icon (using pystray)
# ---------------------------------------------------------------------------

# status -> (circle colour, tooltip)
_ICON_STATES = {
    "active": ((34, 139, 34, 255), "Thomas Active"),
    "working": ((255, 165, 0, 255), "Thomas Not Responding"),
    "stopped": ((139, 0, 0, 255), "Thomas Stopped"),
}


def _make_icon(status: str):
    """Draw the 64px status icon: a coloured disc with a white T."""
    from PIL import Image, ImageDraw, ImageFont

    color = _ICON_STATES.get(status, _ICON_STATES["stopped"])[0]
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=color)
    try:
        font = ImageFont.truetype("arial.ttf", 36)
    except (OSError, ImportError):
        font = ImageFont.load_default()
    d.text((24, 14), "T", font=font, fill=(255, 255, 255, 255))
    return img


class ThomasTrayAgent:
    """
    System tray agent for Thomas.

    Features:
      - Tray icon with status indicator
      - Start/stop server
      - Open web UI
      - Enable/disable auto-start
      - Notifications
    """

    def __init__(self, port: int = 8899):
        self.port = port
        self.state = TrayState.load()
        self.server = ServerProcess(port)
        self._stop_event = threading.Event()
        # Set by the menu's Stop Server so the healthcheck does not "repair" it.
        self._user_stopped = threading.Event()
        self._instance_lock = InstanceLock(_STATE_DIR / f"tray_agent_{port}.lock")
        self._icon = None
        self._healthcheck_thread = None
        self._background = background_thomas.BackgroundThomas()
        self._last_background_lines: tuple[str, ...] | None = None
        self._background_menu_builder = None
        self._auto_start_checked = False
        self._last_auto_start_check_at: float | None = time.monotonic()
        self._notification_queue: list = []
        self._lock = threading.Lock()

        # True once logging prints to an attached console, so _say need not print too.
        self._console_log = False

        # Try to import pystray. Without it there is no icon; run() says so.
        self._headless_reason = ""
        self._headless_hint = ""
        try:
            import pystray  # type: ignore

            self._pystray = pystray
        except ImportError as exc:
            self._pystray = None
            self._headless_reason = f"pystray could not be loaded ({exc})"
            self._headless_hint = f"To get the icon, install it: {_pip_command()} install pystray pillow win10toast"

    def force_headless(self) -> None:
        """Run without an icon on purpose (--no-tray)."""
        self._pystray = None
        self._headless_reason = "it was started with --no-tray"
        self._headless_hint = ""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _setup_logging(self) -> None:
        _ensure_state_dir()
        log_file = _LOG_FILE
        log_file.parent.mkdir(parents=True, exist_ok=True)
        max_bytes = _read_log_int_env("THOMAS_TRAY_LOG_MAX_BYTES", 8_388_608)
        backup_count = _read_log_int_env("THOMAS_TRAY_LOG_BACKUP_COUNT", 3)

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        self._console_log = _console_log_attached(logging.getLogger())
        try:
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            logging.getLogger().addHandler(file_handler)
        except OSError as file_exc:
            log.error("Failed to configure rotating tray log file: %s", file_exc)

    def _say(self, message: str) -> None:
        """Tell whoever launched us: the log file, and the console once (the log line, or a print)."""
        log.warning(message)
        if not self._console_log:
            print(f"[thomas] {message}", flush=True)

    def run(self) -> None:
        """Run the tray agent (blocking)."""
        self._setup_logging()
        log.info("Thomas Tray Agent starting...")

        if not self._instance_lock.acquire():
            self._say(f"Another Thomas tray agent is already running for port {self.port}; this one is exiting.")
            return
        try:
            if self._pystray is None:
                # Toasts come from win10toast, not pystray, so they may still work.
                lost = "no tray icon" if _module_available("win10toast") else "no tray icon and no notifications"
                self._say(
                    f"Tray agent is running headless: {lost}, because "
                    f"{self._headless_reason}. Thomas itself is still served at "
                    f"http://127.0.0.1:{self.port}/. {self._headless_hint}".rstrip()
                )

            # Start server
            if not self.server.start():
                self._say_server_did_not_start()

            # Start healthcheck thread
            self._healthcheck_thread = threading.Thread(
                target=self._healthcheck_loop,
                daemon=True,
                name="tray-healthcheck",
            )
            self._healthcheck_thread.start()

            if self._pystray is None:
                self._run_headless()
            else:
                self._background.start()
                self._run_with_tray()
        finally:
            self._background.stop()
            self._instance_lock.release()

    def stop(self) -> None:
        """Stop the tray agent."""
        self._stop_event.set()
        self._background.stop()
        self.server.stop()
        self.state.save()

    # Menu actions live here, not in closures, so they can be tested without a tray.

    def background_thomas_lines(self) -> tuple[str, ...]:
        """Read the latest independent health and project snapshots without I/O."""
        return self._background.lines()

    def open_background_thomas(self) -> None:
        """Open the caged server's UI, without changing its state."""
        webbrowser.open(background_thomas.BASE_URL)

    def user_start_server(self) -> bool:
        self._user_stopped.clear()
        ok = self.server.start()
        if not ok:
            self._notify("Thomas server did not start (see the tray log)")
        return ok

    def user_stop_server(self) -> None:
        """Stop the server and keep it stopped until Start or Restart."""
        # Set first: the healthcheck must never see "dead" without also seeing "asked".
        self._user_stopped.set()
        self.server.stop()

    def user_restart_server(self) -> bool:
        self._user_stopped.set()  # hold the healthcheck off while we bounce it
        try:
            ok = self.server.restart()
        finally:
            self._user_stopped.clear()
        if not ok:
            self._notify("Thomas server did not restart (see the tray log)")
        return ok

    def _say_server_did_not_start(self) -> None:
        """The first start failed: say why it matters, instead of a red icon and silence."""
        if self.server._port_is_live():
            # Something else serves this port. The healthcheck sees that and ends this agent.
            self._say(
                f"Port {self.port} is already served by another process, so this agent did not start a "
                "server and will exit shortly."
            )
        else:
            self._say(f"The Thomas server did not start on port {self.port} (see {_LOG_FILE}); will keep trying.")

    def toggle_auto_start(self) -> bool:
        """Flip the logon task. The saved flag follows what schtasks really did."""
        previous = is_auto_start_enabled()
        turning_on = not previous
        ok = enable_auto_start(self.port) if turning_on else disable_auto_start()
        self._auto_start_checked = turning_on if ok else previous
        self._last_auto_start_check_at = time.monotonic()
        if self._icon is not None and self._background_menu_builder is not None:
            self._icon.menu = self._background_menu_builder(self.background_thomas_lines())
        if ok:
            self.state.auto_start_enabled = turning_on
            self.state.save()
        else:
            self._notify(
                f"Could not turn auto-start {'on' if turning_on else 'off'}; Windows refused the change (see the tray log)"
            )
        return ok

    def _run_headless(self) -> None:
        """Run without tray icon."""
        try:
            while not self._stop_event.is_set():
                self._stop_event.wait(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def _run_with_tray(self) -> None:
        """Run with system tray icon."""

        # Menu callbacks
        def on_open_ui(icon, item):
            webbrowser.open(f"http://127.0.0.1:{self.port}/")

        def on_start_server(icon, item):
            self.user_start_server()
            self._update_icon(icon)

        def on_stop_server(icon, item):
            self.user_stop_server()
            self._update_icon(icon)

        def on_restart_server(icon, item):
            self.user_restart_server()
            self._update_icon(icon)

        def on_toggle_auto_start(icon, item):
            self.toggle_auto_start()

        def on_open_logs(icon, item):
            log_path = str(_LOG_FILE)
            if sys.platform == "win32":
                os.startfile(log_path)  # type: ignore[attr-defined]
            else:
                webbrowser.open(f"file:///{log_path}")

        def on_quit(icon, item):
            self.stop()
            icon.stop()

        # Build menu; keep the callback wiring and rebuild only on changed section text.
        pystray = self._pystray

        def build_menu(lines):
            background_items = [pystray.MenuItem(line, None, enabled=False) for line in lines]
            return pystray.Menu(
                pystray.MenuItem("Open Thomas", on_open_ui, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Background Thomas", None, enabled=False),
                *background_items,
                pystray.MenuItem("Open background Thomas", lambda icon, item: self.open_background_thomas()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Start Server", on_start_server, visible=lambda i: not self.server.is_running()),
                pystray.MenuItem("Stop Server", on_stop_server, visible=lambda i: self.server.is_running()),
                pystray.MenuItem("Restart Server", on_restart_server),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "Auto-start with Windows", on_toggle_auto_start, checked=lambda i: self._auto_start_checked
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Open Logs", on_open_logs),
                pystray.MenuItem("Quit", on_quit),
            )

        self._auto_start_checked = is_auto_start_enabled()
        self._last_auto_start_check_at = time.monotonic()
        self._background_menu_builder = build_menu
        self._last_background_lines = self.background_thomas_lines()
        menu = build_menu(self._last_background_lines)

        # Create and run icon
        status = self._tray_status()
        self._icon = pystray.Icon("Thomas", _make_icon(status), _ICON_STATES[status][1], menu)

        # Update icon periodically
        def update_icon_loop():
            while not self._stop_event.wait(5):
                if self._icon:
                    try:
                        self._update_icon(self._icon)
                        self._refresh_background_menu(self._icon)
                    except Exception:
                        log.exception("Could not refresh tray icon")

        threading.Thread(target=update_icon_loop, daemon=True).start()
        self._icon.run()

    def _refresh_background_menu(self, icon) -> None:
        """Refresh changed background lines and periodically check the Windows task."""
        if self._background_menu_builder is None:
            return
        try:
            now = time.monotonic()
            check_at = self._last_auto_start_check_at
            if check_at is None or now - check_at >= 600:
                enabled = is_auto_start_enabled()
                self._last_auto_start_check_at = now
                changed = enabled != self._auto_start_checked
                self._auto_start_checked = enabled
            else:
                changed = False
            lines = self.background_thomas_lines()
            if lines == self._last_background_lines and not changed:
                return
            icon.menu = self._background_menu_builder(lines)
            self._last_background_lines = lines
        except Exception:
            log.exception("Could not refresh Background Thomas menu")

    def _tray_status(self) -> str:
        """active: serving. working: process alive but its port is not answering. stopped."""
        if self.server.is_healthy():
            return "active"
        return "working" if self.server.is_running() else "stopped"

    def _update_icon(self, icon) -> None:
        """Update tray icon based on status."""
        if self._pystray is None:
            return

        status = self._tray_status()
        icon.icon = _make_icon(status)
        icon.title = _ICON_STATES[status][1]

    # ------------------------------------------------------------------
    # Healthcheck & Notifications
    # ------------------------------------------------------------------

    def _healthcheck_loop(self) -> None:
        """Periodic healthcheck and auto-restart."""
        while not self._stop_event.is_set():
            time.sleep(HEALTHCHECK_INTERVAL_S)

            if self._stop_event.is_set():
                return

            # "Stop Server" in the menu means stay stopped, not "restart in a minute".
            if self._user_stopped.is_set():
                continue

            # Check if server process is alive and the port is serving.
            if not self.server.is_healthy():
                if not self.server.is_running():
                    # Our subprocess is dead.  Before trying to restart, wait
                    # a moment and check if something else took over the port
                    # (e.g. user re-ran run-ui.ps1 with updated code).
                    time.sleep(2)
                    if self.server._port_is_live():
                        log.info(
                            "Port %d taken over by another instance; this tray agent is now stale -- exiting.",
                            self.port,
                        )
                        self._stop_event.set()
                        if self._icon:
                            self._icon.stop()
                        return

                    # Port is free and our process died -- attempt restart.
                    log.warning("Server process died and port is free; restarting...")
                    time.sleep(RESTART_DELAY_S)
                    if self._stop_event.is_set():
                        return
                    # The menu may have acted during the delay: Stop Server holds us off, and
                    # a Start or Restart that finished has our server up again, and that live
                    # port is ours, not a stranger's (checked below).
                    if self._user_stopped.is_set() or self.server.is_running():
                        continue
                    # Re-check once more -- the user may have started a new
                    # instance during the restart delay.
                    if self.server._port_is_live():
                        log.info("Port %d now in use by another process; exiting.", self.port)
                        self._stop_event.set()
                        if self._icon:
                            self._icon.stop()
                        return
                    if self.server.restart():
                        self._notify("Thomas server restarted")
                    else:
                        self._notify("Thomas server restart failed (retrying)")
                else:
                    # Process alive but port not responding -- could be
                    # transient.  Log but don't restart yet.
                    log.warning("Server process alive but port %d not responding.", self.port)

    def _notify(self, message: str) -> None:
        """Show a notification (consumer-friendly)."""
        log.info("Notification: %s", message)
        self.state.last_notification = message
        self.state.save()

        # Try to show Windows toast notification
        if sys.platform == "win32" and self.state.notifications_enabled:
            try:
                from win10toast import ToastNotifier  # type: ignore

                toaster = ToastNotifier()
                toaster.show_toast("Thomas", message, duration=5, threaded=True)
            except ImportError:
                pass  # win10toast not installed


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def run_tray_agent(port: int = 8899, no_tray: bool = False) -> None:
    """Run the tray agent."""
    agent = ThomasTrayAgent(port=port)
    if no_tray:
        agent.force_headless()
    try:
        agent.run()
    except KeyboardInterrupt:
        agent.stop()


if __name__ == "__main__":
    run_tray_agent()
