"""Tools for document database operations."""

from typing import Any

from thomas.docdb import core
from thomas.tools.base import Tool, ToolResult


class DocumentQueryTool(Tool):
    """Query and retrieve documents from collections."""

    name = "docdb_query"
    category = "docdb"
    description = "Query documents from a collection with filters"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["find_one", "find", "count"], "description": "Query action"},
            "collection": {"type": "string", "description": "Collection name"},
            "query": {"type": "object", "description": "Query filter"},
            "limit": {"type": "integer", "description": "Result limit"},
        },
        "required": ["action", "collection"],
    }

    def __init__(self):
        self.db = core.DocumentDatabase()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            collection_name = args.get("collection", "")
            query = args.get("query", {})
            limit = args.get("limit", 0)

            coll = self.db.get_collection(collection_name)
            if not coll:
                return ToolResult(ok=False, error=f"Collection {collection_name} not found")

            if action == "find_one":
                result = coll.find_one(query)
                return ToolResult(ok=True, data=result)

            elif action == "find":
                results = coll.find(query, limit=limit)
                return ToolResult(ok=True, data={"documents": results, "count": len(results)})

            elif action == "count":
                count = coll.count_documents(query)
                return ToolResult(ok=True, data={"count": count})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class DocumentMutationTool(Tool):
    """Insert, update, and delete documents."""

    name = "docdb_mutate"
    category = "docdb"
    description = "Insert, update, or delete documents"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["insert_one", "insert_many", "update_one", "update_many", "delete_one", "delete_many"],
                "description": "Mutation action",
            },
            "collection": {"type": "string", "description": "Collection name"},
            "document": {"type": "object", "description": "Document to insert"},
            "documents": {"type": "array", "description": "Documents to insert"},
            "query": {"type": "object", "description": "Query filter"},
            "update": {"type": "object", "description": "Update operators"},
        },
        "required": ["action", "collection"],
    }

    def __init__(self):
        self.db = core.DocumentDatabase()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            collection_name = args.get("collection", "")

            coll = self.db.create_collection(collection_name)

            if action == "insert_one":
                doc = args.get("document", {})
                doc_id = coll.insert_one(doc)
                return ToolResult(ok=True, data={"inserted_id": doc_id})

            elif action == "insert_many":
                docs = args.get("documents", [])
                ids = coll.insert_many(docs)
                return ToolResult(ok=True, data={"inserted_ids": ids, "count": len(ids)})

            elif action == "update_one":
                query = args.get("query", {})
                update = args.get("update", {})
                count = coll.update_one(query, update)
                return ToolResult(ok=True, data={"modified": count})

            elif action == "update_many":
                query = args.get("query", {})
                update = args.get("update", {})
                count = coll.update_many(query, update)
                return ToolResult(ok=True, data={"modified": count})

            elif action == "delete_one":
                query = args.get("query", {})
                count = coll.delete_one(query)
                return ToolResult(ok=True, data={"deleted": count})

            elif action == "delete_many":
                query = args.get("query", {})
                count = coll.delete_many(query)
                return ToolResult(ok=True, data={"deleted": count})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class AggregationTool(Tool):
    """Run aggregation pipelines."""

    name = "docdb_aggregate"
    category = "docdb"
    description = "Execute aggregation pipelines with $match, $group, $project, etc."
    parameters = {
        "type": "object",
        "properties": {
            "collection": {"type": "string", "description": "Collection name"},
            "pipeline": {"type": "array", "description": "Aggregation pipeline stages"},
        },
        "required": ["collection", "pipeline"],
    }

    def __init__(self):
        self.db = core.DocumentDatabase()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            collection_name = args.get("collection", "")
            pipeline = args.get("pipeline", [])

            coll = self.db.get_collection(collection_name)
            if not coll:
                return ToolResult(ok=False, error=f"Collection {collection_name} not found")

            results = coll.aggregate(pipeline)
            return ToolResult(ok=True, data={"results": results, "count": len(results)})

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_docdb_tools(registry):
    """Register all docdb tools."""
    registry.register(DocumentQueryTool())
    registry.register(DocumentMutationTool())
    registry.register(AggregationTool())
