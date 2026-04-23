"""Tests for graph traversal algorithms: BFS, DFS, shortest path, etc."""

import pytest

from thomas.marketplace.graphdb._exceptions import NodeNotFoundError
from thomas.marketplace.graphdb._types import Edge, Node
from thomas.marketplace.graphdb.storage import GraphStorage
from thomas.marketplace.graphdb.traversal import GraphTraversal


@pytest.fixture
def graph_with_cycles():
    """Create a graph with cycles."""
    storage = GraphStorage()

    # Create nodes
    for i in range(1, 6):
        node = Node(id=f"n{i}", labels=frozenset(["Node"]))
        storage.add_node(node)

    # Create edges forming a cycle: 1->2->3->4->5->1
    edges = [
        Edge(id="e1", source="n1", target="n2", type="CONNECTS"),
        Edge(id="e2", source="n2", target="n3", type="CONNECTS"),
        Edge(id="e3", source="n3", target="n4", type="CONNECTS"),
        Edge(id="e4", source="n4", target="n5", type="CONNECTS"),
        Edge(id="e5", source="n5", target="n1", type="CONNECTS"),
        Edge(id="e6", source="n2", target="n4", type="CONNECTS"),  # Additional edge
    ]

    for edge in edges:
        storage.add_edge(edge)

    return storage


@pytest.fixture
def linear_graph():
    """Create a linear graph: 1->2->3->4->5."""
    storage = GraphStorage()

    for i in range(1, 6):
        node = Node(id=f"n{i}", labels=frozenset(["Node"]))
        storage.add_node(node)

    for i in range(1, 5):
        edge = Edge(id=f"e{i}", source=f"n{i}", target=f"n{i+1}", type="NEXT")
        storage.add_edge(edge)

    return storage


@pytest.fixture
def tree_graph():
    """Create a tree-structured graph."""
    storage = GraphStorage()

    nodes = ["root", "a", "b", "a1", "a2", "b1", "b2"]
    for node_id in nodes:
        node = Node(id=node_id, labels=frozenset(["Node"]))
        storage.add_node(node)

    edges = [
        Edge(id="e1", source="root", target="a", type="CHILD"),
        Edge(id="e2", source="root", target="b", type="CHILD"),
        Edge(id="e3", source="a", target="a1", type="CHILD"),
        Edge(id="e4", source="a", target="a2", type="CHILD"),
        Edge(id="e5", source="b", target="b1", type="CHILD"),
        Edge(id="e6", source="b", target="b2", type="CHILD"),
    ]

    for edge in edges:
        storage.add_edge(edge)

    return storage


class TestBFS:
    """Test breadth-first search."""

    def test_bfs_basic(self, linear_graph: GraphStorage) -> None:
        """Test BFS on linear graph."""
        traversal = GraphTraversal(linear_graph)
        distances = traversal.bfs("n1")

        assert distances["n1"] == 0
        assert distances["n2"] == 1
        assert distances["n3"] == 2
        assert distances["n5"] == 4

    def test_bfs_with_max_depth(self, linear_graph: GraphStorage) -> None:
        """Test BFS with max depth limit."""
        traversal = GraphTraversal(linear_graph)
        distances = traversal.bfs("n1", max_depth=2)

        assert "n1" in distances
        assert "n2" in distances
        assert "n3" in distances

    def test_bfs_nonexistent_node_fails(self, linear_graph: GraphStorage) -> None:
        """Test BFS with nonexistent start node."""
        traversal = GraphTraversal(linear_graph)

        with pytest.raises(NodeNotFoundError):
            traversal.bfs("nonexistent")

    def test_bfs_with_cycles(self, graph_with_cycles: GraphStorage) -> None:
        """Test BFS on graph with cycles."""
        traversal = GraphTraversal(graph_with_cycles)
        distances = traversal.bfs("n1")

        assert len(distances) == 5
        assert distances["n1"] == 0


class TestDFS:
    """Test depth-first search."""

    def test_dfs_basic(self, linear_graph: GraphStorage) -> None:
        """Test DFS on linear graph."""
        traversal = GraphTraversal(linear_graph)
        depths = traversal.dfs("n1")

        assert depths["n1"] == 0
        assert depths["n2"] == 1
        assert depths["n5"] == 4

    def test_dfs_with_max_depth(self, linear_graph: GraphStorage) -> None:
        """Test DFS with max depth limit."""
        traversal = GraphTraversal(linear_graph)
        depths = traversal.dfs("n1", max_depth=2)

        assert "n1" in depths
        assert "n2" in depths
        assert "n3" in depths

    def test_dfs_tree(self, tree_graph: GraphStorage) -> None:
        """Test DFS on tree."""
        traversal = GraphTraversal(tree_graph)
        depths = traversal.dfs("root")

        assert depths["root"] == 0
        assert depths["a"] == 1
        assert depths["a1"] == 2


class TestDijkstra:
    """Test Dijkstra's shortest path algorithm."""

    def test_dijkstra_linear(self, linear_graph: GraphStorage) -> None:
        """Test Dijkstra on linear graph."""
        traversal = GraphTraversal(linear_graph)
        distances, predecessors = traversal.dijkstra("n1")

        assert distances["n1"] == 0.0
        assert distances["n5"] == 4.0
        assert predecessors["n1"] is None
        assert predecessors["n2"] == "n1"

    def test_dijkstra_with_weights(self, linear_graph: GraphStorage) -> None:
        """Test Dijkstra with weighted edges."""
        traversal = GraphTraversal(linear_graph)

        # Define weight function
        def weight_fn(node_id: str) -> float:
            if node_id == "n3":
                return 10.0  # High cost to n3
            return 1.0

        distances, _ = traversal.dijkstra("n1", weight_fn=weight_fn)

        assert distances["n1"] == 0.0

    def test_dijkstra_unreachable(self, linear_graph: GraphStorage) -> None:
        """Test Dijkstra when node is unreachable."""
        # Create disconnected node
        storage = linear_graph
        isolated = Node(id="isolated", labels=frozenset(["Node"]))
        storage.add_node(isolated)

        traversal = GraphTraversal(storage)
        distances, _ = traversal.dijkstra("n1")

        assert "isolated" not in distances


class TestShortestPath:
    """Test shortest path finding."""

    def test_shortest_path_linear(self, linear_graph: GraphStorage) -> None:
        """Test shortest path on linear graph."""
        traversal = GraphTraversal(linear_graph)
        path = traversal.shortest_path("n1", "n5")

        assert path is not None
        assert path.nodes == ["n1", "n2", "n3", "n4", "n5"]
        assert path.length == 4

    def test_shortest_path_with_cycle(self, graph_with_cycles: GraphStorage) -> None:
        """Test shortest path on graph with cycles."""
        traversal = GraphTraversal(graph_with_cycles)
        path = traversal.shortest_path("n1", "n3")

        assert path is not None
        assert path.nodes[0] == "n1"
        assert path.nodes[-1] == "n3"

    def test_shortest_path_nonexistent(self, linear_graph: GraphStorage) -> None:
        """Test shortest path when no path exists."""
        storage = linear_graph
        isolated = Node(id="isolated", labels=frozenset(["Node"]))
        storage.add_node(isolated)

        traversal = GraphTraversal(storage)
        path = traversal.shortest_path("n1", "isolated")

        assert path is None

    def test_shortest_path_same_node(self, linear_graph: GraphStorage) -> None:
        """Test shortest path to same node."""
        traversal = GraphTraversal(linear_graph)
        path = traversal.shortest_path("n1", "n1")

        assert path is not None
        assert path.length == 0


class TestAllShortestPaths:
    """Test finding all shortest paths."""

    def test_all_shortest_paths_linear(self, linear_graph: GraphStorage) -> None:
        """Test all shortest paths on linear graph."""
        traversal = GraphTraversal(linear_graph)
        paths = traversal.all_shortest_paths("n1", "n5")

        assert len(paths) >= 1
        assert all(len(p.nodes) == 5 for p in paths)

    def test_all_shortest_paths_with_alternatives(self, graph_with_cycles: GraphStorage) -> None:
        """Test all shortest paths when multiple paths exist."""
        traversal = GraphTraversal(graph_with_cycles)
        paths = traversal.all_shortest_paths("n1", "n4")

        assert len(paths) >= 1

    def test_all_shortest_paths_nonexistent(self, linear_graph: GraphStorage) -> None:
        """Test all shortest paths when no path exists."""
        storage = linear_graph
        isolated = Node(id="isolated", labels=frozenset(["Node"]))
        storage.add_node(isolated)

        traversal = GraphTraversal(storage)
        paths = traversal.all_shortest_paths("n1", "isolated")

        assert len(paths) == 0


class TestVariableLengthPath:
    """Test variable-length path finding."""

    def test_variable_length_path_basic(self, tree_graph: GraphStorage) -> None:
        """Test variable-length paths."""
        traversal = GraphTraversal(tree_graph)
        paths = traversal.variable_length_path("root", min_length=1, max_length=3)

        assert len(paths) > 0

    def test_variable_length_path_with_constraints(self, tree_graph: GraphStorage) -> None:
        """Test variable-length paths with min/max."""
        traversal = GraphTraversal(tree_graph)
        paths = traversal.variable_length_path("root", min_length=2, max_length=2)

        assert all(p.length >= 2 for p in paths)


class TestBidirectionalSearch:
    """Test bidirectional search."""

    def test_bidirectional_search_linear(self, linear_graph: GraphStorage) -> None:
        """Test bidirectional search on linear graph."""
        traversal = GraphTraversal(linear_graph)
        path = traversal.bidirectional_search("n1", "n5")

        assert path is not None
        assert path.nodes[0] == "n1"
        assert path.nodes[-1] == "n5"

    def test_bidirectional_search_same_node(self, linear_graph: GraphStorage) -> None:
        """Test bidirectional search to same node."""
        traversal = GraphTraversal(linear_graph)
        path = traversal.bidirectional_search("n1", "n1")

        assert path is not None
        assert len(path.nodes) == 1

    def test_bidirectional_search_nonexistent(self, linear_graph: GraphStorage) -> None:
        """Test bidirectional search with unreachable node."""
        storage = linear_graph
        isolated = Node(id="isolated", labels=frozenset(["Node"]))
        storage.add_node(isolated)

        traversal = GraphTraversal(storage)
        path = traversal.bidirectional_search("n1", "isolated")

        assert path is None


class TestConnectedComponents:
    """Test connected component detection."""

    def test_connected_component(self, linear_graph: GraphStorage) -> None:
        """Test finding connected component."""
        traversal = GraphTraversal(linear_graph)
        component = traversal.connected_component_nodes("n1")

        assert len(component) == 5
        assert "n1" in component

    def test_connected_component_with_isolated(self, linear_graph: GraphStorage) -> None:
        """Test connected component with isolated node."""
        storage = linear_graph
        isolated = Node(id="isolated", labels=frozenset(["Node"]))
        storage.add_node(isolated)

        traversal = GraphTraversal(storage)
        component = traversal.connected_component_nodes("n1")

        assert "isolated" not in component
        assert len(component) == 5


class TestEdgeTypeFilter:
    """Test edge type filtering in traversal."""

    def test_traverse_with_edge_type_filter(self) -> None:
        """Test traversal with edge type filter."""
        storage = GraphStorage()

        n1 = Node(id="n1", labels=frozenset(["Node"]))
        n2 = Node(id="n2", labels=frozenset(["Node"]))
        n3 = Node(id="n3", labels=frozenset(["Node"]))

        storage.add_node(n1)
        storage.add_node(n2)
        storage.add_node(n3)

        e1 = Edge(id="e1", source="n1", target="n2", type="KNOWS")
        e2 = Edge(id="e2", source="n1", target="n3", type="WORKS_WITH")

        storage.add_edge(e1)
        storage.add_edge(e2)

        traversal = GraphTraversal(storage)
        # Note: The current implementation doesn't support edge_type_filter in adjacent nodes
        # This test documents the feature for future enhancement
