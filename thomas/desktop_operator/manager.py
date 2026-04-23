from __future__ import annotations

import atexit
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .client import DesktopOperatorClient
from .contracts import DESKTOP_OPERATOR_SERVICE_ID
from .host_service import get_global_desktop_host_service
from .runtime import resolve_artifacts_dir
from .vm import DesktopVmBootstrap, create_vm_supervisor, resolve_vm_context


class DesktopOperatorServiceManager:
    def __init__(self, *, artifacts_dir: Path | None = None) -> None:
        self.service_id = DESKTOP_OPERATOR_SERVICE_ID
        self.artifacts_dir = (artifacts_dir or resolve_artifacts_dir()).resolve()
        self.process: subprocess.Popen[Any] | None = None
        self.base_url = ""
        self.token = ""
        self.last_error: str | None = None
        self.vm_context = resolve_vm_context()
        self.connection_mode = "local_process"
        self.vm_bootstrap: DesktopVmBootstrap | None = None
        atexit.register(self.stop)

    def start(self) -> DesktopOperatorServiceManager:
        if self.process is not None and self.process.poll() is None and self.base_url and self.token:
            return self
        self.stop()
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

        if self.vm_context.isolated:
            supervisor = create_vm_supervisor(self.vm_context, artifacts_dir=self.artifacts_dir)
            bootstrap = supervisor.ensure_ready()
            self.vm_bootstrap = bootstrap
            if bootstrap.helper_ready:
                self.base_url = bootstrap.helper_base_url.rstrip("/")
                self.token = bootstrap.helper_token
                self.connection_mode = "remote_vm"
                client = self.client()
                deadline = time.time() + 15.0
                while time.time() < deadline:
                    try:
                        client.health()
                        self.last_error = None
                        return self
                    except Exception as exc:  # noqa: BLE001
                        self.last_error = type(exc).__name__
                        time.sleep(0.25)
                self.stop()
                raise RuntimeError("Desktop operator remote helper failed to become healthy.")
            if bootstrap.launch_mode == "dev_loopback":
                return self._start_local_helper()
            self.last_error = bootstrap.refusal_reason or "Desktop VM helper is not ready."
            raise RuntimeError(self.last_error)

        self.vm_bootstrap = None
        return self._start_local_helper()

    def _start_local_helper(self) -> DesktopOperatorServiceManager:
        port = _find_free_port()
        token = secrets.token_urlsafe(32)
        cmd = [
            sys.executable,
            "-m",
            "thomas.desktop_operator.helper_main",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--token",
            token,
            "--artifact-dir",
            str(self.artifacts_dir),
            "--vm-id",
            self.vm_context.vm_id,
            "--vm-provider",
            self.vm_context.provider,
            "--vm-mode",
            self.vm_context.isolation_mode,
        ]
        if self.vm_context.isolated:
            cmd.append("--isolated")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(  # noqa: S603
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )
        self.base_url = f"http://127.0.0.1:{port}"
        self.token = token
        self.connection_mode = "local_process"
        client = self.client()
        deadline = time.time() + 8.0
        while time.time() < deadline:
            if self.process.poll() is not None:
                break
            try:
                client.health()
                self.last_error = None
                return self
            except Exception as exc:  # noqa: BLE001
                self.last_error = type(exc).__name__
                time.sleep(0.15)
        self.stop()
        raise RuntimeError("Desktop operator helper failed to start.")

    def stop(self) -> None:
        proc = self.process
        self.process = None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except Exception:  # noqa: BLE001
                proc.kill()
        self.base_url = ""
        self.token = ""

    def client(self) -> DesktopOperatorClient:
        if not self.base_url or not self.token:
            raise RuntimeError("Desktop operator helper is not running.")
        return DesktopOperatorClient(base_url=self.base_url, token=self.token)

    def ensure_client(self) -> DesktopOperatorClient:
        self.start()
        return self.client()

    def _viewer_snapshot(self) -> dict[str, Any]:
        bootstrap = self.vm_bootstrap.to_dict() if self.vm_bootstrap is not None else {}
        mode = (
            str(bootstrap.get("viewer_mode") or getattr(self.vm_context, "viewer_mode", "none") or "none").strip()
            or "none"
        )
        url = str(bootstrap.get("viewer_url") or getattr(self.vm_context, "viewer_url", "") or "").strip()
        label = str(bootstrap.get("viewer_label") or getattr(self.vm_context, "viewer_label", "") or "").strip()
        command = str(bootstrap.get("viewer_command") or "").strip()
        takeover_supported = bool(
            bootstrap.get("viewer_takeover_supported")
            if "viewer_takeover_supported" in bootstrap
            else getattr(self.vm_context, "viewer_takeover_supported", False)
        )
        available = bool(url or command or mode not in {"", "none"})
        return {
            "mode": mode,
            "url": url,
            "label": label,
            "command": command,
            "takeover_supported": takeover_supported,
            "available": available,
        }

    def status_snapshot(self) -> dict[str, Any]:
        running = bool(self.base_url) and (
            self.connection_mode == "remote_vm" or (self.process is not None and self.process.poll() is None)
        )
        viewer = self._viewer_snapshot()
        host_posture = (
            get_global_desktop_host_service()
            .status(
                viewer_fallback=viewer,
                vm_bootstrap=self.vm_bootstrap,
            )
            .to_dict()
        )
        payload: dict[str, Any] = {
            "service_id": self.service_id,
            "running": running,
            "base_url": self.base_url if running else "",
            "last_error": self.last_error,
            "active_session": None,
            "vm": self.vm_context.to_dict(),
            "vm_bootstrap": self.vm_bootstrap.to_dict() if self.vm_bootstrap is not None else None,
            "viewer": viewer,
            "connection_mode": self.connection_mode,
            "host_posture": host_posture,
            "installation_state": host_posture.get("installation_state") or "not_enabled",
            "session_target": host_posture.get("session_target") or "local_vm",
            "trust_mode": host_posture.get("trust_mode") or "ask_every_time",
            "reboot_required": bool(host_posture.get("reboot_required")),
            "relogin_required": bool(host_posture.get("relogin_required")),
        }
        if running:
            try:
                payload.update(self.client().status())
            except Exception as exc:  # noqa: BLE001
                payload["last_error"] = type(exc).__name__
        return payload


_GLOBAL_MANAGER: DesktopOperatorServiceManager | None = None


def get_global_desktop_operator_manager() -> DesktopOperatorServiceManager:
    global _GLOBAL_MANAGER
    if _GLOBAL_MANAGER is None:
        _GLOBAL_MANAGER = DesktopOperatorServiceManager()
    return _GLOBAL_MANAGER


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
