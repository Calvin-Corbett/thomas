"""A concurrent second look stops when the check can no longer use its verdict."""

from __future__ import annotations

import contextvars
import os
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from thomas.core import contained_process

_cancel: contextvars.ContextVar[threading.Event | None] = contextvars.ContextVar("review_cancel", default=None)
POLL_S = 0.1


class Cancelled(RuntimeError):
    """The owning check failed or ended before this second look was needed."""


def cancel_current() -> None:
    """Stop this hand-in's concurrent reviewer when its check cannot use the verdict."""
    event = _cancel.get()
    if event is not None:
        event.set()


def is_cancelled() -> bool:
    event = _cancel.get()
    return event is not None and event.is_set()


def check_cancelled() -> None:
    if is_cancelled():
        raise Cancelled("the check no longer needs this second look")


@contextmanager
def cancellable() -> Iterator[threading.Event]:
    """Share cancellation through nested jobs and the copied reviewer context."""
    event = _cancel.get()
    if event is not None:
        yield event
        return
    event = threading.Event()
    token = _cancel.set(event)
    try:
        yield event
    finally:
        event.set()
        _cancel.reset(token)


def _stop(process: subprocess.Popen[str]) -> None:
    # Only the process tree created below belongs to this job.
    if os.name == "nt":
        if process.poll() is not None:
            return
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
        if process.poll() is None:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run(
    fallback: Callable[..., subprocess.CompletedProcess[str]],
    command: Sequence[str],
    *,
    timeout: float,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """Use ordinary run outside a job; inside one, reap a cancelled reviewer tree."""
    if _cancel.get() is None:
        return fallback(command, timeout=timeout, **kwargs)
    check_cancelled()
    text = kwargs.pop("input", None)
    kwargs.pop("capture_output", None)
    kwargs.pop("check", None)
    flags = kwargs.pop("creationflags", 0)
    options: dict[str, Any] = (
        {"creationflags": flags | contained_process._CREATE_SUSPENDED | contained_process._CREATE_NO_WINDOW}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    started = time.monotonic()
    with tempfile.TemporaryFile() as prompt, tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        if text is not None:
            prompt.write(text.encode(kwargs.get("encoding") or "utf-8") if isinstance(text, str) else text)
        prompt.seek(0)
        process = subprocess.Popen(command, stdin=prompt, stdout=output, stderr=errors, **options, **kwargs)
        job = None
        try:
            if os.name == "nt":
                job = contained_process.OwnedWindowsJob(process)
                contained_process._resume(process)
            while True:
                check_cancelled()
                left = timeout - (time.monotonic() - started)
                if left <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                try:
                    process.communicate(timeout=min(POLL_S, left))
                    output.seek(0)
                    errors.seek(0)
                    stdout, stderr = output.read(), errors.read()
                    if kwargs.get("text") or kwargs.get("encoding") or kwargs.get("universal_newlines"):
                        encoding = kwargs.get("encoding") or "utf-8"
                        handling = kwargs.get("errors") or "strict"
                        stdout, stderr = stdout.decode(encoding, handling), stderr.decode(encoding, handling)
                        stdout = stdout.replace("\r\n", "\n").replace("\r", "\n")
                        stderr = stderr.replace("\r\n", "\n").replace("\r", "\n")
                    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    continue
        except BaseException:
            try:
                if job is not None:
                    job.close()
                else:
                    _stop(process)
            finally:
                if process.poll() is None:
                    process.kill()
                try:
                    process.communicate(timeout=1)
                except subprocess.TimeoutExpired:
                    # Output is file-backed; inherited handles cannot hold a pipe drain open.
                    for stream in (process.stdin, process.stdout, process.stderr):
                        if stream is not None:
                            stream.close()
            raise
        finally:
            if job is not None:
                job.close()
            elif os.name != "nt":
                _stop(process)
