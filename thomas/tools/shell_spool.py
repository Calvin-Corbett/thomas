"""Spooled subprocess execution: streaming reads, hang detection, kill-and-retry.

Runs a command with ``subprocess.Popen``, pumping stdout/stderr incrementally
(no single blocking ``communicate()``) into both:

- an on-disk **spool file** that always holds the *complete* output, no matter
  how large, so nothing is lost when the inline result is truncated; and
- in-memory buffers used to build the inline (possibly truncated) result.

A monitor loop watches the stream activity timestamp. If the process is still
running but has produced no output for ``idle_timeout`` seconds, the whole
process **tree** is killed (Windows-safe via ``taskkill /T /F``; POSIX via a
process-group kill thanks to ``start_new_session``) and the attempt is marked
``hung``. Hung attempts are retried up to ``hang_retries`` times, and every
hang is recorded as a :class:`HangEvent` (idle seconds + killed pid) so the
caller has kill-and-retry evidence.

This module intentionally depends only on the standard library (tools layer
rule: no imports from agent/server/cli).
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

logger = logging.getLogger(__name__)

_READ_CHUNK = 65536
_POLL_INTERVAL = 0.05
_PUMP_JOIN_TIMEOUT = 5.0

OUTCOME_COMPLETED = "completed"
OUTCOME_HUNG = "hung"
OUTCOME_TIMEOUT = "timeout"
OUTCOME_NOT_FOUND = "not_found"


@dataclass
class HangEvent:
    """Evidence for one detected hang: which attempt, how idle, which pid died."""

    attempt: int
    idle_seconds: float
    killed_pid: int


@dataclass
class SpoolResult:
    """Outcome of a spooled run (final attempt's streams + full hang history).

    Attributes:
        outcome: One of ``completed``, ``hung``, ``timeout``, ``not_found``.
        exit_code: Final attempt's exit code (kill codes for hung/timeout runs).
        stdout: Final attempt's decoded stdout (complete, un-truncated).
        stderr: Final attempt's decoded stderr (complete, un-truncated).
        spool_path: On-disk file holding the complete raw output of every
            attempt (attempts separated by a retry marker line).
        attempts: Total attempts made (1 = no retry was needed).
        hang_events: One entry per detected hang, in order.
    """

    outcome: str
    exit_code: int | None
    stdout: str
    stderr: str
    spool_path: str
    attempts: int
    hang_events: list[HangEvent] = field(default_factory=list)


@dataclass
class _AttemptResult:
    outcome: str
    exit_code: int | None
    stdout: str
    stderr: str
    idle_seconds: float = 0.0
    killed_pid: int = 0


def kill_process_tree(pid: int) -> None:
    """Kill a process and all of its descendants (Windows- and POSIX-safe)."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError) as e:
        logger.warning("killpg failed for pid %s (%s); falling back to kill", pid, e)
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            logger.warning("fallback kill failed for pid %s; process may be gone", pid)


def _pump_stream(
    stream: IO[bytes],
    spool_handle: IO[bytes],
    buffer: bytearray,
    lock: threading.Lock,
    activity: dict[str, float],
) -> None:
    """Incrementally drain one pipe into the spool file and an in-memory buffer."""
    while True:
        chunk = stream.read1(_READ_CHUNK)  # type: ignore[attr-defined]
        if not chunk:
            break
        with lock:
            try:
                spool_handle.write(chunk)
                spool_handle.flush()
            except ValueError:
                # Spool handle closed after a join timeout; keep draining the
                # pipe into memory so the child is not blocked on a full pipe.
                logger.debug("spool handle closed mid-pump; continuing in-memory only")
            buffer.extend(chunk)
            activity["ts"] = time.monotonic()


def _run_attempt(
    shell_cmd: list[str],
    cwd: str | None,
    env: dict[str, str] | None,
    timeout: float,
    idle_timeout: float,
    spool_handle: IO[bytes],
    lock: threading.Lock,
) -> _AttemptResult:
    popen_kwargs: dict[str, object] = {}
    if sys.platform != "win32":
        # Own process group so kill_process_tree can killpg the whole tree.
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        shell_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=env,
        **popen_kwargs,  # type: ignore[arg-type]
    )

    stdout_buf = bytearray()
    stderr_buf = bytearray()
    activity = {"ts": time.monotonic()}
    pumps = [
        threading.Thread(
            target=_pump_stream,
            args=(proc.stdout, spool_handle, stdout_buf, lock, activity),
            daemon=True,
            name="shell-spool-stdout",
        ),
        threading.Thread(
            target=_pump_stream,
            args=(proc.stderr, spool_handle, stderr_buf, lock, activity),
            daemon=True,
            name="shell-spool-stderr",
        ),
    ]
    for pump in pumps:
        pump.start()

    started = time.monotonic()
    outcome = OUTCOME_COMPLETED
    idle_seconds = 0.0
    killed_pid = 0
    while proc.poll() is None:
        now = time.monotonic()
        if now - started > timeout:
            outcome = OUTCOME_TIMEOUT
            killed_pid = proc.pid
            kill_process_tree(proc.pid)
            break
        idle = now - activity["ts"]
        if idle_timeout > 0 and idle > idle_timeout:
            outcome = OUTCOME_HUNG
            idle_seconds = idle
            killed_pid = proc.pid
            kill_process_tree(proc.pid)
            break
        time.sleep(_POLL_INTERVAL)

    try:
        exit_code: int | None = proc.wait(timeout=_PUMP_JOIN_TIMEOUT)
    except subprocess.TimeoutExpired:
        logger.warning("process %s did not exit after tree kill; forcing kill", proc.pid)
        proc.kill()
        exit_code = proc.wait()
    for pump in pumps:
        pump.join(timeout=_PUMP_JOIN_TIMEOUT)

    return _AttemptResult(
        outcome=outcome,
        exit_code=exit_code,
        stdout=bytes(stdout_buf).decode("utf-8", errors="replace"),
        stderr=bytes(stderr_buf).decode("utf-8", errors="replace"),
        idle_seconds=idle_seconds,
        killed_pid=killed_pid,
    )


def run_spooled_command(
    shell_cmd: list[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 30.0,
    idle_timeout: float = 120.0,
    hang_retries: int = 1,
    spool_dir: str | Path | None = None,
) -> SpoolResult:
    """Run ``shell_cmd`` with output spooling, hang detection, and retry.

    Args:
        shell_cmd: Argv list (already shell-wrapped by the caller).
        cwd: Working directory for the process.
        env: Environment for the process.
        timeout: Hard wall-clock limit per attempt, in seconds.
        idle_timeout: Kill the process tree if it produces no output for this
            many seconds while still running (0 disables hang detection).
        hang_retries: How many automatic retries after a detected hang.
        spool_dir: Directory for the spool file (defaults to a
            ``thomas_shell_spool`` folder in the system temp dir).

    Returns:
        A :class:`SpoolResult`. The spool file at ``spool_path`` holds the
        complete output of all attempts and is left on disk for retrieval.

    Raises:
        OSError: If the spool directory or file cannot be created.
    """
    spool_root = Path(spool_dir) if spool_dir is not None else Path(tempfile.gettempdir()) / "thomas_shell_spool"
    spool_root.mkdir(parents=True, exist_ok=True)
    fd, spool_path_str = tempfile.mkstemp(prefix="run-", suffix=".log", dir=str(spool_root))

    lock = threading.Lock()
    attempts = 0
    hang_events: list[HangEvent] = []
    max_attempts = 1 + max(0, int(hang_retries))

    with os.fdopen(fd, "wb") as spool_handle:
        while True:
            attempts += 1
            if attempts > 1:
                with lock:
                    spool_handle.write(f"\n[shell-spool] retry attempt {attempts} after hang\n".encode())
                    spool_handle.flush()
            try:
                attempt = _run_attempt(shell_cmd, cwd, env, timeout, idle_timeout, spool_handle, lock)
            except FileNotFoundError:
                return SpoolResult(
                    outcome=OUTCOME_NOT_FOUND,
                    exit_code=None,
                    stdout="",
                    stderr="",
                    spool_path=spool_path_str,
                    attempts=attempts,
                    hang_events=hang_events,
                )
            if attempt.outcome == OUTCOME_HUNG:
                hang_events.append(
                    HangEvent(
                        attempt=attempts,
                        idle_seconds=attempt.idle_seconds,
                        killed_pid=attempt.killed_pid,
                    )
                )
                logger.warning(
                    "shell hang detected: no output for %.1fs, killed pid %s (attempt %d/%d)",
                    attempt.idle_seconds,
                    attempt.killed_pid,
                    attempts,
                    max_attempts,
                )
                if attempts < max_attempts:
                    continue
            return SpoolResult(
                outcome=attempt.outcome,
                exit_code=attempt.exit_code,
                stdout=attempt.stdout,
                stderr=attempt.stderr,
                spool_path=spool_path_str,
                attempts=attempts,
                hang_events=hang_events,
            )
