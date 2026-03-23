"""
Tests for community detection algorithms.
"""

import pytest

from thomas.marketplace.graph_analytics._types import GraphType
from thomas.marketplace.graph_analytics.community import (
    girvan_newman,
    kclique_communities,
    label_propagation,
    louvain_method,
    modularity_score,
)
from thomas.marketplace.graph_analytics.graph import Graph


class TestModularity:
    """Tests for modularity score calculation."""

    def test_modularity_single_community(self):
        """Test modularity for single community (entire graph)."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(2, 3)

        communities = [set(g.nodes())]
        q = modularity_score(g, communities)

        # Should be positive but not perfect
        assert 0 < q < 1

    def test_modularity_disconnected_communities(self):
        """Test modularity with well-separated communities."""
        g = Graph(GraphType.UNDIRECTED)
        # Community 1
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(0, 2)

        # Community 2
        g.add_edge(3, 4)
        g.add_edge(4, 5)
        g.add_edge(3, 5)

        communities = [{0, 1, 2}, {3, 4, 5}]
        q = modularity_score(g, communities)

        # Should be high modularity
        assert q > 0.3


class TestLabelPropagation:
    """Tests for label propagation algorithm."""

    def test_label_propagation_simple(self):
        """Test label propagation on simple graph."""
        g = Graph(GraphType.UNDIRECTED)
        # Two communities
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(0, 2)
        g.add_edge(3, 4)
        g.add_edge(4, 5)
        g.add_edge(3, 5)

        result = label_propagation(g, seed=42)

        assert result.num_communities() >= 1
        assert result.modularity >= 0

    def test_label_propagation_converges(self):
        """Test label propagation terminates."""
        g = Graph(GraphType.UNDIRECTED)
        for i in range(5):
            g.add_edge(i, (i + 1) % 5)

        result = label_propagation(g, max_iterations=10)

        assert result.num_communities() >= 1

    def test_label_propagation_single_node(self):
        """Test label propagation on single node."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_node(0)

        result = label_propagation(g)

        assert result.num_communities() == 1
        assert 0 in result.communities[0]


class TestLouvain:
    """Tests for Louvain community detection."""

    def test_louvain_two_communities(self):
        """Test Louvain on graph with obvious communities."""
        g = Graph(GraphType.UNDIRECTED)

        # Community 1
        for i in range(4):
            for j in range(i + 1, 4):
                g.add_edge(i, j)

        # Community 2
        for i in range(4, 8):
            for j in range(i + 1, 8):
                g.add_edge(i, j)

        # Connect communities with single edge
        g.add_edge(0, 4)

        result = louvain_method(g, seed=42)

        # Should find at least 1 community
        assert result.num_communities() >= 1
        assert result.modularity > 0

    def test_louvain_complete_graph(self):
        """Test Louvain on complete graph."""
        g = Graph(GraphType.UNDIRECTED)
        for i in range(4):
            for j in range(i + 1, 4):
                g.add_edge(i, j)

        result = louvain_method(g)

        # Should identify as single or few communities
        assert result.num_communities() >= 1

    def test_louvain_single_node(self):
        """Test Louvain on single node."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_node(0)

        result = louvain_method(g)

        assert result.num_communities() == 1


class TestGirvanNewman:
    """Tests for Girvan-Newman algorithm."""

    def test_girvan_newman_simple(self):
        """Test Girvan-Newman on simple graph."""
        g = Graph(GraphType.UNDIRECTED)
        # Create two connected clusters
        for i in range(3):
            for j in range(i + 1, 3):
                g.add_edge(i, j)

        for i in range(3, 6):
            for j in range(i + 1, 6):
                g.add_edge(i, j)

        g.add_edge(0, 3)  # Single bridge

        result = girvan_newman(g, num_communities=2)

        assert result.num_communities() >= 1

    def test_girvan_newman_star_graph(self):
        """Test Girvan-Newman on star graph."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_edge(0, 2)
        g.add_edge(0, 3)

        result = girvan_newman(g, num_communities=2)

        assert result.num_communities() >= 1


class TestKClique:
    """Tests for k-clique communities."""

    def test_kclique_communities_simple(self):
        """Test k-clique communities."""
        g = Graph(GraphType.UNDIRECTED)

        # Create a clique
        for i in range(4):
            for j in range(i + 1, 4):
                g.add_edge(i, j)

        result = kclique_communities(g, k=3)

        assert result.num_communities() >= 1

    def test_kclique_k_larger_than_graph(self):
        """Test k-clique when k > num_nodes."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_edge(1, 2)

        result = kclique_communities(g, k=10)

        # Should return empty communities
        assert result.num_communities() == 0

    def test_kclique_on_directed_graph_error(self):
        """Test k-clique rejects directed graphs."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1)

        with pytest.raises(ValueError):
            kclique_communities(g, k=2)


class TestCommunityResult:
    """Tests for CommunityResult methods."""

    def test_community_result_num_communities(self):
        """Test num_communities() method."""
        from thomas.marketplace.graph_analytics._types import CommunityResult

        result = CommunityResult(communities=[{0, 1}, {2, 3}], modularity=0.5)

        assert result.num_communities() == 2

    def test_community_result_sizes(self):
        """Test community_sizes() method."""
        from thomas.marketplace.graph_analytics._types import CommunityResult

        result = CommunityResult(communities=[{0, 1, 2}, {3, 4}], modularity=0.5)

        sizes = result.community_sizes()
        assert sizes == [3, 2]


class TestIntegration:
    """Integration tests for community detection."""

    def test_all_algorithms_on_same_graph(self):
        """Test all algorithms on same graph."""
        g = Graph(GraphType.UNDIRECTED)

        # Karate club-like structure
        for i in range(5):
            for j in range(i + 1, 5):
                g.add_edge(i, j)

        for i in range(5, 10):
            for j in range(i + 1, 10):
                g.add_edge(i, j)

        g.add_edge(0, 5)

        lp_result = label_propagation(g, seed=42)
        louvain_result = louvain_method(g, seed=42)
        gn_result = girvan_newman(g)

        assert lp_result.num_communities() >= 1
        assert louvain_result.num_communities() >= 1
        assert gn_result.num_communities() >= 1

    def test_modularity_improvement(self):
        """Test that algorithms find reasonable modularity."""
        g = Graph(GraphType.UNDIRECTED)

        # Clear two-community structure
        for i in range(5):
            for j in range(i + 1, 5):
                g.add_edge(i, j)

        for i in range(5, 10):
            for j in range(i + 1, 10):
                g.add_edge(i, j)

        g.add_edge(2, 7)

        result = louvain_method(g)

        # Should have positive modularity
        assert result.modularity > 0
