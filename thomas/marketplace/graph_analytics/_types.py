"""
Type definitions for graph analytics module.

Defines core data structures for representing graphs and algorithm results.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class GraphType(Enum):
    """Enumeration of graph types."""

    DIRECTED = "directed"
    """A directed graph where edges have a direction."""

    UNDIRECTED = "undirected"
    """An undirected graph where edges have no direction."""

    WEIGHTED = "weighted"
    """A weighted graph where edges have associated weights."""


@dataclass
class Node:
    """
    Represents a node in a graph.

    Attributes:
        id: Unique identifier for the node.
        attrs: Optional dictionary of node attributes.
    """

    id: Any
    attrs: dict[str, Any] = field(default_factory=dict)

    def __hash__(self) -> int:
        """Return hash of node ID for use in sets and dicts."""
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        """Check equality based on node ID."""
        if not isinstance(other, Node):
            return NotImplemented
        return self.id == other.id

    def __repr__(self) -> str:
        """Return string representation of node."""
        return f"Node({self.id})"


@dataclass
class Edge:
    """
    Represents an edge in a graph.

    Attributes:
        src: Source node ID.
        dst: Destination node ID.
        weight: Weight of the edge (default 1.0).
        attrs: Optional dictionary of edge attributes.
    """

    src: Any
    dst: Any
    weight: float = 1.0
    attrs: dict[str, Any] = field(default_factory=dict)

    def __hash__(self) -> int:
        """Return hash of edge for use in sets and dicts."""
        return hash((self.src, self.dst))

    def __eq__(self, other: object) -> bool:
        """Check equality based on source and destination."""
        if not isinstance(other, Edge):
            return NotImplemented
        return self.src == other.src and self.dst == other.dst

    def __repr__(self) -> str:
        """Return string representation of edge."""
        return f"Edge({self.src} -> {self.dst}, weight={self.weight})"


@dataclass
class PathResult:
    """
    Result of a shortest path algorithm.

    Attributes:
        path: List of node IDs forming the path (empty if no path exists).
        distance: Total distance of the path (infinity if no path exists).
        distances: Dictionary mapping node IDs to distances from source.
        predecessors: Dictionary mapping node IDs to their predecessors in path.
    """

    path: list[Any] = field(default_factory=list)
    distance: float = float("inf")
    distances: dict[Any, float] = field(default_factory=dict)
    predecessors: dict[Any, Any | None] = field(default_factory=dict)

    def has_path(self) -> bool:
        """Check if a valid path exists."""
        return self.distance != float("inf") and len(self.path) > 0

    def __repr__(self) -> str:
        """Return string representation of path result."""
        return f"PathResult(path={self.path}, distance={self.distance})"


@dataclass
class CommunityResult:
    """
    Result of a community detection algorithm.

    Attributes:
        communities: List of sets, each set containing node IDs in a community.
        modularity: Quality metric for the community structure (0 to 1).
        quality_metrics: Dictionary of additional quality metrics.
        hierarchy: Optional hierarchical structure (for hierarchical methods).
    """

    communities: list[set[Any]] = field(default_factory=list)
    modularity: float = 0.0
    quality_metrics: dict[str, float] = field(default_factory=dict)
    hierarchy: dict[str, Any] | None = None

    def num_communities(self) -> int:
        """Return the number of communities detected."""
        return len(self.communities)

    def community_sizes(self) -> list[int]:
        """Return sorted list of community sizes."""
        return sorted([len(c) for c in self.communities], reverse=True)

    def __repr__(self) -> str:
        """Return string representation of community result."""
        return f"CommunityResult(num_communities={self.num_communities()}, " f"modularity={self.modularity:.4f})"


@dataclass
class CentralityResult:
    """
    Result of a centrality measure calculation.

    Attributes:
        scores: Dictionary mapping node IDs to centrality scores.
        measure: Name of the centrality measure.
        normalized: Whether scores are normalized to [0, 1].
        statistics: Dictionary of summary statistics.
    """

    scores: dict[Any, float] = field(default_factory=dict)
    measure: str = ""
    normalized: bool = False
    statistics: dict[str, float] = field(default_factory=dict)

    def top_nodes(self, k: int = 10) -> list[tuple[Any, float]]:
        """
        Return top k nodes by centrality score.

        Args:
            k: Number of top nodes to return.

        Returns:
            List of (node_id, score) tuples sorted by score descending.
        """
        sorted_scores = sorted(self.scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_scores[:k]

    def __repr__(self) -> str:
        """Return string representation of centrality result."""
        return f"CentralityResult({self.measure}, nodes={len(self.scores)})"


@dataclass
class AnalyticsConfig:
    """
    Configuration for graph analytics operations.

    Attributes:
        max_iterations: Maximum iterations for iterative algorithms.
        tolerance: Convergence tolerance for iterative algorithms.
        damping_factor: Damping factor for PageRank (default 0.85).
        seed: Random seed for reproducibility.
        num_workers: Number of workers for parallel operations.
        verbose: Enable verbose logging.
    """

    max_iterations: int = 1000
    tolerance: float = 1e-6
    damping_factor: float = 0.85
    seed: int | None = None
    num_workers: int = 1
    verbose: bool = False

    def __repr__(self) -> str:
        """Return string representation of config."""
        return f"AnalyticsConfig(max_iter={self.max_iterations}, " f"tol={self.tolerance})"


# Type aliases for common patterns
NodeID = Any
EdgeWeight = float
NodeSet = set[NodeID]
NodeDict = dict[NodeID, Any]
AdjacencyList = dict[NodeID, list[tuple[NodeID, EdgeWeight]]]
