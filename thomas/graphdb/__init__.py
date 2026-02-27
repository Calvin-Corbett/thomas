"""Thomas Graph Database - A property graph database engine.

This module provides a complete property graph database implementation with:
- Property graph storage (nodes and edges)
- Cypher-subset query language
- Graph traversal algorithms (BFS, DFS, shortest path, etc.)
- Graph algorithms (PageRank, community detection, centrality, etc.)
- Schema management and validation
- Index management
- Query optimization
- Multiple serialization formats
"""

from thomas.graphdb._exceptions import (
    ConstraintViolationError,
    EdgeNotFoundError,
    GraphDBError,
    IndexError,
    NodeNotFoundError,
    QuerySyntaxError,
    SchemaError,
    TransactionError,
)
from thomas.graphdb._types import (
    ASTNode,
    Edge,
    EdgeTypeSchema,
    GraphSchema,
    IndexDefinition,
    Node,
    NodeLabelSchema,
    Path,
    PatternElement,
    PropertyDefinition,
    PropertyType,
    QueryPlan,
    QueryPlanStep,
    TraversalDirection,
)
from thomas.graphdb.algorithms import GraphAlgorithms
from thomas.graphdb.index import BTreeIndex, CompositeIndex, IndexManager
from thomas.graphdb.optimizer import QueryOptimizer
from thomas.graphdb.query_engine import QueryExecutor, execute_query
from thomas.graphdb.query_parser import Lexer
from thomas.graphdb.query_planner import Parser, parse_query
from thomas.graphdb.schema import SchemaManager
from thomas.graphdb.serialization import GraphSerializer
from thomas.graphdb.storage import GraphStorage, Transaction
from thomas.graphdb.traversal import GraphTraversal

__version__ = "0.1.0"
__author__ = "Thomas Project"

__all__ = [
    # Exceptions
    "GraphDBError",
    "NodeNotFoundError",
    "EdgeNotFoundError",
    "ConstraintViolationError",
    "QuerySyntaxError",
    "IndexError",
    "SchemaError",
    "TransactionError",
    # Types
    "Node",
    "Edge",
    "Path",
    "PropertyType",
    "TraversalDirection",
    "GraphSchema",
    "NodeLabelSchema",
    "EdgeTypeSchema",
    "PropertyDefinition",
    "IndexDefinition",
    "QueryPlan",
    "QueryPlanStep",
    "ASTNode",
    "PatternElement",
    # Storage and transactions
    "GraphStorage",
    "Transaction",
    # Query processing
    "Lexer",
    "Parser",
    "parse_query",
    "QueryExecutor",
    "execute_query",
    "QueryOptimizer",
    # Algorithms
    "GraphTraversal",
    "GraphAlgorithms",
    # Schema and indices
    "SchemaManager",
    "IndexManager",
    "BTreeIndex",
    "CompositeIndex",
    # Serialization
    "GraphSerializer",
]
