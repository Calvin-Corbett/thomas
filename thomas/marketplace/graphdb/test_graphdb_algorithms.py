"""Tests for graph algorithms: PageRank, centrality, clustering, etc."""

import pytest

from thomas.marketplace.graphdb._types import Edge, Node
from thomas.marketplace.graphdb.algorithms import GraphAlgorithms
from thomas.marketplace.graphdb.storage import GraphStorage


@pytest.fixture
def simple_graph():
    """Create a simple undirected graph."""
    storage = GraphStorage()

    nodes = ["a", "b", "c", "d", "e"]
    for node_id in nodes:
        node = Node(id=node_id, labels=frozenset(["Node"]))
        storage.add_node(node)

    edges = [
        ("a", "b"),
        ("b", "c"),
        ("c", "d"),
        ("d", "e"),
        ("a", "c"),
        ("b", "d"),
    ]

    for i, (src, tgt) in enumerate(edges):
        edge = Edge(id=f"e{i}", source=src, target=tgt, type="CONNECTS")
        storage.add_edge(edge)
        # Add reverse for undirected
        edge_rev = Edge(id=f"e{i}_r", source=tgt, target=src, type="CONNECTS")
        storage.add_edge(edge_rev)

    return storage


@pytest.fixture
def disconnected_graph():
    """Create a graph with multiple components."""
    storage = GraphStorage()

    # Component 1
    for i in range(1, 4):
        node = Node(id=f"a{i}", labels=frozenset(["Node"]))
        storage.add_node(node)

    # Component 2
    for i in range(1, 4):
        node = Node(id=f"b{i}", labels=frozenset(["Node"]))
        storage.add_node(node)

    # Edges in component 1
    storage.add_edge(Edge(id="e1", source="a1", target="a2", type="CONNECTS"))
    storage.add_edge(Edge(id="e2", source="a2", target="a3", type="CONNECTS"))

    # Edges in component 2
    storage.add_edge(Edge(id="e3", source="b1", target="b2", type="CONNECTS"))
    storage.add_edge(Edge(id="e4", source="b2", target="b3", type="CONNECTS"))

    return storage


@pytest.fixture
def directed_graph():
    """Create a directed acyclic graph."""
    storage = GraphStorage()

    nodes = ["1", "2", "3", "4", "5"]
    for node_id in nodes:
        node = Node(id=node_id, labels=frozenset(["Node"]))
        storage.add_node(node)

    edges = [
        ("1", "2"),
        ("1", "3"),
        ("2", "4"),
        ("3", "4"),
        ("4", "5"),
    ]

    for i, (src, tgt) in enumerate(edges):
        edge = Edge(id=f"e{i}", source=src, target=tgt, type="POINTS_TO")
        storage.add_edge(edge)

    return storage


class TestPageRank:
    """Test PageRank algorithm."""

    def test_pagerank_basic(self, simple_graph: GraphStorage) -> None:
        """Test PageRank on simple graph."""
        algo = GraphAlgorithms(simple_graph)
        ranks = algo.pagerank(iterations=10)

        assert len(ranks) == 5
        assert all(0 <= r <= 1 for r in ranks.values())

    def test_pagerank_sums_to_one(self, simple_graph: GraphStorage) -> None:
        """Test that PageRank sums to approximately 1."""
        algo = GraphAlgorithms(simple_graph)
        ranks = algo.pagerank(iterations=20)

        total = sum(ranks.values())
        assert abs(total - 1.0) < 0.01

    def test_pagerank_empty_graph(self) -> None:
        """Test PageRank on empty graph."""
        storage = GraphStorage()
        algo = GraphAlgorithms(storage)
        ranks = algo.pagerank()

        assert len(ranks) == 0


class TestConnectedComponents:
    """Test connected components detection."""

    def test_single_component(self, simple_graph: GraphStorage) -> None:
        """Test graph with single component."""
        algo = GraphAlgorithms(simple_graph)
        components = algo.connected_components()

        assert len(components) == 1
        assert len(components[0]) == 5

    def test_multiple_components(self, disconnected_graph: GraphStorage) -> None:
        """Test graph with multiple components."""
        algo = GraphAlgorithms(disconnected_graph)
        components = algo.connected_components()

        assert len(components) == 2
        assert all(len(c) == 3 for c in components)

    def test_single_node_component(self) -> None:
        """Test single-node components."""
        storage = GraphStorage()

        for i in range(3):
            node = Node(id=f"n{i}", labels=frozenset(["Node"]))
            storage.add_node(node)

        algo = GraphAlgorithms(storage)
        components = algo.connected_components()

        assert len(components) == 3


class TestStronglyConnectedComponents:
    """Test strongly connected components detection."""

    def test_scc_single(self) -> None:
        """Test SCC on strongly connected graph."""
        storage = GraphStorage()

        # Create a cycle: 1->2->3->1
        for i in range(1, 4):
            node = Node(id=f"n{i}", labels=frozenset(["Node"]))
            storage.add_node(node)

        edges = [("n1", "n2"), ("n2", "n3"), ("n3", "n1")]
        for i, (src, tgt) in enumerate(edges):
            edge = Edge(id=f"e{i}", source=src, target=tgt, type="POINTS_TO")
            storage.add_edge(edge)

        algo = GraphAlgorithms(storage)
        sccs = algo.strongly_connected_components()

        assert len(sccs) == 1
        assert len(sccs[0]) == 3

    def test_scc_dag(self, directed_graph: GraphStorage) -> None:
        """Test SCC on DAG (each node is own SCC)."""
        algo = GraphAlgorithms(directed_graph)
        sccs = algo.strongly_connected_components()

        assert len(sccs) == 5


class TestBetweennessCentrality:
    """Test betweenness centrality."""

    def test_betweenness_basic(self, simple_graph: GraphStorage) -> None:
        """Test betweenness centrality."""
        algo = GraphAlgorithms(simple_graph)
        centrality = algo.betweenness_centrality()

        assert len(centrality) == 5
        assert all(c >= 0 for c in centrality.values())

    def test_betweenness_star_graph(self) -> None:
        """Test betweenness on star graph (hub has highest)."""
        storage = GraphStorage()

        # Create star with hub at center
        hub = Node(id="hub", labels=frozenset(["Node"]))
        storage.add_node(hub)

        for i in range(4):
            node = Node(id=f"n{i}", labels=frozenset(["Node"]))
            storage.add_node(node)
            edge1 = Edge(id=f"e{i}", source="hub", target=f"n{i}", type="CONNECTS")
            edge2 = Edge(id=f"e{i}_r", source=f"n{i}", target="hub", type="CONNECTS")
            storage.add_edge(edge1)
            storage.add_edge(edge2)

        algo = GraphAlgorithms(storage)
        centrality = algo.betweenness_centrality()

        hub_centrality = centrality["hub"]
        assert all(hub_centrality >= centrality[f"n{i}"] for i in range(4))


class TestDegreeCentrality:
    """Test degree centrality."""

    def test_degree_centrality(self, simple_graph: GraphStorage) -> None:
        """Test degree centrality."""
        algo = GraphAlgorithms(simple_graph)
        centrality = algo.degree_centrality()

        assert len(centrality) == 5
        assert all(0 <= c <= 1 for c in centrality.values())

    def test_degree_centrality_isolated(self) -> None:
        """Test degree centrality on graph with isolated node."""
        storage = GraphStorage()

        n1 = Node(id="n1", labels=frozenset(["Node"]))
        n2 = Node(id="n2", labels=frozenset(["Node"]))
        isolated = Node(id="isolated", labels=frozenset(["Node"]))

        storage.add_node(n1)
        storage.add_node(n2)
        storage.add_node(isolated)

        edge = Edge(id="e1", source="n1", target="n2", type="CONNECTS")
        storage.add_edge(edge)

        algo = GraphAlgorithms(storage)
        centrality = algo.degree_centrality()

        assert centrality["isolated"] == 0.0


class TestLabelPropagation:
    """Test label propagation community detection."""

    def test_label_propagation(self, simple_graph: GraphStorage) -> None:
        """Test label propagation."""
        algo = GraphAlgorithms(simple_graph)
        labels = algo.label_propagation(iterations=5)

        assert len(labels) == 5
        assert all(isinstance(label, str) for label in labels.values())

    def test_label_propagation_convergence(self) -> None:
        """Test that label propagation converges."""
        storage = GraphStorage()

        # Create two clusters
        for i in range(3):
            node = Node(id=f"c1_n{i}", labels=frozenset(["Node"]))
            storage.add_node(node)

        for i in range(3):
            node = Node(id=f"c2_n{i}", labels=frozenset(["Node"]))
            storage.add_node(node)

        # Strong connections within clusters
        for i in range(2):
            e1 = Edge(id=f"c1_e{i}", source=f"c1_n{i}", target=f"c1_n{i+1}", type="CONNECTS")
            e2 = Edge(id=f"c2_e{i}", source=f"c2_n{i}", target=f"c2_n{i+1}", type="CONNECTS")
            storage.add_edge(e1)
            storage.add_edge(e2)

        algo = GraphAlgorithms(storage)
        labels = algo.label_propagation(iterations=10)

        assert len(labels) == 6


class TestClusteringCoefficient:
    """Test clustering coefficient."""

    def test_clustering_coefficient_all(self, simple_graph: GraphStorage) -> None:
        """Test clustering coefficient for all nodes."""
        algo = GraphAlgorithms(simple_graph)
        coefficients = algo.clustering_coefficient()

        assert len(coefficients) == 5
        assert all(0 <= c <= 1 for c in coefficients.values())

    def test_clustering_coefficient_single(self, simple_graph: GraphStorage) -> None:
        """Test clustering coefficient for single node."""
        algo = GraphAlgorithms(simple_graph)
        coeff = algo.clustering_coefficient("a")

        assert "a" in coeff
        assert 0 <= coeff["a"] <= 1

    def test_clustering_coefficient_isolated(self) -> None:
        """Test clustering coefficient of isolated node."""
        storage = GraphStorage()

        node = Node(id="isolated", labels=frozenset(["Node"]))
        storage.add_node(node)

        algo = GraphAlgorithms(storage)
        coefficients = algo.clustering_coefficient()

        assert coefficients["isolated"] == 0.0


class TestTriangleCount:
    """Test triangle counting."""

    def test_triangle_count_all(self) -> None:
        """Test counting all triangles."""
        storage = GraphStorage()

        # Create triangle: 1-2-3-1
        for i in range(1, 4):
            node = Node(id=f"n{i}", labels=frozenset(["Node"]))
            storage.add_node(node)

        edges = [("n1", "n2"), ("n2", "n3"), ("n3", "n1")]
        for i, (src, tgt) in enumerate(edges):
            e1 = Edge(id=f"e{i}", source=src, target=tgt, type="CONNECTS")
            e2 = Edge(id=f"e{i}_r", source=tgt, target=src, type="CONNECTS")
            storage.add_edge(e1)
            storage.add_edge(e2)

        algo = GraphAlgorithms(storage)
        triangles = algo.triangle_count()

        assert triangles == 1

    def test_triangle_count_single_node(self) -> None:
        """Test triangle count for single node."""
        storage = GraphStorage()

        # Create triangle: 1-2-3-1
        for i in range(1, 4):
            node = Node(id=f"n{i}", labels=frozenset(["Node"]))
            storage.add_node(node)

        edges = [("n1", "n2"), ("n2", "n3"), ("n3", "n1")]
        for i, (src, tgt) in enumerate(edges):
            e1 = Edge(id=f"e{i}", source=src, target=tgt, type="CONNECTS")
            e2 = Edge(id=f"e{i}_r", source=tgt, target=src, type="CONNECTS")
            storage.add_edge(e1)
            storage.add_edge(e2)

        algo = GraphAlgorithms(storage)
        count = algo.triangle_count("n1")

        assert count == 1


class TestDensity:
    """Test graph density."""

    def test_density(self, simple_graph: GraphStorage) -> None:
        """Test graph density calculation."""
        algo = GraphAlgorithms(simple_graph)
        density = algo.density()

        assert 0 <= density <= 1

    def test_density_empty(self) -> None:
        """Test density of empty graph."""
        storage = GraphStorage()
        algo = GraphAlgorithms(storage)
        density = algo.density()

        assert density == 0.0

    def test_density_complete(self) -> None:
        """Test density of complete graph."""
        storage = GraphStorage()

        # Create complete graph K3
        for i in range(3):
            node = Node(id=f"n{i}", labels=frozenset(["Node"]))
            storage.add_node(node)

        for i in range(3):
            for j in range(i + 1, 3):
                e1 = Edge(id=f"e{i}_{j}", source=f"n{i}", target=f"n{j}", type="CONNECTS")
                e2 = Edge(id=f"e{j}_{i}", source=f"n{j}", target=f"n{i}", type="CONNECTS")
                storage.add_edge(e1)
                storage.add_edge(e2)

        algo = GraphAlgorithms(storage)
        density = algo.density()

        assert abs(density - 1.0) < 0.01


class TestDiameter:
    """Test graph diameter."""

    def test_diameter_linear(self) -> None:
        """Test diameter of linear graph."""
        storage = GraphStorage()

        for i in range(5):
            node = Node(id=f"n{i}", labels=frozenset(["Node"]))
            storage.add_node(node)

        for i in range(4):
            e1 = Edge(id=f"e{i}", source=f"n{i}", target=f"n{i+1}", type="CONNECTS")
            e2 = Edge(id=f"e{i}_r", source=f"n{i+1}", target=f"n{i}", type="CONNECTS")
            storage.add_edge(e1)
            storage.add_edge(e2)

        algo = GraphAlgorithms(storage)
        diameter = algo.diameter()

        assert diameter == 4.0

    def test_diameter_disconnected(self, disconnected_graph: GraphStorage) -> None:
        """Test diameter of disconnected graph."""
        algo = GraphAlgorithms(disconnected_graph)
        diameter = algo.diameter()

        assert diameter is None
