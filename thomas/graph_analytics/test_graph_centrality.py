"""
Tests for centrality measures.
"""

from thomas.graph_analytics._types import GraphType
from thomas.graph_analytics.centrality import (
    betweenness_centrality,
    closeness_centrality,
    degree_centrality,
    eigenvector_centrality,
    hits,
    katz_centrality,
    pagerank,
)
from thomas.graph_analytics.graph import Graph


class TestDegreeCentrality:
    """Tests for degree centrality."""

    def test_degree_centrality_star_graph(self):
        """Test degree centrality on star graph."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_edge(0, 2)
        g.add_edge(0, 3)
        g.add_edge(0, 4)

        result = degree_centrality(g, normalized=True)

        assert result.scores[0] == 1.0  # Center has max centrality
        assert result.scores[1] == 0.25  # Leaves
        assert result.measure == "degree_centrality"

    def test_degree_centrality_complete_graph(self):
        """Test degree centrality on complete graph."""
        g = Graph(GraphType.UNDIRECTED)
        for i in range(4):
            for j in range(i + 1, 4):
                g.add_edge(i, j)

        result = degree_centrality(g, normalized=True)

        # All nodes have same degree
        for score in result.scores.values():
            assert score == 1.0

    def test_degree_centrality_unnormalized(self):
        """Test unnormalized degree centrality."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_edge(0, 2)
        g.add_edge(1, 2)

        result = degree_centrality(g, normalized=False)

        assert result.scores[0] == 2
        assert result.scores[1] == 2
        assert result.scores[2] == 2


class TestBetweennessCentrality:
    """Tests for betweenness centrality."""

    def test_betweenness_centrality_path_graph(self):
        """Test betweenness on path graph."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(2, 3)

        result = betweenness_centrality(g, normalized=True)

        # Middle nodes have higher betweenness
        assert result.scores[1] > result.scores[0]
        assert result.scores[1] > result.scores[3]

    def test_betweenness_centrality_star_graph(self):
        """Test betweenness on star graph."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_edge(0, 2)
        g.add_edge(0, 3)

        result = betweenness_centrality(g, normalized=True)

        # Center node has all betweenness
        assert result.scores[0] > 0
        assert result.scores[1] == 0


class TestClosenessCentrality:
    """Tests for closeness centrality."""

    def test_closeness_centrality_star_graph(self):
        """Test closeness on star graph."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_edge(0, 2)
        g.add_edge(0, 3)

        result = closeness_centrality(g, normalized=True)

        # Center has highest closeness
        assert result.scores[0] > result.scores[1]

    def test_closeness_centrality_disconnected(self):
        """Test closeness on disconnected graph."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_node(2)

        result = closeness_centrality(g)

        # Isolated node has low closeness
        assert result.scores[2] == 0.0


class TestEigenvectorCentrality:
    """Tests for eigenvector centrality."""

    def test_eigenvector_centrality_star_graph(self):
        """Test eigenvector centrality on star graph."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_edge(0, 2)
        g.add_edge(0, 3)

        result = eigenvector_centrality(g)

        # Center has highest score
        assert result.scores[0] > result.scores[1]
        assert result.measure == "eigenvector_centrality"

    def test_eigenvector_centrality_normalized(self):
        """Test eigenvector centrality is normalized."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_edge(1, 2)

        result = eigenvector_centrality(g)

        # Scores should be normalized
        total = sum(s**2 for s in result.scores.values())
        assert abs(total - 1.0) < 0.1  # Allow some tolerance


class TestPageRank:
    """Tests for PageRank centrality."""

    def test_pagerank_simple_graph(self):
        """Test PageRank on simple directed graph."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1)
        g.add_edge(0, 2)
        g.add_edge(1, 2)
        g.add_edge(2, 0)

        result = pagerank(g)

        assert len(result.scores) == 3
        assert all(v >= 0 for v in result.scores.values())
        assert result.measure == "pagerank"

    def test_pagerank_sum_normalized(self):
        """Test PageRank sums to roughly 1."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(2, 0)

        result = pagerank(g, damping_factor=0.85)

        total = sum(result.scores.values())
        assert 0.5 < total < 2.0  # Should be close to 1

    def test_pagerank_convergence(self):
        """Test PageRank converges."""
        g = Graph(GraphType.DIRECTED)
        for i in range(5):
            g.add_edge(i, (i + 1) % 5)

        result = pagerank(g, max_iterations=10)

        # All scores should be roughly equal in cycle
        scores = list(result.scores.values())
        assert max(scores) - min(scores) < 0.1


class TestKatzCentrality:
    """Tests for Katz centrality."""

    def test_katz_centrality_simple(self):
        """Test Katz centrality."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1)
        g.add_edge(0, 2)
        g.add_edge(1, 2)

        result = katz_centrality(g, alpha=0.1)

        assert len(result.scores) == 3
        assert result.normalized is True


class TestHITS:
    """Tests for HITS algorithm."""

    def test_hits_simple_graph(self):
        """Test HITS on simple graph."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1)
        g.add_edge(0, 2)
        g.add_edge(1, 2)
        g.add_edge(2, 0)

        hub_result, auth_result = hits(g)

        assert len(hub_result.scores) == 3
        assert len(auth_result.scores) == 3
        assert hub_result.measure == "hits_hub"
        assert auth_result.measure == "hits_authority"

    def test_hits_hub_authority_difference(self):
        """Test HITS distinguishes hubs and authorities."""
        g = Graph(GraphType.DIRECTED)
        # Create structure where 0,1 are hubs (point out) and 2,3 are authorities
        g.add_edge(0, 2)
        g.add_edge(0, 3)
        g.add_edge(1, 2)
        g.add_edge(1, 3)

        hub_result, auth_result = hits(g)

        # Nodes 0,1 should have higher hub score
        assert hub_result.scores[0] > auth_result.scores[0]
        # Nodes 2,3 should have higher authority score
        assert auth_result.scores[2] > hub_result.scores[2]


class TestCentralityStatistics:
    """Tests for centrality statistics."""

    def test_centrality_statistics(self):
        """Test that statistics are computed."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(2, 3)

        result = degree_centrality(g)

        assert "min" in result.statistics
        assert "max" in result.statistics
        assert "mean" in result.statistics

    def test_centrality_top_nodes(self):
        """Test CentralityResult.top_nodes() method."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_edge(0, 2)
        g.add_edge(0, 3)
        g.add_edge(1, 2)

        result = degree_centrality(g)
        top = result.top_nodes(k=2)

        assert len(top) == 2
        assert top[0][1] >= top[1][1]  # Sorted descending


class TestIntegration:
    """Integration tests for centrality measures."""

    def test_all_centrality_measures_on_same_graph(self):
        """Test all centrality measures on same graph."""
        g = Graph(GraphType.UNDIRECTED)
        for i in range(5):
            for j in range(i + 1, 5):
                g.add_edge(i, j)

        deg_result = degree_centrality(g)
        between_result = betweenness_centrality(g)
        close_result = closeness_centrality(g)
        eigen_result = eigenvector_centrality(g)

        # All should compute without error
        assert len(deg_result.scores) == 5
        assert len(between_result.scores) == 5
        assert len(close_result.scores) == 5
        assert len(eigen_result.scores) == 5

    def test_centrality_on_scale_free_graph(self):
        """Test centrality on scale-free network."""
        from thomas.graph_analytics.generators import barabasi_albert_graph

        g = barabasi_albert_graph(20, m=2)

        result = degree_centrality(g)

        assert len(result.scores) == 20
