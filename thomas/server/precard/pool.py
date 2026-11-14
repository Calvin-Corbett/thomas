"""One pool of pytest processes for every check on this machine (spec 2026-10-12 Part 1 item 1), and its off switch.

P, the most pytest processes all checks together run at once, is the smaller of all CPU threads
and the memory left after the machine's reserve divided by one shard's measured size (16 on a 16-thread, 32 GiB
machine with an 800 MiB shard budget). Each shard takes a place from the machine-wide ledger (:mod:`thomas.server.capacity_ledger`, kind
``"shard"``) before it starts, limited to the smallest P any live server process recorded there
(:func:`capacity_ledger.pool_size`), so the caged server's checks and your own server's share one P, and waiting
shards go fewest files first. Each shard's peak committed memory and working set are measured and kept under their
own key (:func:`machine_capacity.record_check_shard_peak`); a confirmation re-run is not, a shard that did not finish
(crashed, stopped or never started) is not, and a peak that cannot be written never costs a shard its result. A shard
out of time takes its whole process tree down with it, so a test's leftover child holding the output open cannot keep
the shard's place in the pool. A ledger that cannot be read or written gives no place: that shard is not started,
never run unreserved, and answers :data:`REFUSED` (its own code, apart from a command that would not launch). Everything
here blocks (file locks, retries): it runs in a check's worker threads, never on the server's event loop.

``THOMAS_PRECARD_PARALLEL=off`` turns this off: a check runs its tests the earlier way, without the ledger, one check
at a time. Both servers need the same setting: a server with it off reserves nothing in the ledger, so the other
server's admissions see its checks only in the free disk they measure.

:class:`Waits` adds up how long a check's shards and re-runs waited for a place and how long they ran once they had
one, so a check that ran out of time mostly waiting is told from one whose tests took the time.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
import subprocess
import threading
import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from thomas.core import machine_capacity, machine_load
from thomas.server import capacity_ledger, green_checkout
from thomas.server.proof.deadline import Deadline
from thomas.server.proof.environment import NOT_STARTED, REFUSED, TIMED_OUT, run_quietly
from thomas.server.proof.runner import _RAN as _FINISHED  # pytest's own exits that mean the session ran: 0, 1, 5
from thomas.server.proof.runner import Run

log = logging.getLogger(__name__)
PARALLEL_ENV = "THOMAS_PRECARD_PARALLEL"
_OFF = frozenset({"off", "0", "false", "no"})
SHARD_KIND = "shard"
SAMPLE_S = 0.5
_MIB = 1024**2
_DRAIN_S = 10.0  # after a kill, how long to wait for the rest of the output before giving up on it
LOAD_WAIT_S = 600.0  # the longest a shard waits for this PC to drop under the load limit before it asks anyway
LINE_POLL_S = 1.0  # how often a shard waiting in the line of test runs asks for its turn
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def parallel() -> bool:
    """False when THOMAS_PRECARD_PARALLEL is off, 0, false or no: the earlier runner, one check at a time."""
    return str(os.environ.get(PARALLEL_ENV) or "").strip().lower() not in _OFF


def size(*, cpus: int | None = None, total_ram_bytes: int | None = None, shard_mb: int | None = None) -> int:
    """P: every CPU thread, or the shards that fit after the memory reserve, whichever is fewer."""
    threads = max(1, int(cpus if cpus is not None else (os.cpu_count() or 1)))
    total = total_ram_bytes if total_ram_bytes is not None else machine_capacity._memory()[0]
    per_shard = max(1, int(shard_mb if shard_mb is not None else machine_capacity.check_shard_mb())) * _MIB
    cpu_term = threads
    if total is None:
        return cpu_term
    usable = max(0, int(total) - machine_capacity._reserve_bytes(int(total)))
    return max(1, min(cpu_term, usable // per_shard))


class _ProcessTable:
    """Every process's parent, read once and shared by every shard this server watches for :data:`SAMPLE_S`.

    Each shard's watcher looked at its tree every half second with ``children(recursive=True)``, and on Windows every
    such call lists every process on the machine (~25 ms of CPU, measured 2026-11-06 with ~800 processes). A check
    worker with 8 to 15 live shards then spent 0.38 of a core watching them, against 0.09 with none, half of what the
    shards themselves used. One list per half second, shared, costs the same however many shards there are.
    """

    def __init__(self, ttl_s: float) -> None:
        self._lock = threading.Lock()
        self._ttl_s = ttl_s
        self._at = float("-inf")
        self._children: dict[int, list[int]] = {}

    def descendants(self, psutil_mod: Any, pid: int) -> list[int] | None:
        """Every process under *pid*, from a list at most ``ttl_s`` old; None when this psutil cannot list parents."""
        ppid_map = getattr(getattr(psutil_mod, "_psplatform", None), "ppid_map", None)
        if ppid_map is None:
            return None
        with self._lock:
            now = time.monotonic()
            if now - self._at >= self._ttl_s:
                try:
                    pairs = ppid_map()
                except (OSError, AttributeError, TypeError, ValueError):
                    return None
                children: dict[int, list[int]] = {}
                for child, parent in pairs.items():
                    if child != parent:
                        children.setdefault(parent, []).append(child)
                self._children, self._at = children, now
            children = self._children
        found: list[int] = []
        todo, visited = [pid], {pid}
        while todo:
            for child in children.get(todo.pop(), ()):
                if child not in visited:
                    visited.add(child)
                    found.append(child)
                    todo.append(child)
        return found


_TABLE = _ProcessTable(SAMPLE_S)


def _tree(psutil_mod: Any, root: Any, seen: dict[int, Any]) -> list[Any]:
    """*root* and every process under it: from the shared table, else psutil's own walk.

    A process counts only if it started no earlier than *root* (psutil's own guard against a reused process id), and
    one already in *seen* is reused while it still runs, so each process is opened once.
    """
    gone = getattr(psutil_mod, "Error", OSError)
    found = _TABLE.descendants(psutil_mod, root.pid)
    if found is None:
        return [root, *root.children(recursive=True)]
    born = root.create_time()
    tree = [root]
    for pid in found:
        known = seen.get(pid)
        try:
            process = known if known is not None and known.is_running() else psutil_mod.Process(pid)
            if process.create_time() >= born:
                tree.append(process)
        except gone:
            continue
    return tree


def _sample(psutil_mod: Any, pid: int, peaks: dict[str, float], seen: dict[int, Any]) -> None:
    """Fold the process tree's committed memory and working set into *peaks* (MiB); keep each process in *seen*."""
    gone = getattr(psutil_mod, "Error", OSError)
    try:
        root = psutil_mod.Process(pid)
        tree = _tree(psutil_mod, root, seen)
    except gone:
        return
    committed = working = 0.0
    for process in tree:
        seen.setdefault(process.pid, process)
        try:
            info = process.memory_info()
        except gone:
            continue
        committed += float(getattr(info, "peak_pagefile", 0) or getattr(info, "private", 0) or info.rss)
        working += float(getattr(info, "peak_wset", 0) or info.rss)
    peaks["committed"] = max(peaks["committed"], committed / _MIB)
    peaks["working_set"] = max(peaks["working_set"], working / _MIB)


def _kill_tree(psutil_mod: Any, pid: int, seen: dict[int, Any]) -> None:
    """Kill *pid*, every process now under it, and every process seen under it earlier that still runs.

    The ones seen earlier count too: pytest-timeout ends pytest with ``os._exit``, which leaves its children running
    with the output pipe open. psutil refuses to kill a process whose id another process has taken since it was seen.
    """
    gone = getattr(psutil_mod, "Error", OSError)
    found = dict(seen)
    try:
        root = psutil_mod.Process(pid)
        found.setdefault(pid, root)
        found.update({child.pid: child for child in root.children(recursive=True)})
    except gone:
        pass
    for process in found.values():
        try:
            process.kill()
        except gone:
            continue


def run_measured(
    command: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout_s: float, sample_s: float = SAMPLE_S
) -> tuple[int, str, float, float]:
    """``run_quietly``, plus the peak committed memory and working set of the process tree, in MiB (0 without psutil).

    Out of time, the whole tree is killed, and the rest of its output is waited for at most :data:`_DRAIN_S` seconds.
    """
    try:
        import psutil
    except ImportError:
        code, output = run_quietly(command, cwd=cwd, env=env, timeout_s=timeout_s)
        return code, output, 0.0, 0.0
    try:
        process = subprocess.Popen(
            list(command), cwd=str(cwd), env=dict(env), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
        )  # fmt: skip
    except (OSError, ValueError) as exc:
        return NOT_STARTED, f"it could not be started: {exc}", 0.0, 0.0
    peaks = {"committed": 0.0, "working_set": 0.0}
    seen: dict[int, Any] = {}
    done = threading.Event()

    def watch() -> None:
        while True:
            _sample(psutil, process.pid, peaks, seen)
            if done.wait(sample_s):
                return

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        output, _ = process.communicate(timeout=timeout_s)
        code = process.returncode
    except subprocess.TimeoutExpired:
        done.set()
        watcher.join(timeout=5)  # its last look at the tree is in *seen* before the kill
        _kill_tree(psutil, process.pid, seen)
        code, output = TIMED_OUT, f"it did not finish within {timeout_s:g}s"
        try:
            process.communicate(timeout=_DRAIN_S)
        except subprocess.TimeoutExpired:  # a process outside the tree holds the output: give up on it, keep going
            log.warning("a shard's output stayed open %g s after it was stopped: %s", _DRAIN_S, list(command)[:4])
    finally:
        done.set()
        watcher.join(timeout=5)
    return code, output or "", peaks["committed"], peaks["working_set"]


class Waits:
    """One check's shard-seconds: waiting for a place in the pool, and running once it had one, summed over its shards.

    Every thread of the check adds to it, so the two sums can pass the check's wall time; their ratio is what counts.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.waited_s = 0.0
        self.ran_s = 0.0

    def add(self, *, waited: float = 0.0, ran: float = 0.0) -> None:
        with self._lock:
            self.waited_s += max(0.0, float(waited))
            self.ran_s += max(0.0, float(ran))

    def mostly_waited(self) -> bool:
        """More of the shards' time went to waiting for places than to running: the pool was busy."""
        with self._lock:
            return self.waited_s > 0.0 and self.waited_s > self.ran_s


def _give_back(line: Any, ticket: int) -> None:
    """Give a shard's place in the line of test runs back; a line that cannot be written never fails the shard."""
    try:
        line.leave(ticket)
    except (sqlite3.Error, OSError):
        log.warning("a check shard could not give back its place in the line of test runs", exc_info=True)


def runner(deadline: Deadline | None, *, files: int, record_peaks: bool = True, waits: Waits | None = None) -> Run:
    """A ``run`` for :func:`proof.run_tests` and :func:`proof.run_one` that takes a place in the pool first.

    A shard that cannot get a place by the deadline answers :data:`TIMED_OUT` with the deadline passed, which the
    runner reads as out of time: the check is unavailable, never failed. A place the ledger refuses before the deadline
    (no room that waiting could free, or a wait that ended early) and a ledger that cannot be used (an ``OSError``:
    unreadable, busy, or locked too long) give no place either, and a shard never runs without one: it answers
    :data:`REFUSED` with the reason, a run that did not happen (``ProofRun.ran`` is False and its files are in
    ``ProofRun.not_started``), never "no one else is running". *files* is the check's selected file count, its place in
    line. One shard's memory and this server's P are read once, here, not for every shard. *waits*, when given, gets
    each shard's wait for its place and its run (:class:`Waits`).
    """
    shard_mb = machine_capacity.check_shard_mb()
    own = size(shard_mb=shard_mb)
    tally = waits.add if waits is not None else (lambda **_seconds: None)

    def run(command: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout_s: float) -> tuple[int, str]:
        where = green_checkout.green_root()
        asked = time.monotonic()
        # A shard fills cores: it waits while this PC is over the limit before it even asks for a place, so it holds
        # no place while it waits, and never longer than LOAD_WAIT_S or the check's own deadline.
        room_s = LOAD_WAIT_S if deadline is None else max(0.0, min(LOAD_WAIT_S, deadline.remaining() - 60.0))
        machine_load.wait_for_room(max_wait_s=room_s, label="check shard")
        # A little past the deadline, so a shard refused for time is refused after it has passed, never just before;
        # read after the wait for room, which spent part of it.
        wait_s = deadline.remaining() + 0.1 if deadline is not None else None
        with contextlib.ExitStack() as place:  # only taking the place is guarded: the shard's own errors are its own
            try:
                place.enter_context(
                    capacity_ledger.admitted(
                        f"shard:{uuid.uuid4().hex}",
                        kind=SHARD_KIND,
                        files=files,
                        memory_bytes=shard_mb * _MIB,
                        where=where,
                        limit=capacity_ledger.pool_size(own),  # one P for every server: the smallest recorded
                        wait_s=wait_s,
                    )
                )
            except capacity_ledger.NotAdmitted as why:
                tally(waited=time.monotonic() - asked)
                words = f"no place in the pool of test processes: {why}"
                # Out of time only when the deadline has passed. A place refused before it (nothing running could give
                # room back, or the wait ended early) is a shard that did not start, never "the change broke the run".
                return (TIMED_OUT, words) if deadline is not None and deadline.passed else (REFUSED, words)
            except OSError as why:  # a ledger that cannot be used is not an empty one: no place, so no shard
                tally(waited=time.monotonic() - asked)
                log.warning("a check shard was not started: the pool's reservation ledger could not be used: %s", why)
                return (
                    REFUSED,
                    f"the pool's reservation ledger could not be used, so the shard did not start: {why}",
                )
            # The same line as the Builds' own test runs (machine_load.Line), so together they keep this PC under
            # its limit. On 2026-11-13 the shards of one check timed out at 1800 s and per test beside thirteen
            # test runs of Builds, and the check said 'unavailable'. Waiting here takes nothing from timeout_s.
            turn = machine_load.line()
            if turn is not None:
                try:
                    ticket = turn.join("check shard")
                    place.callback(_give_back, turn, ticket)
                    while not turn.look(ticket)[0]:
                        if deadline is not None and deadline.passed:
                            tally(waited=time.monotonic() - asked)
                            return TIMED_OUT, deadline.words()
                        time.sleep(LINE_POLL_S)
                except (sqlite3.Error, OSError) as why:  # bookkeeping never stops a shard
                    log.warning("a check shard did not wait in the line of test runs: %s", why)
            started = time.monotonic()
            tally(waited=started - asked)
            left = timeout_s if deadline is None else min(timeout_s, deadline.remaining())
            if left <= 0:
                return TIMED_OUT, deadline.words() if deadline is not None else "no time was left"
            code, output, committed, working = run_measured(command, cwd=cwd, env=env, timeout_s=left)
            tally(ran=time.monotonic() - started)
        # Only a shard that finished is measured: one that crashed or was stopped early has no shard's peak.
        if record_peaks and committed > 0 and code in _FINISHED:
            try:
                machine_capacity.record_check_shard_peak(committed, working)
            except OSError:  # the profile was busy or could not be written: bookkeeping never fails a shard
                log.warning("a check shard's memory peak could not be recorded", exc_info=True)
        return code, output

    return run


__all__ = ["PARALLEL_ENV", "SAMPLE_S", "SHARD_KIND", "Waits", "parallel", "run_measured", "runner", "size"]
