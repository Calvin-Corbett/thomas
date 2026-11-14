"""Running the commit tool for land.py: one real run inside the slot, and one bounded dry run. Stdlib only.

Both runs write the tool's output to a file (never a pipe, which an orphaned grandchild can hold open for ever), run it in a
job object, and are bounded: the real run by what is left of the lease, a dry run by a deadline. At the lease the whole
process tree is killed, orphans included, abandoned git lock files are cleaned up if no git runs, and dev's tip is checked
for the change's key before anything is called a refusal: a landing that completed in the commit tool's last milliseconds
is a landing. The waits go in slices of a few seconds and a slice that took far longer than asked (the machine slept) is
charged as one slice, so a suspend never makes a live landing look overdue. A refusal keeps the tool's whole output in a
file under the queue root (``output/T<ticket>-<stage>.txt``) and the agent sees at least ``GATE_KEEP`` characters of the
gate's own output, so it can fix what was refused. The pre-check that uses the dry run is ``land_precheck``.
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from scripts.crew.brief import landing_proc
from scripts.crew.brief.landing_queue import Lane, Outcome
from scripts.crew.brief.landing_types import Config

BEAT_EVERY = 5.0
SLICE = 5.0
BELOW_NORMAL = 0x00004000
GATE_KEEP = 2000  # characters of a gate's own output the agent sees; the file has all of it
OUTPUT_DIR = "output"


def commit_cmd(commit: Path, args: Any, message: str, *, dry: bool) -> list[str]:
    cmd = [sys.executable, str(commit), "--message", message, "--json"]
    cmd += ["--agent", args.agent] if args.agent else []
    for path in args.include:
        cmd += ["--include", path]
    cmd += ["--allow-scope-fallback", "--fallback-reason", args.fallback_reason] if args.allow_scope_fallback else []
    return cmd + (["--dry-run"] if dry else [])


def parse_outcome(returncode: int, text: str) -> Outcome:
    """The commit tool's verdict. Any line of its output may be a warning: the LAST line that is a JSON result counts."""
    row: dict[str, Any] | None = None
    for line in reversed(text.strip().splitlines()):
        if line.startswith("{"):
            try:
                found = json.loads(line)
            except ValueError:
                continue
            if isinstance(found, dict) and "ok" in found:
                row = found
                break
    if row is None:
        return Outcome(
            returncode == 0, blocker=None if returncode == 0 else "unparsed", message=text.strip()[-GATE_KEEP:]
        )
    detail = " | ".join(
        str(x)
        for x in (
            row.get("message"),
            f"gate {row['gate_name']}: {str(row.get('gate_output') or '')[:GATE_KEEP]}" if row.get("gate_name") else "",
            row.get("next_step"),
        )
        if x
    )
    return Outcome(bool(row.get("ok")), row.get("commit_sha"), row.get("blocker_class"), detail, row.get("gate_name"))


def selected_paths(text: str) -> list[str] | None:
    """The paths the commit tool says it would stage (its JSON ``selected_paths``), or None when it did not say."""
    for line in reversed(text.strip().splitlines()):
        if line.startswith("{"):
            try:
                found = json.loads(line)
            except ValueError:
                continue
            if isinstance(found, dict) and "ok" in found:
                paths = found.get("selected_paths")
                return [str(p) for p in paths] if isinstance(paths, list) else None
    return None


def save_output(queue_root: Path, num: int, stage: str, text: str) -> str | None:
    """Keep the commit tool's whole output for ticket ``num``; the path, or None when it could not be written."""
    path = Path(queue_root) / OUTPUT_DIR / f"T{num:06d}-{stage}.txt"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError:
        return None
    return str(path)


def _discard(path: Path) -> None:
    """Delete the output file; a straggler that is being killed may hold it open for a moment."""
    for _ in range(40):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            time.sleep(0.05)


def _start(cmd: list[str], root: Path, flags: int = 0) -> tuple[subprocess.Popen[Any], landing_proc.JobTree, Path]:
    handle, name = tempfile.mkstemp(prefix="land-commit-", suffix=".log")
    with os.fdopen(handle, "w", encoding="utf-8") as sink:
        proc = landing_proc.popen(
            cmd,
            cwd=root,
            stdout=sink,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=flags,
            **landing_proc.JobTree.popen_flags(),
        )
    return proc, landing_proc.JobTree(proc), Path(name)


def _read(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    _discard(path)
    return text


def _wait_sliced(proc: subprocess.Popen[Any], budget: float, on_tick: Any = None) -> bool:
    """Wait for the process for at most ``budget`` seconds of RUN time. True when it ran out, or when ``on_tick`` answered
    true (stop now). A slice that took much longer than asked means the machine slept: it is charged as one slice."""
    left, ran = budget, 0.0
    while True:
        started = time.time()
        try:
            proc.wait(timeout=max(0.1, min(SLICE, left)))
            return False
        except subprocess.TimeoutExpired:
            pass
        took = time.time() - started
        step = SLICE if took > 6 * SLICE else took
        left, ran = left - step, ran + step
        if on_tick and on_tick(ran):
            return True
        if left <= 0:
            return True


def _stop(proc: subprocess.Popen[Any], tree: landing_proc.JobTree) -> None:
    tree.kill()  # the whole tree, orphaned grandchildren included
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:  # pragma: no cover - the OS refused; the lane's verdict still stands
        pass


def run_commit(
    cmd: list[str], lane: Lane, num: int, cfg: Config, key: str, *, root: Path, includes: Sequence[str] = ()
) -> Outcome:
    budget = lane.lease_left(num)  # the lane's lease started at the grant, not now (a few seconds ago already)
    proc, tree, out_name = _start(cmd, root)
    if not tree.assigned:
        lane.mark_unbounded(num, tree.why_not)  # loud: the lease cannot reach orphaned grandchildren on this ticket
    stop = threading.Event()
    start = landing_proc.start_time(proc.pid)
    script = str(cmd[1]) if len(cmd) > 1 else ""

    ran_box = [0.0]  # seconds the commit tool has run, as charged by the sliced wait (a sleep is not charged)

    def pump() -> None:
        while not stop.wait(BEAT_EVERY):
            lane.beat(num, "holding", proc.pid, start, child_script=script, ran=ran_box[0])

    lane.beat(num, "holding", proc.pid, start, child_script=script, ran=0.0)
    threading.Thread(target=pump, daemon=True).start()
    timed_out = False
    try:

        def tick(ran: float) -> None:
            ran_box[0] = ran
            if ran >= cfg.warn_hold:
                lane.note_overran(num, ran)

        timed_out = _wait_sliced(proc, budget, tick)
        if timed_out:
            _stop(proc, tree)
    finally:
        stop.set()
        tree.kill()  # a finished commit tool leaves nothing running: stragglers it started die with the job
        tree.close()
    text = _read(out_name)
    if timed_out:
        removed, left = landing_proc.clean_stale_locks(root, now=time.time() + landing_proc.LOCK_MIN_AGE)
        note = f" Removed abandoned git lock file(s): {', '.join(removed)}." if removed else ""
        note += f" Git lock file(s) {', '.join(left)} left because git is running." if left else ""
        sha = lane.find_landed(key, includes, True)
        if sha:
            return Outcome(
                True, sha, message=f"landed as {sha}; the commit tool was stopped at the lease just after it finished"
            )
        return Outcome(
            False,
            blocker="lease_expired",
            message=f"the commit tool ran past the {int(cfg.max_hold)}s lease and was stopped.{note}",
            output_file=save_output(lane.store.root, num, "lease", text),
        )
    out = parse_outcome(proc.returncode, text)
    if out.ok:
        return Outcome(True, out.sha or lane.find_landed(key, includes, True), out.blocker, out.message)
    sha = lane.find_landed(
        key, includes, True
    )  # a failure AFTER the branch moved (index lock, a late warning) is a landing
    if sha:
        return Outcome(
            True, sha, message=f"landed as {sha} (the commit tool reported a late failure: {out.message[:120]})"
        )
    return dataclasses.replace(out, output_file=save_output(lane.store.root, num, "refused", text))


def dry_run(
    cmd: list[str],
    root: Path,
    timeout: float,
    tick: Callable[[float], bool] | None = None,
    save: Callable[[str], str | None] | None = None,
) -> tuple[Outcome, list[str] | None, bool]:
    """One bounded dry run of the commit tool at low priority: (verdict, staged paths it reported, stopped early).

    ``tick(ran)`` is called every slice; a true answer stops the run at once (``precheck_stopped``). ``save(text)`` keeps
    the whole output of a refusal and returns where (``Outcome.output_file``)."""
    flags = BELOW_NORMAL if os.name == "nt" else 0
    proc, tree, out_name = _start(cmd, root, flags)
    asked: list[float] = []

    def on_tick(ran: float) -> bool:
        if tick is not None and tick(ran):
            asked.append(ran)
            return True
        return False

    try:
        timed_out = _wait_sliced(proc, timeout, on_tick)
        if timed_out:
            _stop(proc, tree)
    finally:
        tree.kill()
        tree.close()
    text = _read(out_name)
    if timed_out:
        if asked:
            return Outcome(False, blocker="precheck_stopped", message="the pre-check dry run was stopped"), None, True
        message = f"the pre-check dry run did not finish in {int(timeout)} s and was stopped"
        return Outcome(False, blocker="precheck_timeout", message=message), None, True
    out = parse_outcome(proc.returncode, text)
    if not out.ok and save is not None:
        out = dataclasses.replace(out, output_file=save(text))
    return out, selected_paths(text), False
