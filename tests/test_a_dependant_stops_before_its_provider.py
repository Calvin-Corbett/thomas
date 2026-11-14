"""A plugin stops after whatever uses it, and whatever outlives it comes back whole."""

from __future__ import annotations

import asyncio

import pytest

from tests.plugin_stop_fixture import providing, turns
from thomas.core.kernel import Kernel, stop


def test_a_dependant_cleans_up_before_its_provider_starts_stopping() -> None:
    async def scenario() -> None:
        kernel = Kernel()
        order = []

        def provider(ctx, config):
            async def drained() -> None:
                order.append("provider drained")

            async def clean_up() -> None:
                order.append("provider cleaned up")

            ctx.set("thing", 1)
            ctx.on_drain(drained)
            ctx.on_stopped(clean_up)

        def dependant(ctx, config):
            async def clean_up() -> None:
                order.append(f"dependant cleaned up, with thing={ctx['thing']}")

            ctx.on_stopped(clean_up)

        provider.name = "provider"
        dependant.name = "dependant"
        dependant.inject = ("thing",)
        provider_fork = kernel.mount(provider)
        kernel.mount(dependant)

        await stop(provider_fork)

        assert order == ["dependant cleaned up, with thing=1", "provider drained", "provider cleaned up"]

    asyncio.run(scenario())


def test_a_dependant_that_outlives_its_provider_starts_again_rather_than_stay_up_as_a_shell() -> None:
    """A provider that covered an older service leaves that one behind, so nothing takes the dependant off."""

    async def scenario() -> None:
        kernel = Kernel()
        kernel.root.set("thing", "older")
        cleaned_up = []

        def provider(ctx, config):
            ctx.set("thing", "newer")

        def dependant(ctx, config):
            async def clean_up() -> None:
                cleaned_up.append(ctx["thing"])

            ctx.on_stopped(clean_up)

        provider.name = "provider"
        dependant.name = "dependant"
        dependant.inject = ("thing",)
        provider_fork = kernel.mount(provider)
        dependant_fork = kernel.mount(dependant)
        stopped_scope = dependant_fork.ctx

        await stop(provider_fork)

        assert cleaned_up == ["newer"]
        assert dependant_fork.state == "active"
        assert dependant_fork.ctx is not stopped_scope
        async with dependant_fork.ctx.busy():  # it can work, which the scope that stopped cannot
            assert dependant_fork.ctx["thing"] == "older"

        await stop(dependant_fork)
        assert cleaned_up == ["newer", "older"]

    asyncio.run(scenario())


@pytest.mark.parametrize("names", [("a", "c", "b"), ("a", "b", "c")])
def test_a_provider_in_the_middle_waits_for_its_own_dependant(names) -> None:
    """``c`` needs ``a`` and ``b``, and ``b`` needs ``a``. Stopping ``a`` must not close ``b`` under a ``c`` request."""

    async def scenario() -> None:
        kernel = Kernel()
        order = []
        plugins = {
            "a": providing("a", "a-service", order=order),
            "b": providing("b", "b-service", inject=("a-service",), order=order),
            "c": providing("c", inject=("a-service", "b-service"), order=order),
        }
        forks = {name: kernel.mount(plugins[name]) for name in names}
        release = asyncio.Event()
        working = asyncio.Event()

        async def request() -> None:
            async with forks["c"].ctx.busy():
                working.set()
                await release.wait()
                order.append("c request finished")

        running = asyncio.create_task(request())
        await working.wait()
        stopping = asyncio.create_task(stop(forks["a"]))
        await turns()

        assert order == []

        release.set()
        await stopping
        await running
        assert order == ["c request finished", "c cleaned up", "b cleaned up", "a cleaned up"]

    asyncio.run(scenario())


def test_dependants_that_depend_on_each_other_still_stop() -> None:
    async def scenario() -> None:
        kernel = Kernel()
        kernel.root.set("x", "older")
        kernel.root.set("y", "older")
        order = []
        provider = kernel.mount(providing("provider", "thing", order=order))
        kernel.mount(providing("first", "x", inject=("thing", "y"), order=order))
        kernel.mount(providing("second", "y", inject=("thing", "x"), order=order))

        await stop(provider)

        assert sorted(order) == ["first cleaned up", "provider cleaned up", "second cleaned up"]
        assert order[-1] == "provider cleaned up"

    asyncio.run(scenario())


def test_a_dependant_that_outlives_its_provider_leaves_completely_before_it_returns() -> None:
    """Its old scope finishes unwinding first, so nothing of the stopped one comes back later as an older service."""

    async def scenario() -> None:
        kernel = Kernel()
        kernel.root.set("thing", "older")
        seen = []
        generations = iter(range(10))

        def provider(ctx, config):
            ctx.set("thing", "newer")

        def dependant(ctx, config):
            generation = next(generations)
            seen.append(f"apply {generation}")
            ctx.effect(lambda: seen.append(f"undo {generation}"))
            ctx.set("mine-a", f"a{generation}")
            ctx.set("mine-b", f"b{generation}")

        provider.name = "provider"
        dependant.name = "dependant"
        dependant.inject = ("thing",)
        provider_fork = kernel.mount(provider)
        dependant_fork = kernel.mount(dependant)

        await stop(provider_fork)

        assert seen == ["apply 0", "undo 0", "apply 1"]
        assert kernel.root["mine-a"] == "a1"

        await stop(dependant_fork)

        assert not kernel.root.has("mine-a")
        assert not kernel.root.has("mine-b")

    asyncio.run(scenario())


def test_a_chain_of_dependants_that_outlive_their_provider_all_come_back() -> None:
    """Each one returns onto a fresh provider, never onto one that has already run its stop steps."""

    class Resource:
        closed = False

        def use(self) -> None:
            if self.closed:
                raise RuntimeError("used after close")

    async def scenario() -> None:
        kernel = Kernel()
        kernel.root.set("thing", "older")

        def provider(ctx, config):
            ctx.set("thing", "newer")

        def first(ctx, config):
            resource = Resource()

            async def close() -> None:
                resource.closed = True

            ctx.set("first-service", resource)
            ctx.on_stopped(close)

        def second(ctx, config):
            ctx["first-service"].use()
            ctx.set("second-service", "ready")

        provider.name = "provider"
        first.name = "first"
        first.inject = ("thing",)
        second.name = "second"
        second.inject = ("first-service",)
        provider_fork = kernel.mount(provider)
        first_fork = kernel.mount(first)
        second_fork = kernel.mount(second)

        await stop(provider_fork)

        assert second_fork.error is None
        assert first_fork.state == "active"
        assert second_fork.state == "active"
        assert not kernel.root["first-service"].closed

    asyncio.run(scenario())
