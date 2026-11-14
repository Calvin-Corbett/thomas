"""Server plugin mounts and the tools provider they extend at startup.

Phase 3.5 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md).

Startup registers the server's tool registry on the kernel, then mounts two
independent things: the supervisor that holds installed plugins
(``plugin_supervisor``), and the other three plugin systems as kernel services
(``plugin_systems_kernel``). Both mounts run third-party code, so either can
fail — and the failure of one must not cost the other.

**One try each, deliberately.** A shared ``except`` around both mounts produces a
specific defect: the supervisor is stored, the systems mount raises, the handler
sets *both* handles to None, and a supervisor that is still on the bus is now
unreachable. Nothing disposes it at cleanup, and ``/api/plugins/kernel`` answers
"not supervised in this process" about plugins that are running. Neither mount is
a boot requirement either way: Thomas starts without plugin hooks, never not at
all.

This lives beside ``app_routes_init`` rather than inside it so the contract can
be exercised directly — ``tests/test_plugin_startup_wiring.py`` drives these two
functions against a bare ``web.Application`` instead of standing up route
families to reach a nested handler.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from thomas.agent.kernel_wiring import register_tools_provider
from thomas.core.kernel import RUNS, SESSIONS, Context, KernelError, RunsSeam, SessionsSeam, require
from thomas.server.app_keys import APP_TOOLS

log = logging.getLogger(__name__)

#: Where the app keeps each handle. ``plugin_kernel_routes`` reads the first one
#: under its own name, imported from here so the string is written once.
APP_PLUGIN_SUPERVISOR = "thomas_mounted_plugins"
APP_PLUGIN_SYSTEMS = "thomas_plugin_systems"

#: A mutable set, placed on the app at mount time, naming the handles already
#: unwound. Cleanup mutates *this* rather than the app: aiohttp freezes the
#: application before ``on_cleanup`` runs, and assigning a key after the freeze
#: raises a DeprecationWarning per app teardown -- 42 in the main suite and about
#: 907 across the 71 test files that build a real app. Reads are fine frozen;
#: writes are what is deprecated.
APP_PLUGIN_UNMOUNTED = "thomas_plugin_handles_unmounted"
APP_TOOLS_DISPOSER = "thomas_kernel_tools_disposer"
APP_SESSION_DISPOSERS = "thomas_kernel_session_disposers"

#: How mounting plugins at startup fails without it being a bug in Thomas: a
#: plugin's own import error, a manifest of the wrong shape, an unreadable
#: install root -- and KernelError, which is none of those and is what a kernel
#: whose root scope is gone raises at anything registering on it.
PLUGIN_MOUNT_ERRORS = (
    KernelError,
    ImportError,
    AttributeError,
    KeyError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)


def provide_session_services(scope: Context) -> list[Any]:
    """Put the sessions slot and the run log on *scope*, each checked against its seam. Returns the undos.

    ``kernel_wiring`` may not import ``thomas/chat``, so the server sets these, on the process kernel at startup and on
    its own kernel when the rows load.
    """
    from thomas.chat.session_slot import sessions
    from thomas.marketplace.observability import run_store

    undos = [scope.set(SESSIONS, sessions()), scope.set(RUNS, run_store)]
    require(scope, SESSIONS, SessionsSeam)
    require(scope, RUNS, RunsSeam)
    return undos


def mount_plugin_handles(app: Any) -> None:
    """Mount both plugin lanes, storing each handle whatever the other does.

    Both keys are always set, so a later reader never has to tell "the mount
    failed" apart from "startup has not reached the mount yet". Every write to the
    app happens here, in startup, while the app is still mutable.
    """
    app[APP_PLUGIN_UNMOUNTED] = set()
    # Expose the server registry to mounted plugins, and withdraw it at cleanup.
    app[APP_TOOLS_DISPOSER] = None
    app[APP_SESSION_DISPOSERS] = []
    try:
        from thomas.agent.kernel_wiring import get_kernel

        app[APP_SESSION_DISPOSERS] = provide_session_services(get_kernel().root)
    except PLUGIN_MOUNT_ERRORS as exc:
        log.warning("The sessions and run log were not registered on the kernel: %s", exc)
    if APP_TOOLS in app:
        try:
            app[APP_TOOLS_DISPOSER] = register_tools_provider(app[APP_TOOLS])
        except PLUGIN_MOUNT_ERRORS as exc:
            log.warning("The tools provider was not registered on the kernel: %s", exc)

    try:
        from thomas.server.plugin_supervisor import start_plugin_supervisor

        app[APP_PLUGIN_SUPERVISOR] = start_plugin_supervisor()
    except PLUGIN_MOUNT_ERRORS as exc:
        log.warning("Installed plugins were not mounted on the kernel: %s", exc)
        app[APP_PLUGIN_SUPERVISOR] = None

    try:
        from thomas.server.plugin_systems_kernel import mount_plugin_systems

        app[APP_PLUGIN_SYSTEMS] = mount_plugin_systems()
    except PLUGIN_MOUNT_ERRORS as exc:
        log.warning("The plugin systems were not mounted on the kernel: %s", exc)
        app[APP_PLUGIN_SYSTEMS] = None


def dispose_plugin_handles(app: Any) -> None:
    """Unmount both lanes, which unwinds every hook and service they registered.

    Systems first, then the supervisor: the reverse of the order they mounted in.
    One handle whose ``dispose`` raises does not keep the other from being
    unwound -- at this point the process is stopping, and a third-party
    ``dispose`` is exactly where a last traceback comes from.

    Running cleanup twice must dispose nothing twice, and aiohttp does run it
    twice-ish: a failed startup still gets a cleanup. What has been unwound is
    recorded in the set placed on the app at mount time, mutated in place, because
    by now the app is frozen and writing a key to it is deprecated. A key is
    marked before its ``dispose`` is called, so a handle that raises on the way
    out is not asked again either.
    """
    unmounted = app.get(APP_PLUGIN_UNMOUNTED)
    if not isinstance(unmounted, set):
        # Cleanup without a mount -- startup failed before it got here. Nothing
        # was mounted, so there is nothing to remember not to unmount twice.
        unmounted = set()
    for key in (APP_PLUGIN_SYSTEMS, APP_PLUGIN_SUPERVISOR):
        handle = app.get(key)
        if handle is None or key in unmounted:
            continue
        unmounted.add(key)
        with contextlib.suppress(Exception):
            handle.dispose()
    session_undos = app.get(APP_SESSION_DISPOSERS)
    if session_undos and APP_SESSION_DISPOSERS not in unmounted:
        unmounted.add(APP_SESSION_DISPOSERS)
        for undo in reversed(session_undos):
            undo()
    disposer = app.get(APP_TOOLS_DISPOSER)
    if callable(disposer) and APP_TOOLS_DISPOSER not in unmounted:
        unmounted.add(APP_TOOLS_DISPOSER)
        disposer()


__all__ = [
    "APP_PLUGIN_SUPERVISOR",
    "APP_SESSION_DISPOSERS",
    "APP_PLUGIN_SYSTEMS",
    "APP_PLUGIN_UNMOUNTED",
    "PLUGIN_MOUNT_ERRORS",
    "dispose_plugin_handles",
    "mount_plugin_handles",
    "provide_session_services",
]
