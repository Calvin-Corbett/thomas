"""A plugin that fails keeps it to itself, as in Cordis: it reads `failed`, and its neighbours carry on."""

from __future__ import annotations

import pytest

from thomas.core.kernel import Kernel


def _provides(name):
    def plugin(ctx, config):
        ctx.set(name, "value")

    plugin.name = f"provides-{name}"
    return plugin


def _explodes(*inject):
    def plugin(ctx, config):
        raise RuntimeError("boom")

    plugin.name = "explodes"
    plugin.inject = inject
    return plugin


def test_a_mount_that_explodes_still_raises_for_whoever_asked() -> None:
    kernel = Kernel()

    with pytest.raises(RuntimeError, match="boom"):
        kernel.mount(_explodes())

    assert kernel.pending() == []


def test_a_tolerated_mount_keeps_the_fork_and_says_why() -> None:
    fork = Kernel().mount(_explodes(), tolerate=True)

    assert fork.state == "failed"
    assert str(fork.error) == "boom"
    assert not fork.active


def test_a_dependant_that_explodes_does_not_take_its_provider_down() -> None:
    kernel = Kernel()
    dependant = kernel.mount(_explodes("thing"), tolerate=True)
    assert dependant.state == "pending"

    provider = kernel.mount(_provides("thing"))

    assert provider.state == "active"
    assert dependant.state == "failed"


def test_a_failed_plugin_is_not_retried_when_services_change() -> None:
    calls = []

    def flaky(ctx, config):
        calls.append(1)
        raise RuntimeError("boom")

    flaky.name = "flaky"
    flaky.inject = ("thing",)
    kernel = Kernel()
    kernel.mount(flaky, tolerate=True)

    kernel.mount(_provides("thing"))
    kernel.mount(_provides("other"))

    assert calls == [1]


def test_a_failed_plugin_is_not_called_pending() -> None:
    kernel = Kernel()
    kernel.mount(_explodes(), tolerate=True)

    assert kernel.pending() == []


def test_the_states_read_plainly() -> None:
    def waits(ctx, config):
        return None

    waits.name = "waits"
    waits.inject = ("thing",)
    kernel = Kernel()
    fork = kernel.mount(waits)
    assert fork.state == "pending"

    kernel.mount(_provides("thing"))
    assert fork.state == "active"

    fork.stopping = True
    assert fork.state == "unloading"
    fork.stopping = False

    fork.dispose()
    assert fork.state == "disposed"
