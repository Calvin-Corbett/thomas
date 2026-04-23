from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path


def _reserve_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_server_ready(base_url: str, *, timeout_seconds: float = 60.0) -> None:
    deadline = time.monotonic() + max(1.0, timeout_seconds)
    url = f"{base_url.rstrip('/')}/api/session/new"
    payload = json.dumps({}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
                status = int(getattr(response, "status", 0) or 0)
                if 200 <= status < 500:
                    return
        except (urllib.error.URLError, OSError, TimeoutError, ConnectionError) as exc:
            last_error = str(exc)
            time.sleep(1.0)
    raise RuntimeError(f"Timed out waiting for Thomas API server at {base_url}: {last_error}")


@contextmanager
def isolated_thomas_server(
    workspace_root: Path,
    benchmark_home: Path,
    *,
    extra_env: Mapping[str, str] | None = None,
):
    port = _reserve_local_port()
    base_url = f"http://127.0.0.1:{port}"
    server_log = benchmark_home / "thomas_server.log"
    server_log.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    existing_pythonpath = str(env.get("PYTHONPATH") or "").strip()
    pythonpath_parts = [str(workspace_root)]
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    for key, value in dict(extra_env or {}).items():
        env[str(key)] = str(value)

    cmd = [
        sys.executable,
        "-m",
        "thomas.server",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--config",
        str(workspace_root / "thomas.toml"),
        "--data-dir",
        str(benchmark_home / "api-data"),
        "--profile",
        "benchmark",
    ]
    log_handle = server_log.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        cwd=str(workspace_root),
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_server_ready(base_url)
        yield base_url
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        log_handle.close()
