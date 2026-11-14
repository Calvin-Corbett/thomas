"""Contexts, reversible effects, and the event bus.

Phase 3.2 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md). This module is the
bottom of the tree: it imports nothing from Thomas, which is what lets every
other layer sit on top of it without an inversion.

The one idea worth holding: **a registration is an effect that knows its own
undo**. ``thomas/tools/registry.py`` today is a dict whose ``unregister`` is a
manual delete — nothing records who added what, so removing a contributor
cleanly is not possible. Here, every ``set``, ``on`` and ``fork`` pushes its
reversal onto a stack, and disposing runs the stack backwards.

Scope semantics, which are easy to get wrong:

- ``ctx.fork()`` is **opaque** — the child gets its own service store, so it can
  shadow a parent's service without mutating it. This is how one agent gets its
  own view.
- ``ctx.fork(transparent=True)`` is what a plugin gets. Its ``set`` writes
  through to the parent's store so siblings and consumers can actually resolve
  the service, while the *undo* stays on the child's stack. Contribution is
  shared; teardown is scoped. Without this a plugin would mount successfully and
  be invisible to everyone — the precise defect this kernel exists to prevent.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import weakref
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Iterable, Mapping
from contextvars import ContextVar
from typing import Any

log = logging.getLogger(__name__)

_MISSING: Any = object()

# The plugin scopes the running code is inside, so a plugin cannot wait for itself to finish.
_working_in: ContextVar[frozenset[Any]] = ContextVar("thomas_kernel_working_in", default=frozenset())

# How long a forced stop gives each thing it waits for, and again for a step to end once it is cancelled. Force is the
# one stop that has said not to wait, and shutdown has no second press, so nothing may hang it. A plain stop has no limit.
FORCED_STEP_SECONDS = 10.0

# Plugin code nothing is waiting for any more, and which may never end. Python's close waits for every task with no limit,
# so whatever closes the process has to be told about these. Weak, so that one which does end leaves by itself.
_left_behind: weakref.WeakSet[asyncio.Future[Any]] = weakref.WeakSet()

Disposer = Callable[[], None]


def left_behind() -> set[asyncio.Future[Any]]:
    """What a forced stop went on without, and owned tasks whose scope went with no stop to wait for them."""
    return set(_left_behind)


def _step_name(step: Callable[..., Any]) -> str:
    """What the log calls a step. A cleanup hook reaches the stop inside a partial, which has no name of its own."""
    wrapped = getattr(step, "func", step)
    return getattr(wrapped, "__qualname__", repr(wrapped))


class KernelError(Exception):
    """Base for every kernel failure."""


class ServiceNotFound(KernelError):
    """A seam was resolved that no provider ever filled.

    Raised rather than returning ``None`` on purpose: a silent ``None`` is how a
    missing provider becomes a no-op nobody notices.
    """

    def __init__(self, name: str, available: Iterable[str] = ()) -> None:
        self.name = name
        self.available = tuple(sorted(available))
        known = ", ".join(self.available) if self.available else "(none)"
        super().__init__(f"no service named {name!r}; available: {known}")


class ContextDisposed(KernelError):
    """Something tried to register on a scope that has been torn down, or to start work on one being torn down."""


class DisposalStack:
    """Undo callables, run in reverse. The unit of reversibility."""

    __slots__ = ("_undos", "_disposed")

    def __init__(self) -> None:
        self._undos: list[Disposer] = []
        self._disposed = False

    @property
    def disposed(self) -> bool:
        return self._disposed

    @property
    def pending(self) -> int:
        """How many undos are still queued.

        Observability, not bookkeeping: a scope whose count only ever rises is
        holding onto effects that already ran, which is the shape of a leak.
        """
        return len(self._undos)

    def push(self, undo: Disposer) -> Disposer:
        """Record an undo; return a disposer that runs just this one, once."""
        if self._disposed:
            raise ContextDisposed("cannot register on a disposed scope")
        self._undos.append(undo)

        def disposer() -> None:
            try:
                self._undos.remove(undo)
            except ValueError:
                return  # already run, by us or by a full dispose()
            undo()

        return disposer

    def drop(self, undo: Disposer) -> bool:
        """Forget an undo *without* running it. True if it was still queued.

        For the one case where the undo has become unnecessary rather than
        unwanted: the thing it would have torn down has torn itself down. Every
        other caller wants the disposer ``push`` returns.
        """
        try:
            self._undos.remove(undo)
        except ValueError:
            return False
        return True

    def dispose(self, *, strict: bool = False) -> list[BaseException]:
        """Run every undo in reverse. Idempotent.

        Teardown must finish even when one undo misbehaves, so failures are
        collected and returned rather than raised — a half-unwound scope leaks
        exactly the registrations this class exists to remove. Callers who would
        rather hear about it immediately (tests, CI, a plugin author debugging a
        bad teardown) pass ``strict=True``.
        """
        if self._disposed:
            return []
        self._disposed = True
        errors: list[BaseException] = []
        while self._undos:
            undo = self._undos.pop()
            try:
                undo()
            except Exception as exc:
                log.warning("disposal effect failed (non-fatal): %s", exc)
                errors.append(exc)
                if strict:
                    raise
        return errors


class EventBus:
    """Async fan-out with isolated failures that hands back handler results.

    Returning results is deliberate. Thomas's current plugin hooks discard what
    a handler returns (``loop_core.py`` says so in as many words), which is why
    528 extension packs return modified payloads that nothing reads.
    """

    __slots__ = ("_handlers",)

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[..., Any]]] = {}

    def on(self, event: str, handler: Callable[..., Any]) -> Disposer:
        self._handlers.setdefault(event, []).append(handler)

        def off() -> None:
            handlers = self._handlers.get(event)
            if handlers is None:
                return
            try:
                handlers.remove(handler)
            except ValueError:
                return
            if not handlers:
                self._handlers.pop(event, None)

        return off

    async def emit(self, event: str, *args: Any, strict: bool = False, **kwargs: Any) -> list[Any]:
        """Deliver to every subscriber; return what they returned.

        One bad subscriber must never stop a turn, so handler failures are
        logged and skipped. ``strict=True`` propagates instead, which is what a
        plugin author wants while finding out why their handler does nothing.
        """
        results: list[Any] = []
        for handler in list(self._handlers.get(event, ())):
            try:
                outcome = handler(*args, **kwargs)
                if inspect.isawaitable(outcome):
                    outcome = await outcome
            except Exception as exc:
                log.warning("handler for %r failed (non-fatal): %s", event, exc)
                if strict:
                    raise
                continue
            results.append(outcome)
        return results

    async def fold(
        self,
        event: str,
        payload: Mapping[str, Any] | None = None,
        *,
        strict: bool = False,
    ) -> dict[str, Any]:
        """Thread one payload through every subscriber in turn.

        ``emit`` hands each handler the same arguments and returns their answers
        side by side. That is right for a notification and wrong for a hook: two
        plugins that each append to ``payload["marks"]`` both compute their list
        from the *original* payload, so whoever merges the results afterwards
        keeps only the last one — two mounted plugins contributing, one
        contribution surviving. Folding gives each handler what the ones before
        it produced, so a chain of plugins composes instead of overwriting.

        Handler failures are isolated exactly as in ``emit``: the fold carries on
        with the payload as far as it got, because one bad plugin must not cost a
        turn the work every other plugin did.

        A handler returning something that is not a mapping contributes nothing
        to the payload and is not an error — ``None`` is what a hook that only
        observes returns.
        """
        merged: dict[str, Any] = dict(payload or {})
        for handler in list(self._handlers.get(event, ())):
            try:
                outcome = handler(merged)
                if inspect.isawaitable(outcome):
                    outcome = await outcome
            except Exception as exc:
                log.warning("handler for %r failed (non-fatal): %s", event, exc)
                if strict:
                    raise
                continue
            if isinstance(outcome, Mapping):
                merged.update(outcome)
        return merged

    def handler_count(self, event: str) -> int:
        return len(self._handlers.get(event, ()))


class Context:
    """A scope: services, subscriptions, children, and their teardown."""

    def __init__(
        self,
        kernel: Any,
        parent: Context | None = None,
        label: str = "root",
        *,
        transparent: bool = False,
    ) -> None:
        self._kernel = kernel
        self._parent = parent
        self._transparent = transparent and parent is not None
        self.label = label
        self._services: dict[str, Any] = {}
        self._stack = DisposalStack()
        self._provided: set[str] = set()
        self._tasks: dict[asyncio.Task[Any], Disposer] = {}
        self._working: list[asyncio.Task[Any] | None] = []
        self._idle = asyncio.Event()
        self._idle.set()
        self._drains: list[Callable[[], Awaitable[None]]] = []
        self._stopped: list[Callable[[], Awaitable[None]]] = []
        self._closing: asyncio.Task[None] | None = None
        self._closed = asyncio.Event()
        self._stepping: asyncio.Task[Any] | None = None
        self._step_name = ""
        self._leaving: asyncio.TimerHandle | None = None
        self._stop_errors: list[BaseException] = []
        self._refusing = False
        self._forced = asyncio.Event()
        self._readies: list[Callable[[], Any]] = []

    def __repr__(self) -> str:
        return f"<Context {self.label!r} disposed={self.disposed}>"

    @property
    def parent(self) -> Context | None:
        return self._parent

    @property
    def kernel(self) -> Any:
        return self._kernel

    @property
    def disposed(self) -> bool:
        return self._stack.disposed

    @property
    def pending_effects(self) -> int:
        """Undos this scope is still holding. Reported by ``seam_report``.

        A number worth being able to read: on a long-running Thomas it only ever
        rises if something registers effects it never unwinds, and the point of
        this kernel is that such a thing is visible rather than inferred from
        memory growth.
        """
        return self._stack.pending

    # -- service storage ---------------------------------------------------

    def _store(self) -> dict[str, Any]:
        """Where this scope's ``set`` actually writes.

        A transparent (plugin) scope writes through to its parent so consumers
        can resolve what it contributes; an opaque fork keeps its own.
        """
        if self._transparent and self._parent is not None:
            return self._parent._store()
        return self._services

    def _guard(self) -> None:
        if self._stack.disposed:
            raise ContextDisposed(f"scope {self.label!r} is disposed")

    def _guard_work(self) -> None:
        """Refuse new work once a stop is done waiting for it: what comes next promises that nothing runs under it."""
        self._guard()
        if self._refusing:
            raise ContextDisposed(f"scope {self.label!r} is stopping")

    def _known_service_names(self) -> list[str]:
        names: list[str] = []
        scope: Context | None = self
        while scope is not None:
            names.extend(scope._services)
            scope = scope._parent
        return names

    # -- services ----------------------------------------------------------

    def has(self, name: str) -> bool:
        scope: Context | None = self
        while scope is not None:
            if name in scope._services:
                return True
            scope = scope._parent
        return False

    def get(self, name: str, default: Any = _MISSING) -> Any:
        scope: Context | None = self
        while scope is not None:
            if name in scope._services:
                return scope._services[name]
            scope = scope._parent
        if default is _MISSING:
            raise ServiceNotFound(name, self._known_service_names())
        return default

    def set(self, name: str, value: Any) -> Disposer:
        """Provide a service. Returns the disposer that withdraws it."""
        self._guard()
        store = self._store()
        had = name in store
        previous = store.get(name)
        store[name] = value
        self._provided.add(name)

        def undo() -> None:
            self._provided.discard(name)
            # Only withdraw what is still ours. If someone set a newer value on
            # top, theirs wins — an unwind must never clobber a live provider.
            if store.get(name, _MISSING) is not value:
                return
            if had:
                store[name] = previous
            else:
                store.pop(name, None)
            self._kernel._services_changed()

        disposer = self._stack.push(undo)
        self._kernel._services_changed()
        return disposer

    def __getitem__(self, name: str) -> Any:
        return self.get(name)

    def __contains__(self, name: str) -> bool:
        return self.has(name)

    # -- effects, events, scopes -------------------------------------------

    def effect(self, undo: Disposer) -> Disposer:
        """Register an arbitrary reversal on this scope."""
        self._guard()
        return self._stack.push(undo)

    def on(self, event: str, handler: Callable[..., Any]) -> Disposer:
        self._guard()
        off = self._kernel.bus.on(event, handler)
        return self._stack.push(off)

    @property
    def provided(self) -> frozenset[str]:
        """The services this scope is providing right now."""
        return frozenset(self._provided)

    @property
    def working(self) -> int:
        """How many pieces of work a stop would wait for, counting a stop step it is partway through."""
        closing = self._closing is not None and not self._closing.done()
        return len(self._working) + (1 if closing else 0)

    @property
    def inside(self) -> bool:
        """True when the calling code is this scope's own work."""
        return self in _working_in.get()

    @contextlib.asynccontextmanager
    async def busy(self) -> AsyncIterator[None]:
        """Mark work in progress. Stopping this plugin waits until it ends."""
        self._guard_work()
        task = asyncio.current_task()
        self._working.append(task)
        self._idle.clear()
        token = _working_in.set(_working_in.get() | {self})
        try:
            yield
        finally:
            _working_in.reset(token)
            self._working.remove(task)
            if not self._working:
                self._idle.set()

    def task(self, factory: Callable[[], Coroutine[Any, Any, Any]], *, name: str) -> asyncio.Task[Any]:
        """Start background work this plugin owns. It is cancelled when the plugin stops.

        It is also an effect like any other, so it is cancelled if the scope goes by another road, such as an ``apply``
        that raises or a dependency withdrawn. ``dispose`` cannot wait for it to end, but with the scope gone no stop
        could ever reach it.
        """
        self._guard_work()
        # The task keeps its own copy, so a stop from inside it is refused. The caller is not the task, and is left as it was.
        token = _working_in.set(_working_in.get() | {self})
        try:
            task = asyncio.get_running_loop().create_task(factory(), name=f"{self.label}:{name}")
        finally:
            _working_in.reset(token)

        def cancel() -> None:
            task.cancel()
            _left_behind.add(task)  # a stop cancels what it waits for itself, so here the scope went by another road

        self._tasks[task] = cancel
        self._stack.push(cancel)
        task.add_done_callback(self._task_ended)
        return task

    def _task_ended(self, task: asyncio.Task[Any]) -> None:
        self._stack.drop(self._tasks.pop(task))
        if not task.cancelled() and task.exception() is not None:
            log.error("background task %s died: %s", task.get_name(), task.exception())

    def on_drain(self, step: Callable[[], Awaitable[None]]) -> None:
        """Add a step to run while stopping, before the wait for running work."""
        self._guard()
        self._drains.append(step)

    def on_stopped(self, step: Callable[[], Awaitable[None]]) -> None:
        """Add a step to run while stopping, once running work and owned tasks have ended.

        This is for teardown that must not fire under live work, which ``on_drain`` cannot promise. The plugin is still
        plugged in, so its services are there to use. Newest first, like every other undo here. Only ``stop`` runs these,
        because they await: anything that goes straight to ``dispose`` skips them, and ``dispose`` logs that it did.

        One limit. Cancelling an owned task ends its await, not a worker thread it started, because Python cannot stop a
        thread. So a step can run while such a thread is still working, and a step that must not run beside that work has
        to wait for the thread itself.
        """
        self._guard()
        self._stopped.append(step)

    def on_ready(self, start: Callable[[], Any]) -> None:
        """Run ``start`` once the host is up: now if it already is, which is a plugin turned on later."""
        self._guard()
        if self._kernel.ready:
            start()
        else:
            self._readies.append(start)

    def fire_ready(self) -> None:
        starts, self._readies = self._readies, []
        for start in starts:
            start()

    async def drain(self, *, strict: bool = False) -> list[BaseException]:
        """Let this scope's work finish, then run its stop steps. Nothing is unregistered: that is ``dispose``.

        One bad step must not cost a plugin its stop, so a failure is logged, skipped and returned, as in ``dispose``.
        ``strict=True`` propagates instead, which is what a plugin author wants while finding out why a step does
        nothing. Stop steps all get their turn before it does, because half a teardown is worse than a late complaint.

        A forced stop always ends, because Thomas must always be able to close. Python cannot end code that ignores being
        cancelled, so what outlasts its limit is left running, named in the log and returned with the failures.
        """
        failures: list[BaseException] = []
        steps, self._drains = self._drains, []
        for step in steps:
            try:
                await self._drain_step(step)
            except Exception as exc:
                log.warning("drain step for %r failed (non-fatal): %s", self.label, exc)
                failures.append(exc)
                if strict:
                    raise
        await self._work_ended()
        if self._closing is None:
            self._begin_stop_steps()
        await self._closed.wait()
        if not self._closing.cancelled():
            self._closing.exception()  # read, or asyncio reports it as lost: ``_stop_errors`` has every failure
        failures.extend(self._stop_errors)
        if strict and self._stop_errors:
            raise self._stop_errors[0]
        return failures

    async def _until_ended(self, waiting: set[asyncio.Future[Any]]) -> set[asyncio.Future[Any]]:
        """Wait for these and hand back what has not ended, which a plain stop never does: only force limits this wait.

        A press during the wait cancels what is being waited for. Once a stop is forced, ``FORCED_STEP_SECONDS`` is what
        they get. Waits only while there is something to wait for.
        """
        if waiting and not self._forced.is_set():
            pressed = asyncio.ensure_future(self._forced.wait())
            try:
                while waiting and not pressed.done():
                    await asyncio.wait({*waiting, pressed}, return_when=asyncio.FIRST_COMPLETED)
                    waiting = {future for future in waiting if not future.done()}
            finally:
                pressed.cancel()
            for future in waiting:
                future.cancel()
        if waiting:
            _, waiting = await asyncio.wait(waiting, timeout=FORCED_STEP_SECONDS)
        return waiting

    def _left_running(self, kind: str, name: str, left: asyncio.Future[Any]) -> None:
        """Name what a forced stop went on without. Nothing can end it, and by now the name is all a stop can give."""
        problem = KernelError(f"a forced stop of {self.label!r} left {kind} {name} running")
        log.error("%s", problem)
        self._stop_errors.append(problem)
        _left_behind.add(left)

    def _left_step_ended(self, step: asyncio.Future[Any]) -> None:
        """A step no stop is waiting for has ended, so if it failed the log is the only place left to say so."""
        if not step.cancelled() and step.exception() is not None:
            log.warning("a step of %r that a stop went on without failed later: %s", self.label, step.exception())

    async def _drain_step(self, step: Callable[[], Awaitable[None]]) -> None:
        """One drain step, a task only so that a forced stop can go on without it. Raises what the step raised.

        Forced, it gets ``FORCED_STEP_SECONDS`` and is then cancelled, as a stop step is, and it gets that long to end. A
        press during a plain wait has done both already, so what is left then has had its limit.
        """
        running = asyncio.ensure_future(step())
        forced_from_the_start = self._forced.is_set()
        try:
            left = await self._until_ended({running})
            if left and forced_from_the_start:
                running.cancel()
                left = await self._until_ended(left)
        except asyncio.CancelledError:
            running.cancel()  # the stop itself was cancelled, and a step it was inside goes with it
            raise
        finally:
            if not running.done():
                running.add_done_callback(self._left_step_ended)
        if left:
            self._left_running("drain step", _step_name(step), running)
        elif running.cancelled():
            raise KernelError(f"a drain step for {self.label!r} was ended before it finished")
        else:
            running.result()

    async def _work_ended(self) -> None:
        """Return once nothing is running and no owned task is left, or a forced stop has gone on without what is."""
        # A loop because waking is not proof: more work may have begun between the last piece ending and this turn.
        while self._working:
            idle = asyncio.ensure_future(self._idle.wait())
            try:
                left = await self._until_ended({idle})
            finally:
                idle.cancel()
            if left:
                for task in self._working:
                    if task is not None:
                        self._left_running("work", task.get_name(), task)
                break
        # Nothing awaits between that loop ending and this line, so no work can start before new work is refused. That
        # covers owned tasks too: one that starts a replacement as it ends would otherwise keep a stop here forever.
        self._refusing = True
        tasks: set[asyncio.Future[Any]] = set(self._tasks)
        for task in tasks:
            task.cancel()
        for task in await self._until_ended(tasks):
            self._left_running("owned task", task.get_name(), task)

    def _begin_stop_steps(self) -> None:
        name = f"{self.label}:stop steps"
        self._closing = asyncio.get_running_loop().create_task(self._run_stop_steps(), name=name)
        self._closing.add_done_callback(self._stop_steps_ended)

    def _stop_steps_ended(self, steps: asyncio.Task[None]) -> None:
        if steps is self._closing:
            self._closed.set()
        else:
            self._left_step_ended(steps)

    def _leave_stop_step(self, stepping: asyncio.Task[Any]) -> None:
        """A stop step ignored being cancelled and has had its limit, so another task takes the steps after it."""
        self._leaving = None
        self._left_running("stop step", self._step_name, stepping)
        self._begin_stop_steps()

    async def _run_stop_steps(self) -> None:
        """Every stop step, once. A task of its own, which every stop waits for, for two reasons.

        Force can end a stuck step without ending the stop, and a stop that is cancelled leaves the step running rather
        than half done, for the next stop to find.
        """
        _working_in.set(_working_in.get() | {self})  # this task's own copy: a step cannot stop its own plugin either
        # Only now can it be cancelled. A task cancelled before its first turn never runs, which would skip every step.
        self._stepping = asyncio.current_task()
        await self._next_stop_step()

    async def _next_stop_step(self) -> None:
        """One stop step, then the rest, in ``finally`` so that a step that fails cannot cost the ones after it."""
        if asyncio.current_task() is not self._closing:
            return  # the step this task ran was left behind, and another task has the rest
        if self._leaving is not None:
            self._leaving.cancel()
            self._leaving = None
        if not self._stopped:
            return
        step = self._stopped.pop()
        self._step_name = _step_name(step)
        loop = asyncio.get_running_loop()
        limit = loop.call_later(FORCED_STEP_SECONDS, self.cancel_work) if self._forced.is_set() else None
        try:
            await step()
        except asyncio.CancelledError:
            # What ``cancel_work`` does to a stuck step. The steps after it still get their turn.
            log.warning("stop step for %r was ended before it finished", self.label)
            self._stop_errors.append(KernelError(f"a stop step for {self.label!r} was ended before it finished"))
        except Exception as exc:
            log.warning("stop step for %r failed (non-fatal): %s", self.label, exc)
            self._stop_errors.append(exc)  # ``drain`` hands this on, and raises it for a strict caller
            raise
        finally:
            if limit is not None:
                limit.cancel()
            await self._next_stop_step()

    def cancel_work(self) -> None:
        """End running work rather than wait for it: what a forced stop does. A stuck stop step counts as work.

        It holds for what comes next too. This scope takes no new work, every wait left in this stop has a limit, and a
        step that has yet to begin gets ``FORCED_STEP_SECONDS``. Each step is let begin, because force is not a reason to
        skip cleaning up. A stop step that ignores this is left behind ``FORCED_STEP_SECONDS`` later.
        """
        self._forced.set()
        self._refusing = True
        for task in list(self._working):
            if task is not None:
                task.cancel()
        stepping = self._stepping
        if stepping is not None and not stepping.done():
            stepping.cancel()
            if self._leaving is None:
                self._leaving = stepping.get_loop().call_later(FORCED_STEP_SECONDS, self._leave_stop_step, stepping)

    async def emit(self, event: str, *args: Any, strict: bool = False, **kwargs: Any) -> list[Any]:
        return await self._kernel.bus.emit(event, *args, strict=strict, **kwargs)

    async def fold(
        self,
        event: str,
        payload: Mapping[str, Any] | None = None,
        *,
        strict: bool = False,
    ) -> dict[str, Any]:
        """Dispatch a hook: every subscriber in turn, each seeing the last one's work."""
        return await self._kernel.bus.fold(event, payload, strict=strict)

    def fork(self, label: str = "fork", *, transparent: bool = False) -> Context:
        """Open a child scope that dies with this one.

        The parent holds ``child.dispose`` so the child cannot outlive it; the
        child takes that entry back off the parent when it disposes itself (see
        ``dispose``), so a scope that opens and closes children all day does not
        make the parent's stack grow.
        """
        self._guard()
        child = Context(self._kernel, self, label, transparent=transparent)
        self._stack.push(child.dispose)
        return child

    def dispose(self, *, strict: bool = False) -> list[BaseException]:
        """Unwind this scope, and stop the parent from holding it afterwards.

        Dropping our entry from the parent is the other half of ``fork``. Without
        it every mount left a disposed ``Context`` on the root's stack forever —
        measured at about 410 bytes per reload, replug or swap, and the root's
        count rose 10 -> 110 over 100 mounts of the same plugin. The stack is the
        kernel's record of what still needs undoing, and a scope that has already
        unwound is not that. Dropped before the unwind rather than after, so a
        ``strict=True`` failure mid-teardown cannot leave the entry behind.
        """
        if self._parent is not None and not self._stack.disposed:
            self._parent._stack.drop(self.dispose)
        if self._stopped and not self._stack.disposed:
            # Disposing never awaits, so it cannot run them. Teardown that was promised and skipped must not be silent.
            log.warning("%r went without a stop, so %d stop step(s) did not run", self.label, len(self._stopped))
        return self._stack.dispose(strict=strict)
