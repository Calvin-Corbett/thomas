"""Ports, processes and child commands for BootDoctor.

Recovery runs unattended, often from a process with no console of its own; a
console child of such a process opens a visible window unless told not to, so
every child started here goes through ``_NO_WINDOW``.
"""

from __future__ import annotations

import os
import re
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

_NO_WINDOW = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0
# Who holds a port is asked of netstat and PowerShell, which a stuck machine can leave waiting. No answer reads as
# "owner unknown", which never names a Thomas process and so never stops anything.
_LOOKUP_TIMEOUT_S = 10.0

_EXE_NAME = re.compile(r"""([^\\/"]+?\.(?:exe|com|bat|cmd))\b""", re.IGNORECASE)


def _is_port_listening(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except KeyboardInterrupt:
        return False
    except OSError:
        return False


def _bootdoctor_sleep(seconds: float) -> None:
    deadline = time.monotonic() + max(0.0, float(seconds or 0.0))
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        try:
            time.sleep(min(remaining, 0.25))
        except KeyboardInterrupt:
            continue


def _listening_pids_windows(port: int) -> list[int]:
    """PIDs listening on the port; empty when netstat fails or does not answer in time (owner unknown)."""
    cmd = ["netstat", "-ano", "-p", "tcp"]
    try:
        out = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            timeout=_LOOKUP_TIMEOUT_S,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    pids: list[int] = []
    for raw in str(out.stdout or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        proto, local, remote, state, pid_raw = parts[0], parts[1], parts[2], parts[3], parts[4]
        # netstat translates the state name (ABHOEREN, ECOUTE, ...), so a listener is told by its remote end, which
        # is always port 0; LISTENING is still accepted.
        if proto.upper() != "TCP" or not (remote.rsplit(":", 1)[-1] == "0" or state.upper() == "LISTENING"):
            continue
        if not local.endswith(f":{int(port)}"):
            continue
        try:
            pid = int(pid_raw)
        except ValueError:
            continue
        if pid > 0 and pid not in pids:
            pids.append(pid)
    return pids


def _pid_cmdline(pid: int) -> str:
    try:
        import psutil  # type: ignore
    except ImportError:
        psutil = None
    if psutil is not None:
        try:
            proc = psutil.Process(int(pid))
            try:
                return " ".join(proc.cmdline()).strip()
            except psutil.Error:
                return str(proc.name() or "").strip()
        except psutil.Error:
            pass

    if os.name == "nt":
        ps_cmd = (
            f'(Get-CimInstance Win32_Process -Filter "ProcessId={int(pid)}" '
            "| Select-Object -ExpandProperty CommandLine)"
        )
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                errors="replace",
                check=False,
                timeout=_LOOKUP_TIMEOUT_S,
                creationflags=_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return str(out.stdout or "").strip()
    return ""


def _is_thomas_cmdline(cmdline: str) -> bool:
    s = str(cmdline or "").lower()
    if not s:
        return False
    patterns = (
        r"-m\s+thomas(\.server)?(\s+serve)?\b",
        r"-m\s+thomas\.tray_agent\b",
        r"\bthomas(\.exe)?\s+serve\b",
    )
    return any(re.search(pat, s) for pat in patterns)


def process_name(cmdline: str) -> str:
    """The program's file name from a command line, without its folders or arguments.

    A command line can carry paths, user names and tokens, so reports name the program and stop there.
    """
    text = str(cmdline or "").strip()
    match = _EXE_NAME.search(text)
    if match:
        return match.group(1).strip()
    first = text.split(None, 1)[0].strip('"') if text else ""
    return Path(first).name


def thomas_owns_port(port: int) -> bool:
    """True when a program listening on the port is a Thomas process.

    A Thomas that is still starting has bound its port but does not answer HTTP yet. Only Windows lists the
    owner (netstat); elsewhere this is False.
    """
    if os.name != "nt":
        return False
    return any(_is_thomas_cmdline(_pid_cmdline(pid)) for pid in _listening_pids_windows(int(port)))


def port_owner_note(port: int) -> str:
    """Say what holds the port, so a foreign listener is not mistaken for Thomas.

    Only the program's file name is reported: a command line can carry paths and tokens, and this text goes into
    the report file and to the configured model.
    """
    pids = _listening_pids_windows(int(port)) if os.name == "nt" else []
    if not pids:
        return "the owning program could not be identified"
    notes: list[str] = []
    for pid in pids[:3]:
        cmdline = _pid_cmdline(pid)
        kind = "a Thomas process" if _is_thomas_cmdline(cmdline) else "not a Thomas process"
        notes.append(f"PID {pid} ({process_name(cmdline) or 'name unavailable'}) is {kind}")
    return "held by " + "; ".join(notes)


def _kill_pid(pid: int) -> bool:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
                creationflags=_NO_WINDOW,
            )
            return True
        os.kill(int(pid), signal.SIGTERM)
        return True
    except (OSError, ValueError):
        return False


def _run_cmd(cmd: list[str], *, cwd: Path, timeout_s: float = 60.0) -> tuple[bool, str]:
    try:
        out = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return False, f"{type(e).__name__}: {e}"

    ok = int(out.returncode or 0) == 0
    detail = (out.stdout or "") + ("\n" + out.stderr if out.stderr else "")
    detail = detail.strip()
    if not detail:
        detail = f"exit={out.returncode}"
    if len(detail) > 2000:
        detail = detail[:2000] + "\n... (truncated)"
    return ok, detail


def _spawn_thomas_server(
    *,
    py_exe: Path,
    root: Path,
    host: str,
    port: int,
    stdout: Any,
) -> subprocess.Popen[str]:
    kwargs: dict[str, Any] = {
        "cwd": str(root),
        "stdout": stdout,
        "stderr": subprocess.STDOUT,
        "text": True,
    }
    if _NO_WINDOW:
        kwargs["creationflags"] = _NO_WINDOW
    return subprocess.Popen(
        [str(py_exe), "-m", "thomas.server", "--host", str(host), "--port", str(int(port))],
        **kwargs,
    )
