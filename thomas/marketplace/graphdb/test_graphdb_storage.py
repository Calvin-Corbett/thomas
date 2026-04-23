"""Tests for graph storage engine with CRUD, indices, transactions, and batch operations."""

import pytest

from thomas.marketplace.graphdb._exceptions import (
    GraphDBError,
    NodeNotFoundError,
    TransactionError,
)
from thomas.marketplace.graphdb._types import Edge, Node
from thomas.marketplace.graphdb.storage import GraphStorage


@pytest.fixture
def storage():
    """Create a fresh storage instance."""
    return GraphStorage()


class TestNodeCRUD:
    """Test node create, read, update, delete operations."""

    def test_add_node(self, storage: GraphStorage) -> None:
        """Test adding a node."""
        node = Node(id="n1", labels=frozenset(["Person"]), properties={"name": "Alice"})
        storage.add_node(node)

        assert "n1" in storage.node_store
        assert storage.node_store["n1"].properties["name"] == "Alice"

    def test_add_duplicate_node_fails(self, storage: GraphStorage) -> None:
        """Test that adding duplicate node raises error."""
        node = Node(id="n1", labels=frozenset(["Person"]))
        storage.add_node(node)

        with pytest.raises(GraphDBError):
            storage.add_node(node)

    def test_get_node(self, storage: GraphStorage) -> None:
        """Test getting a node."""
        node = Node(id="n1", labels=frozenset(["Person"]), properties={"age": 30})
        storage.add_node(node)

        retrieved = storage.get_node("n1")
        assert retrieved.id == "n1"
        assert retrieved.properties["age"] == 30

    def test_get_nonexistent_node_fails(self, storage: GraphStorage) -> None:
        """Test that getting nonexistent node raises error."""
        with pytest.raises(NodeNotFoundError):
            storage.get_node("nonexistent")

    def test_update_node(self, storage: GraphStorage) -> None:
        """Test updating a node."""
        node = Node(id="n1", labels=frozenset(["Person"]), properties={"name": "Alice"})
        storage.add_node(node)

        updated = Node(
            id="n1", labels=frozenset(["Person", "Developer"]), properties={"name": "Alice", "role": "Engineer"}
        )
        storage.update_node(updated)

        retrieved = storage.get_node("n1")
        assert "Developer" in retrieved.labels
        assert retrieved.properties["role"] == "Engineer"

    def test_delete_node(self, storage: GraphStorage) -> None:
        """Test deleting a node."""
        node = Node(id="n1", labels=frozenset(["Person"]))
        storage.add_node(node)
        storage.delete_node("n1")

        assert "n1" not in storage.node_store

    def test_delete_node_deletes_edges(self, storage: GraphStorage) -> None:
        """Test that deleting a node also deletes its edges."""
        n1 = Node(id="n1", labels=frozenset(["Person"]))
        n2 = Node(id="n2", labels=frozenset(["Person"]))
        storage.add_node(n1)
        storage.add_node(n2)

        edge = Edge(id="e1", source="n1", target="n2", type="KNOWS")
        storage.add_edge(edge)

        storage.delete_node("n1")

        assert "e1" not in storage.edge_store


class TestEdgeCRUD:
    """Test edge create, read, update, delete operations."""

    def test_add_edge(self, storage: GraphStorage) -> None:
        """Test adding an edge."""
        n1 = Node(id="n1", labels=frozenset(["Person"]))
        n2 = Node(id="n2", labels=frozenset(["Person"]))
        storage.add_node(n1)
        storage.add_node(n2)

        edge = Edge(id="e1", source="n1", target="n2", type="KNOWS")
        storage.add_edge(edge)

        assert "e1" in storage.edge_store
        assert storage.edge_store["e1"].type == "KNOWS"

    def test_add_edge_to_nonexistent_node_fails(self, storage: GraphStorage) -> None:
        """Test that adding edge to nonexistent node fails."""
        n1 = Node(id="n1", labels=frozenset(["Person"]))
        storage.add_node(n1)

        edge = Edge(id="e1", source="n1", target="nonexistent", type="KNOWS")
        with pytest.raises(NodeNotFoundError):
            storage.add_edge(edge)

    def test_get_edge(self, storage: GraphStorage) -> None:
        """Test getting an edge."""
        n1 = Node(id="n1", labels=frozenset(["Person"]))
        n2 = Node(id="n2", labels=frozenset(["Person"]))
        storage.add_node(n1)
        storage.add_node(n2)

        edge = Edge(id="e1", source="n1", target="n2", type="KNOWS", properties={"since": 2020})
        storage.add_edge(edge)

        retrieved = storage.get_edge("e1")
        assert retrieved.properties["since"] == 2020

    def test_delete_edge(self, storage: GraphStorage) -> None:
        """Test deleting an edge."""
        n1 = Node(id="n1", labels=frozenset(["Person"]))
        n2 = Node(id="n2", labels=frozenset(["Person"]))
        storage.add_node(n1)
        storage.add_node(n2)

        edge = Edge(id="e1", source="n1", target="n2", type="KNOWS")
        storage.add_edge(edge)
        storage.delete_edge("e1")

        assert "e1" not in storage.edge_store


class TestIndices:
    """Test label and property indices."""

    def test_label_index(self, storage: GraphStorage) -> None:
        """Test label indexing."""
        n1 = Node(id="n1", labels=frozenset(["Person"]))
        n2 = Node(id="n2", labels=frozenset(["Person"]))
        n3 = Node(id="n3", labels=frozenset(["Company"]))

        storage.add_node(n1)
        storage.add_node(n2)
        storage.add_node(n3)

        persons = storage.find_nodes_by_label("Person")
        assert len(persons) == 2
        assert "n1" in persons and "n2" in persons

    def test_property_index(self, storage: GraphStorage) -> None:
        """Test property indexing."""
        n1 = Node(id="n1", labels=frozenset(["Person"]), properties={"city": "NYC"})
        n2 = Node(id="n2", labels=frozenset(["Person"]), properties={"city": "LA"})
        n3 = Node(id="n3", labels=frozenset(["Person"]), properties={"city": "NYC"})

        storage.add_node(n1)
        storage.add_node(n2)
        storage.add_node(n3)

        nyc_nodes = storage.find_nodes_by_property("city", "NYC")
        assert len(nyc_nodes) == 2
        assert "n1" in nyc_nodes and "n3" in nyc_nodes

    def test_edge_type_index(self, storage: GraphStorage) -> None:
        """Test edge type indexing."""
        n1 = Node(id="n1", labels=frozenset(["Person"]))
        n2 = Node(id="n2", labels=frozenset(["Person"]))
        storage.add_node(n1)
        storage.add_node(n2)

        e1 = Edge(id="e1", source="n1", target="n2", type="KNOWS")
        e2 = Edge(id="e2", source="n1", target="n2", type="WORKS_WITH")

        storage.add_edge(e1)
        storage.add_edge(e2)

        knows_edges = storage.find_edges_by_type("KNOWS")
        assert len(knows_edges) == 1
        assert "e1" in knows_edges


class TestAdjacency:
    """Test adjacency list operations."""

    def test_outbound_edges(self, storage: GraphStorage) -> None:
        """Test getting outbound edges."""
        n1 = Node(id="n1", labels=frozenset(["Person"]))
        n2 = Node(id="n2", labels=frozenset(["Person"]))
        n3 = Node(id="n3", labels=frozenset(["Person"]))

        storage.add_node(n1)
        storage.add_node(n2)
        storage.add_node(n3)

        e1 = Edge(id="e1", source="n1", target="n2", type="KNOWS")
        e2 = Edge(id="e2", source="n1", target="n3", type="WORKS_WITH")
        storage.add_edge(e1)
        storage.add_edge(e2)

        outbound = storage.get_outbound_edges("n1")
        assert len(outbound) == 2

    def test_inbound_edges(self, storage: GraphStorage) -> None:
        """Test getting inbound edges."""
        n1 = Node(id="n1", labels=frozenset(["Person"]))
        n2 = Node(id="n2", labels=frozenset(["Person"]))

        storage.add_node(n1)
        storage.add_node(n2)

        e1 = Edge(id="e1", source="n1", target="n2", type="KNOWS")
        storage.add_edge(e1)

        inbound = storage.get_inbound_edges("n2")
        assert len(inbound) == 1
        assert inbound[0].source == "n1"

    def test_adjacent_nodes(self, storage: GraphStorage) -> None:
        """Test getting adjacent nodes."""
        n1 = Node(id="n1", labels=frozenset(["Person"]))
        n2 = Node(id="n2", labels=frozenset(["Person"]))
        n3 = Node(id="n3", labels=frozenset(["Person"]))

        storage.add_node(n1)
        storage.add_node(n2)
        storage.add_node(n3)

        e1 = Edge(id="e1", source="n1", target="n2", type="KNOWS")
        e2 = Edge(id="e2", source="n3", target="n1", type="KNOWS")
        storage.add_edge(e1)
        storage.add_edge(e2)

        adjacent = storage.get_adjacent_nodes("n1", direction="both")
        assert len(adjacent) == 2
        assert "n2" in adjacent and "n3" in adjacent


class TestTransactions:
    """Test transaction support."""

    def test_begin_transaction(self, storage: GraphStorage) -> None:
        """Test beginning a transaction."""
        txn = storage.begin_transaction()
        assert txn.is_active

    def test_commit_transaction(self, storage: GraphStorage) -> None:
        """Test committing a transaction."""
        node = Node(id="n1", labels=frozenset(["Person"]))
        storage.add_node(node)

        txn = storage.begin_transaction()
        txn.begin()

        n2 = Node(id="n2", labels=frozenset(["Person"]))
        storage.add_node(n2)

        storage.commit_transaction()

        assert "n2" in storage.node_store

    def test_rollback_transaction(self, storage: GraphStorage) -> None:
        """Test rolling back a transaction."""
        node = Node(id="n1", labels=frozenset(["Person"]))
        storage.add_node(node)

        txn = storage.begin_transaction()
        txn.begin()

        n2 = Node(id="n2", labels=frozenset(["Person"]))
        storage.add_node(n2)

        storage.rollback_transaction()

        assert "n2" not in storage.node_store

    def test_nested_transaction_fails(self, storage: GraphStorage) -> None:
        """Test that nested transactions fail."""
        storage.begin_transaction()

        with pytest.raises(TransactionError):
            storage.begin_transaction()


class TestBatchOperations:
    """Test batch operations."""

    def test_batch_add_nodes(self, storage: GraphStorage) -> None:
        """Test batch adding nodes."""
        nodes = [
            Node(id="n1", labels=frozenset(["Person"])),
            Node(id="n2", labels=frozenset(["Person"])),
            Node(id="n3", labels=frozenset(["Person"])),
        ]
        storage.batch_add_nodes(nodes)

        assert len(storage.node_store) == 3

    def test_batch_add_edges(self, storage: GraphStorage) -> None:
        """Test batch adding edges."""
        for i in range(1, 4):
            n = Node(id=f"n{i}", labels=frozenset(["Person"]))
            storage.add_node(n)

        edges = [
            Edge(id="e1", source="n1", target="n2", type="KNOWS"),
            Edge(id="e2", source="n2", target="n3", type="KNOWS"),
        ]
        storage.batch_add_edges(edges)

        assert len(storage.edge_store) == 2

    def test_batch_delete_nodes(self, storage: GraphStorage) -> None:
        """Test batch deleting nodes."""
        for i in range(1, 4):
            n = Node(id=f"n{i}", labels=frozenset(["Person"]))
            storage.add_node(n)

        storage.batch_delete_nodes(["n1", "n3"])

        assert len(storage.node_store) == 1
        assert "n2" in storage.node_store


class TestStatistics:
    """Test graph statistics."""

    def test_get_stats(self, storage: GraphStorage) -> None:
        """Test getting graph statistics."""
        n1 = Node(id="n1", labels=frozenset(["Person"]))
        n2 = Node(id="n2", labels=frozenset(["Person"]))
        storage.add_node(n1)
        storage.add_node(n2)

        e1 = Edge(id="e1", source="n1", target="n2", type="KNOWS")
        storage.add_edge(e1)

        stats = storage.get_stats()

        assert stats["node_count"] == 2
        assert stats["edge_count"] == 1
        assert "Person" in stats["labels"]
        assert "KNOWS" in stats["edge_types"]

    def test_clear_storage(self, storage: GraphStorage) -> None:
        """Test clearing all data."""
        n1 = Node(id="n1", labels=frozenset(["Person"]))
        storage.add_node(n1)

        e1 = Edge(id="e1", source="n1", target="n1", type="SELF")
        storage.add_edge(e1)

        storage.clear()

        assert len(storage.node_store) == 0
        assert len(storage.edge_store) == 0
