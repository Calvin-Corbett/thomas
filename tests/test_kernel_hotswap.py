"""Phase 3.5: a plugin can come off a running kernel and go back on.

`plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md`.

The properties that make "swap it while it runs" mean something:

1. Unplugging removes everything the plugin registered and keeps the way back.
2. A swap whose replacement fails leaves the *previous* plugin running, and says
   so — the case that matters, because a self-edit with a typo in it is the
   normal way a reload fails.
3. Swapping one plugin does not disturb another, including one that depends on a
   service the swapped plugin provides.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from thomas.core.kernel import Kernel, SwapError, swap, unplug


class Stamper:
    """Subscribes to one event and stamps the payload, like a bundled pack."""

    inject: tuple[str, ...] = ()

    def __init__(self, name: str, mark: str) -> None:
        self.name = name
        self.mark = mark

    def apply(self, ctx, config) -> None:
        def handler(payload):
            data = dict(payload or {})
            data["mark"] = self.mark
            data["config"] = dict(config)
            return data

        ctx.on("tool_pre", handler)


class Exploding:
    """A plugin whose code is broken — the shape of a bad self-edit."""

    name = "stamper"
    inject: tuple[str, ...] = ()

    def apply(self, ctx, config) -> None:
        raise ValueError("this version does not import")


def _fire(kernel: Kernel, payload=None):
    return asyncio.run(kernel.root.emit("tool_pre", payload or {}))


# ---------------------------------------------------------------------------
# unplug and replug
# ---------------------------------------------------------------------------


def test_unplugging_removes_the_subscription() -> None:
    kernel = Kernel()
    fork = kernel.mount(Stamper("stamper", "v1"))
    assert _fire(kernel)[0]["mark"] == "v1"

    unplug(fork)

    assert _fire(kernel) == []
    assert kernel.mounted() == []


def test_replugging_puts_it_back_with_the_same_config() -> None:
    kernel = Kernel()
    fork = kernel.mount(Stamper("stamper", "v1"), {"level": 3})

    held = unplug(fork)
    back = held.replug()

    result = _fire(kernel)[0]
    assert result["mark"] == "v1"
    assert result["config"] == {"level": 3}
    assert back.active


def test_unplugging_twice_is_refused_rather_than_silent() -> None:
    kernel = Kernel()
    fork = kernel.mount(Stamper("stamper", "v1"))
    unplug(fork)

    with pytest.raises(SwapError):
        unplug(fork)


def test_replug_can_substitute_a_freshly_loaded_version() -> None:
    """The reload case: what goes back is new code, not the object that came off."""
    kernel = Kernel()
    held = unplug(kernel.mount(Stamper("stamper", "v1")))

    held.replug(Stamper("stamper", "v2"))

    assert _fire(kernel)[0]["mark"] == "v2"


# ---------------------------------------------------------------------------
# swapping
# ---------------------------------------------------------------------------


def test_a_swap_replaces_the_running_behaviour() -> None:
    kernel = Kernel()
    fork = kernel.mount(Stamper("stamper", "v1"))

    swap(fork, Stamper("stamper", "v2"))

    assert _fire(kernel)[0]["mark"] == "v2"
    assert len(kernel.mounted()) == 1


def test_a_swap_keeps_the_old_config_unless_given_a_new_one() -> None:
    kernel = Kernel()
    fork = kernel.mount(Stamper("stamper", "v1"), {"level": 3})

    fork = swap(fork, Stamper("stamper", "v2"))
    assert _fire(kernel)[0]["config"] == {"level": 3}

    swap(fork, Stamper("stamper", "v3"), {"level": 9})
    assert _fire(kernel)[0]["config"] == {"level": 9}


def test_a_failed_swap_leaves_the_previous_version_running() -> None:
    """The load-bearing one. A broken edit must not unplug a working plugin."""
    kernel = Kernel()
    fork = kernel.mount(Stamper("stamper", "v1"))

    with pytest.raises(SwapError) as caught:
        swap(fork, Exploding())

    assert caught.value.restored is True
    assert _fire(kernel)[0]["mark"] == "v1"
    assert len(kernel.mounted()) == 1


def test_a_failed_swap_hands_back_the_fork_the_old_version_runs_under() -> None:
    """Without this the caller holds a disposed handle to a live plugin."""
    kernel = Kernel()
    fork = kernel.mount(Stamper("stamper", "v1"))

    with pytest.raises(SwapError) as caught:
        swap(fork, Exploding())

    restored = caught.value.fork
    assert restored is not None
    assert restored.active
    assert restored is not fork


def test_swapping_one_plugin_leaves_its_neighbour_alone() -> None:
    kernel = Kernel()
    kernel.mount(Stamper("other", "other-v1"))
    fork = kernel.mount(Stamper("stamper", "v1"))

    swap(fork, Stamper("stamper", "v2"))

    marks = {result["mark"] for result in _fire(kernel)}
    assert marks == {"other-v1", "v2"}


def test_a_swap_does_not_await():
    """Atomicity, asserted where it is created.

    ``swap`` is synchronous, so on the event loop that runs a turn nothing can
    dispatch between the old plugin's subscriptions going away and the new
    plugin's arriving. Make it a coroutine and that guarantee is gone quietly,
    so the shape is pinned here rather than in a comment.
    """
    assert not inspect.iscoroutinefunction(swap)
    assert not inspect.iscoroutinefunction(unplug)


# ---------------------------------------------------------------------------
# services and dependants
# ---------------------------------------------------------------------------


class Provider:
    """Contributes a service rather than a subscription."""

    inject: tuple[str, ...] = ()

    def __init__(self, name: str, value: str) -> None:
        self.name = name
        self.value = value

    def apply(self, ctx, config) -> None:
        ctx.set("thing", self.value)


class Dependant:
    """Mounts only while ``thing`` exists — the kernel's inject gating."""

    name = "dependant"
    inject = ("thing",)

    def apply(self, ctx, config) -> None:
        value = ctx["thing"]
        ctx.on("tool_pre", lambda payload: {"saw": value})


def test_unplugging_a_provider_withdraws_its_service_and_its_dependants() -> None:
    kernel = Kernel()
    provider = kernel.mount(Provider("provider", "first"))
    kernel.mount(Dependant())
    assert _fire(kernel)[0] == {"saw": "first"}

    held = unplug(provider)

    assert not kernel.root.has("thing")
    assert _fire(kernel) == []
    assert [fork.name for fork in kernel.pending()] == ["dependant"]

    held.replug()
    assert _fire(kernel)[0] == {"saw": "first"}


def test_swapping_a_provider_reruns_its_dependants_against_the_new_value() -> None:
    """A dependant must see the replacement, not a cached read of the old one."""
    kernel = Kernel()
    provider = kernel.mount(Provider("provider", "first"))
    kernel.mount(Dependant())

    swap(provider, Provider("provider", "second"))

    assert _fire(kernel)[0] == {"saw": "second"}
    assert kernel.pending() == []
