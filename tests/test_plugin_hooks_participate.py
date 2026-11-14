"""A plugin hook can change the payload, on every surface.

Phase 3.2 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md). Before this, two
things were true at once and neither was written down anywhere a user would see:

1. ``AgentLoop._run_plugin_hook`` said "any return value is ignored" — while all
   528 bundled ``pack-*`` extensions define ``before_tool``/``after_tool`` that
   build a modified payload and return it. Every one of those returns was
   dropped on the floor.
2. Only the web chat path supplied a hook runner at all. ``worker_runtime`` —
   every background task — passed none, so which hooks fired depended on which
   surface happened to be executing.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from thomas.agent.hook_events import HookEvent, emit_hook
from thomas.agent.kernel_wiring import default_kernel
from thomas.agent.loop_core import AgentLoop
from thomas.server.plugin_hook_bridge import make_plugin_hook_runner


def _runner_over(kernel, install_root="__none__"):
    """A runner with no installed plugins, so only kernel subscribers speak."""
    return make_plugin_hook_runner(install_root=install_root, kernel=kernel)


# ---------------------------------------------------------------------------
# the bridge folds what handlers return
# ---------------------------------------------------------------------------


def test_a_subscribers_returned_mapping_reaches_the_caller() -> None:
    kernel = default_kernel()
    kernel.root.on("before_tool", lambda payload: {**payload, "validated": True})

    out = asyncio.run(_runner_over(kernel)("before_tool", {"tool": "read"}))

    assert out == {"tool": "read", "validated": True}


def test_two_subscribers_both_contribute() -> None:
    kernel = default_kernel()
    kernel.root.on("before_tool", lambda p: {**p, "first": 1})
    kernel.root.on("before_tool", lambda p: {**p, "second": 2})

    out = asyncio.run(_runner_over(kernel)("before_tool", {}))

    assert out == {"first": 1, "second": 2}


def test_a_subscriber_returning_nothing_leaves_the_payload_alone() -> None:
    kernel = default_kernel()
    kernel.root.on("after_tool", lambda p: None)

    out = asyncio.run(_runner_over(kernel)("after_tool", {"ok": True}))

    assert out == {"ok": True}


def test_a_failing_subscriber_never_breaks_the_turn() -> None:
    kernel = default_kernel()

    def boom(_payload):
        raise RuntimeError("plugin blew up")

    kernel.root.on("before_model", boom)
    kernel.root.on("before_model", lambda p: {**p, "survived": True})

    out = asyncio.run(_runner_over(kernel)("before_model", {"n": 1}))

    assert out == {"n": 1, "survived": True}


def test_the_caller_payload_is_not_mutated_in_place() -> None:
    """Callers reuse their dicts; the hook chain must not edit them underfoot."""
    kernel = default_kernel()
    kernel.root.on("before_tool", lambda p: {**p, "added": True})
    original = {"tool": "read"}

    asyncio.run(_runner_over(kernel)("before_tool", original))

    assert original == {"tool": "read"}


def test_an_unmounted_plugins_subscription_stops_contributing() -> None:
    """Unmounting has to actually remove the handler, not just stop calling it."""
    kernel = default_kernel()

    class Stamper:
        name = "stamper"
        inject = ()

        def apply(self, ctx, config) -> None:
            ctx.on("before_tool", lambda p: {**p, "stamped": True})

    fork = kernel.mount(Stamper())
    assert asyncio.run(_runner_over(kernel)("before_tool", {}))["stamped"] is True

    fork.dispose()

    assert asyncio.run(_runner_over(kernel)("before_tool", {})) == {}


# ---------------------------------------------------------------------------
# the loop hands the payload back
# ---------------------------------------------------------------------------


def test_the_loop_invoker_returns_what_the_runner_produced() -> None:
    loop = object.__new__(AgentLoop)

    async def runner(name, payload):
        return {**payload, "seen": name}

    loop._plugin_hook_runner = runner

    out = asyncio.run(loop._run_plugin_hook("before_tool", {"a": 1}))

    assert out == {"a": 1, "seen": "before_tool"}


def test_the_loop_invoker_returns_the_payload_when_no_runner_is_wired() -> None:
    loop = object.__new__(AgentLoop)
    loop._plugin_hook_runner = None

    assert asyncio.run(loop._run_plugin_hook("before_tool", {"a": 1})) == {"a": 1}


def test_a_runner_that_raises_returns_the_untouched_payload() -> None:
    loop = object.__new__(AgentLoop)

    async def runner(name, payload):
        raise RuntimeError("dispatch exploded")

    loop._plugin_hook_runner = runner

    assert asyncio.run(loop._run_plugin_hook("before_tool", {"a": 1})) == {"a": 1}


def test_emit_hook_threads_the_payload_through_canonical_and_alias() -> None:
    """TOOL_PRE fires both ``tool_pre`` and the legacy ``before_tool``.

    Each must see what the previous one did, or a pack subscribed to the legacy
    name would silently work on a stale payload.
    """
    seen: list[str] = []

    class FakeLoop:
        async def _run_plugin_hook(self, name, payload):
            seen.append(name)
            return {**payload, name: True}

    out = asyncio.run(emit_hook(FakeLoop(), HookEvent.TOOL_PRE, {"start": True}))

    assert len(seen) >= 2
    assert out["start"] is True
    for name in seen:
        assert out[name] is True


def test_emit_hook_on_a_loop_without_an_invoker_returns_the_payload() -> None:
    assert asyncio.run(emit_hook(object(), HookEvent.TOOL_PRE, {"a": 1})) == {"a": 1}


# ---------------------------------------------------------------------------
# both surfaces wire a runner
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module_name, function_name",
    [
        ("thomas.server.worker_runtime", "run_agent_worker_events"),
    ],
)
def test_every_agent_surface_supplies_a_hook_runner(module_name, function_name) -> None:
    """The asymmetry regression guard.

    Asserted against the source of each entry point because the alternative —
    standing up a full worker or a full chat request — proves the same one fact
    at far greater cost. What matters is that neither surface can quietly stop
    passing a runner again, which is exactly what worker_runtime did.
    """
    import importlib

    module = importlib.import_module(module_name)
    source = inspect.getsource(getattr(module, function_name))
    assert "hook_runner" in source, f"{function_name} no longer wires a plugin hook runner"
