from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any

from thomas.core.kernel import late, seams

log = logging.getLogger(__name__)

# Failures the best-effort notification path swallows (with logging).  The
# production notifier (thomas.notifications.delegation_hooks) is itself
# hardened to never raise; this guard exists for injected notifiers.  A
# notification failure must never break delegation.
_NOTIFY_EXCEPTIONS = (
    ImportError,
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    LookupError,
)
# Task 3h: what the chat that asked is told when the check before your card sends a single worker's change nowhere.
_NOT_HANDED_IN = (
    "This change to Thomas was not handed in for your approval: the check before your card found "
    "something, and a single worker has no team to send it back to. Ask again to have it fixed."
)


def _not_counted() -> None:  # an ending's chat event went out; nobody is counting
    return None


_lent_notifier: tuple[Callable[..., Any]] | None = None


def lend_notifier(notifier: Callable[..., Any]) -> Callable[[], None]:
    """Make *notifier* what delegations notify through, until the returned call is made.

    An emitter built with no ``notifier`` looks here each time it notifies, so a notifier lent after it was built is
    used, and one taken back stops being used at once. Nothing is lent while the notifications row is off, and then an
    ending, a block or a wait for approval is reported to the chat and notifies nobody. The call it returns takes back
    only what this call lent.
    """
    global _lent_notifier
    mine = (notifier,)
    _lent_notifier = mine

    def take_back() -> None:
        global _lent_notifier
        if _lent_notifier is mine:
            _lent_notifier = None

    return take_back


class _DelegationEmitter:
    def __init__(
        self,
        emit_event: Callable[[dict[str, Any]], Awaitable[None]],
        notifier: Callable[..., Any] | None = None,
    ) -> None:
        self._emit_event = emit_event
        self._notifier = notifier
        self._endings: dict[str, asyncio.Event | bool] = {}

    async def _deliver_once(
        self, record: dict[str, Any], deliver: Callable[[Callable[[], None]], Awaitable[None]]
    ) -> None:
        """One ending per execution reaches the chat, and a failed delivery can be retried.

        A worker and its watchdog can both report how an execution ended, and the chat used to hear both: "timed
        out" for a task that had completed. Each report now carries the ending that was stored (``keep_first_terminal``
        in ``task_bot_runtime``), so once one has been delivered a later one is dropped. A report that comes while
        another is being delivered waits for it. If a delivery raised or was cancelled before its chat event went
        out, the waiting report delivers. Once the chat event is out (*deliver* calls the function it is given), the
        ending counts as delivered even if the notification after it fails, so no retry sends the chat a second one.
        Ported from refs/salvage/praxis-native-20260919/wt-native-scheduling (694a668b).
        """
        execution_id = str(record.get("execution_id") or "")
        if not execution_id:
            await deliver(lambda: None)
            return
        while (claim := self._endings.get(execution_id)) is not None:
            if claim is True:
                log.info("delegation ending already delivered (execution_id=%s)", execution_id)
                return
            await claim.wait()
        in_flight = asyncio.Event()
        self._endings[execution_id] = in_flight
        sent: list[bool] = []
        try:
            await deliver(lambda: sent.append(True))
        finally:
            if sent:
                self._endings[execution_id] = True
            else:
                self._endings.pop(execution_id, None)
            in_flight.set()

    async def _notify_lifecycle(self, event: str, record: dict[str, Any], text: str = "") -> None:
        """Best-effort user notification (CAP-045); never raises."""
        try:
            notifier = self._notifier
            if notifier is None:
                # CAP-045: the notifications row lends its notifier while it runs. No import here, so a server
                # started with the row off never loads the notifications code, and off means no notifier.
                lent = _lent_notifier
                notifier = lent[0] if lent is not None else None
            if notifier is None:
                return
            await asyncio.to_thread(notifier, event, record, text=text)
        except _NOTIFY_EXCEPTIONS:
            log.warning(
                "delegation %s notification failed (execution_id=%s)",
                event,
                record.get("execution_id", ""),
                exc_info=True,
            )

    async def approval_needed(self, record: dict[str, Any], *, specialist_id: str, bot: Any, text: str = "") -> None:
        """Notify that a delegation is paused waiting for user approval."""
        await self._notify_lifecycle("approval_needed", record, text)

    async def started(self, record: dict[str, Any], *, specialist_id: str, bot: Any) -> None:
        await self._emit_event(
            {
                "type": "delegation_started",
                "execution_id": record.get("execution_id", ""),
                "task_id": record.get("task_id", ""),
                "session_id": record.get("session_id", ""),
                "backend_type": record.get("backend_type", ""),
                "state": record.get("state", "queued"),
                "summary": record.get("summary", ""),
                "last_progress": record.get("last_progress", ""),
                "runtime_profile": record.get("runtime_profile") or {},
                "specialist_id": specialist_id,
                "is_canvas": bool(record.get("is_canvas")),
                "canvas_html": record.get("canvas_html", ""),
                "canvas_status": record.get("canvas_status", ""),
                "canvas_review_status": record.get("canvas_review_status", ""),
                "proof_status": record.get("proof_status", "missing"),
                "receipt": record.get("receipt") or {},
                **bot.to_event_dict(),
            }
        )

    async def progress(self, record: dict[str, Any], *, specialist_id: str, bot: Any, text: str) -> None:
        await self._emit_event(
            {
                "type": "delegation_progress",
                "execution_id": record.get("execution_id", ""),
                "task_id": record.get("task_id", ""),
                "session_id": record.get("session_id", ""),
                "backend_type": record.get("backend_type", ""),
                "state": record.get("state", "executing"),
                "summary": record.get("summary", ""),
                "last_progress": text or record.get("last_progress", ""),
                "runtime_profile": record.get("runtime_profile") or {},
                "specialist_id": specialist_id,
                "is_canvas": bool(record.get("is_canvas")),
                "canvas_html": record.get("canvas_html", ""),
                "canvas_status": record.get("canvas_status", ""),
                "canvas_review_status": record.get("canvas_review_status", ""),
                "proof_status": record.get("proof_status", "missing"),
                "receipt": record.get("receipt") or {},
                **bot.to_event_dict(),
            }
        )

    async def completed(self, record: dict[str, Any], *, specialist_id: str, bot: Any, text: str = "") -> None:
        await self._deliver_once(
            record, lambda sent: self._completed(record, specialist_id=specialist_id, bot=bot, text=text, sent=sent)
        )

    async def failed(self, record: dict[str, Any], *, specialist_id: str, bot: Any, text: str) -> None:
        await self._deliver_once(
            record, lambda sent: self._failed(record, specialist_id=specialist_id, bot=bot, text=text, sent=sent)
        )

    async def _completed(
        self,
        record: dict[str, Any],
        *,
        specialist_id: str,
        bot: Any,
        text: str = "",
        sent: Callable[[], Any] = _not_counted,
    ) -> None:
        await self._emit_event(
            {
                "type": "delegation_completed",
                "execution_id": record.get("execution_id", ""),
                "task_id": record.get("task_id", ""),
                "session_id": record.get("session_id", ""),
                "backend_type": record.get("backend_type", ""),
                "state": "completed",
                "summary": record.get("summary", ""),
                "last_progress": text or record.get("last_progress", ""),
                "artifact_url": record.get("artifact_url", ""),
                "artifact_name": record.get("artifact_name", ""),
                "artifact_kind": record.get("artifact_kind", ""),
                "artifacts": record.get("artifacts") or [],
                "proof_status": record.get("proof_status", "missing"),
                "proof": record.get("proof") or {},
                "receipt": record.get("receipt") or {},
                "runtime_profile": record.get("runtime_profile") or {},
                "specialist_id": specialist_id,
                "is_canvas": bool(record.get("is_canvas")),
                "canvas_html": record.get("canvas_html", ""),
                "canvas_status": record.get("canvas_status", ""),
                "canvas_review_status": record.get("canvas_review_status", ""),
                **bot.to_event_dict(),
            }
        )
        sent()
        await self._notify_lifecycle("completed", record, text)
        await self._settle_green(record, promote=True, text=text)
        self._offer_self_change_review(record)

    async def _failed(
        self, record: dict[str, Any], *, specialist_id: str, bot: Any, text: str, sent: Callable[[], Any] = _not_counted
    ) -> None:
        await self._emit_event(
            {
                "type": "delegation_failed",
                "execution_id": record.get("execution_id", ""),
                "task_id": record.get("task_id", ""),
                "session_id": record.get("session_id", ""),
                "backend_type": record.get("backend_type", ""),
                "state": "failed",
                "summary": record.get("summary", ""),
                "last_progress": text,
                "proof_status": record.get("proof_status", "failed"),
                "proof": record.get("proof") or {},
                "receipt": record.get("receipt") or {},
                "runtime_profile": record.get("runtime_profile") or {},
                "specialist_id": specialist_id,
                **bot.to_event_dict(),
            }
        )
        sent()
        await self._notify_lifecycle("failed", record, text)
        await self._settle_green(record, promote=False, text=text)
        # A failed run can still have changed Thomas's own code; the owner gets
        # the same Undo / Accept card either way.
        self._offer_self_change_review(record)

    async def _settle_green(self, record: dict[str, Any], *, promote: bool, text: str) -> None:
        """A self-fix's green: its change to the commit-master inbox when the run
        finished, gone either way. A run that had no green is untouched.

        Task 3h: checked first (``thomas.server.precard``), the same check a Thomas
        project gets. A single worker has no team to send a failure back to, so a
        change that fails is not handed in and the chat that asked gets the findings."""
        execution_id = str(record.get("execution_id") or "")
        if not execution_id:
            return
        try:
            from thomas.server import precard
            from thomas.server.green_handoff import settle

            chat = str(record.get("session_id") or "")
            checked = await self._check_before_card(execution_id) if promote else None
            if checked is not None and checked.state == precard.UNAVAILABLE and precard.workers.generation_stopping():
                return  # sent away by this server's stop: left as a restart leaves it, never handed in unchecked
            if checked is not None and checked.failed:
                promote = False
                await self._emit_event({"type": "text", "text": f"\n\n{_NOT_HANDED_IN}\n\n{checked.findings}\n\n"})
            line = checked.line if checked is not None and not checked.failed else ""
            submission = await asyncio.to_thread(
                settle,
                execution_id,
                promote=promote,
                summary=text or str(record.get("summary") or ""),
                chat=chat,
                checked=line,
                patch=(checked.patch or None) if checked is not None else None,  # the bytes that were checked
            )
            if submission is not None:
                # The approval happens at the Windows sign-in; the chat that asked
                # mirrors each card, with its pairing code, and then the verdict.
                following = late.call(seams.FOLLOW_SELF_CHANGE, submission.name, chat, checked=line)
                asyncio.create_task(following, name=f"self-fix:{submission.name}")
        except _NOTIFY_EXCEPTIONS:
            log.warning("green was not settled for %s", execution_id, exc_info=True)

    @staticmethod
    async def _check_before_card(execution_id: str) -> Any:
        """The check before your card, off the event loop; None when this run had no green to check.

        ``check_for_hand_in``: the green's processes end first, and a change that moved while it was being
        checked fails, so what ``settle`` hands in is exactly what was checked."""
        from thomas.server import green_checkout, precard

        if await asyncio.to_thread(green_checkout.find_green, execution_id) is None:
            return None
        return await precard.workers.off_the_loop(precard.check_for_hand_in, execution_id)

    def _offer_self_change_review(self, record: dict[str, Any]) -> None:
        """End of the reply: what Thomas changed about himself, undoable."""
        try:
            from thomas.server.self_change_review import offer

            offer(str(record.get("session_id") or ""))
        except _NOTIFY_EXCEPTIONS:
            log.warning("self-change review card was not offered", exc_info=True)


class WorkerHeartbeat:
    """When a worker last showed it was alive, kept where the watchdog can read it
    without the server loop.

    Measured 2026-09-23: a Chat turn's search held that loop for about 120 s and
    145 s; every worker's progress waited on it, and four workers that were working
    were failed together the moment it came back. The worker's thread beats this, and
    so does any helper it spawned; the watchdog on the server loop reads it; neither
    needs the other's loop.

    It also carries the watchdog's stop. Cancelling the task that waited for the
    worker's thread left the thread running: exec-a5ab521aff9c went on to "attempt 2
    of 12" after its card said failed. A stop sets a flag the worker checks between
    attempts and cancels the run inside the worker's own loop.

    Workers run on a pool of their own (``chat_delegation_scheduler``), so one can wait
    for a thread. That wait is not silence, and a stop that comes during it means the
    worker never starts: ``enter`` and ``request_stop`` decide that under one lock.
    """

    def __init__(self, execution_id: str = "") -> None:
        self.execution_id = str(execution_id or "")
        self._lock = threading.Lock()
        self._last: float | None = None
        self._stop = threading.Event()
        self._cancel: Callable[[], None] | None = None
        self._entered = False
        self._waiting = False

    def beat(self) -> None:
        with self._lock:
            self._last = time.monotonic()

    def age_s(self) -> float | None:
        """Seconds since the last beat; None until the worker first shows life."""
        with self._lock:
            last = self._last
        return None if last is None else max(0.0, time.monotonic() - last)

    @property
    def stop_requested(self) -> bool:
        return self._stop.is_set()

    def wait_for_thread(self) -> None:
        """Every worker thread is taken, so this worker waits for one; until it has one it is not silent."""
        with self._lock:
            self._waiting = not self._entered

    @property
    def waiting_for_thread(self) -> bool:
        with self._lock:
            return self._waiting

    def enter(self) -> bool:
        """The worker's thread is starting it. False when a stop came first: the worker then never starts.
        A worker that waited for its thread is silent from now, not from when it was queued."""
        with self._lock:
            if self._stop.is_set():
                return False
            self._entered = True
            if self._waiting:
                self._waiting = False
                self._last = time.monotonic()
            return True

    def bind_cancel(self, cancel: Callable[[], None]) -> None:
        """How to cancel the worker's run, given from its own thread. Used at once if a
        stop came before the thread started."""
        with self._lock:
            self._cancel = cancel
        if self._stop.is_set():
            cancel()

    def request_stop(self) -> bool:
        """Stop the worker. Returns whether its thread had already started it; if not, it never will."""
        with self._lock:
            self._stop.set()
            cancel, entered = self._cancel, self._entered
        if cancel is not None:
            cancel()
        return entered


_HEARTBEATS: dict[str, WorkerHeartbeat] = {}
_HEARTBEATS_LOCK = threading.Lock()


def register_worker_heartbeat(execution_id: str) -> WorkerHeartbeat:
    """A fresh heartbeat for a running worker, findable by its execution id: its
    runner checks it between attempts and its task.spawn helpers beat it."""
    heartbeat = WorkerHeartbeat(execution_id)
    if heartbeat.execution_id:
        with _HEARTBEATS_LOCK:
            _HEARTBEATS[heartbeat.execution_id] = heartbeat
    return heartbeat


def release_worker_heartbeat(heartbeat: WorkerHeartbeat) -> None:
    with _HEARTBEATS_LOCK:
        if _HEARTBEATS.get(heartbeat.execution_id) is heartbeat:
            del _HEARTBEATS[heartbeat.execution_id]


def worker_heartbeat(execution_id: str) -> WorkerHeartbeat | None:
    with _HEARTBEATS_LOCK:
        return _HEARTBEATS.get(str(execution_id or ""))


def beat_worker(execution_id: str) -> None:
    """A sign of life for the running worker with this id, if there is one."""
    heartbeat = worker_heartbeat(execution_id)
    if heartbeat is not None:
        heartbeat.beat()


# Progress hand-overs still waiting for the server loop. Past this many, a new
# progress line is dropped rather than queued; the record on disk keeps the latest.
_MAX_PENDING_PROGRESS = 256


class _ThreadsafeDelegationEmitter:
    """How a worker's thread reports to the server loop.

    Progress no longer waits for that loop. Each event used to be handed over and
    awaited, so whenever the loop was busy the worker stopped at its next step and
    looked silent. Progress is now queued and the worker carries on, and the chat
    still gets every event in the order it was sent. Lifecycle events (started,
    completed, failed, approval) are still awaited, after the progress before them.
    Every hand-over beats the worker's heartbeat, which the watchdog reads directly.
    """

    def __init__(
        self,
        emitter: _DelegationEmitter,
        loop: asyncio.AbstractEventLoop,
        heartbeat: WorkerHeartbeat | None = None,
    ) -> None:
        self._emitter = emitter
        self._loop = loop
        self.heartbeat = heartbeat
        self._order: asyncio.Lock | None = None  # made on the server loop, on first use
        self._pending = 0
        self._pending_lock = threading.Lock()

    async def _in_order(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        # Runs on the server loop. Hand-overs start in the order they were sent and
        # take this lock first, so the chat sees events in the worker's order.
        if self._order is None:
            self._order = asyncio.Lock()
        async with self._order:
            return await getattr(self._emitter, method)(*args, **kwargs)

    def _hand_over(self, method: str, *args: Any, **kwargs: Any) -> concurrent.futures.Future[Any]:
        if self.heartbeat is not None:
            self.heartbeat.beat()
        return asyncio.run_coroutine_threadsafe(self._in_order(method, args, kwargs), self._loop)

    async def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        return await asyncio.wrap_future(self._hand_over(method, *args, **kwargs))

    def _progress_delivered(self, future: concurrent.futures.Future[Any] | None) -> None:
        with self._pending_lock:
            self._pending -= 1
        if future is not None and not future.cancelled() and future.exception() is not None:
            log.warning("a worker progress event was not delivered", exc_info=future.exception())

    async def started(self, record: dict[str, Any], *, specialist_id: str, bot: Any) -> None:
        await self._call("started", record, specialist_id=specialist_id, bot=bot)

    async def progress(self, record: dict[str, Any], *, specialist_id: str, bot: Any, text: str) -> None:
        with self._pending_lock:
            backed_up = self._pending >= _MAX_PENDING_PROGRESS
            if not backed_up:
                self._pending += 1
        if backed_up:
            if self.heartbeat is not None:
                self.heartbeat.beat()
            log.debug("the server loop is behind; a progress line was dropped: %s", str(text)[:80])
            return
        try:
            future = self._hand_over("progress", record, specialist_id=specialist_id, bot=bot, text=text)
        except RuntimeError:  # the server loop is closed; the worker hears it, as before
            self._progress_delivered(None)
            raise
        future.add_done_callback(self._progress_delivered)

    async def completed(self, record: dict[str, Any], *, specialist_id: str, bot: Any, text: str = "") -> None:
        await self._call("completed", record, specialist_id=specialist_id, bot=bot, text=text)

    async def failed(self, record: dict[str, Any], *, specialist_id: str, bot: Any, text: str) -> None:
        await self._call("failed", record, specialist_id=specialist_id, bot=bot, text=text)

    async def approval_needed(self, record: dict[str, Any], *, specialist_id: str, bot: Any, text: str = "") -> None:
        await self._call("approval_needed", record, specialist_id=specialist_id, bot=bot, text=text)
