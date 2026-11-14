"""The kernel's contract: registrations are reversible, dependencies gate.

Phase 3.2 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md). These tests pin the
two properties Thomas's existing plugin surfaces do not have:

1. Everything a plugin registers unwinds when it is unmounted. The current
   ``thomas/tools/registry.py`` cannot do this — its ``unregister`` is a manual
   delete with no record of who added what.
2. A plugin whose declared dependency never appears never mounts, and says so.
   This is the structural answer to the recurring "a correct mechanism with no
   consumer" defect: absence becomes observable at mount time instead of a
   silent no-op at run time.

Async tests follow the repo convention (``asyncio.run``), not pytest-asyncio.
"""

from __future__ import annotations

import asyncio

import pytest

from thomas.core.kernel import Context, Kernel, ServiceNotFound

# ---------------------------------------------------------------------------
# services and resolution
# ---------------------------------------------------------------------------


def test_a_service_set_on_a_context_is_readable_from_that_context() -> None:
    kernel = Kernel()
    kernel.root.set("tools", "REGISTRY")
    assert kernel.root["tools"] == "REGISTRY"
    assert kernel.root.has("tools")


def test_service_resolution_walks_up_to_the_parent() -> None:
    kernel = Kernel()
    kernel.root.set("llm", "CLIENT")
    child = kernel.root.fork("child")
    assert child["llm"] == "CLIENT"


def test_a_child_service_shadows_the_parent_without_mutating_it() -> None:
    kernel = Kernel()
    kernel.root.set("llm", "PARENT")
    child = kernel.root.fork("child")
    child.set("llm", "CHILD")
    assert child["llm"] == "CHILD"
    assert kernel.root["llm"] == "PARENT"


def test_an_absent_service_raises_rather_than_returning_none() -> None:
    """A missing seam must be loud. Returning None is how a no-op hides."""
    kernel = Kernel()
    with pytest.raises(ServiceNotFound):
        _ = kernel.root["nope"]
    assert kernel.root.get("nope", "fallback") == "fallback"


# ---------------------------------------------------------------------------
# reversible effects
# ---------------------------------------------------------------------------


def test_disposing_a_set_restores_the_previous_value() -> None:
    kernel = Kernel()
    kernel.root.set("tools", "FIRST")
    undo = kernel.root.set("tools", "SECOND")
    assert kernel.root["tools"] == "SECOND"
    undo()
    assert kernel.root["tools"] == "FIRST"


def test_disposing_the_first_ever_set_removes_the_service_entirely() -> None:
    kernel = Kernel()
    undo = kernel.root.set("tools", "ONLY")
    undo()
    assert not kernel.root.has("tools")


def test_an_undo_does_not_clobber_a_newer_value_set_by_someone_else() -> None:
    """The classic unwind bug: A sets, B overwrites, A disposes, B's value dies."""
    kernel = Kernel()
    undo_a = kernel.root.set("tools", "A")
    kernel.root.set("tools", "B")
    undo_a()
    assert kernel.root["tools"] == "B"


def test_effects_unwind_in_reverse_order() -> None:
    kernel = Kernel()
    order: list[str] = []
    kernel.root.effect(lambda: order.append("first"))
    kernel.root.effect(lambda: order.append("second"))
    kernel.root.dispose()
    assert order == ["second", "first"]


def test_disposal_is_idempotent() -> None:
    kernel = Kernel()
    calls: list[int] = []
    kernel.root.effect(lambda: calls.append(1))
    kernel.root.dispose()
    kernel.root.dispose()
    assert calls == [1]


def test_one_failing_effect_does_not_strand_the_others() -> None:
    kernel = Kernel()
    ran: list[str] = []

    def boom() -> None:
        raise RuntimeError("effect blew up")

    kernel.root.effect(lambda: ran.append("early"))
    kernel.root.effect(boom)
    kernel.root.effect(lambda: ran.append("late"))
    errors = kernel.root.dispose()
    assert ran == ["late", "early"]
    assert len(errors) == 1


def test_disposing_a_parent_disposes_its_children() -> None:
    kernel = Kernel()
    child = kernel.root.fork("child")
    grandchild = child.fork("grandchild")
    kernel.root.dispose()
    assert child.disposed
    assert grandchild.disposed


def test_a_child_that_disposes_itself_stops_weighing_on_its_parent() -> None:
    """The leak hot swap turned from a shape into a cost.

    ``fork`` puts ``child.dispose`` on the parent's stack so the child cannot
    outlive it. Nothing used to take that entry back off, so every mount left a
    disposed Context on the root forever — measured at about 410 bytes each, and
    a reload, a replug and a swap each mount again.
    """
    kernel = Kernel()
    before = kernel.root.pending_effects

    for _ in range(100):
        kernel.root.fork("plugin:demo", transparent=True).dispose()

    assert kernel.root.pending_effects == before


def test_a_hundred_mounts_and_unmounts_leave_the_root_where_it_started() -> None:
    """The same property through the door plugins actually come in by."""

    class Stamp:
        name = "stamp"

        def apply(self, ctx, config) -> None:
            ctx.on("before_tool", lambda payload: payload)

    kernel = Kernel()
    baseline = kernel.root.pending_effects

    for _ in range(100):
        kernel.mount(Stamp()).dispose()

    assert kernel.root.pending_effects == baseline
    assert kernel.bus.handler_count("before_tool") == 0


def test_dropping_an_undo_does_not_run_it() -> None:
    """``drop`` is for an undo that became unnecessary, not one to be run early."""
    from thomas.core.kernel import DisposalStack

    stack = DisposalStack()
    ran: list[int] = []

    def undo() -> None:
        ran.append(1)

    stack.push(undo)
    assert stack.drop(undo) is True
    assert stack.drop(undo) is False
    stack.dispose()

    assert ran == []
    assert stack.pending == 0


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------


def test_a_handler_receives_emitted_events() -> None:
    kernel = Kernel()
    seen: list[dict] = []
    kernel.root.on("tool/call", lambda payload: seen.append(payload))
    asyncio.run(kernel.root.emit("tool/call", {"name": "read"}))
    assert seen == [{"name": "read"}]


def test_emit_returns_handler_results_so_a_hook_can_act() -> None:
    """Thomas's current hooks discard return values. The kernel hands them back."""
    kernel = Kernel()
    kernel.root.on("before_tool", lambda payload: {**payload, "validated": True})
    results = asyncio.run(kernel.root.emit("before_tool", {"name": "read"}))
    assert results == [{"name": "read", "validated": True}]


def test_an_async_handler_is_awaited() -> None:
    kernel = Kernel()

    async def handler(payload: dict) -> str:
        await asyncio.sleep(0)
        return f"saw {payload['name']}"

    kernel.root.on("tool/call", handler)
    results = asyncio.run(kernel.root.emit("tool/call", {"name": "grep"}))
    assert results == ["saw grep"]


def test_one_failing_handler_does_not_stop_the_others() -> None:
    kernel = Kernel()

    def boom(_payload: dict) -> None:
        raise RuntimeError("handler blew up")

    kernel.root.on("tool/call", boom)
    kernel.root.on("tool/call", lambda _payload: "survived")
    results = asyncio.run(kernel.root.emit("tool/call", {}))
    assert "survived" in results


def test_unsubscribing_stops_delivery() -> None:
    kernel = Kernel()
    seen: list[int] = []
    off = kernel.root.on("ping", lambda _p: seen.append(1))
    off()
    asyncio.run(kernel.root.emit("ping", {}))
    assert seen == []


def test_disposing_the_context_unsubscribes_its_handlers() -> None:
    kernel = Kernel()
    seen: list[int] = []
    child = kernel.root.fork("child")
    child.on("ping", lambda _p: seen.append(1))
    child.dispose()
    asyncio.run(kernel.root.emit("ping", {}))
    assert seen == []


def test_fold_gives_each_handler_what_the_last_one_produced() -> None:
    """A hook is a chain, not a broadcast.

    With ``emit`` both handlers below compute their list from the original
    payload and the caller's merge keeps only the second — which is how mounting
    a second plugin cancelled the first one's contribution.
    """
    kernel = Kernel()
    kernel.root.on("before_tool", lambda p: {**p, "marks": [*p.get("marks", []), "first"]})
    kernel.root.on("before_tool", lambda p: {**p, "marks": [*p.get("marks", []), "second"]})

    assert asyncio.run(kernel.root.fold("before_tool", {}))["marks"] == ["first", "second"]


def test_fold_leaves_the_callers_payload_alone() -> None:
    kernel = Kernel()
    kernel.root.on("ping", lambda p: {**p, "added": True})
    original = {"n": 1}

    assert asyncio.run(kernel.root.fold("ping", original)) == {"n": 1, "added": True}
    assert original == {"n": 1}


def test_fold_ignores_a_handler_that_returns_no_mapping() -> None:
    kernel = Kernel()
    kernel.root.on("ping", lambda _p: None)
    kernel.root.on("ping", lambda _p: "not a payload")

    assert asyncio.run(kernel.root.fold("ping", {"n": 1})) == {"n": 1}


def test_fold_carries_on_past_a_failing_handler() -> None:
    kernel = Kernel()

    def boom(_payload: dict) -> None:
        raise RuntimeError("handler blew up")

    kernel.root.on("ping", lambda p: {**p, "first": True})
    kernel.root.on("ping", boom)
    kernel.root.on("ping", lambda p: {**p, "third": True})

    assert asyncio.run(kernel.root.fold("ping", {})) == {"first": True, "third": True}


# ---------------------------------------------------------------------------
# plugins and inject gating
# ---------------------------------------------------------------------------


class _RecordingPlugin:
    """A plugin that registers a service and an event handler when applied."""

    name = "recorder"
    inject: tuple[str, ...] = ()

    def __init__(self) -> None:
        self.applies = 0

    def apply(self, ctx: Context, config: dict) -> None:
        self.applies += 1
        ctx.set("recorder", f"live-{self.applies}")
        ctx.on("ping", lambda _p: "recorder-heard-it")


def test_mounting_a_plugin_applies_it() -> None:
    kernel = Kernel()
    plugin = _RecordingPlugin()
    kernel.mount(plugin)
    assert plugin.applies == 1
    assert kernel.root["recorder"] == "live-1"


def test_unmounting_a_plugin_unwinds_everything_it_registered() -> None:
    kernel = Kernel()
    fork = kernel.mount(_RecordingPlugin())
    assert kernel.root.has("recorder")
    fork.dispose()
    assert not kernel.root.has("recorder")
    assert asyncio.run(kernel.root.emit("ping", {})) == []


def test_a_plugin_with_an_unmet_dependency_does_not_apply() -> None:
    kernel = Kernel()

    class NeedsTools(_RecordingPlugin):
        inject = ("tools",)

    plugin = NeedsTools()
    fork = kernel.mount(plugin)
    assert plugin.applies == 0
    assert not fork.active
    assert fork.missing == ("tools",)


def test_a_pending_plugin_applies_when_its_dependency_arrives() -> None:
    kernel = Kernel()

    class NeedsTools(_RecordingPlugin):
        inject = ("tools",)

    plugin = NeedsTools()
    fork = kernel.mount(plugin)
    assert plugin.applies == 0

    kernel.root.set("tools", "REGISTRY")
    assert plugin.applies == 1
    assert fork.active


def test_a_plugin_unapplies_when_its_dependency_goes_away() -> None:
    kernel = Kernel()

    class NeedsTools(_RecordingPlugin):
        inject = ("tools",)

    plugin = NeedsTools()
    undo_tools = kernel.root.set("tools", "REGISTRY")
    fork = kernel.mount(plugin)
    assert fork.active
    assert kernel.root.has("recorder")

    undo_tools()

    assert not fork.active
    assert not kernel.root.has("recorder")


def test_a_plugin_reapplies_when_its_dependency_returns() -> None:
    kernel = Kernel()

    class NeedsTools(_RecordingPlugin):
        inject = ("tools",)

    plugin = NeedsTools()
    undo_tools = kernel.root.set("tools", "REGISTRY")
    kernel.mount(plugin)
    undo_tools()
    kernel.root.set("tools", "REGISTRY-AGAIN")

    assert plugin.applies == 2
    assert kernel.root["recorder"] == "live-2"


def test_pending_plugins_are_reportable() -> None:
    """Absence has to be visible, not inferred from nothing happening."""
    kernel = Kernel()

    class NeedsTools(_RecordingPlugin):
        inject = ("tools", "llm")

    kernel.mount(NeedsTools())
    pending = kernel.pending()
    assert len(pending) == 1
    assert pending[0].plugin.name == "recorder"
    assert set(pending[0].missing) == {"tools", "llm"}


def test_a_plain_function_is_a_valid_plugin() -> None:
    kernel = Kernel()
    applied: list[str] = []

    def my_plugin(ctx: Context, config: dict) -> None:
        applied.append(config["label"])

    kernel.mount(my_plugin, {"label": "hello"})
    assert applied == ["hello"]


def test_a_plugin_that_raises_does_not_leave_a_half_mounted_scope() -> None:
    kernel = Kernel()

    def bad_plugin(ctx: Context, config: dict) -> None:
        ctx.set("half", "written")
        raise RuntimeError("plugin blew up during apply")

    with pytest.raises(RuntimeError):
        kernel.mount(bad_plugin)
    assert not kernel.root.has("half")


# ---------------------------------------------------------------------------
# strict mode
#
# Teardown and delivery both swallow failures by default so one bad contributor
# cannot strand a scope or stop a turn. Strict mode is the developer-facing
# escape: it surfaces the failure instead. Tested here because an option nobody
# exercises is exactly the "mechanism with no consumer" this kernel exists to
# make impossible.
# ---------------------------------------------------------------------------


def test_strict_disposal_surfaces_a_failing_undo() -> None:
    kernel = Kernel()

    def boom() -> None:
        raise RuntimeError("effect blew up")

    kernel.root.effect(boom)
    with pytest.raises(RuntimeError):
        kernel.root.dispose(strict=True)


def test_strict_emit_surfaces_a_failing_handler() -> None:
    kernel = Kernel()

    def boom(_payload: dict) -> None:
        raise RuntimeError("handler blew up")

    kernel.root.on("ping", boom)
    with pytest.raises(RuntimeError):
        asyncio.run(kernel.root.emit("ping", {}, strict=True))


def test_default_emit_still_tolerates_a_failing_handler() -> None:
    """The permissive default is the contract; strict is opt-in only."""
    kernel = Kernel()

    def boom(_payload: dict) -> None:
        raise RuntimeError("handler blew up")

    kernel.root.on("ping", boom)
    kernel.root.on("ping", lambda _p: "survived")
    assert asyncio.run(kernel.root.emit("ping", {})) == ["survived"]
