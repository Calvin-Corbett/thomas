"""Type definitions for the graph database engine."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PropertyType(Enum):
    """Supported property types in the graph database."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    LIST = "list"
    MAP = "map"


class TraversalDirection(Enum):
    """Direction for graph traversal operations."""

    OUTBOUND = "outbound"
    INBOUND = "inbound"
    BOTH = "both"


@dataclass(frozen=True)
class Node:
    """Represents a node in the property graph.

    Attributes:
        id: Unique identifier for the node
        labels: Set of labels associated with this node
        properties: Dictionary of node properties
    """

    id: str
    labels: frozenset[str] = field(default_factory=frozenset)
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate node properties."""
        if not self.id:
            raise ValueError("Node id cannot be empty")
        if not isinstance(self.labels, frozenset):
            object.__setattr__(self, "labels", frozenset(self.labels))
        if not isinstance(self.properties, dict):
            object.__setattr__(self, "properties", dict(self.properties))

    def has_label(self, label: str) -> bool:
        """Check if node has a specific label."""
        return label in self.labels

    def get_property(self, key: str, default: Any = None) -> Any:
        """Get a property value with optional default."""
        return self.properties.get(key, default)


@dataclass(frozen=True)
class Edge:
    """Represents an edge in the property graph.

    Attributes:
        id: Unique identifier for the edge
        source: ID of the source node
        target: ID of the target node
        type: Edge type/relationship type
        properties: Dictionary of edge properties
    """

    id: str
    source: str
    target: str
    type: str
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate edge properties."""
        if not self.id or not self.source or not self.target or not self.type:
            raise ValueError("Edge id, source, target, and type cannot be empty")
        if not isinstance(self.properties, dict):
            object.__setattr__(self, "properties", dict(self.properties))

    def get_property(self, key: str, default: Any = None) -> Any:
        """Get a property value with optional default."""
        return self.properties.get(key, default)


@dataclass
class PropertyDefinition:
    """Definition of a property in a schema.

    Attributes:
        name: Property name
        type: Property type
        required: Whether this property is required
        unique: Whether values must be unique
        indexed: Whether to create an index
    """

    name: str
    type: PropertyType
    required: bool = False
    unique: bool = False
    indexed: bool = False


@dataclass
class NodeLabelSchema:
    """Schema for a node label.

    Attributes:
        label: The node label
        properties: Property definitions for this label
        abstract: Whether this is an abstract label
    """

    label: str
    properties: dict[str, PropertyDefinition] = field(default_factory=dict)
    abstract: bool = False


@dataclass
class EdgeTypeSchema:
    """Schema for an edge type.

    Attributes:
        type: The edge type
        properties: Property definitions for this edge type
        source_labels: Allowed source node labels (empty = any)
        target_labels: Allowed target node labels (empty = any)
    """

    type: str
    properties: dict[str, PropertyDefinition] = field(default_factory=dict)
    source_labels: set[str] = field(default_factory=set)
    target_labels: set[str] = field(default_factory=set)


@dataclass
class GraphSchema:
    """Complete schema for the graph.

    Attributes:
        node_label_schemas: Node label schemas by label name
        edge_type_schemas: Edge type schemas by type name
        constraints: Global constraints
    """

    node_label_schemas: dict[str, NodeLabelSchema] = field(default_factory=dict)
    edge_type_schemas: dict[str, EdgeTypeSchema] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)

    def add_node_label_schema(self, schema: NodeLabelSchema) -> None:
        """Add or update a node label schema."""
        self.node_label_schemas[schema.label] = schema

    def add_edge_type_schema(self, schema: EdgeTypeSchema) -> None:
        """Add or update an edge type schema."""
        self.edge_type_schemas[schema.type] = schema

    def get_node_label_schema(self, label: str) -> NodeLabelSchema | None:
        """Get schema for a node label."""
        return self.node_label_schemas.get(label)

    def get_edge_type_schema(self, edge_type: str) -> EdgeTypeSchema | None:
        """Get schema for an edge type."""
        return self.edge_type_schemas.get(edge_type)


@dataclass
class IndexDefinition:
    """Definition of an index.

    Attributes:
        id: Unique identifier for the index
        name: Human-readable name
        index_type: Type of index (label, property, composite, fulltext)
        fields: Fields included in the index
        unique: Whether the index enforces uniqueness
        active: Whether the index is active
    """

    id: str
    name: str
    index_type: str
    fields: list[str]
    unique: bool = False
    active: bool = True

    def __post_init__(self) -> None:
        """Validate index definition."""
        if not self.id or not self.name:
            raise ValueError("Index id and name cannot be empty")
        if self.index_type not in ("label", "property", "composite", "fulltext"):
            raise ValueError(f"Invalid index_type: {self.index_type}")
        if not self.fields:
            raise ValueError("Index must have at least one field")


@dataclass
class QueryPlanStep:
    """Single step in a query execution plan.

    Attributes:
        operation: Type of operation (scan, expand, filter, project, aggregate)
        details: Operation-specific details
        estimated_rows: Estimated number of rows produced
        cost: Estimated cost
    """

    operation: str
    details: dict[str, Any] = field(default_factory=dict)
    estimated_rows: int = -1
    cost: float = 0.0


@dataclass
class QueryPlan:
    """Execution plan for a query.

    Attributes:
        steps: Sequence of execution steps
        estimated_total_cost: Total estimated cost
        total_estimated_rows: Total estimated rows
        optimizations_applied: List of optimizations applied
    """

    steps: list[QueryPlanStep] = field(default_factory=list)
    estimated_total_cost: float = 0.0
    total_estimated_rows: int = -1
    optimizations_applied: list[str] = field(default_factory=list)

    def add_step(self, step: QueryPlanStep) -> None:
        """Add a step to the plan."""
        self.steps.append(step)
        self.estimated_total_cost += step.cost
        if self.total_estimated_rows < 0:
            self.total_estimated_rows = step.estimated_rows
        else:
            self.total_estimated_rows = min(self.total_estimated_rows, step.estimated_rows)


@dataclass
class ASTNode:
    """Abstract syntax tree node for parsed queries.

    Attributes:
        type: Node type (QUERY, MATCH, WHERE, RETURN, CREATE, DELETE, SET, etc.)
        value: Node value/content
        children: Child nodes
    """

    type: str
    value: Any = None
    children: list["ASTNode"] = field(default_factory=list)

    def add_child(self, child: "ASTNode") -> None:
        """Add a child node."""
        self.children.append(child)


@dataclass
class PatternElement:
    """Element in a MATCH pattern (node or edge).

    Attributes:
        variable: Variable name (None if not bound)
        element_type: 'node' or 'edge'
        labels_or_type: Node labels or edge type
        properties: Property constraints
    """

    variable: str | None
    element_type: str
    labels_or_type: set[str] | None = None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Path:
    """Represents a path through the graph.

    Attributes:
        nodes: List of node IDs in the path
        edges: List of edge IDs connecting nodes
        length: Path length (number of edges)
    """

    nodes: list[str] = field(default_factory=list)
    edges: list[str] = field(default_factory=list)

    @property
    def length(self) -> int:
        """Get the length of the path."""
        return len(self.edges)

    def __hash__(self) -> int:
        """Make path hashable."""
        return hash((tuple(self.nodes), tuple(self.edges)))

    def __eq__(self, other: object) -> bool:
        """Check path equality."""
        if not isinstance(other, Path):
            return NotImplemented
        return self.nodes == other.nodes and self.edges == other.edges
