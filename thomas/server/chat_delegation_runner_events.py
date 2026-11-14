"""Worker event-stream helpers for the delegation runner, split out so the runner
stays under the size limit: user-facing tool phrases, per-tool outcome recording,
supervisor timeouts and the async event-stream plumbing."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

from thomas.agent.completion_gate import GATE_BLOCKED_ERROR
from thomas.core import task_bot_runtime
from thomas.server.chat_delegation_deliverable import _WorkerFatal, _WorkerRetry
from thomas.server.chat_delegation_emitter import (
    WorkerHeartbeat,
    _ThreadsafeDelegationEmitter,
    register_worker_heartbeat,
    release_worker_heartbeat,
    worker_heartbeat,
)
from thomas.server.chat_delegation_scheduler import scheduler_for_running_loop
from thomas.server.issue_ledger import record_issue

log = logging.getLogger(__name__)


def _runner_setting(name: str) -> float:
    """Timeouts stay defined (and monkeypatched by tests) on the runner module; read
    them there at call time so this module never imports the runner at import time."""

    import importlib

    return float(getattr(importlib.import_module("thomas.server.chat_delegation_runner"), name))


# Progress lines are USER-FACING (the activity card under "Handed off to ...").
# Raw tool telemetry ("Finished fs.read_file; continuing.") reads like a stack
# trace to the owner; phrase every step like a teammate's status update.
_TOOL_PHRASES = {
    "fs.read_file": ("Reading files", "Read what I needed"),
    "fs.write_file": ("Writing the file", "Saved the file"),
    "fs.list_dir": ("Looking through the workspace", "Scanned the workspace"),
    "fs.search": ("Searching the workspace", "Searched the workspace"),
    "web.search": ("Searching the web", "Found some sources"),
    "web.fetch": ("Reading a web page", "Read the page"),
    "shell.exec": ("Running a command", "Command finished"),
    "ssh.exec": ("Running a remote command", "Remote command finished"),
}


def _tool_phrase(tool_name: str, *, done: bool = False, failed: bool = False) -> str:
    active, finished = _TOOL_PHRASES.get(str(tool_name or "tool"), ("Working on the next step", "Step finished"))
    if failed:
        return f"{active} hit a snag — trying another way."
    return f"{finished} — moving on." if done else f"{active}…"


_MAX_EFFORT_IDLE_EVENT_TIMEOUT_S = 360.0
# Reasoning efforts whose single model pass can outlast the ordinary idle window.
_LONG_REASONING_EFFORTS = frozenset({"xhigh", "max"})
# A worker that fails the same step this many times IN A ROW stops spinning
# "hit a snag" and hands control to the recovery machinery instead.
_MAX_CONSECUTIVE_SNAGS = 6


# Progress-line history (fix round 1, I1). A pass-budget retry used to carry
# only the single line captured right before the stop, and that line was
# usually a generic tool phrase ("Command finished — moving on.") with no
# real detail. Keeping the last few gives the replan prompt more to work with.
_PROGRESS_HISTORY_KEEP = 3


class ProgressHistory:
    """The current attempt's own progress lines, most recent last, kept short."""

    def __init__(self, keep: int = _PROGRESS_HISTORY_KEEP) -> None:
        self._keep = max(1, int(keep))
        self._lines: list[str] = []

    def record(self, line: str) -> None:
        text = str(line or "").strip()
        if text:
            self._lines.append(text)
            del self._lines[: -self._keep]

    def recent(self) -> list[str]:
        return list(self._lines)


# How often a worker waiting for a thread refreshes its record; the stale sweep allows 15 quiet minutes.
_WAITING_REFRESH_S = 60.0


async def note_waiting_for_thread(
    noted: list[float], emitter: Any, execution_id: str, repo_root: Path, specialist_id: str, bot: Any
) -> None:
    """While a worker waits for a thread of its pool, its record says so rather than "running", and its heartbeat
    stays fresh, so the stale sweep never fails a task that is only waiting its turn. *noted* holds when this was
    last written. Written under the record's lock, and never once the record has ended."""
    from thomas.server.chat_delegation_session import _normalize_record

    now = time.monotonic()
    if noted and now - noted[0] < _WAITING_REFRESH_S:
        return
    text = None
    if not noted:
        busy = scheduler_for_running_loop().limit
        text = f"Waiting for a free worker: all {busy} are busy with other tasks."
    with task_bot_runtime._record_lock(execution_id, repo_root):
        current = task_bot_runtime.get_execution(execution_id, repo_root) or {}
        if str(current.get("state") or "").strip().lower() in task_bot_runtime.TERMINAL_STATES:
            return
        task_bot_runtime.update_execution(
            execution_id, progress_summary=text, heartbeat=True, actor=bot.name, repo_root=repo_root, force=True
        )
    noted[:] = [now]
    if text is not None:
        record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
        await emitter.progress(record, specialist_id=specialist_id, bot=bot, text=text)


async def report_progress(
    emitter: Any,
    execution_id: str,
    progress: str,
    *,
    actor: str,
    repo_root: Path,
    specialist_id: str,
    bot: Any,
    history: ProgressHistory | None = None,
) -> None:
    """Save *progress* to the execution record and tell the emitter -- the three
    calls every report site in the runner used to repeat by hand. Also
    remembers the line in *history*, if given (fix round 1, I1)."""
    from thomas.server.chat_delegation_session import _normalize_record

    task_bot_runtime.update_execution(
        execution_id, progress_summary=progress, actor=actor, repo_root=repo_root, force=True
    )
    record = _normalize_record(task_bot_runtime.get_execution(execution_id, repo_root))
    await emitter.progress(record, specialist_id=specialist_id, bot=bot, text=progress)
    if history is not None:
        history.record(progress)


def _record_tool_outcome(
    tool_name: str,
    *,
    ok: bool,
    succeeded_tools: list[str],
    failed_tools: list[str],
) -> None:
    """Keep every failed action visible; a later same-named call is not proof of recovery."""
    target = succeeded_tools if ok else failed_tools
    if tool_name not in target:
        target.append(tool_name)


def _supervisor_worker_timeout_s(worker_kwargs: dict[str, Any], *, has_progress: bool) -> float:
    """Return a bounded watchdog window appropriate to the active worker tier.

    The long window follows the task's reasoning effort as well as the token economy.
    `worker_kwargs["effort"]` is the economy dial ("cheap", "balanced", ...), so a task
    thinking at xhigh or max on the cheap economy used to get the ordinary 120 s for a
    single model pass (measured 2026-09-23: `effort: "cheap"` next to
    `reasoning_effort: "xhigh"` on the same record).
    """

    base = (
        _runner_setting("_WORKER_IDLE_EVENT_TIMEOUT_S")
        if has_progress
        else _runner_setting("_WORKER_FIRST_EVENT_TIMEOUT_S")
    )
    effort = str(worker_kwargs.get("effort") or "").strip().lower()
    reasoning = str(worker_kwargs.get("reasoning_effort") or "").strip().lower()
    if has_progress and (effort in {"max", "exhaustive"} or reasoning in _LONG_REASONING_EFFORTS):
        return max(base, _MAX_EFFORT_IDLE_EVENT_TIMEOUT_S)
    return base


class _LoopStallClock:
    """When the watchdog's loop last ran, and every stretch it could not.

    The watchdog lives on the server's event loop. When something else holds that
    loop -- measured 2026-09-23, a Chat turn's search for about 120 s and 145 s --
    every overdue check fires the moment it comes back, and a worker's silence then
    includes time in which nobody could have heard it. This clock notices its own
    late wake-ups so that time is not charged to the worker.
    """

    _TOLERANCE_S = 0.5  # later than this past its wake-up time, the loop was held
    _KEEP = 64

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._stalls: list[tuple[float, float]] = []

    async def wait(self, tasks: set[asyncio.Task[Any]], timeout_s: float) -> tuple[set[Any], set[Any]]:
        """``asyncio.wait`` that records it if the loop woke it late."""
        due = self._clock() + max(0.0, timeout_s)
        try:
            return await asyncio.wait(tasks, timeout=timeout_s)
        finally:
            self.woke(due)

    def woke(self, due: float) -> None:
        now = self._clock()
        if now - due > self._TOLERANCE_S:
            self._stalls.append((due, now))
            del self._stalls[: -self._KEEP]
            log.info("server loop was held for %.1fs; not charged to the worker", now - due)

    def blocked_s(self, window_s: float) -> float:
        """Seconds within the last *window_s* in which the loop could not run."""
        now = self._clock()
        start = now - max(0.0, window_s)
        return sum(max(0.0, min(end, now) - max(begin, start)) for begin, end in self._stalls)


def _worker_silence_s(
    record_age_s: float | None, heartbeat: WorkerHeartbeat | None, stalls: _LoopStallClock
) -> float | None:
    """How long the worker has really been silent: the fresher of its two signs of life
    (the record on disk and its in-memory heartbeat), less any of that time in which
    the server loop itself could not run. None when neither has been seen yet, and
    while the worker waits for a thread of its pool: that wait is not silence."""
    if heartbeat is not None and heartbeat.waiting_for_thread:
        return None
    ages = [age for age in (record_age_s, heartbeat.age_s() if heartbeat is not None else None) if age is not None]
    if not ages:
        return None
    silence = min(ages)
    return max(0.0, silence - stalls.blocked_s(silence))


def _start_worker_thread(
    runner: Callable[..., Awaitable[None]],
    app: Any,
    emitter: Any,
    worker_kwargs: dict[str, Any],
    execution_id: str,
) -> tuple[asyncio.Future[Any], list[str], WorkerHeartbeat]:
    """Start the worker in its own thread with what its supervisor watches: the
    refusal sink (see `_sink_refusal`) and a heartbeat the thread beats directly.

    The thread comes from the delegated workers' own pool, never the shared one
    (`chat_delegation_scheduler`): a finishing worker waits for its notice, and the
    notice's notification needs a thread from the shared pool."""
    heartbeat = register_worker_heartbeat(execution_id)
    threaded_kwargs = dict(worker_kwargs)
    threaded_kwargs["emitter"] = _ThreadsafeDelegationEmitter(emitter, asyncio.get_running_loop(), heartbeat)
    refusal_sink: list[str] = []
    threaded_kwargs["policy_refusal_sink"] = refusal_sink
    thread = scheduler_for_running_loop().start(
        _run_worker_thread_entry, runner, app, threaded_kwargs, heartbeat, on_wait=heartbeat.wait_for_thread
    )
    return thread, refusal_sink, heartbeat


_WORKER_STOP_WAIT_S = 2.0  # how long a stop waits for the worker's thread before recording


async def _stop_worker(heartbeat: WorkerHeartbeat, thread_task: asyncio.Future[Any]) -> None:
    """Stop the worker itself, not just the future that waits for its thread.

    `thread_task.cancel()` alone cancels only the asyncio wrapper around the
    thread; the thread ran on and exec-a5ab521aff9c wrote "attempt 2 of 12" after
    its card said failed. This sets the stop flag and cancels the run in the
    worker's own loop, then gives the thread a moment to end so that the reason
    recorded next is the last word on the card. A worker still waiting for a
    thread of its pool never starts after this, so there is nothing to wait for.
    """
    if not heartbeat.request_stop():
        release_worker_heartbeat(heartbeat)
        thread_task.cancel()
        return
    if not thread_task.done():
        await asyncio.wait({thread_task}, timeout=_WORKER_STOP_WAIT_S)
    if not thread_task.done():
        thread_task.cancel()


def _worker_stopped(execution_id: str) -> bool:
    """True once the supervisor has stopped this worker (the check between attempts)."""
    heartbeat = worker_heartbeat(execution_id)
    return heartbeat is not None and heartbeat.stop_requested


def _live_attempts(execution_id: str, max_attempts: int) -> Iterator[int]:
    """Attempt numbers 1..max_attempts, ending early once the worker has been stopped."""
    for attempt in range(1, max_attempts + 1):
        if _worker_stopped(execution_id):
            log.info("worker %s was stopped; attempt %d does not start", execution_id, attempt)
            return
        yield attempt


def _record_worker_cancelled(execution_id: str, bot: Any, repo_root: Path) -> None:
    """A cancelled run is recorded as failed -- unless its supervisor stopped it and has
    already recorded why. "Background execution cancelled." written over that would
    replace the real reason on the card with a side effect of stopping."""
    if _worker_stopped(execution_id):
        return
    task_bot_runtime.fail_execution(
        execution_id,
        actor=bot.name,
        summary="Background execution cancelled.",
        blocker="cancelled",
        repo_root=repo_root,
        keep_first_terminal=True,
    )


async def _next_worker_event(
    stream: Any, *, saw_event: bool, timeout_s: float | None = None, execution_id: str = ""
) -> dict[str, Any] | None:
    """Wait for the worker's next event, cancelling the stream if it never comes.

    `timeout_s` exists because this watchdog and `_supervisor_worker_timeout_s`
    were two spellings of one decision and they disagreed. The supervisor reads the
    effort dial and grants 360s for "max"/"exhaustive" -- Thorough in the UI -- while
    this function took no effort argument and always used the 120s idle constant.
    The stricter one wins, so choosing Thorough changed nothing and a worker that
    thought for over two minutes was cut off mid-step.

    Worth knowing what the cut costs: the timeout path cancels the pending
    `__anext__()`, which destroys the generator. After that StopAsyncIteration reads
    downstream as "the worker said nothing" rather than "we stopped listening", so
    the run is reported as silent rather than interrupted.

    `execution_id` names the worker whose heartbeat counts too. A lead waiting on a
    `task.spawn` helper emits nothing of its own until the helper finishes, but the
    helper's steps beat the lead's heartbeat; while that stays fresher than the
    window, the lead is waiting, not hung, and the wait goes on.
    """

    if timeout_s is None:
        timeout_s = (
            _runner_setting("_WORKER_IDLE_EVENT_TIMEOUT_S")
            if saw_event
            else _runner_setting("_WORKER_FIRST_EVENT_TIMEOUT_S")
        )
    heartbeat = worker_heartbeat(execution_id) if execution_id else None
    next_task = asyncio.create_task(stream.__anext__())
    wait_s = max(0.001, float(timeout_s))
    while True:
        done, _pending = await asyncio.wait({next_task}, timeout=wait_s)
        age_s = heartbeat.age_s() if heartbeat is not None else None
        if done or age_s is None or age_s >= timeout_s:
            break
        wait_s = max(0.001, float(timeout_s) - age_s)
    if done:
        if heartbeat is not None:
            heartbeat.beat()
        try:
            return next_task.result()
        except StopAsyncIteration:
            return None

    def _consume_background_result(task: asyncio.Task[Any]) -> None:
        try:
            task.result()
        except (asyncio.CancelledError, StopAsyncIteration):
            pass
        except (RuntimeError, OSError, ValueError, TypeError):
            log.debug("worker event stream background cleanup failed", exc_info=True)

    next_task.cancel()
    cancelled, _pending = await asyncio.wait({next_task}, timeout=_runner_setting("_WORKER_STREAM_CLOSE_TIMEOUT_S"))
    if cancelled:
        _consume_background_result(next_task)
    else:
        next_task.add_done_callback(_consume_background_result)
    await _close_worker_event_stream(stream, consume_result=_consume_background_result)
    phase = "first event" if not saw_event else "next event"
    raise _WorkerRetry(f"provider-native worker produced no {phase} within {timeout_s:g}s")


async def _close_worker_event_stream(
    stream: Any,
    *,
    consume_result: Callable[[asyncio.Task[Any]], None] | None = None,
) -> None:
    close = getattr(stream, "aclose", None)
    if callable(close):
        try:
            close_task = asyncio.ensure_future(close())
            closed, _pending = await asyncio.wait(
                {close_task}, timeout=_runner_setting("_WORKER_STREAM_CLOSE_TIMEOUT_S")
            )
            if closed:
                if consume_result is not None:
                    consume_result(close_task)
                else:
                    close_task.result()
            else:
                close_task.cancel()
                if consume_result is not None:
                    close_task.add_done_callback(consume_result)
        except (RuntimeError, OSError, ValueError, TypeError):
            log.debug("worker event stream close failed", exc_info=True)


def _sink_refusal(sink: list[str] | None, refusal_text: str) -> None:
    """Share a policy refusal with the supervising watchdog, which cannot see the
    worker's scope.

    `_run_agent_worker_supervised` reports watchdog timeouts itself and never reaches
    `_finalize_worker_completion`, where remedies are composed - so the cause of a run
    was discarded at the exact moment the person was told it had failed. Measured
    2026-09-19 by driving the UI: a task blocked from writing inside `thomas/agent/`
    was announced as "the refactor stalled after 135 seconds ... I can retry by
    splitting the work into smaller, targeted steps". Every word true, and the advice
    impossible, because scope was never the obstacle.

    Lives in this module rather than the runner, which sits exactly at its 800-line
    limit until the Phase 0b split.
    """
    if sink is None or refusal_text in sink:
        return
    sink.append(refusal_text)


# Machinery-authored error text that is always safe to surface verbatim: a
# fixed, argument-free template thomas/agent/loop_execution.py writes itself,
# never a provider's raw response. Provider/LLM error text stays hidden by
# design -- test_a_provider_failure_keeps_its_name_and_hides_its_detail pins
# that "429 from upstream, key sk-abc123" must never reach the chat -- so only
# text this module can vouch for by its exact shape gets through. The full
# template shape (not just a prefix) is matched, so nothing that merely starts
# with similar words is mistaken for it (fix round 1, minors).
_PASS_BUDGET_EXHAUSTED_RE = re.compile(r"^Pass budget exhausted after \d+ passes while work was still active\.")


def _worker_error(event: dict[str, Any]) -> RuntimeError:
    """What a worker's error event is raised as, named for what actually happened.

    Every error used to become "provider-native worker reported a retryable error",
    and the chat passed that on as a provider error. On 2026-09-22 three self-fixes
    ended that way with no provider at fault: Thomas's completion gate had refused
    the worker's finish. The provider's own error text still never reaches the chat;
    only whether it was Thomas's checks that said no.

    One more case is now named instead of flattened: thomas/agent/loop_execution.py's
    runaway-guard message ("Pass budget exhausted after N passes while work was
    still active...") is Thomas's own fixed text, not a provider's, and it was
    falling into the same generic bucket -- so a self-fix that was still actively
    working just ran out of passes for that attempt, and both the next attempt's
    replan prompt and the failure card lost the reason (Ruling J, live evidence
    exec-349fa8edcf3b, 2026-09-23).
    """
    retryable = event.get("retryable") is not False
    error_text = str(event.get("error") or "").strip()
    if error_text.startswith(GATE_BLOCKED_ERROR):
        reason = "the worker's finish did not pass Thomas's acceptance checks"
        return _WorkerRetry(reason) if retryable else _WorkerFatal(reason)
    if _PASS_BUDGET_EXHAUSTED_RE.match(error_text):
        return _WorkerRetry(error_text) if retryable else _WorkerFatal(error_text)
    if retryable:
        return _WorkerRetry("provider-native worker reported a retryable error")
    return _WorkerFatal("provider-native worker reported a non-retryable error")


def _failure_text(last_error: str, attempt: int, max_attempts: int) -> str:
    """The user-facing failure text: names the stop, the attempt count, and the
    error's own first sentence -- never a pass-budget template's tail ("...continue
    it in the same conversation"), which promises ongoing work to a card that
    already stopped for good (fix round 1, I1/I2)."""
    error_text = str(last_error or "").strip()
    first_sentence = error_text.split(". ", 1)[0].rstrip(". ")
    if _PASS_BUDGET_EXHAUSTED_RE.match(error_text):
        stop = "ran out of passes"
    elif error_text:
        stop = "hit a failure"
    else:
        stop, first_sentence = "stopped", ""
    detail = f" — {first_sentence}." if first_sentence and first_sentence != stop else "."
    return f"Background execution {stop} (attempt {attempt} of {max_attempts}){detail}"


# Blockers for which this module unconditionally writes a repair record
# (record_issue) when it fails an execution. The announcement's "recorded for
# repair" language is tied to this real fact, not a free-text model claim
# (fix round 1, I5).
_REPAIR_RECORDED_BLOCKERS = frozenset({"provider_native_failed", "provider_native_timeout"})


def _repair_recorded(blocker: str) -> bool:
    return str(blocker or "").strip() in _REPAIR_RECORDED_BLOCKERS


def _record_worker_failed_issue(
    execution_id: str, prompt: str, last_error: str, max_attempts: int, repo_root: Path
) -> None:
    """A worker that exhausted its self-recovery budget, recorded for repair."""
    record_issue(
        surface="chat-worker",
        kind="worker_failed",
        message=f"out of attempts: {last_error}"[:300],
        context={"execution_id": execution_id, "task": str(prompt or "")[:160], "attempts": str(max_attempts)},
        repo_root=repo_root,
    )


def _record_timeout_issue(execution_id: str, timeout_s: float, record: dict[str, Any] | None, repo_root: Path) -> None:
    """The live failure mode with nothing recorded: a supervisor timeout used to
    fail the card with no repair record at all. Context carries the timeout and
    the worker's own last progress line, not just that it timed out (fix round 1, I5)."""
    record_issue(
        surface="chat-worker",
        kind="worker_timeout",
        message=f"provider-native worker timed out after {timeout_s:g}s",
        context={
            "execution_id": execution_id,
            "timeout_s": f"{timeout_s:g}",
            "progress": str((record or {}).get("progress_summary") or "")[:200],
        },
        repo_root=repo_root,
    )


def _run_worker_thread_entry(
    runner: Callable[..., Awaitable[None]],
    app: Any,
    kwargs: dict[str, Any],
    heartbeat: WorkerHeartbeat | None = None,
) -> None:
    """The worker thread: run the worker on this thread's own loop, cancellable from
    the supervisor through *heartbeat*. A run its supervisor stopped ends quietly,
    and one stopped before its thread started never starts."""

    async def run() -> None:
        if heartbeat is not None:
            loop, task = asyncio.get_running_loop(), asyncio.current_task()

            def cancel() -> None:
                try:
                    loop.call_soon_threadsafe(task.cancel)
                except RuntimeError:  # this loop has already closed: the run is over
                    pass

            heartbeat.bind_cancel(cancel)
        await runner(app, **kwargs)

    try:
        if heartbeat is not None and not heartbeat.enter():
            log.info("worker %s was stopped before its thread started; it does not run", heartbeat.execution_id)
            return
        asyncio.run(run())
    except asyncio.CancelledError:
        if heartbeat is None or not heartbeat.stop_requested:
            raise
    finally:
        if heartbeat is not None:
            release_worker_heartbeat(heartbeat)
