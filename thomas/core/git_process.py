"""One way to run git, with a timeout that is actually an upper bound.

``subprocess.run(["git", ...], timeout=N)`` looks like it bounds the call. It
does not. On a timeout, ``run`` kills the process it started and then drains the
pipes -- and draining waits for every writer to close them. Git on Windows is
commonly reached through a launcher (``Git\\cmd\\git.exe``) that spawns the real
git as a grandchild; the grandchild inherits the pipe handles, killing the
launcher does not touch it, and the drain blocks until it finishes on its own.

Measured 2026-09-24 (``git log --all -p -n 600`` on this checkout):

* ``mingw64\\bin\\git.exe``: 13.76 s untimed; with ``timeout=0.3`` it returned
  after 0.32 s -- the bound held, because that is the real binary.
* ``cmd\\git.exe``: 12.27 s untimed; with ``timeout=0.3`` it returned after
  12.29 s -- the bound did nothing at all.

So a caller that set a 2-second timeout could still be gone for twelve seconds,
and every timeout in the server was decoration. :func:`run_git` closes that by
bounding the drain too: after the kill it waits a short grace period, and if the
pipes are still held it abandons the process to a reaper thread and returns. The
caller is back within ``timeout + grace``, always.

Being off the event loop is the other half, and it is not this module's job --
see ``thomas/core/event_loop_offload.py``. A bounded blocking call on the loop
still blocks the loop for its bound.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Default bound for a read-only query against a warm repository.
DEFAULT_TIMEOUT_S = 15.0
# How long to wait for the pipes after the kill before abandoning the process.
DRAIN_GRACE_S = 0.5
# Reported in place of an exit status when the call was abandoned. Chosen so the
# usual ``returncode != 0`` test in callers treats it as the failure it is.
TIMED_OUT_RETURNCODE = -9

# Concurrent git spawns allowed across the process. Git is disk-bound here, and
# a burst of them (one measured path asked for about 200 for a single page) turns
# into a thread-pool queue and a thrashing disk rather than parallel speed. Set
# generously: this is a guard against a pathological burst, not a throttle on
# ordinary use, and a warm read here costs well under a tenth of a second.
_DEFAULT_MAX_CONCURRENT = 8
# Longest a caller waits for a free slot before being told git is saturated.
_SLOT_WAIT_S = 20.0


def _max_concurrent() -> int:
    raw = str(os.environ.get("THOMAS_GIT_MAX_CONCURRENT", "") or "").strip()
    try:
        value = int(raw) if raw else _DEFAULT_MAX_CONCURRENT
    except ValueError:
        value = _DEFAULT_MAX_CONCURRENT
    return max(1, min(32, value))


# Global spawn permit pool -- initialized at import, because a git call can happen
# before the server boots (build identity, project validation) and the ceiling has
# to hold then too. Every acquire is released in run_git's finally, so there is
# nothing to shut down.
_spawn_slots = threading.BoundedSemaphore(_max_concurrent())


# Every git call needs these settings: read-only status must not refresh the
# live checkout's index, and server processes must not wait for a credential prompt.
_BASE_ENV = {
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
}


@dataclass(frozen=True)
class GitResult:
    """What one git invocation produced, including why it stopped."""

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    seconds: float
    # True when git never started at all -- no binary on PATH, a working
    # directory that is gone, no handle available. Callers distinguish this from
    # "git ran and said no", because the two mean different things to a person:
    # one is a broken install, the other is an answer.
    spawn_failed: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.spawn_failed

    def output(self) -> str:
        """stdout, stripped -- the reading most callers want."""
        return (self.stdout or "").strip()

    def message(self) -> str:
        """The best available explanation of a failure, for a caller to report."""
        detail = (self.stderr or self.stdout or "").strip()
        if self.timed_out:
            return detail or f"git did not finish within its {self.seconds:.1f}s bound"
        return detail or f"exit {self.returncode}"


class _GitEnvironment(dict[str, str]):
    """A real process environment whose mock-call representation hides secrets."""

    def __repr__(self) -> str:
        return "<git environment (values redacted)>"


def git_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """A redacted-in-repr environment with mandatory lock and prompt settings."""
    env = _GitEnvironment(os.environ)
    if extra:
        env.update({str(key): str(value) for key, value in extra.items()})
    env.update(_BASE_ENV)
    return env


def _abandon(proc: subprocess.Popen[str]) -> None:
    """Hand a process that would not let go of its pipes to a reaper thread.

    The thread is what makes the bound real: the caller returns now, and the
    handles are still closed properly whenever the grandchild finally exits, so
    abandoning does not leak.
    """

    def reap() -> None:
        # Named, not broad: the process is already killed, so the only faults
        # available here are a handle that is gone (OSError) or one the reader
        # threads closed first (ValueError: I/O operation on closed file).
        try:
            proc.wait()
        except (OSError, ValueError):
            pass
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass

    threading.Thread(target=reap, name="git-reap", daemon=True).start()


def run_git(
    args: list[str] | tuple[str, ...],
    *,
    cwd: str | Path | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    slot_wait: float | None = None,
    env: dict[str, str] | None = None,
    git_binary: str = "git",
) -> GitResult:
    """Run ``git <args>`` under a bound the caller can rely on.

    Once a spawn slot is free this returns within ``timeout`` +
    :data:`DRAIN_GRACE_S`, whatever git leaves holding the pipes. Waiting for
    that slot is bounded separately, and being unable to get one is reported the
    same way a timeout is.

    ``slot_wait`` caps that queueing for a caller working to a deadline of its
    own: a health probe with two seconds of budget left wants to be told git is
    busy, not to wait :data:`_SLOT_WAIT_S` for a turn it can no longer use.

    Git process failures return a :class:`GitResult` with a non-zero
    ``returncode`` and a ``stderr`` that says what happened. Unexpected faults
    from the process interface can still raise. Callers that need to fail closed
    check ``result.ok`` and report ``result.message()``.
    """
    argv = [git_binary, *(str(arg) for arg in args)]
    bound = max(0.1, float(timeout))
    started = time.monotonic()
    # The slot wait is bounded too, or the promise above would only cover the part
    # of the wait this function can see. A caller that cannot get a slot is told
    # so rather than queueing behind a 120-second custodian sweep forever.
    slot_bound = max(0.1, float(slot_wait)) if slot_wait is not None else max(bound, _SLOT_WAIT_S)
    if not _spawn_slots.acquire(timeout=slot_bound):
        return GitResult(
            TIMED_OUT_RETURNCODE,
            "",
            f"git was not run: {_max_concurrent()} git processes were already in flight",
            True,
            time.monotonic() - started,
        )
    try:
        try:
            proc = subprocess.Popen(  # noqa: S603 - fixed argv, never a shell
                argv,
                cwd=str(cwd) if cwd is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                # No caller here feeds git anything, and a server process has no
                # terminal to inherit -- so give git nothing to read rather than
                # a handle it could wait on.
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=git_env(env),
            )
        except (OSError, ValueError) as exc:
            # git absent from PATH, cwd gone, no handle available, or an invalid
            # argument combination. Named rather than broad: a bug in this
            # module still shows its face.
            return GitResult(1, "", f"{type(exc).__name__}: {exc}", False, time.monotonic() - started, True)

        try:
            stdout, stderr = proc.communicate(timeout=bound)
            return GitResult(int(proc.returncode or 0), stdout or "", stderr or "", False, time.monotonic() - started)
        except subprocess.TimeoutExpired:
            pass
        except (OSError, ValueError) as exc:
            _abandon(proc)
            return GitResult(1, "", f"{type(exc).__name__}: {exc}", False, time.monotonic() - started)

        _kill_quietly(proc)
        try:
            stdout, stderr = proc.communicate(timeout=DRAIN_GRACE_S)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            # The pipes are held by something we did not start -- the launcher's
            # grandchild. This is the exact case that made every timeout in the
            # server a lie; the caller gets its answer now regardless.
            _abandon(proc)
            log.warning("git %s exceeded its %.1fs bound and was abandoned", " ".join(argv[1:3]), bound)
            return GitResult(
                TIMED_OUT_RETURNCODE,
                "",
                f"git did not finish within {bound:.1f}s and was abandoned",
                True,
                time.monotonic() - started,
            )
        return GitResult(TIMED_OUT_RETURNCODE, stdout or "", stderr or "", True, time.monotonic() - started)
    finally:
        _spawn_slots.release()


def _kill_quietly(proc: subprocess.Popen[str]) -> None:
    try:
        proc.kill()
    except OSError:
        pass


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "DRAIN_GRACE_S",
    "TIMED_OUT_RETURNCODE",
    "GitResult",
    "git_env",
    "run_git",
]
