"""Investigation tools — agent can query evidence findings in chat.

Registered when ~/.thomas/investigation.sqlite3 exists.
Tools:
    investigate.query    — FTS search across claims + documents
    investigate.patterns — Return detected patterns sorted by strength
    investigate.timeline — Chronological events, filterable by date range
    investigate.status   — Case status: docs, claims, patterns
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from thomas.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)


def _get_store():
    """Lazy-import store so we don't break anything at import time."""
    from thomas.investigation.store import InvestigationStore
    return InvestigationStore()


# ---------------------------------------------------------------------------
# investigate.status
# ---------------------------------------------------------------------------

class InvestigateStatusTool(Tool):
    name = "investigate.status"
    category = "investigation"
    description = (
        "Show investigation processing status for a case: "
        "documents processed, claims extracted, patterns detected, timeline events. "
        "Call with no args for the latest case, or provide case_id."
    )
    parameters = {
        "type": "object",
        "properties": {
            "case_id": {
                "type": "string",
                "description": "Case ID to query. Omit for the latest case.",
            },
        },
    }

    async def execute(self, args: Dict[str, Any]) -> ToolResult:
        try:
            store = _get_store()
            case_id = args.get("case_id")

            if case_id:
                case = store.get_case(case_id)
            else:
                case = store.get_latest_case()

            if not case:
                store.close()
                return ToolResult(ok=True, data="No investigation cases found. Run 'thomas investigate run <folder>' first.")

            summary = store.get_case_summary(case.id)
            store.close()
            return ToolResult(ok=True, data=summary)
        except Exception as exc:
            return ToolResult(ok=False, error=str(exc))


# ---------------------------------------------------------------------------
# investigate.query
# ---------------------------------------------------------------------------

class InvestigateQueryTool(Tool):
    name = "investigate.query"
    category = "investigation"
    description = (
        "Search evidence claims and documents by keyword. "
        "Uses full-text search across all extracted claims. "
        "Example queries: 'missed visitation', 'hostile message', 'safety concern'."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search keywords or phrase to find in claims.",
            },
            "case_id": {
                "type": "string",
                "description": "Case ID to search. Omit for the latest case.",
            },
            "category": {
                "type": "string",
                "description": "Filter by claim category: communication, visitation, financial, safety, emotional, legal, medical, other.",
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (default: 20).",
            },
        },
        "required": ["query"],
    }

    async def execute(self, args: Dict[str, Any]) -> ToolResult:
        try:
            store = _get_store()
            case_id = args.get("case_id")

            if case_id:
                case = store.get_case(case_id)
            else:
                case = store.get_latest_case()

            if not case:
                store.close()
                return ToolResult(ok=True, data="No investigation cases found.")

            query = args.get("query", "")
            category = args.get("category")
            limit = args.get("limit", 20)

            claims = store.search_claims(query, case.id, category=category, limit=limit)
            store.close()

            if not claims:
                return ToolResult(ok=True, data=f"No claims matching '{query}'.")

            return ToolResult(ok=True, data={
                "case_name": case.name,
                "query": query,
                "count": len(claims),
                "claims": claims,
            })
        except Exception as exc:
            return ToolResult(ok=False, error=str(exc))


# ---------------------------------------------------------------------------
# investigate.patterns
# ---------------------------------------------------------------------------

class InvestigatePatternsTool(Tool):
    name = "investigate.patterns"
    category = "investigation"
    description = (
        "Return detected evidence patterns sorted by strength. "
        "Patterns are recurring behaviors found across multiple documents "
        "(e.g. 'consistently hostile communication', 'missed visitations during holidays'). "
        "Each pattern includes evidence count, category, strength score, and date range."
    )
    parameters = {
        "type": "object",
        "properties": {
            "case_id": {
                "type": "string",
                "description": "Case ID. Omit for the latest case.",
            },
            "category": {
                "type": "string",
                "description": "Filter by category: communication, visitation, financial, safety, emotional, legal, medical.",
            },
            "min_strength": {
                "type": "number",
                "description": "Minimum pattern strength score (default: 0).",
            },
        },
    }

    async def execute(self, args: Dict[str, Any]) -> ToolResult:
        try:
            store = _get_store()
            case_id = args.get("case_id")

            if case_id:
                case = store.get_case(case_id)
            else:
                case = store.get_latest_case()

            if not case:
                store.close()
                return ToolResult(ok=True, data="No investigation cases found.")

            min_strength = args.get("min_strength", 0.0)
            category = args.get("category")

            patterns = store.get_patterns(case.id, min_strength=min_strength, category=category)
            store.close()

            if not patterns:
                return ToolResult(ok=True, data="No patterns found. Run 'thomas investigate run <folder>' first.")

            return ToolResult(ok=True, data={
                "case_name": case.name,
                "count": len(patterns),
                "patterns": patterns,
            })
        except Exception as exc:
            return ToolResult(ok=False, error=str(exc))


# ---------------------------------------------------------------------------
# investigate.timeline
# ---------------------------------------------------------------------------

class InvestigateTimelineTool(Tool):
    name = "investigate.timeline"
    category = "investigation"
    description = (
        "Return a chronological timeline of events extracted from evidence. "
        "Each event includes a date, summary, category, and severity. "
        "Filterable by date range (start/end in YYYY-MM-DD format)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "case_id": {
                "type": "string",
                "description": "Case ID. Omit for the latest case.",
            },
            "start_date": {
                "type": "string",
                "description": "Start date filter in YYYY-MM-DD format.",
            },
            "end_date": {
                "type": "string",
                "description": "End date filter in YYYY-MM-DD format.",
            },
        },
    }

    async def execute(self, args: Dict[str, Any]) -> ToolResult:
        try:
            store = _get_store()
            case_id = args.get("case_id")

            if case_id:
                case = store.get_case(case_id)
            else:
                case = store.get_latest_case()

            if not case:
                store.close()
                return ToolResult(ok=True, data="No investigation cases found.")

            start = args.get("start_date")
            end = args.get("end_date")

            events = store.get_timeline(case.id, start_date=start, end_date=end)
            store.close()

            if not events:
                return ToolResult(ok=True, data="No timeline events found.")

            return ToolResult(ok=True, data={
                "case_name": case.name,
                "count": len(events),
                "events": events,
            })
        except Exception as exc:
            return ToolResult(ok=False, error=str(exc))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_investigation_tools(registry) -> None:
    """Register investigation tools if the investigation DB exists.

    Lightweight check — if no investigation database exists, skip quietly.
    """
    try:
        from thomas.investigation.store import InvestigationStore
        store = InvestigationStore()
        cases = store.list_cases()
        store.close()

        # Only register if there's at least one case
        if not cases:
            return

        registry.register(InvestigateStatusTool())
        registry.register(InvestigateQueryTool())
        registry.register(InvestigatePatternsTool())
        registry.register(InvestigateTimelineTool())
        log.debug("Investigation tools registered (%d cases)", len(cases))

    except Exception:
        # DB doesn't exist or can't be opened — skip silently
        pass
