"""A row lends tools to runs while it runs, and a run that kept them is refused once the row stops."""

from __future__ import annotations

import asyncio
import gc

import pytest

from thomas.agent.kernel_wiring import (
    LENT_TOOLS,
    LentTool,
    contribute_tools,
    contributed_tools,
    default_kernel,
    set_kernel,
)
from thomas.core.kernel import Kernel
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry


class Lent(Tool):
    name = "row.echo"
    description = "Echo from a row"
    parameters = {"type": "object", "properties": {"word": {"type": "string"}}}

    def __init__(self):
        self.calls = 0

    async def execute(self, args):
        self.calls += 1
        return ToolResult(ok=True, data=args.get("word", "echo"))


class Row:
    name = "lender"
    inject = ()

    def __init__(self, tools):
        self.tools = tools

    def apply(self, ctx, config):
        contribute_tools(ctx, self.tools, owner=self.name)


@pytest.fixture
def kernel():
    k = default_kernel()
    set_kernel(k)
    yield k
    set_kernel(None)


def _run(registry, name="row.echo", args=None):
    return asyncio.run(registry.execute(name, args or {}))


def _built_registry():
    registry = ToolRegistry()
    for tool in contributed_tools():
        registry.register(tool)
    return registry


def test_nothing_is_lent_until_a_row_lends(kernel):
    assert contributed_tools() == []


def test_a_run_gets_the_tool_while_the_row_runs_and_a_refusal_after(kernel):
    tool = Lent()
    fork = kernel.mount(Row([tool]))
    registry = _built_registry()
    assert _run(registry, args={"word": "hi"}).data == "hi"
    fork.dispose()
    refused = _run(registry)
    assert not refused.ok and "turned off" in refused.error
    assert tool.calls == 1
    assert contributed_tools() == []
    assert not asyncio.run(registry.get("row.echo").execute({})).ok


def test_a_run_built_after_the_row_stops_never_sees_it(kernel):
    kernel.mount(Row([Lent()])).dispose()
    assert _built_registry().get("row.echo") is None


def test_turning_the_row_on_again_does_not_revive_an_old_run(kernel):
    first = kernel.mount(Row([Lent()]))
    old = _built_registry()
    first.dispose()
    second = kernel.mount(Row([Lent()]))
    new = _built_registry()
    assert _run(new).ok
    assert not _run(old).ok
    second.dispose()


def test_two_rows_cannot_lend_one_name(kernel):
    first = kernel.mount(Row([Lent()]))
    with pytest.raises(ValueError, match="already lends"):
        kernel.mount(Row([Lent()]))
    assert [t.name for t in contributed_tools()] == ["row.echo"]
    first.dispose()
    assert contributed_tools() == []


@pytest.mark.parametrize("bad", [object(), type("Nameless", (Tool,), {})()])
def test_a_bad_tool_fails_the_row_and_lends_nothing(kernel, bad):
    with pytest.raises((TypeError, ValueError)):
        kernel.mount(Row([Lent(), bad]))
    assert contributed_tools() == []


def test_a_hundred_cycles_leave_nothing_behind(kernel):
    first = kernel.mount(Row([Lent()]))
    first.dispose()
    baseline = kernel.root.pending_effects
    ledger = kernel.root.get(LENT_TOOLS)
    old_runs = []
    for cycle in range(100):
        tool = Lent()
        fork = kernel.mount(Row([tool]))
        registry = _built_registry()
        assert _run(registry, args={"word": str(cycle)}).data == str(cycle)
        assert len(ledger) == 1
        fork.dispose()
        assert not _run(registry).ok
        assert tool.calls == 1
        assert len(ledger) == 0
        assert contributed_tools() == []
        assert kernel.root.pending_effects == baseline
        old_runs.append(registry)
    assert all(not _run(r).ok for r in old_runs)
    assert kernel.mounted() == []
    assert isinstance(kernel, Kernel)
    gc.collect()


def _config(sandbox):
    import dataclasses

    from thomas.core.config import load_config

    cfg = load_config()
    return dataclasses.replace(cfg, tools=dataclasses.replace(cfg.tools, sandbox_root=str(sandbox), allow_shell=False))


def test_a_server_tool_set_carries_the_lent_tools_and_drops_them(kernel, tmp_path):
    from thomas.server import app_helpers

    fork = kernel.mount(Row([Lent()]))
    registry = app_helpers._build_tools(_config(tmp_path))
    assert registry.get("row.echo") is not None
    assert _run(registry).ok
    fork.dispose()
    assert not _run(registry).ok
    assert app_helpers._build_tools(_config(tmp_path)).get("row.echo") is None


def test_a_built_in_name_wins_over_a_lent_one(kernel, tmp_path):
    from thomas.server import app_helpers

    class Shadow(Lent):
        pass

    built = app_helpers._build_tools(_config(tmp_path))
    name = next(t.name for t in built.list_tools())
    Shadow.name = name
    kernel.mount(Row([Shadow()]))
    again = app_helpers._build_tools(_config(tmp_path))
    assert not isinstance(again.get(name), LentTool)


class PathLent(Lent):
    name = "row.write"
    parameters = {"type": "object", "properties": {"path": {"type": "string"}}}
    optional_empty_path_keys = ("path",)


def test_a_lent_tool_keeps_the_attributes_the_loop_reads_off_it(kernel):
    from thomas.agent.loop_tool_paths import _optional_empty_path_keys

    fork = kernel.mount(Row([PathLent()]))
    registry = _built_registry()
    assert _optional_empty_path_keys(registry, "row.write") == frozenset({"path"})
    assert not hasattr(registry.get("row.write"), "no_such_attribute")
    fork.dispose()
    assert not _run(registry, "row.write").ok
