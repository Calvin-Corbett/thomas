"""Graph storage engine with adjacency list and index support."""

import copy
from collections import defaultdict
from typing import Any

from thomas.marketplace.graphdb._exceptions import (
    EdgeNotFoundError,
    GraphDBError,
    NodeNotFoundError,
    TransactionError,
)
from thomas.marketplace.graphdb._types import Edge, Node


class Transaction:
    """Manages a database transaction with copy-on-write semantics."""

    def __init__(self, storage: "GraphStorage") -> None:
        """Initialize a transaction.

        Args:
            storage: The graph storage engine
        """
        self.storage = storage
        self.is_active = False
        self.node_store: dict[str, Node] | None = None
        self.edge_store: dict[str, Edge] | None = None
        self.outbound_edges: dict[str, list[str]] | None = None
        self.inbound_edges: dict[str, list[str]] | None = None
        self.label_index: dict[str, set[str]] | None = None
        self.property_index: dict[str, dict[Any, set[str]]] | None = None
        self.edge_type_index: dict[str, set[str]] | None = None

    def begin(self) -> None:
        """Begin a new transaction with copy-on-write snapshots."""
        if self.is_active:
            raise TransactionError("Transaction already active")

        self.is_active = True
        self.node_store = copy.copy(self.storage.node_store)
        self.edge_store = copy.copy(self.storage.edge_store)
        self.outbound_edges = copy.deepcopy(self.storage.outbound_edges)
        self.inbound_edges = copy.deepcopy(self.storage.inbound_edges)
        self.label_index = {k: v.copy() for k, v in self.storage.label_index.items()}
        self.property_index = {
            k: {kk: vv.copy() for kk, vv in v.items()} for k, v in self.storage.property_index.items()
        }
        self.edge_type_index = {k: v.copy() for k, v in self.storage.edge_type_index.items()}

    def commit(self) -> None:
        """Commit the transaction and apply changes to main storage."""
        if not self.is_active:
            raise TransactionError("No active transaction to commit")

        self.storage.node_store = self.node_store
        self.storage.edge_store = self.edge_store
        self.storage.outbound_edges = self.outbound_edges
        self.storage.inbound_edges = self.inbound_edges
        self.storage.label_index = self.label_index
        self.storage.property_index = self.property_index
        self.storage.edge_type_index = self.edge_type_index
        self.is_active = False

    def rollback(self) -> None:
        """Rollback the transaction, discarding changes."""
        if not self.is_active:
            raise TransactionError("No active transaction to rollback")
        self.is_active = False
        self.node_store = None
        self.edge_store = None
        self.outbound_edges = None
        self.inbound_edges = None
        self.label_index = None
        self.property_index = None
        self.edge_type_index = None


class GraphStorage:
    """Storage engine for property graph with adjacency list representation."""

    def __init__(self) -> None:
        """Initialize the graph storage engine."""
        # Core storage
        self.node_store: dict[str, Node] = {}
        self.edge_store: dict[str, Edge] = {}

        # Adjacency lists (both directions)
        self.outbound_edges: dict[str, list[str]] = defaultdict(list)
        self.inbound_edges: dict[str, list[str]] = defaultdict(list)

        # Indices
        self.label_index: dict[str, set[str]] = defaultdict(set)
        self.property_index: dict[str, dict[Any, set[str]]] = defaultdict(lambda: defaultdict(set))
        self.edge_type_index: dict[str, set[str]] = defaultdict(set)

        # Unique constraints
        self.unique_constraints: dict[str, set[Any]] = defaultdict(set)

        # Transaction management
        self.current_transaction: Transaction | None = None

    def _get_active_store(self) -> "GraphStorage":
        """Get the active storage (transaction or main)."""
        if self.current_transaction and self.current_transaction.is_active:
            return self.current_transaction.storage
        return self

    def begin_transaction(self) -> Transaction:
        """Begin a new transaction.

        Returns:
            Transaction object

        Raises:
            TransactionError: If a transaction is already active
        """
        if self.current_transaction and self.current_transaction.is_active:
            raise TransactionError("Transaction already active")

        self.current_transaction = Transaction(self)
        self.current_transaction.begin()
        return self.current_transaction

    def commit_transaction(self) -> None:
        """Commit the current transaction.

        Raises:
            TransactionError: If no transaction is active
        """
        if not self.current_transaction or not self.current_transaction.is_active:
            raise TransactionError("No active transaction")
        self.current_transaction.commit()

    def rollback_transaction(self) -> None:
        """Rollback the current transaction.

        Raises:
            TransactionError: If no transaction is active
        """
        if not self.current_transaction or not self.current_transaction.is_active:
            raise TransactionError("No active transaction")
        self.current_transaction.rollback()

    def add_node(self, node: Node) -> None:
        """Add a node to the graph.

        Args:
            node: Node to add

        Raises:
            GraphDBError: If node already exists
        """
        if node.id in self.node_store:
            raise GraphDBError(f"Node {node.id} already exists")

        self.node_store[node.id] = node

        # Update label index
        for label in node.labels:
            self.label_index[label].add(node.id)

        # Update property index
        for key, value in node.properties.items():
            self.property_index[key][value].add(node.id)

    def get_node(self, node_id: str) -> Node:
        """Get a node by ID.

        Args:
            node_id: The node ID

        Returns:
            The node

        Raises:
            NodeNotFoundError: If node doesn't exist
        """
        if node_id not in self.node_store:
            raise NodeNotFoundError(node_id)
        return self.node_store[node_id]

    def update_node(self, node: Node) -> None:
        """Update a node.

        Args:
            node: Updated node

        Raises:
            NodeNotFoundError: If node doesn't exist
        """
        if node.id not in self.node_store:
            raise NodeNotFoundError(node.id)

        old_node = self.node_store[node.id]

        # Update label index
        removed_labels = old_node.labels - node.labels
        added_labels = node.labels - old_node.labels

        for label in removed_labels:
            self.label_index[label].discard(node.id)
        for label in added_labels:
            self.label_index[label].add(node.id)

        # Update property index
        removed_keys = set(old_node.properties.keys()) - set(node.properties.keys())
        for key in removed_keys:
            old_value = old_node.properties[key]
            self.property_index[key][old_value].discard(node.id)

        for key, value in node.properties.items():
            if key in old_node.properties:
                old_value = old_node.properties[key]
                if old_value != value:
                    self.property_index[key][old_value].discard(node.id)
                    self.property_index[key][value].add(node.id)
            else:
                self.property_index[key][value].add(node.id)

        self.node_store[node.id] = node

    def delete_node(self, node_id: str) -> None:
        """Delete a node and its edges.

        Args:
            node_id: The node ID

        Raises:
            NodeNotFoundError: If node doesn't exist
        """
        if node_id not in self.node_store:
            raise NodeNotFoundError(node_id)

        node = self.node_store[node_id]

        # Delete all edges connected to this node
        outbound = list(self.outbound_edges.get(node_id, []))
        inbound = list(self.inbound_edges.get(node_id, []))

        for edge_id in outbound + inbound:
            if edge_id in self.edge_store:
                self._delete_edge_internal(edge_id)

        # Update label index
        for label in node.labels:
            self.label_index[label].discard(node_id)

        # Update property index
        for key, value in node.properties.items():
            self.property_index[key][value].discard(node_id)

        del self.node_store[node_id]
        self.outbound_edges.pop(node_id, None)
        self.inbound_edges.pop(node_id, None)

    def add_edge(self, edge: Edge) -> None:
        """Add an edge to the graph.

        Args:
            edge: Edge to add

        Raises:
            GraphDBError: If edge already exists
            NodeNotFoundError: If source or target node doesn't exist
        """
        if edge.id in self.edge_store:
            raise GraphDBError(f"Edge {edge.id} already exists")

        if edge.source not in self.node_store:
            raise NodeNotFoundError(edge.source)
        if edge.target not in self.node_store:
            raise NodeNotFoundError(edge.target)

        self.edge_store[edge.id] = edge

        # Update adjacency lists
        self.outbound_edges[edge.source].append(edge.id)
        self.inbound_edges[edge.target].append(edge.id)

        # Update edge type index
        self.edge_type_index[edge.type].add(edge.id)

        # Update property index
        for key, value in edge.properties.items():
            self.property_index[key][value].add(edge.id)

    def get_edge(self, edge_id: str) -> Edge:
        """Get an edge by ID.

        Args:
            edge_id: The edge ID

        Returns:
            The edge

        Raises:
            EdgeNotFoundError: If edge doesn't exist
        """
        if edge_id not in self.edge_store:
            raise EdgeNotFoundError(edge_id)
        return self.edge_store[edge_id]

    def update_edge(self, edge: Edge) -> None:
        """Update an edge.

        Args:
            edge: Updated edge

        Raises:
            EdgeNotFoundError: If edge doesn't exist
        """
        if edge.id not in self.edge_store:
            raise EdgeNotFoundError(edge.id)

        old_edge = self.edge_store[edge.id]

        # Update property index
        removed_keys = set(old_edge.properties.keys()) - set(edge.properties.keys())
        for key in removed_keys:
            old_value = old_edge.properties[key]
            self.property_index[key][old_value].discard(edge.id)

        for key, value in edge.properties.items():
            if key in old_edge.properties:
                old_value = old_edge.properties[key]
                if old_value != value:
                    self.property_index[key][old_value].discard(edge.id)
                    self.property_index[key][value].add(edge.id)
            else:
                self.property_index[key][value].add(edge.id)

        self.edge_store[edge.id] = edge

    def _delete_edge_internal(self, edge_id: str) -> None:
        """Internal method to delete an edge without checking existence."""
        edge = self.edge_store[edge_id]

        # Update adjacency lists
        if edge.source in self.outbound_edges:
            self.outbound_edges[edge.source] = [e for e in self.outbound_edges[edge.source] if e != edge_id]
        if edge.target in self.inbound_edges:
            self.inbound_edges[edge.target] = [e for e in self.inbound_edges[edge.target] if e != edge_id]

        # Update edge type index
        self.edge_type_index[edge.type].discard(edge_id)

        # Update property index
        for key, value in edge.properties.items():
            self.property_index[key][value].discard(edge_id)

        del self.edge_store[edge_id]

    def delete_edge(self, edge_id: str) -> None:
        """Delete an edge.

        Args:
            edge_id: The edge ID

        Raises:
            EdgeNotFoundError: If edge doesn't exist
        """
        if edge_id not in self.edge_store:
            raise EdgeNotFoundError(edge_id)
        self._delete_edge_internal(edge_id)

    def get_outbound_edges(self, node_id: str, edge_type: str | None = None) -> list[Edge]:
        """Get outbound edges from a node.

        Args:
            node_id: The node ID
            edge_type: Optional filter by edge type

        Returns:
            List of edges

        Raises:
            NodeNotFoundError: If node doesn't exist
        """
        if node_id not in self.node_store:
            raise NodeNotFoundError(node_id)

        edge_ids = self.outbound_edges.get(node_id, [])
        edges = [self.edge_store[eid] for eid in edge_ids]

        if edge_type:
            edges = [e for e in edges if e.type == edge_type]

        return edges

    def get_inbound_edges(self, node_id: str, edge_type: str | None = None) -> list[Edge]:
        """Get inbound edges to a node.

        Args:
            node_id: The node ID
            edge_type: Optional filter by edge type

        Returns:
            List of edges

        Raises:
            NodeNotFoundError: If node doesn't exist
        """
        if node_id not in self.node_store:
            raise NodeNotFoundError(node_id)

        edge_ids = self.inbound_edges.get(node_id, [])
        edges = [self.edge_store[eid] for eid in edge_ids]

        if edge_type:
            edges = [e for e in edges if e.type == edge_type]

        return edges

    def get_adjacent_nodes(self, node_id: str, direction: str = "both", edge_type: str | None = None) -> list[str]:
        """Get adjacent node IDs.

        Args:
            node_id: The node ID
            direction: 'outbound', 'inbound', or 'both'
            edge_type: Optional filter by edge type

        Returns:
            List of adjacent node IDs

        Raises:
            NodeNotFoundError: If node doesn't exist
        """
        if node_id not in self.node_store:
            raise NodeNotFoundError(node_id)

        adjacent = set()

        if direction in ("outbound", "both"):
            edges = self.get_outbound_edges(node_id, edge_type)
            adjacent.update(e.target for e in edges)

        if direction in ("inbound", "both"):
            edges = self.get_inbound_edges(node_id, edge_type)
            adjacent.update(e.source for e in edges)

        return list(adjacent)

    def find_nodes_by_label(self, label: str) -> list[str]:
        """Find node IDs by label.

        Args:
            label: The label to search for

        Returns:
            List of node IDs
        """
        return list(self.label_index.get(label, set()))

    def find_nodes_by_property(self, key: str, value: Any) -> list[str]:
        """Find node IDs by property.

        Args:
            key: Property key
            value: Property value

        Returns:
            List of node IDs
        """
        return list(self.property_index.get(key, {}).get(value, set()))

    def find_edges_by_type(self, edge_type: str) -> list[str]:
        """Find edge IDs by type.

        Args:
            edge_type: The edge type

        Returns:
            List of edge IDs
        """
        return list(self.edge_type_index.get(edge_type, set()))

    def batch_add_nodes(self, nodes: list[Node]) -> None:
        """Add multiple nodes in batch.

        Args:
            nodes: List of nodes to add
        """
        for node in nodes:
            self.add_node(node)

    def batch_add_edges(self, edges: list[Edge]) -> None:
        """Add multiple edges in batch.

        Args:
            edges: List of edges to add
        """
        for edge in edges:
            self.add_edge(edge)

    def batch_delete_nodes(self, node_ids: list[str]) -> None:
        """Delete multiple nodes.

        Args:
            node_ids: List of node IDs to delete
        """
        for node_id in node_ids:
            if node_id in self.node_store:
                self.delete_node(node_id)

    def batch_delete_edges(self, edge_ids: list[str]) -> None:
        """Delete multiple edges.

        Args:
            edge_ids: List of edge IDs to delete
        """
        for edge_id in edge_ids:
            if edge_id in self.edge_store:
                self.delete_edge(edge_id)

    def clear(self) -> None:
        """Clear all data from the graph."""
        self.node_store.clear()
        self.edge_store.clear()
        self.outbound_edges.clear()
        self.inbound_edges.clear()
        self.label_index.clear()
        self.property_index.clear()
        self.edge_type_index.clear()
        self.unique_constraints.clear()

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about the graph.

        Returns:
            Dictionary with graph statistics
        """
        return {
            "node_count": len(self.node_store),
            "edge_count": len(self.edge_store),
            "label_count": len(self.label_index),
            "edge_type_count": len(self.edge_type_index),
            "labels": list(self.label_index.keys()),
            "edge_types": list(self.edge_type_index.keys()),
        }
