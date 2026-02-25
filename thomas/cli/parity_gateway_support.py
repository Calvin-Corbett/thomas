"""Gateway/process/network helper functions for CLI parity commands."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

import click

from thomas.cli.parity_support import (
    gateway_state_file,
    load_gateway_state,
    write_json,
)
from thomas.core.config import AppConfig


def parse_json_file(path: Path) -> Any:
    return __import__("json").loads(path.read_text(encoding="utf-8-sig"))


def is_pid_running(pid: int) -> bool:
    if int(pid) <= 0:
        return False
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}"],
            capture_output=True,
            text=True,
            check=False,
        )
        text = str(out.stdout or "").lower()
        if "no tasks are running" in text:
            return False
        return str(int(pid)) in text
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def kill_pid(pid: int) -> bool:
    if int(pid) <= 0:
        return False
    if os.name == "nt":
        out = subprocess.run(
            ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        return int(out.returncode or 1) == 0
    try:
        os.kill(int(pid), signal.SIGTERM)
        return True
    except Exception:
        return False


def port_in_use(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=0.35):
            return True
    except OSError:
        return False


def find_free_port(host: str, preferred: int, max_offset: int = 25) -> Optional[int]:
    for candidate in range(int(preferred), int(preferred) + int(max_offset) + 1):
        if not port_in_use(host, candidate):
            return candidate
    return None


def resolve_bind_port(host: str, port: int, auto_port: bool) -> int:
    selected = int(port)
    if port_in_use(host, selected):
        if not auto_port:
            raise click.ClickException(
                f"Port {selected} is busy. Re-run with --auto-port or choose a different --port."
            )
        free_port = find_free_port(host, selected)
        if free_port is None:
            raise click.ClickException(f"No free port found in range {selected}..{selected + 25}.")
        click.echo(f"Port {selected} is busy; auto-selecting {free_port}.")
        selected = int(free_port)
    return selected


def http_get_json(url: str, timeout_s: float = 2.0, token: str = "") -> dict[str, Any]:
    json = __import__("json")
    headers = {}
    token_val = str(token or "").strip()
    if token_val:
        headers["Authorization"] = f"Bearer {token_val}"
    req = urllib.request.Request(url=url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            status = int(getattr(resp, "status", 0) or 0)
            body = resp.read().decode("utf-8", errors="replace")
        payload: Any
        try:
            payload = json.loads(body)
        except Exception:
            payload = {"raw": body[:2000]}
        return {"ok": True, "status": status, "payload": payload}
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        payload: Any
        try:
            payload = json.loads(body) if body else {}
        except Exception:
            payload = {"raw": body[:2000]}
        return {"ok": False, "status": int(getattr(e, "code", 0) or 0), "error": str(e), "payload": payload}
    except Exception as e:
        return {"ok": False, "status": 0, "error": f"{type(e).__name__}: {e}", "payload": {}}


def probe_gateway(host: str, port: int, *, token: str = "") -> dict[str, Any]:
    base = f"http://{host}:{int(port)}"
    tcp_ok = port_in_use(host, int(port))
    version = http_get_json(f"{base}/api/version", token=token)
    models = http_get_json(f"{base}/api/models", token=token)
    engines = http_get_json(f"{base}/api/engines", token=token)
    healthy = bool(tcp_ok and (version.get("ok") or models.get("ok")))
    return {
        "host": host,
        "port": int(port),
        "base_url": base,
        "tcp_open": bool(tcp_ok),
        "version": version,
        "models": models,
        "engines": engines,
        "healthy": healthy,
    }


def save_gateway_state(config: AppConfig, payload: dict[str, Any]) -> None:
    write_json(gateway_state_file(config), payload)


def clear_gateway_state(config: AppConfig) -> None:
    path = gateway_state_file(config)
    if path.exists():
        path.unlink(missing_ok=True)


def active_gateway_target(
    config: AppConfig,
    host: Optional[str],
    port: Optional[int],
) -> tuple[str, int, dict[str, Any]]:
    state = load_gateway_state(config)
    state_host = str(state.get("host") or "").strip()
    state_port_raw = state.get("port")
    state_port = int(state_port_raw) if isinstance(state_port_raw, int) else 0
    if host:
        use_host = str(host).strip()
    elif state_host:
        use_host = state_host
    else:
        use_host = "127.0.0.1"
    if port is not None:
        use_port = int(port)
    elif state_port > 0:
        use_port = int(state_port)
    else:
        use_port = 8899
    return use_host, use_port, state


def gateway_spawn(
    *,
    config_path: str,
    host: str,
    port: int,
    log_path: Path,
) -> subprocess.Popen[Any]:
    cmd: list[str] = [sys.executable, "-m", "thomas.cli.main"]
    cfg = str(config_path or "").strip()
    if cfg:
        cmd.extend(["-c", cfg])
    cmd.extend(["serve", "--host", str(host), "--port", str(int(port))])

    log_path.parent.mkdir(parents=True, exist_ok=True)
    out = log_path.open("a", encoding="utf-8")
    creationflags = 0
    if os.name == "nt":
        creationflags = int(getattr(subprocess, "DETACHED_PROCESS", 0)) | int(
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    return subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=out,
        stderr=out,
        close_fds=True,
        creationflags=creationflags,
    )


__all__ = [
    "active_gateway_target",
    "clear_gateway_state",
    "gateway_spawn",
    "is_pid_running",
    "kill_pid",
    "parse_json_file",
    "probe_gateway",
    "resolve_bind_port",
    "save_gateway_state",
]
