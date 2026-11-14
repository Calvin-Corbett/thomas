"""Phase 3.5: what server startup does when one of the two mounts fails.

`plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md`.

Startup mounts two independent things: the supervisor that holds the installed
plugins, and the three plugin systems as kernel services. Both run third-party
code, so either can fail -- and the failure of one must not cost the other.

The defect this pins is the one a shared ``except`` produces: the supervisor is
stored, the systems mount raises, the handler sets *both* handles to None, and a
supervisor that is still on the bus is now unreachable. Nothing disposes it at
cleanup, and ``/api/plugins/kernel`` answers "not supervised in this process"
about plugins that are running.

Both mounts live in ``thomas/server/plugin_startup.py`` as two plain functions,
which is what these tests drive. Reaching them through ``create_app`` would mean
standing up every route family to get at a nested handler, and the contract being
checked here is not about routing.
"""

from __future__ import annotations

import inspect
import warnings

import pytest
from aiohttp import web

from thomas.core.kernel import KernelError
from thomas.server import app_routes_init
from thomas.server.plugin_startup import (
    APP_PLUGIN_SUPERVISOR,
    APP_PLUGIN_SYSTEMS,
    dispose_plugin_handles,
    mount_plugin_handles,
)


class _Handle:
    """Stands in for a mount handle: the thing cleanup has to be able to find."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.disposals = 0

    @property
    def disposed(self) -> bool:
        return self.disposals > 0

    def dispose(self) -> None:
        self.disposals += 1


class _AngryHandle(_Handle):
    """A handle whose ``dispose`` raises, which third-party teardown does."""

    def dispose(self) -> None:
        super().dispose()
        raise RuntimeError(f"{self.label} refused to unmount")


def _mounts(
    monkeypatch: pytest.MonkeyPatch,
    *,
    supervisor: object | Exception,
    systems: object | Exception,
) -> None:
    """Make each mount either hand back a handle or fail the way it fails live."""

    def _answer(value: object | Exception):
        def call(*args: object, **kwargs: object) -> object:
            if isinstance(value, Exception):
                raise value
            return value

        return call

    monkeypatch.setattr("thomas.server.plugin_supervisor.start_plugin_supervisor", _answer(supervisor))
    monkeypatch.setattr("thomas.server.plugin_systems_kernel.mount_plugin_systems", _answer(systems))


def test_a_failed_systems_mount_does_not_throw_away_the_supervisor(monkeypatch: pytest.MonkeyPatch) -> None:
    """The supervisor mounted. Cleanup must still be able to unmount it."""
    app = web.Application()
    supervisor = _Handle("supervisor")
    _mounts(monkeypatch, supervisor=supervisor, systems=KernelError("the root scope is gone"))

    mount_plugin_handles(app)

    assert app[APP_PLUGIN_SUPERVISOR] is supervisor
    assert app[APP_PLUGIN_SYSTEMS] is None

    dispose_plugin_handles(app)
    assert supervisor.disposed, "a handle startup dropped is a mount nothing can unwind"


def test_a_supervisor_that_will_not_start_still_leaves_the_systems_mounted(monkeypatch: pytest.MonkeyPatch) -> None:
    """And the server starts either way -- plugins are not a boot requirement."""
    app = web.Application()
    systems = _Handle("systems")
    _mounts(monkeypatch, supervisor=ImportError("a plugin's own import blew up"), systems=systems)

    mount_plugin_handles(app)

    assert app[APP_PLUGIN_SUPERVISOR] is None
    assert app[APP_PLUGIN_SYSTEMS] is systems

    dispose_plugin_handles(app)
    assert systems.disposed


def test_both_handles_are_kept_when_both_mounts_succeed(monkeypatch: pytest.MonkeyPatch) -> None:
    app = web.Application()
    supervisor, systems = _Handle("supervisor"), _Handle("systems")
    _mounts(monkeypatch, supervisor=supervisor, systems=systems)

    mount_plugin_handles(app)
    assert (app[APP_PLUGIN_SUPERVISOR], app[APP_PLUGIN_SYSTEMS]) == (supervisor, systems)

    dispose_plugin_handles(app)
    assert (supervisor.disposed, systems.disposed) == (True, True)


def test_neither_mount_being_possible_still_leaves_both_keys_answerable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A reader must never meet a missing key: None means "it did not mount"."""
    app = web.Application()
    _mounts(
        monkeypatch,
        supervisor=OSError("the install root is unreadable"),
        systems=KernelError("the root scope is gone"),
    )

    mount_plugin_handles(app)
    assert (app[APP_PLUGIN_SUPERVISOR], app[APP_PLUGIN_SYSTEMS]) == (None, None)

    dispose_plugin_handles(app)  # nothing to unwind, and it does not raise


def test_a_handle_that_will_not_dispose_does_not_keep_the_other_mounted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Teardown runs third-party code too, and one bad exit is not all of them."""
    app = web.Application()
    systems, supervisor = _AngryHandle("systems"), _Handle("supervisor")
    _mounts(monkeypatch, supervisor=supervisor, systems=systems)

    mount_plugin_handles(app)
    dispose_plugin_handles(app)

    assert systems.disposed, "the raising handle was still asked"
    assert supervisor.disposed, "a raising dispose must not take the second unmount down with it"


def test_cleanup_twice_disposes_nothing_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    """aiohttp can run cleanup after a failed startup; a double unmount is not free."""
    app = web.Application()
    supervisor, systems = _Handle("supervisor"), _Handle("systems")
    _mounts(monkeypatch, supervisor=supervisor, systems=systems)

    mount_plugin_handles(app)
    dispose_plugin_handles(app)
    dispose_plugin_handles(app)

    assert (supervisor.disposals, systems.disposals) == (1, 1)


def test_cleanup_does_not_write_to_the_frozen_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """aiohttp freezes the app before ``on_cleanup`` runs.

    Assigning a key after the freeze is deprecated, and cleanup used to clear both
    handle keys: one DeprecationWarning per app teardown, which the suite pays 907
    times across the files that build a real app. What has been unwound is
    recorded in a set placed on the app during startup and mutated in place.
    """
    app = web.Application()
    supervisor, systems = _Handle("supervisor"), _Handle("systems")
    _mounts(monkeypatch, supervisor=supervisor, systems=systems)

    mount_plugin_handles(app)
    app.freeze()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        dispose_plugin_handles(app)

    assert [str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)] == []
    assert (supervisor.disposed, systems.disposed) == (True, True)


def test_a_handle_that_raises_on_the_way_out_is_not_asked_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """Marked before it is asked, so a second cleanup does not retry a bad exit."""
    app = web.Application()
    systems = _AngryHandle("systems")
    _mounts(monkeypatch, supervisor=_Handle("supervisor"), systems=systems)

    mount_plugin_handles(app)
    dispose_plugin_handles(app)
    dispose_plugin_handles(app)

    assert systems.disposals == 1


def test_the_mount_order_is_reversed_at_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Services the supervised plugins may resolve outlive nothing they need."""
    order: list[str] = []

    class _Recording(_Handle):
        def dispose(self) -> None:
            super().dispose()
            order.append(self.label)

    app = web.Application()
    _mounts(monkeypatch, supervisor=_Recording("supervisor"), systems=_Recording("systems"))

    mount_plugin_handles(app)
    dispose_plugin_handles(app)

    assert order == ["systems", "supervisor"]


def test_server_startup_and_cleanup_are_the_callers() -> None:
    """These two functions are not a side road: the real handlers call them.

    Read from the source rather than by running startup, because running it means
    building every route family, and a handler that stopped calling these is the
    only way this contract can be true here and false in the server.
    """
    source = inspect.getsource(app_routes_init._setup_routes_and_handlers)

    assert "mount_plugin_handles(app_ref)" in source
    assert "dispose_plugin_handles(app_ref)" in source
    assert app_routes_init.mount_plugin_handles is mount_plugin_handles
    assert app_routes_init.dispose_plugin_handles is dispose_plugin_handles
