"""Taking a plugin off a running kernel, and putting one back.

Phase 3.5 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md). 3.2 built the host
and 3.3 moved the runtime in; both of those happen at boot. This module is the
part that happens while Thomas is answering you.

Three properties, and the reason each one is here:

- **Unplug keeps the way back.** ``fork.dispose()`` already unwinds everything a
  plugin registered, but it also forgets the plugin, so "off for a moment" and
  "gone" were the same operation. ``unplug`` returns an :class:`Unplugged` that
  still holds the plugin, its config and the scope it was mounted under — the
  minimum needed to put it back exactly where it was.

- **A failed swap leaves the old one running.** ``swap`` disposes the old fork
  and mounts the new one; if the new plugin raises during ``apply`` — the normal
  outcome of a self-edit with a typo in it — the old plugin is remounted before
  the error is raised. A swap that fails is not a swap that unplugs.

- **Nothing interleaves.** Neither function awaits. On the event loop that runs
  a turn, a swap is therefore indivisible: no ``emit`` can land between the old
  plugin's last subscription going away and the new one's arriving. This is what
  makes "swap it while it is running" mean something other than "swap it and
  hope nothing was mid-dispatch".

What a swap deliberately does not do is preserve the plugin's *position* in the
handler order: the new subscriptions are appended, as any fresh mount's are. The
bus folds every handler's result in turn, so order is observable; a plugin that
depended on running before another must say so with ``inject``, which is the
mechanism that already exists for it.

    from thomas.core.kernel import swap, unplug

    held = unplug(fork)          # its hooks are gone; the plugin is not lost
    fork = held.replug()         # ...and back, same scope, same config

    fork = swap(fork, rebuilt)   # or: replace it with a freshly loaded version
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Mapping
from typing import Any

from thomas.core.kernel.context import Context, KernelError
from thomas.core.kernel.plugins import Fork, plugin_inject, plugin_name

log = logging.getLogger(__name__)


class SelfStop(KernelError):
    """A plugin tried to stop itself from inside its own work, which would wait for itself forever."""


class SwapError(KernelError):
    """A live swap failed.

    ``restored`` is the question a caller actually has: is the old plugin back
    on the bus, or is the kernel now running neither? It is an attribute rather
    than prose in the message so a status surface can report it without parsing
    a string.

    ``fork`` is the *new* fork the restored plugin is running under. A caller
    holding the old one has a disposed handle to a plugin that is very much
    alive, which would read as "unmounted" everywhere it is checked; handing the
    live fork back with the error is what keeps a failed reload from looking
    like a successful unplug.
    """

    def __init__(self, message: str, *, restored: bool, fork: Fork | None = None) -> None:
        super().__init__(message)
        self.restored = restored
        self.fork = fork


class Unplugged:
    """A plugin taken off the kernel, holding everything needed to put it back.

    Deliberately not a ``Fork``: a fork is a *mounted* thing, and conflating the
    two is how "unplugged" quietly starts reading as "still there". Nothing this
    object holds is registered on the kernel — the plugin's subscriptions, its
    services and its child scope are already unwound.

    ``errors`` is what went wrong during ``stop`` on the way here. A failed step does not cost a plugin its stop, but it
    may have left something open, and by now the scope that could have said so is gone.
    """

    __slots__ = ("kernel", "plugin", "config", "parent", "name", "errors")

    def __init__(self, kernel: Any, plugin: Any, config: Mapping[str, Any], parent: Context) -> None:
        self.kernel = kernel
        self.plugin = plugin
        self.config = dict(config or {})
        self.parent = parent
        self.name = plugin_name(plugin)
        self.errors: tuple[BaseException, ...] = ()

    def __repr__(self) -> str:
        return f"<Unplugged {self.name!r}>"

    def replug(self, plugin: Any = None, config: Mapping[str, Any] | None = None) -> Fork:
        """Mount it again, in the same scope, with the same config by default.

        ``plugin`` overrides what goes back — that is the reload case, where the
        thing returning is a freshly imported instance of the same plugin rather
        than the object that came off.
        """
        target = self.plugin if plugin is None else plugin
        settings = self.config if config is None else dict(config)
        if self.parent.disposed:
            raise SwapError(
                f"cannot replug {self.name!r}: the scope it was mounted under is gone",
                restored=False,
            )
        return self.kernel.mount(target, settings, ctx=self.parent)


def unplug(fork: Fork) -> Unplugged:
    """Take a mounted plugin off the kernel without losing it.

    Everything it registered unwinds, exactly as it would on ``dispose``. What
    comes back is the handle that can undo the unplugging.
    """
    if fork.disposed:
        raise SwapError(f"{fork.name!r} is already unplugged", restored=False)
    held = Unplugged(fork.kernel, fork.plugin, fork.config, fork.parent)
    fork.dispose()
    log.debug("unplugged %r", held.name)
    return held


def _dependants(fork: Fork, spare: Iterable[Fork] = ()) -> list[Fork]:
    """What must stop before this fork: whatever injects a service it provides, and theirs, each before its provider.

    Depth first, adding a fork only once everything that depends on it is in. A fork reached twice, as in a diamond,
    then still lands ahead of every provider it uses, which the order things were found in does not promise.
    """
    ordered: list[Fork] = []
    seen = {fork, *spare}

    def visit(provider: Fork) -> None:
        offered = provider.ctx.provided if provider.ctx is not None else frozenset()
        for other in provider.kernel.mounted():
            if other not in seen and offered.intersection(plugin_inject(other.plugin)):
                seen.add(other)
                visit(other)
                ordered.append(other)

    visit(fork)
    return ordered


def _stop_chain(fork: Fork, spare: Iterable[Fork]) -> tuple[list[Fork], list[Context]]:
    """Who a stop of this fork takes down, in order, and their scopes."""
    chain = [*_dependants(fork, spare), fork]
    return chain, [member.ctx for member in chain if member.ctx is not None]


def stop_would_wait(fork: Fork) -> bool:
    """Whether a stop of this fork has running work to wait for, in the fork or in anything that uses it."""
    return any(scope.working > 0 for scope in _stop_chain(fork, ())[1])


def refuse_self_stop(fork: Fork, *, spare: Iterable[Fork] = ()) -> None:
    """Raise ``SelfStop`` if a stop of this fork would wait for the code asking for it.

    ``stop`` asks this first. A host that changes something before it stops a fork asks too, because by the time ``stop``
    refuses, what it changed already says the fork is on its way off.
    """
    if any(scope.inside for scope in _stop_chain(fork, spare)[1]):
        raise SelfStop(f"{fork.name!r} cannot be stopped from inside its own work")


async def _take_off(fork: Fork, chain: list[Fork], scopes: list[Context], *, force: bool) -> Unplugged:
    """The one stop this fork gets: every scope in ``chain`` finishes, then the fork unplugs."""
    for member in chain:
        member.stopping = True
    failures: list[BaseException] = []
    try:
        for scope in scopes:
            if force:
                scope.cancel_work()
            failures.extend(await scope.drain())
    finally:
        for member in chain:
            member.stopping = False
    held = unplug(fork)
    held.errors = tuple(failures)
    # A dependant outlives its provider when an older value of the service comes back. It has already stopped, so it
    # starts again on a fresh scope rather than stay up as a shell that refuses all work.
    fork.kernel._restart([member for member in chain if member.ctx in scopes])
    return held


async def stop(fork: Fork, *, force: bool = False, spare: Iterable[Fork] = ()) -> Unplugged:
    """Take a plugin off once its running work has finished, dependants first.

    Each scope runs its drain steps, waits for running work, cancels its owned tasks, then runs its stop steps, and a
    dependant finishes all of that before its provider begins. The waiting happens here, and ``unplug`` at the end
    still never awaits, so the swap itself stays indivisible. A plain stop has no time limit. ``force`` ends the work
    instead and limits every wait by ``FORCED_STEP_SECONDS``, because shutdown has no second press and Thomas must always
    be able to close: what ignores being cancelled is left running, named in the log and in ``errors``, and the stop
    finishes. A stop already waiting can be ended the same way with ``Context.cancel_work``, wherever it is stuck.

    A fork stops once, however many ask. A stop that finds one under way waits for it and returns the same
    ``Unplugged``, and if it is forced it ends what that stop is waiting for. If the stop it waited on was cancelled,
    it takes over.

    ``spare`` names forks this stop leaves up even though they use this one, for a host taking back a plugin that failed
    the moment it arrived. What was already running cannot have used it, so its failure is no reason to disturb them. A
    spared fork that loses its only provider still goes when that service does, by ``dispose`` rather than a stop.

    A plugin cannot stop itself from inside its own work, because it would wait for itself: a toggle from inside a turn
    deadlocked the host in DeepSeek Harness (discussion 10826).
    """
    refuse_self_stop(fork, spare=spare)
    chain, scopes = _stop_chain(fork, spare)
    while (running := fork.stop_result) is not None:
        if force:
            for scope in scopes:
                scope.cancel_work()
        await asyncio.wait({running})
        if not running.cancelled():
            return running.result()
    running = fork.stop_result = asyncio.get_running_loop().create_future()
    try:
        running.set_result(await _take_off(fork, chain, scopes, force=force))
    finally:
        if not running.done():
            fork.stop_result = None
            running.cancel()
    return running.result()


def swap(fork: Fork, new_plugin: Any, config: Mapping[str, Any] | None = None) -> Fork:
    """Replace a mounted plugin with another one, atomically.

    On success the old plugin's registrations are gone and the new plugin's are
    live. On failure the old plugin is back and :class:`SwapError` says so, so a
    caller never has to guess which half of the operation it is looking at.
    """
    held = unplug(fork)
    settings = held.config if config is None else dict(config)
    try:
        replacement = held.kernel.mount(new_plugin, settings, ctx=held.parent)
    except BaseException as exc:
        # The new plugin failed to apply. Its own scope already unwound inside
        # Fork._apply, so there is nothing of it left to clean up — only the
        # hole where the old one used to be.
        # BaseException, matching Fork._apply: a plugin that dies for any reason
        # at all must not leave the kernel running neither version. Both paths
        # below log and re-raise, so nothing is swallowed.
        try:
            restored_fork = held.replug()
        except BaseException as restore_exc:
            log.error(
                "swap of %r failed AND the previous plugin could not be restored: %s",
                held.name,
                restore_exc,
            )
            raise SwapError(
                f"swap of {held.name!r} failed and it could not be restored: {restore_exc}",
                restored=False,
            ) from exc
        log.warning("swap of %r failed; the previous version is still running: %s", held.name, exc)
        raise SwapError(
            f"swap of {held.name!r} failed ({exc}); the previous version is still running",
            restored=True,
            fork=restored_fork,
        ) from exc
    log.info("swapped %r for %r", held.name, plugin_name(new_plugin))
    return replacement


__all__ = ["SelfStop", "SwapError", "Unplugged", "refuse_self_stop", "stop", "swap", "unplug"]
