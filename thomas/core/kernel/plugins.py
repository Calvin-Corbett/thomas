"""Plugins, mounting, and dependency gating.

Phase 3.2 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md).

The load-bearing behaviour here is ``inject`` gating. A plugin declares the
services it needs; the kernel applies it only when every one of them exists, and
un-applies it when one goes away. That turns Thomas's most persistent defect
shape — a correct mechanism with no consumer, four fresh instances found on
2026-09-08 — from an invisible run-time no-op into a mount-time fact you can
list with ``kernel.pending()``.

A plugin is either an object with an ``apply(ctx, config)`` method or a plain
``callable(ctx, config)``. Both may carry ``name`` and ``inject`` attributes.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Protocol, runtime_checkable

from thomas.core.kernel.context import Context, EventBus

log = logging.getLogger(__name__)

# A plugin's apply may set services, which re-triggers settling. Bound so a
# pathological mutual-retrigger cannot spin forever.
_MAX_SETTLE_PASSES = 32


@runtime_checkable
class Plugin(Protocol):
    """The structural contract. Duck-typed — no base class to inherit."""

    name: str
    inject: tuple[str, ...]

    def apply(self, ctx: Context, config: Mapping[str, Any]) -> None: ...


def plugin_name(plugin: Any) -> str:
    return getattr(plugin, "name", None) or getattr(plugin, "__name__", None) or type(plugin).__name__


def plugin_inject(plugin: Any) -> tuple[str, ...]:
    return tuple(getattr(plugin, "inject", ()) or ())


def plugin_apply(plugin: Any) -> Callable[..., Any]:
    """The callable that does the applying: ``.apply`` if present, else the plugin."""
    applier = getattr(plugin, "apply", None)
    if callable(applier):
        return applier
    if callable(plugin):
        return plugin
    raise TypeError(f"{plugin_name(plugin)!r} is not a plugin: needs an apply(ctx, config) method or to be callable")


class Fork:
    """One mounted plugin and the scope holding everything it registered."""

    def __init__(
        self,
        kernel: Kernel,
        plugin: Any,
        config: dict[str, Any],
        parent: Context,
    ) -> None:
        self.kernel = kernel
        self.plugin = plugin
        self.config = config
        self.parent = parent
        self._child: Context | None = None
        self._disposed = False
        self.error: BaseException | None = None
        self.stopping = False
        # What ``stop`` will hand back, once one has begun. A fork stops once, however many ask.
        self.stop_result: asyncio.Future[Any] | None = None

    def __repr__(self) -> str:
        return f"<Fork {plugin_name(self.plugin)!r} {self.state}>"

    @property
    def name(self) -> str:
        return plugin_name(self.plugin)

    @property
    def active(self) -> bool:
        return self._child is not None

    @property
    def state(self) -> str:
        """``pending``, ``active``, ``failed``, ``unloading`` or ``disposed``: the words a status page shows."""
        if self._disposed:
            return "disposed"
        if self.stopping:
            return "unloading"
        if self.error is not None:
            return "failed"
        return "active" if self.active else "pending"

    @property
    def disposed(self) -> bool:
        return self._disposed

    @property
    def ctx(self) -> Context | None:
        """The plugin's own scope, or None while it is pending."""
        return self._child

    @property
    def missing(self) -> tuple[str, ...]:
        """Declared dependencies that no provider has filled."""
        return tuple(name for name in plugin_inject(self.plugin) if not self.parent.has(name))

    def _apply(self) -> None:
        child = self.parent.fork(f"plugin:{self.name}", transparent=True)
        self._child = child
        try:
            plugin_apply(self.plugin)(child, self.config)
        except BaseException as exc:
            # A plugin that dies mid-apply must leave nothing behind. Unwinding
            # here is what makes a failed mount indistinguishable from no mount.
            log.warning("plugin %r failed during apply, unwinding: %s", self.name, exc)
            self._child = None
            child.dispose()
            raise

    def _unapply(self) -> None:
        child, self._child = self._child, None
        if child is not None:
            child.dispose()

    def dispose(self) -> None:
        """Unmount: unwind everything the plugin registered and forget it."""
        if self._disposed:
            return
        self._disposed = True
        self._unapply()
        self.kernel._forget(self)


class Kernel:
    """The root context, the event bus, and the set of mounted plugins."""

    def __init__(self) -> None:
        self.bus = EventBus()
        self.root = Context(self, None, "root")
        self._forks: list[Fork] = []
        self._settling = False
        self._dirty = False
        self.ready = False

    def __repr__(self) -> str:
        return f"<Kernel active={len(self.mounted())} pending={len(self.pending())}>"

    # -- mounting ----------------------------------------------------------

    def mount(
        self,
        plugin: Any,
        config: Mapping[str, Any] | None = None,
        *,
        ctx: Context | None = None,
        tolerate: bool = False,
    ) -> Fork:
        """Mount a plugin. Applies now if its dependencies are met, else waits.

        A plugin that raises raises to the caller and is forgotten, unless ``tolerate`` is set: then the fork stays,
        reads ``failed`` and holds the reason. A host loading rows wants that, because no plugin may stop it starting.
        """
        plugin_apply(plugin)  # fail fast on something that is not a plugin at all
        fork = Fork(self, plugin, dict(config or {}), ctx or self.root)
        self._forks.append(fork)
        try:
            self._settle(raising=None if tolerate else fork)
        except BaseException as exc:
            log.warning("mount of %r failed, forgetting it: %s", plugin_name(plugin), exc)
            self._forget(fork)
            raise
        return fork

    def mounted(self) -> list[Fork]:
        return [fork for fork in self._forks if fork.active]

    def pending(self) -> list[Fork]:
        """Plugins waiting on a service nobody provides. Absence, made visible."""
        return [fork for fork in self._forks if not fork.active and fork.error is None]

    def _forget(self, fork: Fork) -> None:
        try:
            self._forks.remove(fork)
        except ValueError:
            return

    def mark_ready(self, *, strict: bool = False) -> None:
        """The host is up: plugins waiting for that start now.

        A plugin that fails starting reads ``failed`` and the rest carry on, because no plugin may stop the host.
        ``strict=True`` propagates instead, for a plugin author finding out why one does nothing.
        """
        self.ready = True
        for fork in self.mounted():
            try:
                fork.ctx.fire_ready()
            except Exception as exc:
                log.warning("plugin %r failed starting and stays off: %s", fork.name, exc)
                fork.error = exc
                fork._unapply()
                if strict:
                    raise

    # -- settling ----------------------------------------------------------

    def _services_changed(self) -> None:
        """Called by Context.set and its undo. Re-evaluates who can run."""
        if self._settling:
            self._dirty = True
            return
        self._settle()

    def _restart(self, forks: Iterable[Fork]) -> None:
        """Take these forks off, and only then let settling put them back on fresh scopes.

        Each service they withdraw would otherwise settle at once, bringing a fork back while its old scope was still
        unwinding, and back onto a provider that had yet to leave.
        """
        self._settling = True
        try:
            for fork in forks:
                fork._unapply()
        finally:
            self._settling = False
        self._settle()

    def _settle(self, raising: Fork | None = None) -> None:
        self._settling = True
        try:
            for _ in range(_MAX_SETTLE_PASSES):
                self._dirty = False
                for fork in list(self._forks):
                    if fork.disposed or fork.error is not None:
                        continue
                    satisfied = not fork.missing
                    if satisfied and not fork.active:
                        try:
                            fork._apply()
                        except Exception as exc:
                            if fork is raising:
                                raise
                            # A dependant that fails here used to raise into whichever plugin just provided the
                            # service. It stays failed until it is turned on again, as in Cordis.
                            log.warning("plugin %r failed and stays off: %s", fork.name, exc)
                            fork.error = exc
                    elif not satisfied and fork.active:
                        log.debug(
                            "unmounting %r: dependency withdrawn (%s)",
                            fork.name,
                            ", ".join(fork.missing),
                        )
                        fork._unapply()
                if not self._dirty:
                    return
            log.warning(
                "kernel did not settle in %d passes; plugins are re-triggering each other",
                _MAX_SETTLE_PASSES,
            )
        finally:
            self._settling = False

    # -- convenience -------------------------------------------------------

    def dispose(self) -> list[BaseException]:
        """Tear the whole kernel down, plugins first."""
        for fork in list(self._forks):
            fork.dispose()
        return self.root.dispose()
