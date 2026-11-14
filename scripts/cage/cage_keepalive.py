"""Keeps the cage's way out running: the egress proxy and the caged server.

The caged Thomas reaches its models only through the egress proxy, which lives in
the promoter service (promoter_service.py, the ThomasSelfChangePromoter task,
started at your sign-in). From 2026-09-23 21:51 to 2026-09-24 11:10 that process
was gone and nothing brought it back: every model call from the caged server
failed. The ThomasCageKeepalive task (enable_cage_keepalive.ps1) runs this as you
every 15 minutes, and it writes one line per thing it does:

* nothing listens on 127.0.0.1:8897 -> run the ThomasSelfChangePromoter task;
* nothing listens on 127.0.0.1:8898 -> run the ThomasCagedServer task, unless
  - that task is disabled or not registered;
  - the off switch ``C:\\ProgramData\\ThomasCage\\caged_server.off`` exists. Create
    that file (any content) when you stop the caged server on purpose, so it stays
    stopped; delete it to let this start the server again;
  - a tracked .py file the server loads from this checkout -- thomas/,
    scripts/cage/, scripts/monolith_source_loader.py, scripts/breakglass_auth.py --
    differs from HEAD, staged or not, and Python cannot read it as code. A
    half-written file must not start. One that loads does not stop it: the
    server that just stopped was running it, and from 2026-11-09 the restart
    watcher no longer waits for such files, so refusing here would leave the
    server down after every restart (07:04 to 08:02 that day, for 38 files).
    Uncommitted work elsewhere (scripts/forge/, scripts/crew/) does not stop it.
* after asking Task Scheduler to run a task it waits up to 30 seconds for the port,
  and says "port now listening" only when it is.
* a server run request whose Last Run Time is unchanged on the next pass is
  followed by /End then /Run if its port is still dead. An advanced Last Run Time
  is evidence of a start, not a reason to end a slow server.

A reason to leave the server stopped (the off switch, a disabled or missing task)
is said once, not every 15 minutes. Nothing is printed when both ports are up.
Exit 0 when everything is up, started or stopped on purpose; 1 when something
stays down. Standard library only, so any Python can run it.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CAGE_ROOT = Path(os.environ.get("THOMAS_CAGE_ROOT") or r"C:\ProgramData\ThomasCage")
PROXY_PORT = 8897
SERVER_PORT = 8898
PROMOTER_TASK = "ThomasSelfChangePromoter"
SERVER_TASK = "ThomasCagedServer"
SERVER_CODE = ("thomas", "scripts/cage", "scripts/monolith_source_loader.py", "scripts/breakglass_auth.py")
START_WAIT_S = 30.0
# Under pythonw there is no console, so every console program started without this
# opens a window of its own on your screen.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def listening(port: int, host: str = "127.0.0.1", timeout_s: float = 0.5) -> bool:
    """Whether something accepts a connection on host:port right now.

    A listener on loopback accepts at once; Windows takes about two seconds to
    refuse a closed port, so a short timeout reads as nothing listening.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def modified_server_code(repo: Path) -> list[str]:
    """Tracked .py files the caged server loads that differ from HEAD. RuntimeError when git cannot say."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "diff", "--name-only", "-z", "HEAD", "--", *SERVER_CODE],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        creationflags=NO_WINDOW,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip() or f"git exited {proc.returncode}")
    return [path for path in proc.stdout.split("\0") if path.endswith(".py")]


def cannot_load(repo: Path, paths: list[str]) -> list[str]:
    """Which of these files Python cannot read as code; a file that is gone is not one of them."""
    broken: list[str] = []
    for path in paths:
        try:
            compile((repo / path).read_bytes(), path, "exec", dont_inherit=True)
        except FileNotFoundError:
            continue
        except (SyntaxError, ValueError, OSError):
            broken.append(path)
    return broken


def _schtasks(*args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["schtasks", *args], capture_output=True, text=True, errors="replace", timeout=60, creationflags=NO_WINDOW
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, str(exc)
    return proc.returncode, f"{proc.stdout}\n{proc.stderr}"


def run_task(name: str) -> tuple[int, str]:
    """Ask Task Scheduler to run *name* now: (exit code, what schtasks said)."""
    code, said = _schtasks("/Run", "/TN", name)
    return code, " ".join(said.split())


def task_state(name: str) -> str | None:
    """Task Scheduler's status for *name* ("Ready", "Running", "Disabled", ...), or None when it is not registered."""
    code, said = _schtasks("/Query", "/TN", name, "/FO", "CSV", "/NH")
    rows = [row for row in csv.reader(said.splitlines()) if len(row) >= 3]
    return rows[0][2].strip() if code == 0 and rows else None


@dataclass(frozen=True)
class TaskReport:
    status: str
    last_run_time: str
    last_result: str

    def describe(self) -> str:
        return f"status={self.status!r}, last run time={self.last_run_time!r}, last result={self.last_result!r}"


def task_report(name: str) -> TaskReport | None:
    """Read the verbose CSV fields, including quoted commas in scheduler dates."""
    code, said = _schtasks("/Query", "/TN", name, "/V", "/FO", "CSV", "/NH")
    rows = [row for row in csv.reader(said.splitlines()) if len(row) >= 7]
    if code != 0 or not rows:
        return None
    row = rows[0]
    return TaskReport(row[3].strip(), row[5].strip(), row[6].strip())


def end_task(name: str) -> tuple[int, str]:
    code, said = _schtasks("/End", "/TN", name)
    return code, " ".join(said.split())


def _waiter(probe: Callable[[int], bool], sleep: Callable[[float], None], clock: Callable[[], float]):
    def wait(port: int) -> bool:
        deadline = clock() + START_WAIT_S
        while True:
            if probe(port):
                return True
            if clock() >= deadline:
                return False
            sleep(1.0)

    return wait


class _Once:
    """Says a reason to leave something stopped once, and again only when it changes."""

    def __init__(self, memory: Path | None, say: Callable[[str], object]) -> None:
        self.memory, self.say = memory, say
        try:
            self.said = json.loads(memory.read_text(encoding="utf-8")) if memory else {}
        except (OSError, ValueError):
            self.said = {}

    def tell(self, key: str, line: str | None) -> None:
        if line is not None and self.said.get(key) != line:
            self.say(line)
        if self.said.get(key) == line:
            return
        self.remember(key, line)

    def remember(self, key: str, value: object) -> None:
        self.said[key] = value
        if self.memory is not None:
            try:
                self.memory.write_text(json.dumps(self.said), encoding="utf-8")
            except OSError:
                pass


def _start(what: str, port: int, task: str, *, state, run, wait) -> tuple[bool, str]:
    """Ask Task Scheduler for *task* and look at *port* again: (listening now, the line to say)."""
    head = f"{what}: nothing listens on 127.0.0.1:{port}"
    status = state(task)
    if status is None:
        return False, f"{head}; not started: {task} is not registered"
    if status == "Disabled":
        return False, f"{head}; not started: {task} is disabled"
    if status == "Running":
        return False, (
            f"{head}, but Task Scheduler still shows {task} running, so a run request would be ignored;"
            f" nothing was ended -- after `schtasks /End /TN {task}` the next pass can start it"
        )
    code, said = run(task)
    if code != 0:
        return False, f"{head}; could not start {task} (schtasks exit {code}: {said})"
    if wait(port):
        return True, f"{head}; started {task} (port now listening)"
    return False, f"{head}; asked Task Scheduler to run {task}; nothing listens on {port} after {START_WAIT_S:g} s"


def _start_server(*, status, details, end, run, wait, once) -> tuple[bool, str]:
    snapshot = details(SERVER_TASK)
    previous = once.said.get("server_run")
    diagnostic = f"; Task Scheduler: {snapshot.describe()}" if snapshot else "; Task Scheduler details unavailable"
    recovery = ""
    if isinstance(previous, str) and snapshot and snapshot.last_run_time:
        if previous != snapshot.last_run_time:
            once.remember("server_run", None)
            return False, (
                "server: nothing listens on 127.0.0.1:8898; Last Run Time advanced since the run request;"
                " nothing was ended" + diagnostic
            )
        code, said = end(SERVER_TASK)
        recovery = f"; Last Run Time unchanged since the run request; /End exit {code}: {said}"
        if code != 0:
            return False, "server: could not end ThomasCagedServer" + recovery + diagnostic
        status = "Ready"
        once.remember("server_run", None)

    def request(task: str) -> tuple[int, str]:
        code, said = run(task)
        if code == 0 and snapshot and snapshot.last_run_time:
            once.remember("server_run", snapshot.last_run_time)
        return code, said

    up, line = _start("server", SERVER_PORT, SERVER_TASK, state=lambda _: status, run=request, wait=wait)
    if up:
        once.remember("server_run", None)
    after = details(SERVER_TASK)
    if after:
        diagnostic += f"; Task Scheduler after: {after.describe()}"
    return up, line + recovery + diagnostic


def keep_alive(
    *,
    repo: Path = REPO_ROOT,
    probe: Callable[[int], bool] = listening,
    modified: Callable[[Path], list[str]] = modified_server_code,
    run: Callable[[str], tuple[int, str]] = run_task,
    state: Callable[[str], str | None] = task_state,
    details: Callable[[str], TaskReport | None] = task_report,
    end: Callable[[str], tuple[int, str]] = end_task,
    say: Callable[[str], object] = print,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    off_switch: Path | None = None,
    memory: Path | None = None,
) -> int:
    """One pass. 0 when everything is up, started or stopped on purpose; 1 when something stays down."""
    wait = _waiter(probe, sleep, clock)
    down = False
    if not probe(PROXY_PORT):
        up, line = _start("proxy", PROXY_PORT, PROMOTER_TASK, state=state, run=run, wait=wait)
        down = not up
        say(line)
    once = _Once(memory, say)
    if probe(SERVER_PORT):
        once.tell("server", None)
        if once.said.get("server_run") is not None:
            once.remember("server_run", None)
        return 1 if down else 0
    head = f"server: nothing listens on 127.0.0.1:{SERVER_PORT}; not started"
    status = state(SERVER_TASK)
    switch = off_switch if off_switch is not None else CAGE_ROOT / "caged_server.off"
    why = {None: f"{SERVER_TASK} is not registered", "Disabled": f"{SERVER_TASK} is disabled"}.get(status)
    if switch.exists():
        why = f"the off switch {switch} is there"
    if why:
        once.remember("server_run", None)
        once.tell("server", f"{head}: {why}; left stopped")
        return 1 if down else 0
    once.tell("server", None)
    try:
        changed = modified(repo)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        say(f"{head}: git could not list changes ({exc})")
        return 1
    broken = cannot_load(repo, changed)
    if broken:
        listed = ", ".join(broken[:5]) + (", ..." if len(broken) > 5 else "")
        say(f"{head}: {len(broken)} file(s) being edited cannot be loaded yet ({listed})")
        return 1
    up, line = _start_server(status=status, details=details, end=end, run=run, wait=wait, once=once)
    say(line)
    return 1 if down or not up else 0


def _writer(log: Path | None) -> Callable[[str], None]:
    """Each line to the console when there is one, and appended to *log* with the time."""

    def say(line: str) -> None:
        if sys.stdout is not None:
            print(line)
        if log is not None:
            stamp = datetime.now().astimezone().isoformat(timespec="seconds")
            with log.open("a", encoding="utf-8") as out:
                out.write(f"{stamp} {line}\n")

    return say


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restart the cage's egress proxy and caged server when they are down.")
    parser.add_argument("--repo", default=str(REPO_ROOT), help="the checkout the caged server loads its code from")
    parser.add_argument("--log", default="", help="append each line to this file too (pythonw has no console)")
    args = parser.parse_args(argv)
    memory = CAGE_ROOT / "keepalive.state.json" if CAGE_ROOT.is_dir() else None
    return keep_alive(repo=Path(args.repo), say=_writer(Path(args.log) if args.log else None), memory=memory)


if __name__ == "__main__":
    raise SystemExit(main())
