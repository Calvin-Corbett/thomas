"""``check.run``: the Build agent's narrow way to check its own work.

The builder edits files but, below guardrails ``open``, has no command tool, so
it could not run the project's tests after changing them. This tool runs a
closed set of checks and nothing else:

- ``pytest`` on project-relative paths / node ids, with a short list of flags;
- ``ruff check`` and ``ruff format --check --diff`` on project-relative paths;
- read-only ``git status``, ``git diff`` and ``git log``.

Every argument is validated against that allowlist before anything starts. The
process is launched from an argv list (never a shell) in the project root, with
a 9-minute limit that kills the whole process tree, and its output is capped
to the tail, where pytest and ruff print their verdicts. Run as the cage account
in a green, it runs as the green, as the caged shell does (``thomas.core.green_place``).

The same pytest call on a project nothing has changed in is answered from its
last result (``thomas.tools.check_reuse``), marked ``reused``; ``fresh`` runs it.

A failing check is a successful tool call: ``ok`` is True and ``exit_code``
carries the verdict. ``ok`` is False only when the arguments were refused, the
run timed out, or the process could not start.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from thomas.core import cage_account, machine_load
from thomas.core.green_place import GREEN_AGENT_ID, green_of
from thomas.tools import check_reuse
from thomas.tools.base import Tool, ToolResult
from thomas.tools.shell_spool import kill_process_tree

# One run ends inside the agent loop's own 600 s limit for a tool (loop_core.default_tool_timeout_s). At 900 the loop
# gave up first: 96 calls in four days to 2026-10-27 came back "Tool timed out after 600s" with no output, so the
# run's own timeout, which names what it was running, never spoke.
DEFAULT_TIMEOUT_S = 540
# pytest waits its turn in this PC's line of test runs (machine_load.Line) for as long as that takes, and then has all
# of DEFAULT_TIMEOUT_S: until 2026-11-13 it waited at most 120 s and then started on a PC with no room, and 48 runs in
# one morning ended at the limit above with nothing learned. A call answers within this long, inside the loop's limit:
# with the verdict, or that the tests are still queued or running, and the same call again waits on for the same run.
ANSWER_WITHIN_S = 480.0
LINE_POLL_S = 1.0
_LOOK_S = 0.05  # how often a call looks whether its run has ended
_REPLACE_MAX = 2  # runs in a row a call may end because the project changed while they ran
log = logging.getLogger(__name__)
OUTPUT_CAP_CHARS = 20_000
# The agent loop keeps only the first 5,000 characters of a tool result, so the
# verdict (the last lines of a pytest/ruff run) is repeated ahead of the output.
_VERDICT_TAIL_CHARS = 2_500
_GIT_LOG_DEFAULT = 20
# git diff options that only choose what is shown (2026-10-27: 41 calls in four days were refused for "--" or one of
# these, each a turn spent on nothing); "--staged" is git's other name for "--cached".
_GIT_DIFF_OPTIONS = {
    "--stat": "--stat",
    "--cached": "--cached",
    "--staged": "--cached",
    "--check": "--check",
    "--name-only": "--name-only",
    "--name-status": "--name-status",
}
_GIT_LOG_MAX = 50
# The variables scripts/cage/shell_runner.py child_env() sets for a green's commands.
_AGENT_ID_KEYS = ("THOMAS_AGENT_ID", "AGENT_ID")

CHECKS = ("pytest", "ruff_check", "ruff_format_check", "git_status", "git_diff", "git_log")

# pytest flags that take no value.
_PYTEST_BARE_FLAGS = frozenset({"-q", "-x", "-v", "-vv", "--no-header", "-rA"})
# --timeout=N (pytest-timeout, up to the tool's own limit): on 2026-10-26 a team's check.run hit the 10-minute limit
# twice on files that held hanging tests, with no word of which test hung; a per-test timeout fails it with its stack.
_PYTEST_VALUE_FLAG_RE = re.compile(
    r"^(?:--maxfail=[1-9]\d{0,3}|--tb=(?:short|line|no)|--timeout=(?:[1-9]\d?|[1-5]\d\d|600)|--durations=(?:\d|[1-4]\d|50))$"
)
# 2026-10-07: a Build team ran `pytest -q -p no:cacheprovider --no-header --tb=short` with no target, the whole
# ~13k-test suite (about 53 minutes) against the 15-minute limit. It could never pass.
_WHOLE_SUITE_REFUSED = (
    "pytest refused: it names no test file, node id or -k selection, so it would run the whole test suite, which is "
    "too large to run here; name the test files you changed, e.g. tests/test_x.py or tests/test_x.py::test_name"
)


class CheckRefused(ValueError):
    """An argument outside the allowlist; the message names it and why."""


def _project_path(item: str, root: Path, *, what: str) -> str:
    """Accept ``item`` only as a relative path that stays inside ``root``."""
    if not item or item != item.strip():
        raise CheckRefused(f"{what} '{item}' refused: empty or padded with whitespace")
    if item.startswith("-"):
        raise CheckRefused(f"{what} '{item}' refused: not an allowed option")
    if item.startswith("@"):
        raise CheckRefused(f"{what} '{item}' refused: @file argument expansion is not allowed")
    if "\x00" in item or any(ch in item for ch in ";|&<>`$\n\r"):
        raise CheckRefused(f"{what} '{item}' refused: contains shell metacharacters; give a plain relative path")
    win, posix = PureWindowsPath(item), PurePosixPath(item)
    if win.drive or win.root or posix.root:
        raise CheckRefused(
            f"{what} '{item}' refused: absolute paths are not allowed; use a path relative to the project"
        )
    if ".." in win.parts or ".." in posix.parts:
        raise CheckRefused(f"{what} '{item}' refused: '..' would leave the project folder")
    resolved = (root / item).resolve()
    if resolved != root and root not in resolved.parents:
        raise CheckRefused(f"{what} '{item}' refused: it resolves outside the project folder")
    return item


def _pytest_target(item: str, root: Path) -> str:
    path_part = item.split("::", 1)[0]
    _project_path(path_part, root, what="pytest target")
    return item


def _pytest_argv(args: list[str], root: Path) -> list[str]:
    out: list[str] = []
    named = False  # a test file, node id or -k selection; nothing named is the whole suite
    i = 0
    while i < len(args):
        item = args[i]
        if item in _PYTEST_BARE_FLAGS or _PYTEST_VALUE_FLAG_RE.match(item):
            out.append(item)
        elif item == "-k":
            if i + 1 >= len(args):
                raise CheckRefused("pytest option '-k' refused: it needs an expression after it")
            expr = args[i + 1]
            if not expr.strip() or expr.startswith(("-", "@")) or "\x00" in expr:
                raise CheckRefused(f"pytest -k expression '{expr}' refused: must be a plain name expression")
            out += ["-k", expr]
            named = True
            i += 1
        elif item == "-p":
            plugin = args[i + 1] if i + 1 < len(args) else ""
            if plugin != "no:cacheprovider":
                raise CheckRefused(f"pytest option '-p {plugin}' refused: only '-p no:cacheprovider' is allowed")
            out += ["-p", plugin]
            i += 1
        elif item.startswith("-"):
            raise CheckRefused(
                f"pytest option '{item}' refused: allowed options are -q, -x, -v, -vv, -k <expr>, --maxfail=N, "
                "--timeout=N (1-600 s a test), --durations=N (0-50), -p no:cacheprovider, --no-header, -rA, "
                "--tb=short|line|no"
            )
        else:
            out.append(_pytest_target(item, root))
            named = named or (root / item.split("::", 1)[0]).resolve() != root.resolve()
        i += 1
    if not named:
        raise CheckRefused(_WHOLE_SUITE_REFUSED)
    return [sys.executable, "-m", "pytest", *out]


def _ruff_argv(args: list[str], root: Path, *, format_check: bool) -> list[str]:
    what = "ruff format --check path" if format_check else "ruff check path"
    paths = [_project_path(item, root, what=what) for item in args]
    # A non-writing diff lets the builder repair the exact formatting mismatch
    # instead of guessing from "would reformat" and repeating passing tests.
    base = ["format", "--check", "--diff"] if format_check else ["check"]
    return [sys.executable, "-m", "ruff", *base, *paths]


def _git_argv(check: str, args: list[str], root: Path) -> list[str]:
    # core.fsmonitor could name a program to run; a read-only check never runs one.
    git = ["git", "-c", "core.fsmonitor=false"]
    if check == "git_status":
        if args == ["--short"]:  # what it runs anyway
            args = []
        if args:
            raise CheckRefused(f"git status argument '{args[0]}' refused: git_status takes no arguments")
        return [*git, "status", "--short"]
    if check == "git_diff":
        options: list[str] = []
        paths: list[str] = []
        for item in args:
            if item == "--":
                continue  # the separator is put in below, ahead of the paths
            option = _GIT_DIFF_OPTIONS.get(item)
            if option is not None:
                options += [] if option in options else [option]
            else:
                paths.append(_project_path(item, root, what="git diff path"))
        return [*git, "diff", "--no-ext-diff", *options, "--", *paths]
    # git_log
    count = _GIT_LOG_DEFAULT
    rest = list(args)
    if rest[:1] == ["-n"]:
        rest = rest[1:]
        if not rest:
            raise CheckRefused("git log option '-n' refused: it needs a count after it")
    if len(rest) > 1 or (rest and not rest[0].isdigit()):
        raise CheckRefused(
            f"git log argument '{rest[0]}' refused: git_log takes only a count (-n N, 1..{_GIT_LOG_MAX})"
        )
    if rest:
        count = int(rest[0])
        if not 1 <= count <= _GIT_LOG_MAX:
            raise CheckRefused(f"git log count '{rest[0]}' refused: must be 1..{_GIT_LOG_MAX}")
    return [*git, "log", "--oneline", "-n", str(count)]


def build_argv(check: str, args: list[str], root: Path) -> list[str]:
    """The exact argv for an allowed check, or :class:`CheckRefused`."""
    if check not in CHECKS:
        raise CheckRefused(f"check '{check}' refused: allowed checks are {', '.join(CHECKS)}")
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise CheckRefused("args refused: must be a list of strings")
    if check == "pytest":
        return _pytest_argv(args, root)
    if check in {"ruff_check", "ruff_format_check"}:
        return _ruff_argv(args, root, format_check=check == "ruff_format_check")
    return _git_argv(check, args, root)


def cap_output(text: str, cap: int = OUTPUT_CAP_CHARS) -> str:
    """Keep the last ``cap`` characters, with a note saying what was dropped."""
    if len(text) <= cap:
        return text
    return f"[output truncated: showing last {cap} of {len(text)} characters]\n" + text[-cap:]


def _child_env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    # The Build runner imports Thomas under PYTHONSAFEPATH; the project's own
    # tests must import the project's code (forge_code_runner.release_safe_path_for_children).
    env.pop("PYTHONSAFEPATH", None)
    # tests/conftest.py fails a run when the real Thomas data it watches changes, unless the run carries the green
    # id. In a green that data is the caged server's own, written while its Build team tests: measured 2026-10-13,
    # 162 passing tests were failed for the server's thomas.db-wal. So a check in a green carries the id the caged
    # shell gives a green's commands, and a check anywhere else never passes one on, even one it inherited. Only as
    # the cage account, as the caged shell always is: a green made by the Thomas that runs as you is tested as you,
    # over your real data folder and ~/.thomas, which is what the tripwire is there to watch.
    in_a_green = bool(green_of(root)) and cage_account.running_as_cage_account()
    for key in _AGENT_ID_KEYS:
        if in_a_green:
            env[key] = GREEN_AGENT_ID
        elif str(env.get(key) or "").strip() == GREEN_AGENT_ID:
            del env[key]
    # Every git the tests start is then one process, not Git for Windows' launcher and the git it starts: measured
    # 2026-10-28, child processes were 43-44% of the most-selected test files' CPU, nearly all of them git.
    from thomas.core import git_launcher  # here, not at the top: a team was editing that import line (2026-10-28)

    return git_launcher.real_git_first(env)


def _run_blocking(argv: list[str], cwd: Path, timeout: float, started: dict[str, Any]) -> tuple[int | None, str]:
    """Run ``argv``; return ``(exit_code, combined_output)``, exit_code None on timeout.

    ``started["proc"]`` receives the process so a cancelled caller can kill it."""
    popen_kwargs: dict[str, Any] = {}
    if sys.platform != "win32":
        popen_kwargs["start_new_session"] = True  # so kill_process_tree can kill the group
    proc = subprocess.Popen(
        argv,
        cwd=str(cwd),
        env=_child_env(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=False,
        **popen_kwargs,
    )
    started["proc"] = proc
    try:
        raw, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_process_tree(proc.pid)
        try:
            raw, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            raw, _ = proc.communicate()
        return None, (raw or b"").decode("utf-8", errors="replace")
    return proc.returncode, (raw or b"").decode("utf-8", errors="replace")


@dataclass
class _Job:
    """One pytest call: waiting in the line, running, or finished and not yet read."""

    status: str = "queued"
    state: Any = None  # the project as it was when the run started (check_reuse.fingerprint); None while it waits
    ahead: int = 0
    future: Any = None  # the run, on the background loop (a concurrent.futures.Future)
    started: dict[str, Any] = field(default_factory=dict)  # holds "proc" once the test process is going
    replaces: int = 0  # how many runs in a row this one replaced while they were going


# One run for each (project, pytest arguments): the same call again joins the run that is waiting or going.
_JOBS: dict[tuple[str, tuple[str, ...]], _Job] = {}
_BACKGROUND: asyncio.AbstractEventLoop | None = None
_BACKGROUND_LOCK = threading.Lock()
_UNWINDING = 0  # runs on the background loop that have not yet given their place back


def _background() -> asyncio.AbstractEventLoop:
    """The loop test runs wait and run on: one for the process, in a thread of its own.

    Each pass of a Build is its own ``asyncio.run`` (dispatch_agent_loop), which cancels every task of its loop when
    the pass ends. A run on that loop gave its place in the line back at every pass end and joined again at the back,
    and a run that had started was killed with the pass (review, 2026-11-13). Here a run outlives the pass that asked
    for it: the next pass makes the same call and joins it, or finds its verdict.
    """
    global _BACKGROUND
    with _BACKGROUND_LOCK:
        if _BACKGROUND is None or _BACKGROUND.is_closed():
            _BACKGROUND = asyncio.new_event_loop()
            threading.Thread(target=_BACKGROUND.run_forever, name="check-run-jobs", daemon=True).start()
        return _BACKGROUND


def _spent(job: _Job, state: Any, fresh: bool) -> bool:
    """Whether a run in the registry is not the one this call is for."""
    if job.future.cancelled():
        return True
    if job.status == "queued":
        return False  # it will test the project as it is when its turn comes
    same = state is not None and job.state == state
    if job.future.done():
        # A verdict that is in belongs to the call that waited on it. A later call takes it only for the same known
        # project, and never when it asked for a fresh run or the folder has no git state that would show an edit.
        return fresh or not same
    return (state is not None and not same) or (fresh and state is None)


def _end_process(job: _Job) -> None:
    proc = job.started.get("proc")
    if proc is not None and proc.poll() is None:
        kill_process_tree(proc.pid)


def forget_jobs(wait_s: float = 5.0) -> None:
    """End every run this process holds, give their places back, and forget them."""
    jobs = list(_JOBS.values())
    _JOBS.clear()
    for job in jobs:
        job.future.cancel()
        _end_process(job)
    pause = threading.Event()
    for _ in range(int(wait_s / 0.01)):
        if _UNWINDING <= 0:
            break
        pause.wait(0.01)


def _end_processes_at_exit() -> None:
    """A test process must not outlive the Build that asked for it."""
    for job in list(_JOBS.values()):
        _end_process(job)


atexit.register(_end_processes_at_exit)


def _not_yet(job: _Job, argv: list[str]) -> ToolResult:
    """What a call answers when its tests have no verdict yet."""
    if job.status == "queued":
        words = f"These tests have not started yet: {job.ahead} test run(s) are ahead of them in this PC's line."
    else:
        words = "These tests are still running."
    return ToolResult(
        ok=True,
        data={
            "check": "pytest",
            "argv": argv,
            "status": job.status,
            "ahead": job.ahead,
            "passed": None,
            "message": (
                f"{words} There is no verdict yet: this is neither a pass nor a failure. Call check.run again with "
                "the same arguments to go on waiting for this same run; it is never started twice."
            ),
        },
    )


class CheckRunTool(Tool):
    name = "check.run"
    category = "shell"
    description = (
        "Run one of the project's checks and return its exit code and output. Allowed checks ONLY: "
        "pytest (relative test paths or node ids like tests/test_x.py::test_y, and flags -q -x -v -vv "
        "-k <expr> --maxfail=N --timeout=N --durations=N -p no:cacheprovider --no-header -rA --tb=short|line|no; "
        "name the test files "
        "you changed or a -k selection: the whole suite is too large to run here and is refused); "
        "ruff_check and ruff_format_check (relative paths; format checks show a repair diff, never rewrite); "
        "git_status, git_diff (optional --stat, --cached, --check, --name-only, --name-status and relative paths), "
        "git_log (optional -n N, 1..50). "
        "Runs in the project folder, no shell, 9-minute limit for the run itself, output "
        "capped to its last 20,000 characters. "
        "pytest waits its turn in one line for the whole PC; when there is no verdict after 8 minutes the call answers "
        "with status 'queued' or 'running', which is neither a pass nor a failure: call it again with the same "
        "arguments to go on waiting for the same run (it is never started twice). "
        "A failing check still returns ok with a non-zero exit_code. Use it to run the tests and ruff on "
        "the files you changed before you say you are done. "
        "The same pytest call again, with nothing in the project changed since, returns the earlier result marked "
        "'reused' without running; set fresh to true to run it anyway."
    )
    parameters = {
        "type": "object",
        "properties": {
            "check": {
                "type": "string",
                "enum": list(CHECKS),
                "description": "Which check to run.",
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Arguments for the check, one per item (paths relative to the project).",
            },
            "fresh": {
                "type": "boolean",
                "description": "Run pytest even if this same call already ran on the project as it is now.",
            },
        },
        "required": ["check"],
    }

    def __init__(
        self, project_root: Path, *, timeout: float = DEFAULT_TIMEOUT_S, reuse_dir: Path | None = None
    ) -> None:
        self._root = Path(project_root).resolve()
        self.timeout = timeout
        self._reuse_dir = reuse_dir

    def _reuse_folder(self) -> Path:
        if self._reuse_dir is None:
            from thomas.core.config import resolve_thomas_data_dir

            self._reuse_dir = Path(resolve_thomas_data_dir()) / "check_reuse"
        return self._reuse_dir

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        check = str(args.get("check") or "")
        raw_args = args.get("args") or []
        try:
            argv = build_argv(check, raw_args, self._root)
        except CheckRefused as exc:
            return ToolResult(ok=False, error=f"check.run refused: {exc}. Nothing was run.")
        if check != "pytest":
            return await self._run(check, argv, None, None)
        # The same tests on a project nothing has changed in can only say what is known: answer from the last run.
        state = await asyncio.to_thread(check_reuse.fingerprint, self._root, _child_env(self._root))
        key = check_reuse.key_of(argv)
        if state and not args.get("fresh"):
            earlier = await asyncio.to_thread(check_reuse.recall, self._reuse_folder(), self._root, key, state)
            if earlier is not None:
                waiting = _JOBS.get((str(self._root), tuple(argv)))
                if waiting is not None and waiting.future.done():
                    del _JOBS[(str(self._root), tuple(argv))]
                return ToolResult(ok=True, data=earlier)
        # pytest is what fills this PC's cores (2026-10-25: "make sure thomas doesnt ever max out the pc always 90%").
        # The run waits its turn in a task of its own, so its wait is never cut off by this call's limit.
        where = (str(self._root), tuple(argv))
        job, chain = _JOBS.get(where), 0
        if job is not None and _spent(job, state, bool(args.get("fresh"))):
            if job.future.done():
                job = None
            elif job.replaces < _REPLACE_MAX:
                job.future.cancel()  # no call can read its verdict now: its process ends and its place is given back
                job, chain = None, job.replaces + 1
            # Else each run so far changed the project on its own (a file its tests write that git does not ignore):
            # this one's verdict is the best there is, so the call waits for it instead of starting it again.
        if job is None:
            job = _JOBS[where] = _Job(replaces=chain)
            job.future = asyncio.run_coroutine_threadsafe(self._in_line(job, check, argv, key), _background())
        loop = asyncio.get_running_loop()
        answer_by = loop.time() + ANSWER_WITHIN_S
        while not job.future.done() and loop.time() < answer_by:
            await asyncio.sleep(_LOOK_S)
        if not job.future.done():
            return _not_yet(job, argv)
        if _JOBS.get(where) is job:
            del _JOBS[where]
        if job.future.cancelled():
            return ToolResult(
                ok=False,
                error="check.run: these tests were replaced by a later call for the same tests. Nothing is known from them.",
            )
        return job.future.result()

    async def _in_line(self, job: _Job, check: str, argv: list[str], key: Any) -> ToolResult:
        """Wait for a place in the line of test runs on this PC, run the tests, and give the place back."""
        global _UNWINDING
        _UNWINDING += 1
        began, line, ticket = time.monotonic(), None, None
        try:
            try:
                line = await asyncio.to_thread(machine_load.line)
                if line is not None:
                    ticket = await asyncio.to_thread(line.join, "check.run")
                    while True:
                        start, job.ahead = await asyncio.to_thread(line.look, ticket)
                        if start:
                            break
                        await asyncio.sleep(LINE_POLL_S)
            except (sqlite3.Error, OSError) as exc:  # the tests run all the same: bookkeeping never stops a check
                log.warning("check.run did not wait in the line of test runs (%s: %s)", type(exc).__name__, exc)
            waited = time.monotonic() - began
            job.state = await asyncio.to_thread(check_reuse.fingerprint, self._root, _child_env(self._root))
            job.status = "running"
            result = await self._run(check, argv, job.state, key, job.started)
            if waited >= 1.0:
                machine_load._note_wait(
                    "check.run", waited, "its turn in the line of test runs"
                )  # the step log, as before
                if result.ok and isinstance(result.data, dict):
                    result.data["waited_for_room"] = (
                        f"waited {waited:.0f} s for its turn in the line of test runs on this PC before starting"
                    )
            return result
        finally:
            try:
                if line is not None and ticket is not None:
                    await asyncio.shield(asyncio.to_thread(line.leave, ticket))
            except (sqlite3.Error, OSError):
                log.warning("check.run could not give back its place in the line of test runs", exc_info=True)
            finally:
                _UNWINDING -= 1

    async def _run(
        self, check: str, argv: list[str], state: Any, key: Any, started: dict[str, Any] | None = None
    ) -> ToolResult:
        """Run the check now, with the whole of its own time."""
        run_for = float(self.timeout)
        started = {} if started is None else started
        try:
            exit_code, output = await asyncio.to_thread(_run_blocking, argv, self._root, run_for, started)
        except asyncio.CancelledError:
            # The loop gave up on this call; the check must not outlive it.
            proc = started.get("proc")
            if proc is not None and proc.poll() is None:
                kill_process_tree(proc.pid)
            raise
        except OSError as exc:
            return ToolResult(ok=False, error=f"check.run could not start '{argv[0]}' for {check}: {exc}")
        if exit_code is None:
            tail = cap_output(output, _VERDICT_TAIL_CHARS)
            return ToolResult(
                ok=False,
                error=(
                    f"check.run {check} timed out after {int(run_for)} s and its process tree was killed. "
                    f"Last output:\n{tail}"
                ),
            )
        data = {
            "check": check,
            "argv": argv,
            "exit_code": exit_code,
            "passed": exit_code == 0,
            "verdict_tail": output[-_VERDICT_TAIL_CHARS:],
            "output": cap_output(output),
        }
        if state and key:
            # Kept only when the project is as it was when the run began: a file changed while the tests ran may or
            # may not have been seen by them, so that result answers nothing later.
            after = await asyncio.to_thread(check_reuse.fingerprint, self._root, _child_env(self._root))
            if after == state:
                await asyncio.to_thread(check_reuse.remember, self._reuse_folder(), self._root, key, state, dict(data))
        return ToolResult(ok=True, data=data)


def register_check_run_tool(registry: Any, project_root: Path) -> None:
    """Register ``check.run`` rooted at ``project_root``."""
    registry.register(CheckRunTool(project_root))
