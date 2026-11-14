"""Seams fail where they are wired, not deep inside a turn.

Phase 3.2 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md). Two properties:

1. A provider of the wrong shape is rejected with the seam and the missing
   methods named. Thomas's habit is to accept a proxy for the real thing — a tag
   for a drawing, a name for a contract — and discover the gap much later.
2. ``seam_report`` states which seams nobody filled. An unfilled seam that reads
   as working is the failure this whole phase exists to remove.
"""

from __future__ import annotations

import asyncio

import pytest

from thomas.core.kernel import Kernel, ServiceNotFound
from thomas.core.kernel.seams import (
    AGENT_LOOP,
    SEAMS,
    TOOLS,
    SeamViolation,
    ToolsSeam,
    require,
    seam_report,
)


class _GoodTools:
    """Satisfies ToolsSeam structurally, without inheriting anything."""

    def get(self, name: str):
        return f"tool:{name}"

    def list_tools(self, category: str | None = None) -> list:
        return ["read", "write"]

    async def execute(self, name: str, args: dict):
        return f"ran {name}"


class _HalfTools:
    """Looks close enough to pass a casual eye. Missing ``execute``."""

    def get(self, name: str):
        return None

    def list_tools(self, category: str | None = None) -> list:
        return []


def test_a_conforming_provider_resolves() -> None:
    kernel = Kernel()
    kernel.root.set(TOOLS, _GoodTools())
    tools = require(kernel.root, TOOLS, ToolsSeam)
    assert tools.get("read") == "tool:read"
    assert asyncio.run(tools.execute("read", {})) == "ran read"


def test_a_provider_missing_a_method_is_rejected_by_name() -> None:
    kernel = Kernel()
    kernel.root.set(TOOLS, _HalfTools())
    with pytest.raises(SeamViolation) as caught:
        require(kernel.root, TOOLS, ToolsSeam)
    message = str(caught.value)
    assert TOOLS in message
    assert "execute" in message


def test_requiring_an_unprovided_seam_names_the_seam() -> None:
    kernel = Kernel()
    with pytest.raises(ServiceNotFound) as caught:
        require(kernel.root, AGENT_LOOP)
    assert AGENT_LOOP in str(caught.value)


def test_require_without_a_protocol_just_resolves() -> None:
    kernel = Kernel()
    kernel.root.set(TOOLS, "anything")
    assert require(kernel.root, TOOLS) == "anything"


def test_the_report_names_every_unfilled_seam() -> None:
    kernel = Kernel()
    kernel.root.set(TOOLS, _GoodTools())
    report = seam_report(kernel)
    assert report["seams"][TOOLS] is True
    assert TOOLS not in report["unfilled"]
    assert AGENT_LOOP in report["unfilled"]
    assert set(report["seams"]) == set(SEAMS)


def test_the_report_names_plugins_stuck_on_a_missing_seam() -> None:
    """A plugin waiting forever must be listed, not merely quiet."""
    kernel = Kernel()

    class NeedsLoop:
        name = "transcript"
        inject = (AGENT_LOOP,)

        def apply(self, ctx, config) -> None:  # pragma: no cover - never reached
            raise AssertionError("must not apply without its seam")

    kernel.mount(NeedsLoop())
    report = seam_report(kernel)
    assert report["mounted"] == []
    assert report["pending_plugins"] == [{"plugin": "transcript", "missing": [AGENT_LOOP]}]


def test_the_report_moves_a_plugin_from_pending_to_mounted() -> None:
    kernel = Kernel()
    applied: list[str] = []

    class NeedsTools:
        name = "counter"
        inject = (TOOLS,)

        def apply(self, ctx, config) -> None:
            applied.append("yes")

    kernel.mount(NeedsTools())
    assert seam_report(kernel)["pending_plugins"][0]["missing"] == [TOOLS]

    kernel.root.set(TOOLS, _GoodTools())

    report = seam_report(kernel)
    assert applied == ["yes"]
    assert report["mounted"] == ["counter"]
    assert report["pending_plugins"] == []
