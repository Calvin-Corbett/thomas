"""The check before your card in its own process, so the server stays free while it runs (2026-10-27).

Python runs one thread at a time in a process. With every check inside the server, five at once held its one core at
95 to 98% on 2026-10-27: health answered in 60 to 120 s, and every request and team waited behind them. Here each
check is a child process with its own core. The settle thread that asked for it waits for it on the check threads,
so the count the landed-code drain waits on still counts it; its timing notes come back with its verdict; it is
ended when this server stops, and it ends itself, and its tests, when this server is gone.

The check runs in this process as before under pytest (unless ``THOMAS_PRECARD_WORKER=on``), with
``THOMAS_PRECARD_WORKER=off``, and when the parallel check is off: ``slot.one_at_a_time`` is a lock in this process,
and only this process can keep checks to one at a time.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import subprocess
import sys
import threading
import time
from typing import IO, Any

from thomas.server.precard import check, clocks, handover, pool, workers

log = logging.getLogger(__name__)

WORKER_ENV = "THOMAS_PRECARD_WORKER"
_OFF = frozenset({"off", "0", "false", "no"})
RESULT_MARK = "THOMAS-PRECARD-RESULT "
POLL_S = 2.0
# The check keeps its own limits: up to ADMISSION_WAIT_S for its turn, then its deadline. Past both and this grace,
# its process is ended rather than waited on forever. The deadline alone and the grace (4,500 s) ended checks that had
# waited for their turn before their hour was up (2026-10-27).
GRACE_S = 900.0
DEADLINE_S = check.ADMISSION_WAIT_S + check.CHECK_DEADLINE_S + GRACE_S
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def separate() -> bool:
    """Whether a check runs in its own process."""
    chosen = str(os.environ.get(WORKER_ENV) or "").strip().lower()
    if chosen in _OFF:
        return False
    if os.environ.get("PYTEST_CURRENT_TEST") and chosen != "on":
        return False
    return pool.parallel()


def check_for_hand_in(execution_id: str, *, processes_ended: bool = False) -> check.Checked:
    """:func:`handover.check_for_hand_in`, in its own process when :func:`separate`. Never raises."""
    if not separate():
        return handover.check_for_hand_in(execution_id, processes_ended=processes_ended)
    argv = [sys.executable, "-m", "thomas.server.precard.worker_process", str(execution_id)]
    if processes_ended:
        argv.append("--processes-ended")
    return run(argv)


def run(argv: list[str], *, deadline_s: float = DEADLINE_S) -> check.Checked:
    """Run one check process to its verdict; end it when this server stops or it outlives *deadline_s*."""
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
        )
    except OSError as exc:
        return _unavailable(f"the check's own process would not start: {exc}", costly=True)
    out: list[str] = []
    err: list[str] = []
    readers = [_reader(proc.stdout, out), _reader(proc.stderr, err)]
    while True:
        try:
            proc.wait(timeout=POLL_S)
            break
        except subprocess.TimeoutExpired:
            if workers.generation_stopping():
                _end(proc)
                return _unavailable("this server is stopping", costly=False)
            if time.monotonic() - started > deadline_s:
                _end(proc)
                return _unavailable(f"its own process ran past {int(deadline_s)} s and was ended", costly=False)
    for reader in readers:
        reader.join(timeout=10)
    result = _result("".join(out))
    if result is None:
        tail = " ".join("".join(err).split()[-60:])
        log.warning("a check process ended (exit %s) without a verdict: %s", proc.returncode, tail)
        return _unavailable(f"its own process ended (exit {proc.returncode}) without a verdict: {tail[-300:]}")
    clocks.merge(result.get("clocks") or {})
    return result["checked"]


def _reader(stream: IO[str] | None, into: list[str]) -> threading.Thread:
    def read() -> None:
        if stream is not None:
            into.append(stream.read())

    thread = threading.Thread(target=read, name="check-process-pipe", daemon=True)
    thread.start()
    return thread


def _end(proc: subprocess.Popen[str]) -> None:
    from thomas.tools.shell_spool import kill_process_tree

    kill_process_tree(proc.pid)
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        log.warning("check process %s did not end after its tree was killed", proc.pid)


def _result(output: str) -> dict[str, Any] | None:
    """The verdict line a check process printed last, or None."""
    for line in reversed(output.splitlines()):
        if line.startswith(RESULT_MARK):
            try:
                payload = json.loads(line[len(RESULT_MARK) :])
                fields = {field.name for field in dataclasses.fields(check.Checked)}
                checked = check.Checked(**{k: v for k, v in payload["checked"].items() if k in fields})
            except (ValueError, KeyError, TypeError):
                return None
            return {"checked": checked, "clocks": payload.get("clocks") or {}}
    return None


def _unavailable(why: str, *, costly: bool = True) -> check.Checked:
    return check._unavailable(why, cause="incomplete" if costly else "busy", costly=costly)


def _watch_parent(parent: int) -> None:
    """End this check, and every test it started, when the server that asked for it is gone."""
    import psutil

    try:
        born = psutil.Process(parent).create_time()
    except psutil.Error:
        os._exit(3)

    def watch() -> None:
        while True:
            time.sleep(POLL_S)
            try:
                alive = psutil.Process(parent).create_time() == born
            except psutil.Error:
                alive = False
            if not alive:
                for child in psutil.Process().children(recursive=True):
                    try:
                        child.kill()
                    except psutil.Error:
                        pass
                os._exit(3)

    threading.Thread(target=watch, name="check-parent-watch", daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python -m thomas.server.precard.worker_process <execution_id> [--processes-ended]")
        return 2
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    if argv is None:
        _watch_parent(os.getppid())
    with clocks.collecting() as observed:
        checked = handover.check_for_hand_in(args[0], processes_ended="--processes-ended" in args[1:])
    payload = {"checked": dataclasses.asdict(checked), "clocks": observed}
    sys.stdout.write(RESULT_MARK + json.dumps(payload, default=str) + "\n")
    sys.stdout.flush()
    return 0


__all__ = ["RESULT_MARK", "WORKER_ENV", "check_for_hand_in", "main", "run", "separate"]


if __name__ == "__main__":
    raise SystemExit(main())
