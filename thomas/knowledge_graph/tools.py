"""Tools for knowledge graph operations."""

from typing import Any

from thomas.knowledge_graph import core
from thomas.tools.base import Tool, ToolResult


class TripleManagementTool(Tool):
    """Manage triples in knowledge graph."""

    name = "kg_triples"
    category = "knowledge_graph"
    description = "Add and query triples in knowledge graph"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add_fact", "query_triples", "get_outgoing", "get_incoming"],
                "description": "Triple action",
            },
            "subject": {"type": "string", "description": "Triple subject"},
            "predicate": {"type": "string", "description": "Triple predicate"},
            "object": {"type": "string", "description": "Triple object"},
            "confidence": {"type": "number", "description": "Confidence score"},
            "entity_id": {"type": "string", "description": "Entity identifier"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.kg = core.KnowledgeGraph()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "add_fact":
                subject = args.get("subject", "")
                predicate = args.get("predicate", "")
                obj = args.get("object", "")
                confidence = args.get("confidence", 1.0)

                if not all([subject, predicate, obj]):
                    return ToolResult(ok=False, error="subject, predicate, object required")

                self.kg.add_fact(subject, predicate, obj, confidence)
                return ToolResult(ok=True, data={"added": True})

            elif action == "query_triples":
                subject = args.get("subject")
                predicate = args.get("predicate")
                obj = args.get("object")

                triples = self.kg.query_triples(subject, predicate, obj)
                return ToolResult(
                    ok=True,
                    data={
                        "triples": [
                            {"s": t.subject, "p": t.predicate, "o": t.obj, "conf": t.confidence} for t in triples
                        ],
                        "count": len(triples),
                    },
                )

            elif action == "get_outgoing":
                entity_id = args.get("entity_id", "")
                if not entity_id:
                    return ToolResult(ok=False, error="entity_id required")

                triples = self.kg.get_outgoing(entity_id)
                return ToolResult(
                    ok=True,
                    data={
                        "triples": [{"predicate": t.predicate, "target": t.obj} for t in triples],
                        "count": len(triples),
                    },
                )

            elif action == "get_incoming":
                entity_id = args.get("entity_id", "")
                if not entity_id:
                    return ToolResult(ok=False, error="entity_id required")

                triples = self.kg.get_incoming(entity_id)
                return ToolResult(
                    ok=True,
                    data={
                        "triples": [{"predicate": t.predicate, "source": t.subject} for t in triples],
                        "count": len(triples),
                    },
                )

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class EntityManagementTool(Tool):
    """Manage entities in knowledge graph."""

    name = "kg_entities"
    category = "knowledge_graph"
    description = "Manage entities and relationships"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add_entity", "get_entity_info", "find_path", "graph_schema"],
                "description": "Entity action",
            },
            "entity_id": {"type": "string", "description": "Entity identifier"},
            "entity_type": {"type": "string", "description": "Entity type"},
            "start": {"type": "string", "description": "Start entity for pathfinding"},
            "end": {"type": "string", "description": "End entity for pathfinding"},
            "max_hops": {"type": "integer", "description": "Max hops for pathfinding"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.kg = core.KnowledgeGraph()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "add_entity":
                entity_id = args.get("entity_id", "")
                entity_type = args.get("entity_type", "Thing")

                if not entity_id:
                    return ToolResult(ok=False, error="entity_id required")

                entity = core.Entity(entity_id, entity_type)
                self.kg.add_entity(entity)
                return ToolResult(ok=True, data={"entity_id": entity_id, "added": True})

            elif action == "get_entity_info":
                entity_id = args.get("entity_id", "")
                if not entity_id:
                    return ToolResult(ok=False, error="entity_id required")

                info = self.kg.get_entity_info(entity_id)
                if not info:
                    return ToolResult(ok=False, error=f"Entity {entity_id} not found")

                return ToolResult(ok=True, data=info)

            elif action == "find_path":
                start = args.get("start", "")
                end = args.get("end", "")
                max_hops = args.get("max_hops", 5)

                if not start or not end:
                    return ToolResult(ok=False, error="start and end required")

                path = self.kg.find_path(start, end, max_hops)
                if not path:
                    return ToolResult(ok=False, error="No path found")

                return ToolResult(ok=True, data={"path": path, "hops": len(path) - 1})

            elif action == "graph_schema":
                schema = self.kg.get_schema()
                return ToolResult(ok=True, data=schema)

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_knowledge_graph_tools(registry):
    """Register all knowledge graph tools."""
    registry.register(TripleManagementTool())
    registry.register(EntityManagementTool())
