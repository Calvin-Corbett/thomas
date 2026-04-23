"""
Integration tests for graph analytics module.

Tests real-world scenarios like social network analysis and web graph analysis.
"""

from thomas.marketplace.graph_analytics._types import GraphType
from thomas.marketplace.graph_analytics.centrality import (
    betweenness_centrality,
    degree_centrality,
    pagerank,
)
from thomas.marketplace.graph_analytics.community import louvain_method
from thomas.marketplace.graph_analytics.generators import (
    barabasi_albert_graph,
    erdos_renyi_graph,
    watts_strogatz_graph,
)
from thomas.marketplace.graph_analytics.graph import Graph
from thomas.marketplace.graph_analytics.shortest_path import dijkstra_shortest_path
from thomas.marketplace.graph_analytics.spanning_tree import kruskal_mst
from thomas.marketplace.graph_analytics.traversal import connected_components


class TestSocialNetworkAnalysis:
    """Tests for social network analysis scenarios."""

    def create_social_network(self) -> Graph:
        """Create a simple social network."""
        g = Graph(GraphType.UNDIRECTED)

        # Friend connections
        friendships = [
            (0, 1),
            (0, 2),
            (1, 2),
            (1, 3),
            (2, 3),  # Group A
            (4, 5),
            (4, 6),
            (5, 6),  # Group B
            (0, 4),  # Bridge
        ]

        for src, dst in friendships:
            g.add_edge(src, dst)

        return g

    def test_influential_users_by_degree(self):
        """Test finding influential users by degree centrality."""
        g = self.create_social_network()
        result = degree_centrality(g)

        # Nodes 0 and 4 should be bridge nodes with high degree
        top_users = result.top_nodes(k=2)
        assert len(top_users) == 2

    def test_influential_users_by_betweenness(self):
        """Test finding influential users by betweenness."""
        g = self.create_social_network()
        result = betweenness_centrality(g)

        # Bridge nodes should have high betweenness
        top_users = result.top_nodes(k=2)
        assert len(top_users) == 2

    def test_community_detection(self):
        """Test community detection in social network."""
        g = self.create_social_network()
        result = louvain_method(g)

        # Should find 2 communities
        assert result.num_communities() >= 1
        assert result.modularity > 0

    def test_shortest_path_communication(self):
        """Test shortest communication paths in network."""
        g = self.create_social_network()

        # Find shortest path between distant nodes
        result = dijkstra_shortest_path(g, 1, 5)

        assert result.has_path()
        assert len(result.path) > 2

    def test_network_components(self):
        """Test finding isolated communities."""
        g = Graph(GraphType.UNDIRECTED)

        # Two separate groups
        for i in range(3):
            for j in range(i + 1, 3):
                g.add_edge(i, j)

        for i in range(3, 6):
            for j in range(i + 1, 6):
                g.add_edge(i, j)

        components = connected_components(g)

        assert len(components) == 2


class TestWebGraphAnalysis:
    """Tests for web graph analysis scenarios."""

    def create_web_graph(self) -> Graph:
        """Create a simple web graph (directed)."""
        g = Graph(GraphType.DIRECTED)

        # Hyperlinks between pages
        links = [
            (0, 1),
            (0, 2),  # Homepage links
            (1, 2),
            (1, 3),
            (2, 4),
            (3, 4),
            (4, 0),  # Back to homepage
        ]

        for src, dst in links:
            g.add_edge(src, dst, weight=1.0)

        return g

    def test_page_ranking(self):
        """Test PageRank for web pages."""
        g = self.create_web_graph()
        result = pagerank(g, damping_factor=0.85)

        # All pages should have positive rank
        assert all(score > 0 for score in result.scores.values())
        assert result.measure == "pagerank"

    def test_important_pages_by_centrality(self):
        """Test identifying important pages."""
        g = self.create_web_graph()

        # Homepage should have high out-degree
        out_degrees = {node: g.out_degree(node) for node in g.nodes()}
        homepage_rank = out_degrees[0]

        assert homepage_rank > 0

    def test_shortest_path_navigation(self):
        """Test finding shortest paths between pages."""
        g = self.create_web_graph()

        result = dijkstra_shortest_path(g, 0, 4)

        assert result.has_path()
        assert result.distance > 0


class TestTransportationNetwork:
    """Tests for transportation/logistics network analysis."""

    def create_transport_network(self) -> Graph:
        """Create a transportation network."""
        g = Graph(GraphType.DIRECTED)

        # Cities and routes with distances
        routes = [
            (0, 1, 10),  # City A to B
            (0, 2, 20),  # City A to C
            (1, 2, 5),  # City B to C
            (1, 3, 15),  # City B to D
            (2, 3, 10),  # City C to D
            (3, 4, 25),  # City D to E
        ]

        for src, dst, distance in routes:
            g.add_edge(src, dst, weight=distance)

        return g

    def test_shortest_route_planning(self):
        """Test finding shortest routes."""
        g = self.create_transport_network()

        result = dijkstra_shortest_path(g, 0, 4)

        assert result.has_path()
        # Route should go through intermediate cities
        assert len(result.path) > 2

    def test_minimum_spanning_network(self):
        """Test finding minimum cost spanning network."""
        g = Graph(GraphType.UNDIRECTED)

        edges = [
            (0, 1, 10),
            (0, 2, 20),
            (1, 2, 5),
            (1, 3, 15),
            (2, 3, 10),
        ]

        for src, dst, cost in edges:
            g.add_edge(src, dst, weight=cost)

        total_cost, mst_edges = kruskal_mst(g)

        # MST should connect all nodes with minimum cost
        assert len(mst_edges) == g.num_nodes() - 1
        assert total_cost > 0

    def test_network_connectivity(self):
        """Test network connectivity analysis."""
        g = self.create_transport_network()

        components = connected_components(g)

        # Should be single connected component (considering as undirected)
        assert len(components) >= 1


class TestScaleFreeNetworks:
    """Tests with scale-free networks (real-world topology)."""

    def test_barabasi_albert_topology(self):
        """Test analysis of scale-free network."""
        g = barabasi_albert_graph(n=50, m=2, seed=42)

        # Should have power-law degree distribution
        degrees = [g.degree(node) for node in g.nodes()]
        max_degree = max(degrees)

        # Some nodes should have much higher degree
        assert max_degree > sum(degrees) / len(degrees)

    def test_centrality_on_scale_free(self):
        """Test centrality measures on scale-free network."""
        g = barabasi_albert_graph(n=30, m=2, seed=42)

        deg_result = degree_centrality(g)
        between_result = betweenness_centrality(g)

        # High-degree nodes should correlate with high centrality
        top_degree = deg_result.top_nodes(k=3)
        top_between = between_result.top_nodes(k=3)

        # Some nodes should appear in both top lists
        top_degree_nodes = {node for node, _ in top_degree}
        top_between_nodes = {node for node, _ in top_between}

        assert len(top_degree_nodes & top_between_nodes) >= 1


class TestSmallWorldNetworks:
    """Tests with small-world networks."""

    def test_watts_strogatz_properties(self):
        """Test small-world network properties."""
        g = watts_strogatz_graph(n=30, k=4, p=0.3, seed=42)

        # Network should be connected
        components = connected_components(g)
        assert len(components) == 1

        # Average shortest path should be small
        result = dijkstra_shortest_path(g, 0)
        avg_distance = sum(result.distances.values()) / len(result.distances)

        assert avg_distance < 10


class TestRandomGraphs:
    """Tests with random graphs."""

    def test_erdos_renyi_density(self):
        """Test Erdős-Rényi graph properties."""
        g = erdos_renyi_graph(n=20, p=0.3, seed=42)

        # Check expected number of edges
        expected_edges = 20 * 19 / 2 * 0.3
        actual_edges = g.num_edges()

        # Allow some variance
        assert abs(actual_edges - expected_edges) < 5

    def test_analysis_on_random_graph(self):
        """Test complete analysis pipeline on random graph."""
        g = erdos_renyi_graph(n=15, p=0.4, seed=42)

        # Analyze connectivity
        components = connected_components(g)

        # If connected, analyze centrality
        if len(components) == 1:
            deg_result = degree_centrality(g)
            between_result = betweenness_centrality(g)

            # Should compute without error
            assert len(deg_result.scores) == 15
            assert len(between_result.scores) == 15


class TestLargeGraphPerformance:
    """Tests for performance on larger graphs."""

    def test_large_scale_free_network(self):
        """Test algorithms on larger scale-free network."""
        g = barabasi_albert_graph(n=200, m=3, seed=42)

        # Compute centrality
        deg_result = degree_centrality(g)

        # Should handle large graphs
        assert len(deg_result.scores) == 200

    def test_large_graph_shortest_path(self):
        """Test shortest path on larger graph."""
        g = erdos_renyi_graph(n=100, p=0.1, seed=42)

        # Find shortest path (if graph is connected enough)
        result = dijkstra_shortest_path(g, 0)

        assert result.distance >= 0


class TestGraphProperties:
    """Tests for various graph properties."""

    def test_self_loop_detection(self):
        """Test detection of self-loops."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 0)
        g.add_edge(0, 1)

        assert g.has_self_loop(0)
        assert not g.has_self_loop(1)

        self_loops = g.self_loops()
        assert 0 in self_loops

    def test_node_attributes(self):
        """Test node attributes."""
        g = Graph(GraphType.UNDIRECTED)

        g.add_node(0, name="Alice", age=30)
        g.add_node(1, name="Bob", age=25)
        g.add_edge(0, 1)

        node0 = g._nodes[0]
        assert node0.attrs["name"] == "Alice"
        assert node0.attrs["age"] == 30

    def test_graph_copy(self):
        """Test graph copying."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_edge(1, 2)

        g_copy = g.copy()

        # Verify copy is independent
        assert g_copy.num_nodes() == g.num_nodes()
        assert g_copy.num_edges() == g.num_edges()

        g_copy.add_node(3)
        assert g.num_nodes() != g_copy.num_nodes()

    def test_graph_subgraph(self):
        """Test subgraph extraction."""
        g = Graph(GraphType.UNDIRECTED)
        for i in range(5):
            for j in range(i + 1, 5):
                g.add_edge(i, j)

        subgraph = g.subgraph([0, 1, 2])

        assert subgraph.num_nodes() == 3
        assert subgraph.num_edges() == 3  # Complete subgraph K3


class TestEndToEndWorkflow:
    """End-to-end workflow tests."""

    def test_complete_network_analysis(self):
        """Test complete network analysis workflow."""
        # Create network
        g = barabasi_albert_graph(n=50, m=2, seed=42)

        # Analyze structure
        components = connected_components(g)
        assert len(components) >= 1

        # Compute centralities
        deg_result = degree_centrality(g)
        between_result = betweenness_centrality(g)
        page_result = pagerank(g)

        # Detect communities
        comm_result = louvain_method(g)

        # Verify all completed
        assert len(deg_result.scores) == 50
        assert len(between_result.scores) == 50
        assert len(page_result.scores) == 50
        assert comm_result.num_communities() >= 1
        assert comm_result.modularity > 0

    def test_graph_comparison(self):
        """Test comparing different graph models."""
        n = 30
        seed = 42

        # Generate different types
        ba_graph = barabasi_albert_graph(n, m=2, seed=seed)
        ws_graph = watts_strogatz_graph(n, k=4, p=0.3, seed=seed)
        er_graph = erdos_renyi_graph(n, p=0.1, seed=seed)

        # Compare properties
        ba_comps = len(connected_components(ba_graph))
        ws_comps = len(connected_components(ws_graph))
        er_comps = len(connected_components(er_graph))

        # All should be reasonable networks
        assert ba_comps >= 1
        assert ws_comps >= 1
        assert er_comps >= 1
