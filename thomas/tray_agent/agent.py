"""
thomas/tray_agent/agent.py
-------------------------
Thomas System Tray Agent -- 24/7 background process with tray icon.

Features:
  - Hidden background process (no visible terminal)
  - System tray icon showing status
  - Auto-start with Windows boot (Task Scheduler)
  - Auto-restart within 10 seconds if crashed
  - Friendly notifications for consumers
  - Super-user toggle for advanced controls

Usage:
    python -m thomas.tray_agent

Consumer rules:
  - Normal user sees tray icon + occasional notifications
  - Super-user toggle in Settings shows logs, manual controls
"""

from __future__ import annotations

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

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TRAY_APP_NAME = "Thomas"
TRAY_APP_VERSION = "1.0.0"
RESTART_DELAY_S = 10
HEALTHCHECK_INTERVAL_S = 30
SERVER_STARTUP_TIMEOUT_S = 30

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
    except (OSError, FileNotFoundError):
        return default


# ---------------------------------------------------------------------------
# Tray State
# ---------------------------------------------------------------------------


@dataclass
class TrayState:
    """Persistent state for tray agent."""

    auto_start_enabled: bool = True
    super_user_mode: bool = False
    last_notification: str = ""
    server_port: int = 8899
    notifications_enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "auto_start_enabled": self.auto_start_enabled,
            "super_user_mode": self.super_user_mode,
            "last_notification": self.last_notification,
            "server_port": self.server_port,
            "notifications_enabled": self.notifications_enabled,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TrayState:
        return cls(
            auto_start_enabled=d.get("auto_start_enabled", True),
            super_user_mode=d.get("super_user_mode", False),
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


def _get_task_name() -> str:
    return "ThomasTrayAgent"


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


def _get_script_path() -> str:
    """Get the path to the tray agent script."""
    return str((Path(__file__).parent / "__main__.py").resolve())


def is_auto_start_enabled() -> bool:
    """Check if auto-start is configured in Windows Task Scheduler."""
    try:
        import subprocess

        result = subprocess.run(
            ["schtasks", "/Query", "/TN", _get_task_name()],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except ImportError:
        return False


def enable_auto_start() -> bool:
    """Enable auto-start with Windows boot via Task Scheduler."""
    try:
        exe = _get_exe_path()
        script = _get_script_path()
        str(_get_repo_root())

        # Create task that runs at logon
        cmd = [
            "schtasks",
            "/Create",
            "/TN",
            _get_task_name(),
            "/TR",
            f'"{exe}" "{script}"',
            "/SC",
            "ON_LOGON",
            "/RL",
            "HIGHEST",
            "/F",  # Force overwrite if exists
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            log.info("Auto-start enabled via Task Scheduler")
            return True
        log.error("Failed to enable auto-start: %s", result.stderr)
        return False
    except Exception as e:
        log.error("Failed to enable auto-start: %s", e)
        return False


def disable_auto_start() -> bool:
    """Disable auto-start."""
    try:
        result = subprocess.run(
            ["schtasks", "/Delete", "/TN", _get_task_name(), "/F"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 or "The system cannot find the file specified" in result.stderr:
            log.info("Auto-start disabled")
            return True
        log.error("Failed to disable auto-start: %s", result.stderr)
        return False
    except Exception as e:
        log.error("Failed to disable auto-start: %s", e)
        return False


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

                # Start server as hidden subprocess, logging to file
                _ensure_state_dir()
                server_env = os.environ.copy()
                server_env["THOMAS_LOG_FILE"] = str(_SERVER_LOG_FILE)
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


class ThomasTrayAgent:
    """
    System tray agent for Thomas.

    Features:
      - Tray icon with status indicator
      - Start/stop server
      - Open web UI
      - Enable/disable auto-start
      - Super-user mode toggle
      - Notifications
    """

    def __init__(self, port: int = 8899):
        self.port = port
        self.state = TrayState.load()
        self.server = ServerProcess(port)
        self._stop_event = threading.Event()
        self._icon = None
        self._healthcheck_thread = None
        self._notification_queue: list = []
        self._lock = threading.Lock()

        # Try to import pystray
        try:
            import pystray  # type: ignore

            self._pystray = pystray
        except ImportError:
            self._pystray = None
            log.warning("pystray not installed -- running in headless mode")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Run the tray agent (blocking)."""
        # Setup logging
        _ensure_state_dir()
        log_file = _LOG_FILE
        log_file.parent.mkdir(parents=True, exist_ok=True)
        max_bytes = _read_log_int_env("THOMAS_TRAY_LOG_MAX_BYTES", 8_388_608)
        backup_count = _read_log_int_env("THOMAS_TRAY_LOG_BACKUP_COUNT", 3)

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        try:
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            logging.getLogger().addHandler(file_handler)
        except Exception as file_exc:
            log.error("Failed to configure rotating tray log file: %s", file_exc)

        log.info("Thomas Tray Agent starting...")

        # Start server
        self.server.start()

        # Start healthcheck thread
        self._healthcheck_thread = threading.Thread(
            target=self._healthcheck_loop,
            daemon=True,
            name="tray-healthcheck",
        )
        self._healthcheck_thread.start()

        if self._pystray is None:
            log.info("Running in headless mode (no tray icon)")
            self._run_headless()
        else:
            self._run_with_tray()

    def stop(self) -> None:
        """Stop the tray agent."""
        self._stop_event.set()
        self.server.stop()
        self.state.save()

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
        from PIL import Image, ImageDraw, ImageFont

        # Create icon
        def make_icon(status: str = "active") -> Image.Image:
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)

            # Background circle
            if status == "active":
                color = (34, 139, 34, 255)  # Green
            elif status == "working":
                color = (255, 165, 0, 255)  # Orange
            else:
                color = (139, 0, 0, 255)  # Red

            d.ellipse((4, 4, 60, 60), fill=color)

            # "T" letter
            try:
                font = ImageFont.truetype("arial.ttf", 36)
            except ImportError:
                font = ImageFont.load_default()
            d.text((24, 14), "T", font=font, fill=(255, 255, 255, 255))

            return img

        # Menu callbacks
        def on_open_ui(icon, item):
            webbrowser.open(f"http://127.0.0.1:{self.port}/")

        def on_start_server(icon, item):
            self.server.start()
            self._update_icon(icon)

        def on_stop_server(icon, item):
            self.server.stop()
            self._update_icon(icon)

        def on_restart_server(icon, item):
            self.server.restart()
            self._update_icon(icon)

        def on_toggle_auto_start(icon, item):
            if is_auto_start_enabled():
                disable_auto_start()
                self.state.auto_start_enabled = False
            else:
                enable_auto_start()
                self.state.auto_start_enabled = True
            self.state.save()

        def on_toggle_super_user(icon, item):
            self.state.super_user_mode = not self.state.super_user_mode
            self.state.save()

        def on_open_logs(icon, item):
            log_path = str(_LOG_FILE)
            if sys.platform == "win32":
                os.startfile(log_path)  # type: ignore[attr-defined]
            else:
                webbrowser.open(f"file:///{log_path}")

        def on_quit(icon, item):
            self.stop()
            icon.stop()

        # Build menu
        pystray = self._pystray
        menu_items = [
            pystray.MenuItem("Open Thomas", on_open_ui, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Start Server", on_start_server, visible=lambda i: not self.server.is_running()),
            pystray.MenuItem("Stop Server", on_stop_server, visible=lambda i: self.server.is_running()),
            pystray.MenuItem("Restart Server", on_restart_server),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Auto-start with Windows",
                on_toggle_auto_start,
                checked=lambda i: is_auto_start_enabled(),
            ),
            pystray.MenuItem(
                "Super-user mode",
                on_toggle_super_user,
                checked=lambda i: self.state.super_user_mode,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Logs", on_open_logs),
            pystray.MenuItem("Quit", on_quit),
        ]

        menu = pystray.Menu(*menu_items)

        # Create and run icon
        self._icon = pystray.Icon(
            "Thomas",
            make_icon("active"),
            "Thomas Active",
            menu,
        )

        # Update icon periodically
        def update_icon_loop():
            while not self._stop_event.is_set():
                time.sleep(5)
                if self._icon:
                    self._update_icon(self._icon)

        threading.Thread(target=update_icon_loop, daemon=True).start()

        # Run (blocking)
        self._icon.run()

    def _update_icon(self, icon) -> None:
        """Update tray icon based on status."""
        if self._pystray is None:
            return

        from PIL import Image, ImageDraw, ImageFont

        status = "active" if self.server.is_running() else "stopped"

        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        if status == "active":
            color = (34, 139, 34, 255)  # Green
            tooltip = "Thomas Active"
        else:
            color = (139, 0, 0, 255)  # Red
            tooltip = "Thomas Stopped"

        d.ellipse((4, 4, 60, 60), fill=color)

        try:
            font = ImageFont.truetype("arial.ttf", 36)
        except ImportError:
            font = ImageFont.load_default()
        d.text((24, 14), "T", font=font, fill=(255, 255, 255, 255))

        icon.icon = img
        icon.title = tooltip

    # ------------------------------------------------------------------
    # Healthcheck & Notifications
    # ------------------------------------------------------------------

    def _healthcheck_loop(self) -> None:
        """Periodic healthcheck and auto-restart."""
        while not self._stop_event.is_set():
            time.sleep(HEALTHCHECK_INTERVAL_S)

            if self._stop_event.is_set():
                return

            # Check if server process is alive and the port is serving.
            if not self.server.is_healthy():
                if not self.server.is_running():
                    # Our subprocess is dead.  Before trying to restart, wait
                    # a moment and check if something else took over the port
                    # (e.g. user re-ran run-ui.ps1 with updated code).
                    time.sleep(2)
                    if self.server._port_is_live():
                        log.info(
                            "Port %d taken over by another instance; " "this tray agent is now stale â€” exiting.",
                            self.port,
                        )
                        self._stop_event.set()
                        if self._icon:
                            self._icon.stop()
                        return

                    # Port is free and our process died â€” attempt restart.
                    log.warning("Server process died and port is free; restarting...")
                    time.sleep(RESTART_DELAY_S)
                    if self._stop_event.is_set():
                        return
                    # Re-check once more â€” the user may have started a new
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
                    # Process alive but port not responding â€” could be
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
        agent._pystray = None  # Force headless mode
    try:
        agent.run()
    except KeyboardInterrupt:
        agent.stop()


if __name__ == "__main__":
    run_tray_agent()
