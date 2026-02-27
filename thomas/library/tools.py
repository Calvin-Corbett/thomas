"""Tools for library module - research library and knowledge storage."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from thomas.tools.base import Tool, ToolResult

from .store import ResearchLibrary

log = logging.getLogger(__name__)


class LibraryAddEntryTool(Tool):
    """Add an entry to the research library."""

    name = "library_add_entry"
    category = "library"
    description = "Add a research note, document, or reference to the library."
    parameters = {
        "type": "object",
        "properties": {
            "library_root": {
                "type": "string",
                "description": "Path to library root directory",
            },
            "title": {
                "type": "string",
                "description": "Entry title",
            },
            "category": {
                "type": "string",
                "description": "Entry category (e.g., 'research-notes', 'papers', 'docs')",
            },
            "content": {
                "type": "string",
                "description": "Full content of the entry",
            },
            "summary": {
                "type": "string",
                "description": "Brief summary (optional)",
            },
            "source": {
                "type": "string",
                "description": "Source reference (optional)",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tags for categorization (optional)",
            },
            "query": {
                "type": "string",
                "description": "Original search query if auto-captured (optional)",
            },
            "dedupe": {
                "type": "boolean",
                "description": "Skip if fingerprint already exists (default: true)",
            },
        },
        "required": ["library_root", "title", "category", "content"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            library_root = Path(args["library_root"])
            library = ResearchLibrary(library_root)

            result = library.add_entry(
                title=args["title"],
                category=args["category"],
                content=args["content"],
                summary=args.get("summary", ""),
                source=args.get("source", ""),
                tags=args.get("tags", []),
                query=args.get("query", ""),
                auto_captured=False,
                dedupe=args.get("dedupe", True),
            )

            return ToolResult(ok=True, data=result)
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class LibraryListEntriesTool(Tool):
    """List entries in the research library."""

    name = "library_list_entries"
    category = "library"
    description = "List library entries with optional filtering and search."
    parameters = {
        "type": "object",
        "properties": {
            "library_root": {
                "type": "string",
                "description": "Path to library root directory",
            },
            "category": {
                "type": "string",
                "description": "Filter by category (optional)",
            },
            "query": {
                "type": "string",
                "description": "Search query to match against titles, summaries, tags (optional)",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of entries to return (default: 20)",
            },
        },
        "required": ["library_root"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            library_root = Path(args["library_root"])
            library = ResearchLibrary(library_root)

            entries = library.list_entries(
                category=args.get("category"),
                query=args.get("query"),
                limit=args.get("limit", 20),
            )

            return ToolResult(ok=True, data={"entries": entries})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class LibraryGetEntryTool(Tool):
    """Get a specific library entry with full content."""

    name = "library_get_entry"
    category = "library"
    description = "Retrieve a specific library entry by ID with full content."
    parameters = {
        "type": "object",
        "properties": {
            "library_root": {
                "type": "string",
                "description": "Path to library root directory",
            },
            "entry_id": {
                "type": "string",
                "description": "Entry ID to retrieve",
            },
        },
        "required": ["library_root", "entry_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            library_root = Path(args["library_root"])
            library = ResearchLibrary(library_root)

            entry = library.get_entry(args["entry_id"])
            if entry is None:
                return ToolResult(ok=False, error=f"Entry not found: {args['entry_id']}")

            return ToolResult(ok=True, data=entry)
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class LibraryScanEntriesTool(Tool):
    """Scan recently updated entries for incremental processing."""

    name = "library_scan_entries"
    category = "library"
    description = "Get entries updated after a checkpoint for incremental processing."
    parameters = {
        "type": "object",
        "properties": {
            "library_root": {
                "type": "string",
                "description": "Path to library root directory",
            },
            "updated_after_ts_utc": {
                "type": "integer",
                "description": "Unix timestamp to filter by (default: 0)",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum entries to return (default: 100)",
            },
        },
        "required": ["library_root"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            library_root = Path(args["library_root"])
            library = ResearchLibrary(library_root)

            entries = library.scan_entries(
                updated_after_ts_utc=args.get("updated_after_ts_utc", 0),
                limit=args.get("limit", 100),
            )

            return ToolResult(ok=True, data={"entries": entries})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class LibraryBuildContextTool(Tool):
    """Build context from library for LLM queries."""

    name = "library_build_context"
    category = "library"
    description = "Build formatted context from library matching a query for LLM consumption."
    parameters = {
        "type": "object",
        "properties": {
            "library_root": {
                "type": "string",
                "description": "Path to library root directory",
            },
            "query": {
                "type": "string",
                "description": "Search query to find relevant entries",
            },
            "max_tokens": {
                "type": "integer",
                "description": "Maximum tokens for context (default: 900)",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum entries to include (default: 4)",
            },
        },
        "required": ["library_root", "query"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            library_root = Path(args["library_root"])
            library = ResearchLibrary(library_root)

            context = library.build_context(
                query=args["query"],
                max_tokens=args.get("max_tokens", 900),
                limit=args.get("limit", 4),
            )

            return ToolResult(ok=True, data={"context": context})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class LibraryAddResearchNoteTool(Tool):
    """Add a research note to the library."""

    name = "library_add_research_note"
    category = "library"
    description = "Add a research question and answer as a library entry."
    parameters = {
        "type": "object",
        "properties": {
            "library_root": {
                "type": "string",
                "description": "Path to library root directory",
            },
            "query": {
                "type": "string",
                "description": "Research question or search query",
            },
            "answer": {
                "type": "string",
                "description": "Research answer or findings",
            },
            "source": {
                "type": "string",
                "description": "Source reference (default: 'assistant')",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tags (default: research, auto-captured)",
            },
        },
        "required": ["library_root", "query", "answer"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            library_root = Path(args["library_root"])
            library = ResearchLibrary(library_root)

            result = library.add_research_note(
                query=args["query"],
                answer=args["answer"],
                source=args.get("source", "assistant"),
                category="research-notes",
                tags=args.get("tags"),
            )

            return ToolResult(ok=True, data=result)
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_library_tools(registry):
    """Register library tools with the tool registry."""
    tools = [
        LibraryAddEntryTool(),
        LibraryListEntriesTool(),
        LibraryGetEntryTool(),
        LibraryScanEntriesTool(),
        LibraryBuildContextTool(),
        LibraryAddResearchNoteTool(),
    ]
    for tool in tools:
        registry.register(tool)
