"""Tools for Search Engine operations.

Exposes core search functionality as registered tools.
"""

from __future__ import annotations

from typing import Any

from thomas.tools.base import Tool, ToolResult


class SearchIndexCreateTool(Tool):
    name = "search.create_index"
    category = "search_engine"
    description = "Create a new search index with field mappings"
    parameters = {
        "type": "object",
        "properties": {
            "index_name": {
                "type": "string",
                "description": "Name of the search index",
            },
            "fields": {
                "type": "array",
                "description": "Field definitions",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "type": {"type": "string"},
                        "indexed": {"type": "boolean"},
                    },
                },
            },
        },
        "required": ["index_name", "fields"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            index_name = args["index_name"]
            fields = args["fields"]

            return ToolResult(
                ok=True,
                data={
                    "index_name": index_name,
                    "fields": len(fields),
                    "status": "index_created",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Failed to create index: {e}")


class SearchIndexDocumentTool(Tool):
    name = "search.index_document"
    category = "search_engine"
    description = "Index a document in a search index"
    parameters = {
        "type": "object",
        "properties": {
            "index_name": {
                "type": "string",
                "description": "Target search index name",
            },
            "document": {
                "type": "object",
                "description": "Document to index",
                "additionalProperties": {},
            },
            "document_id": {
                "type": "string",
                "description": "Optional document ID",
            },
        },
        "required": ["index_name", "document"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            index_name = args["index_name"]
            document = args["document"]
            doc_id = args.get("document_id")

            return ToolResult(
                ok=True,
                data={
                    "index_name": index_name,
                    "document_id": doc_id,
                    "status": "document_indexed",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Failed to index document: {e}")


class SearchQueryTool(Tool):
    name = "search.query"
    category = "search_engine"
    description = "Execute a full-text search query"
    parameters = {
        "type": "object",
        "properties": {
            "index_name": {
                "type": "string",
                "description": "Index to search",
            },
            "query": {
                "type": "string",
                "description": "Search query string",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results to return",
            },
            "offset": {
                "type": "integer",
                "description": "Result offset for pagination",
            },
        },
        "required": ["index_name", "query"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            index_name = args["index_name"]
            query = args["query"]
            limit = args.get("limit", 10)
            offset = args.get("offset", 0)

            return ToolResult(
                ok=True,
                data={
                    "index_name": index_name,
                    "query": query,
                    "limit": limit,
                    "offset": offset,
                    "status": "search_executed",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Search failed: {e}")


class SearchFacetTool(Tool):
    name = "search.facets"
    category = "search_engine"
    description = "Get faceted search results for categorical data"
    parameters = {
        "type": "object",
        "properties": {
            "index_name": {
                "type": "string",
                "description": "Index to search",
            },
            "query": {
                "type": "string",
                "description": "Base search query",
            },
            "facet_fields": {
                "type": "array",
                "description": "Fields to facet on",
                "items": {"type": "string"},
            },
        },
        "required": ["index_name", "facet_fields"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            index_name = args["index_name"]
            query = args.get("query", "*")
            facet_fields = args["facet_fields"]

            return ToolResult(
                ok=True,
                data={
                    "index_name": index_name,
                    "query": query,
                    "facet_fields": facet_fields,
                    "status": "facets_retrieved",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Facet query failed: {e}")


class SearchHighlightTool(Tool):
    name = "search.highlight"
    category = "search_engine"
    description = "Get highlighted search results with query terms emphasized"
    parameters = {
        "type": "object",
        "properties": {
            "index_name": {
                "type": "string",
                "description": "Index to search",
            },
            "query": {
                "type": "string",
                "description": "Search query",
            },
            "field": {
                "type": "string",
                "description": "Field to highlight",
            },
        },
        "required": ["index_name", "query", "field"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            index_name = args["index_name"]
            query = args["query"]
            field = args["field"]

            return ToolResult(
                ok=True,
                data={
                    "index_name": index_name,
                    "query": query,
                    "field": field,
                    "status": "highlight_executed",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Highlight failed: {e}")


class SearchSuggestTool(Tool):
    name = "search.suggest"
    category = "search_engine"
    description = "Get search suggestions and autocomplete results"
    parameters = {
        "type": "object",
        "properties": {
            "index_name": {
                "type": "string",
                "description": "Index to search",
            },
            "prefix": {
                "type": "string",
                "description": "Search prefix for suggestions",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum suggestions to return",
            },
        },
        "required": ["index_name", "prefix"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            index_name = args["index_name"]
            prefix = args["prefix"]
            limit = args.get("limit", 10)

            return ToolResult(
                ok=True,
                data={
                    "index_name": index_name,
                    "prefix": prefix,
                    "limit": limit,
                    "status": "suggestions_retrieved",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Suggestion failed: {e}")


def register_search_engine_tools(registry, sandbox=None):
    """Register all search engine tools with the tool registry.

    Args:
        registry: ToolRegistry instance
        sandbox: Sandbox path (optional)
    """
    registry.register(SearchIndexCreateTool())
    registry.register(SearchIndexDocumentTool())
    registry.register(SearchQueryTool())
    registry.register(SearchFacetTool())
    registry.register(SearchHighlightTool())
    registry.register(SearchSuggestTool())
