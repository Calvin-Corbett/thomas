"""``self.issues``: what has actually been going wrong with Thomas lately.

Thomas has been recording his own failures for months -- five modules call
``issue_ledger.record_issue`` -- and nothing ever showed them to him. A route
renders the ledger for a person; the model had no way to read it. So he could
never look at his own problems, pick one, and fix it.

The shape matters as much as the access. A chronological tail is the wrong
thing to hand a fixer: the same failure repeats hundreds of times, so the list
is mostly one line over and over, and the newest entry is rarely the worst one.
This returns a work queue instead -- one row per distinct failure, how many
times it happened, when it was last seen, and the loudest first -- so the
obvious next move is to fix the thing at the top.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from thomas.tools.base import Tool, ToolResult

# Reads the newest ledger rows: (limit=..., repo_root=...) -> list of dicts.
# The ledger lives in thomas.server, which the tools layer must not import
# (tests/test_architecture.py::test_dependency_direction), so the server hands
# its reader in when it registers the tool.
IssueReader = Callable[..., list[dict[str, Any]]]

# Enough history to see a pattern, not so much that fixed things keep surfacing.
_DEFAULT_HOURS = 24
_DEFAULT_LIMIT = 12
# The ledger keeps far more than a window's worth; read wide, then filter.
_SCAN_LINES = 5000


def _within(row: dict[str, Any], cutoff: datetime) -> bool:
    try:
        return datetime.fromisoformat(str(row.get("ts") or "")) >= cutoff
    except (ValueError, TypeError):
        return False


class SelfIssuesTool(Tool):
    name = "self.issues"
    category = "self"
    description = (
        "List what has actually been going wrong with Thomas recently, worst first: one row "
        "per distinct failure with how many times it happened, where, and when it was last "
        "seen. Use it when asked what is broken, what to fix next, or to check whether a fix "
        "you made actually stopped the failure it was meant to stop."
    )
    parameters = {
        "type": "object",
        "properties": {
            "hours": {
                "type": "integer",
                "description": f"How far back to look. Default {_DEFAULT_HOURS}.",
            },
            "limit": {
                "type": "integer",
                "description": f"How many distinct issues to return. Default {_DEFAULT_LIMIT}.",
            },
        },
    }

    def __init__(self, read_issues: IssueReader, repo_root: str | Path | None = None) -> None:
        self._read_issues = read_issues
        self._repo_root = repo_root

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            hours = max(1, int(args.get("hours") or _DEFAULT_HOURS))
        except (TypeError, ValueError):
            hours = _DEFAULT_HOURS
        try:
            limit = max(1, int(args.get("limit") or _DEFAULT_LIMIT))
        except (TypeError, ValueError):
            limit = _DEFAULT_LIMIT

        rows = self._read_issues(limit=_SCAN_LINES, repo_root=self._repo_root)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        windowed = [row for row in rows if isinstance(row, dict) and _within(row, cutoff)]
        if not windowed:
            return ToolResult(ok=True, data=f"No issues recorded in the last {hours}h.")

        # Grouped on what the failure IS, so one bug is one line of work.
        counts: Counter[tuple[str, str, str]] = Counter()
        last_seen: dict[tuple[str, str, str], str] = {}
        for row in windowed:
            key = (
                str(row.get("surface") or "unknown"),
                str(row.get("kind") or "error"),
                str(row.get("message") or "").strip(),
            )
            counts[key] += 1
            stamp = str(row.get("ts") or "")
            if stamp > last_seen.get(key, ""):
                last_seen[key] = stamp

        lines = [f"{len(counts)} distinct issue(s) in the last {hours}h, most frequent first:"]
        for (surface, kind, message), count in counts.most_common(limit):
            occurrences = "1 time" if count == 1 else f"{count} times"
            lines.append(f"- [{surface}/{kind}] {occurrences}, last {last_seen.get((surface, kind, message), '?')}")
            lines.append(f"    {message}")
        return ToolResult(ok=True, data="\n".join(lines))


def register_self_issue_tools(registry: Any, read_issues: IssueReader, repo_root: str | Path | None = None) -> None:
    """Let Thomas read his own issue ledger."""
    registry.register(SelfIssuesTool(read_issues, repo_root))


__all__ = ["SelfIssuesTool", "register_self_issue_tools"]
