"""``self.unlanded``: the work on Thomas's own branches that is not on dev, and what the ratchet did with it.

It reads the ratchet's records (thomas/server/ratchet/report.py), never git: the
census of what was found, the ledger of what happened to each candidate since,
and the halt, when a landing broke a test and every run is stopped.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from thomas.tools.base import Tool, ToolResult

# The ratchet's report lives in thomas.server, which the tools layer must not import
# (tests/test_architecture.py::test_dependency_direction); the server hands its reader in.
ReportReader = Callable[[], dict[str, Any]]

_DEFAULT_LIMIT = 20
_WORDS = {
    "queued": "not proven yet",
    "proving": "being proven now",
    "repairing": "a Build team is repairing it",
    "settling": "being handed to the promoter",
    "awaiting_card": "waiting for your card",
    "landed": "landed",
    "already_on_dev": "already on dev",
    "reported": "reported",
    "not_for_ratchet": "not for the ratchet",
    "active": "still being worked on",
}


class SelfUnlandedTool(Tool):
    name = "self.unlanded"
    category = "self"
    description = (
        "List the work on Thomas's own branches that is not on dev, and what the ratchet did with each: not "
        "proven yet, being proven, being repaired, waiting for your card, landed, already on dev, reported with "
        "its reason, or not for the ratchet. Use it when asked what is still unlanded, or why a branch or commit "
        "did not land."
    )
    parameters = {
        "type": "object",
        "properties": {
            "state": {"type": "string", "description": "Only rows in this state, e.g. reported or awaiting_card."},
            "limit": {"type": "integer", "description": f"How many rows to list. Default {_DEFAULT_LIMIT}."},
        },
    }

    def __init__(self, read_report: ReportReader) -> None:
        self._read_report = read_report

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            limit = max(1, int(args.get("limit") or _DEFAULT_LIMIT))
        except (TypeError, ValueError):
            limit = _DEFAULT_LIMIT
        wanted = str(args.get("state") or "").strip().lower()
        report = self._read_report()
        rows = [row for row in report.get("candidates") or [] if isinstance(row, dict)]
        if not rows:
            return ToolResult(
                ok=True,
                data="The ratchet has no record here yet: it runs in the caged Thomas, once a day or when "
                "POST /api/ratchet/run asks.",
            )
        counts = report.get("counts") or {}
        summary = ", ".join(f"{count} {_WORDS.get(state, state)}" for state, count in sorted(counts.items()))
        lines = [f"Against dev {str(report.get('dev_sha') or '')[:12]}: {summary}."]
        halted = report.get("halted") or {}
        if halted:
            reason = str(halted.get("reason") or "a landing broke a test")
            lines.insert(0, f"The ratchet is stopped: {reason}. It starts again once those tests pass on dev.")
        for row in [r for r in rows if not wanted or r.get("state") == wanted][:limit]:
            state = str(row.get("state") or "")
            sha = str(row.get("sha") or "")[:12]
            lines.append(f"- {row.get('ref') or sha} ({sha}): {_WORDS.get(state, state)} -- {row.get('reason') or ''}")
        return ToolResult(ok=True, data="\n".join(lines))


def register_self_unlanded_tools(registry: Any, read_report: ReportReader) -> None:
    """Let Thomas say what is still unlanded, from the ratchet's own records."""
    registry.register(SelfUnlandedTool(read_report))


__all__ = ["SelfUnlandedTool", "register_self_unlanded_tools"]
