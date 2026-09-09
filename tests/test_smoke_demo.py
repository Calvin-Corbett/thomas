from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

_API_KEY_ENV_VARS = (
    "THOMAS_MODELS_OPENAI_API_KEY",
    "THOMAS_MODELS_ANTHROPIC_API_KEY",
    "THOMAS_MODELS_GEMINI_API_KEY",
    "THOMAS_MODELS_XAI_API_KEY",
    "THOMAS_MODELS_OPENROUTER_API_KEY",
)


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _terminate_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass


def _wait_for_health(
    base_url: str,
    proc: subprocess.Popen[str],
    output_path: Path,
    timeout_s: float = 180.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    url = f"{base_url}/api/health"
    last_error = "unreachable"

    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                payload = json.loads(body or "{}")
                if resp.status == 200 and isinstance(payload, dict) and "status" in payload:
                    return payload
                last_error = f"unexpected status {resp.status}"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(0.25)

    try:
        output_tail = output_path.read_text(encoding="utf-8", errors="replace")[-3000:]
    except OSError:
        output_tail = ""

    raise AssertionError(
        f"Demo server failed to become healthy at {url}; last_error={last_error}; output_tail={output_tail}"
    )


def test_demo_server_no_key_boot_contract_windows_safe(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    data_root = (tmp_path / ".thomas").resolve()
    demo_root = data_root / "demo"
    stale_marker = demo_root / "stale-marker.txt"

    demo_root.mkdir(parents=True, exist_ok=True)
    stale_marker.write_text("stale", encoding="utf-8")

    env = os.environ.copy()
    for key in _API_KEY_ENV_VARS:
        env.pop(key, None)
    env["PYTHONUNBUFFERED"] = "1"

    port = _pick_free_port()
    cmd = [
        sys.executable,
        "-m",
        "thomas.server",
        "--demo",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--data-dir",
        str(data_root),
    ]

    # Write child output to a FILE, not a pipe: nothing drains a pipe while we
    # poll health, so a chatty boot fills the OS pipe buffer and the server
    # blocks mid-boot on a print — deadlocking the test until its timeout.
    output_path = tmp_path / "demo-server-output.log"
    with output_path.open("w", encoding="utf-8", errors="replace") as output_file:
        proc = subprocess.Popen(
            cmd,
            cwd=str(repo_root),
            env=env,
            stdout=output_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
    try:
        payload = _wait_for_health(f"http://127.0.0.1:{port}", proc, output_path, timeout_s=180.0)
        assert "status" in payload
        assert demo_root.exists()
        assert not stale_marker.exists()
    finally:
        _terminate_process(proc)
