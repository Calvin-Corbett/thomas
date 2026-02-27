"""Knowledge graph module for semantic reasoning and entity relations."""

from thomas.knowledge_graph.core import (
    Entity,
    KnowledgeGraph,
    Relation,
    Triple,
)
from thomas.knowledge_graph.tools import register_knowledge_graph_tools

__all__ = [
    "Triple",
    "Entity",
    "Relation",
    "KnowledgeGraph",
    "register_knowledge_graph_tools",
]
