"""Thomas's checker: runs a change's tests as an account of its own, where the Build teams cannot write the answer.

Spec 2026-10-12, section 8.1. The check before your card runs as thomas-agent, the Build teams' own account, and its
result reaches the promoter as a line that account writes. A window lands changes without a card, so its tests run
here: as ``thomas-checker`` (scripts/cage/enable_window.ps1), in copies made from the commit the promoter wrote, never
a team's green, with the answer in a folder only this account can write and thomas-agent cannot read.

Each job, oldest first, is run by scripts/cage/checker_run.py: copies at its commit and at its base, the tests that
cover the changed files, each failure re-run alone on both, and a boot check that Thomas still imports. Then the answer,
once every test process has ended, and the copies removed.

An answer counts only once its completion receipt is published beside it (scripts/cage/checker_completion.py),
after every test process of the job has ended; an answer file the service did not write is answered UNAVAILABLE and
the job is never run on it (review B2).

The identity split (review B1): a change's own code must not run as this account, which writes the results and state
folders a forged answer would land in. Every test process runs as ``thomas-runner`` instead -- an account
enable_window.ps1 gives read on the repo and write only inside a job's copy, never ``jobs``, ``results`` or ``state``
(scripts/cage/checker_runner.py launches it; scripts/cage/checker_launch.py is the Windows launcher). The service
fails closed: with no such identity it answers every job UNAVAILABLE rather than run a change's tests as itself. So a
change cannot write its own PASSED or another job's; the window's second look stands as a second line.
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

if __package__ in (None, ""):  # run as a script by the ThomasChecker task
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.cage import checker_completion as cc  # noqa: E402
from scripts.cage import checker_jobs as cj  # noqa: E402
from scripts.cage import checker_runner  # noqa: E402
from scripts.cage.checker_run import (  # noqa: E402, F401 - the runner, kept importable from here
    BOOT_IMPORTS,
    JOB_DEADLINE_S,
    WORKERS,
    CopyFailed,
    Tools,
    _remove,
    boot_problem,
    make_copy,
    run_job,
)

from thomas.server import proof  # noqa: E402

log = logging.getLogger("thomas.checker")

REPO_ROOT = Path(__file__).resolve().parents[2]
KEEP_RESULTS_S = 7 * 86400.0
FENCE_EVERY_S = 3600.0


def pending_jobs(root: Path) -> list[cj.Job]:
    """Jobs without a completed answer, oldest first. An answer file alone never finishes a job (review B2). A file that is
    not a job is passed over and said once in the log."""
    jobs: list[cj.Job] = []
    folder = Path(root) / cj.JOBS
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            job = cj.Job.parse(cj.read_json(path))
        except (ValueError, OSError, RecursionError) as exc:
            log.warning("not a job, passed over: %s (%s)", path.name, exc)
            continue
        if path.stem != job.id:
            continue
        try:
            if cc.read(root, job) is not None:
                continue
        except (ValueError, OSError, RecursionError):
            pass  # damaged or unsolicited evidence is answered UNAVAILABLE by serve_once, never skipped
        jobs.append(job)
    return sorted(jobs, key=lambda job: (job.posted_at, job.id))


def serve_once(
    root: Path, repo: Path, *, python: str, tools: Tools | None = None, runner: checker_runner.Runner | None = None
) -> cj.Result | None:
    """Answer the oldest waiting job, if there is one. *runner* is the isolated test-runner identity (review B1)."""
    waiting = pending_jobs(root)
    if not waiting:
        return None
    job = waiting[0]
    log.info("checking %s (%s) %s on %s", job.id, job.kind, job.commit[:12], job.base[:12])
    if os.path.lexists(cc.result_path(root, job)) or os.path.lexists(cc.receipt_path(root, job)):
        # Something wrote an answer before the checker ran the job: an integrity fault, never a pass (review B1, B2).
        why = "an answer the checker did not write"
        result = cj.Result(
            job.id, job.kind, job.base, job.commit, job.tree, cj.UNAVAILABLE, why, finished_at=time.time()
        )
    else:
        result = run_job(job, repo=repo, copies=Path(root) / cj.COPIES, python=python, tools=tools, runner=runner)
    result = cc.publish(root, job, result)  # the answer first, its receipt last
    log.info("%s: %s %s", job.id, result.verdict, result.why)
    return result


def prune(root: Path, now: float, keep_s: float = KEEP_RESULTS_S) -> int:
    """Remove answers older than *keep_s* and copies a crash left behind. Returns how many were removed."""
    removed = 0
    for path in (Path(root) / cj.RESULTS).glob("*.json"):
        if now - path.stat().st_mtime > keep_s:
            path.unlink(missing_ok=True)
            (Path(root) / cj.STATE / cc.COMPLETED / path.name).unlink(missing_ok=True)
            removed += 1
    for place in (Path(root) / cj.COPIES).glob("*"):
        if place.is_dir() and now - place.stat().st_mtime > 86400.0:
            _remove(place)
            removed += 1
    return removed


def fence_probe(connect: Callable[..., object] = socket.create_connection) -> dict[str, object]:
    """Whether this account can reach past this machine. The window opens only when it cannot."""
    try:
        conn = connect(("1.1.1.1", 443), timeout=5)
    except OSError as exc:
        return {"fenced": True, "detail": f"no connection out: {type(exc).__name__}"}
    close = getattr(conn, "close", None)
    if callable(close):
        close()
    return {"fenced": False, "detail": "a connection to 1.1.1.1:443 went through"}


def _beat(path: Path, stop: threading.Event, every_s: float = 10.0) -> None:
    while True:
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")  # whole, so a reader never sees half a timestamp
        try:
            tmp.write_text(str(time.time()), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            # Windows refuses the replace while a reader has the file open. One refusal ended this thread three times
            # (2026-10-23/24): the checker ran on, unseen, and the window landed nothing. The next beat tries again.
            log.warning("heartbeat not written this time: %s", exc)
        if stop.wait(every_s):
            return


def _take_lock(folder: Path):
    """One checker at a time. The checker runs on Windows only (its account, task and fence are Windows')."""
    import msvcrt

    handle = open(folder / "checker.lock", "a+", encoding="utf-8")  # noqa: SIM115 - held for the process lifetime
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return None
    return handle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Thomas's changes as the checker account.")
    parser.add_argument("--repo", default=str(REPO_ROOT))
    parser.add_argument("--root", default=str(cj.CHECK_ROOT))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=3.0)
    args = parser.parse_args(argv)
    root, repo = Path(args.root), Path(args.repo)
    state = root / cj.STATE
    state.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(state / "checker.log"), level=logging.INFO, format="%(asctime)s %(message)s")
    lock = _take_lock(state)
    if lock is None:
        log.warning("another checker holds the lock; this copy exits")
        return 0
    python = proof.interpreter(repo)
    runner = checker_runner.Runner(state)  # the isolated test-runner identity (review B1); fails closed when absent
    if not runner.available():
        log.warning(
            "no isolated test-runner identity: every job is UNAVAILABLE until enable_window.ps1 sets one (%s)",
            runner.reason(),
        )
    stop = threading.Event()
    threading.Thread(target=_beat, args=(state / cj.HEARTBEAT, stop), daemon=True).start()
    fenced_at = 0.0
    try:
        while True:
            if time.time() - fenced_at > FENCE_EVERY_S:
                cj.write_json(state / cj.FENCE, {**fence_probe(), "checked_at": time.time()})
                fenced_at = time.time()
            try:
                done = serve_once(root, repo, python=python, runner=runner)
                prune(root, time.time())
            except (OSError, ValueError, RuntimeError):
                log.exception("a checker pass failed")
                done = None
            if args.once:
                return 0
            if done is None:
                time.sleep(args.interval)
    finally:
        stop.set()


if __name__ == "__main__":
    raise SystemExit(main())
