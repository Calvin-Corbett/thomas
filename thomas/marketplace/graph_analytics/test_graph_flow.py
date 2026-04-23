"""
Tests for network flow algorithms.
"""

from thomas.marketplace.graph_analytics._types import GraphType
from thomas.marketplace.graph_analytics.flow import (
    flow_decomposition,
    max_flow_edmonds_karp,
    maximum_bipartite_matching,
    min_cost_flow,
    min_cut,
    residual_graph,
)
from thomas.marketplace.graph_analytics.graph import Graph


class TestMaxFlow:
    """Tests for maximum flow (Edmonds-Karp)."""

    def test_max_flow_simple(self):
        """Test max flow on simple graph."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1, 10)
        g.add_edge(0, 2, 10)
        g.add_edge(1, 2, 2)
        g.add_edge(1, 3, 4)
        g.add_edge(2, 4, 10)
        g.add_edge(3, 2, 9)
        g.add_edge(3, 4, 10)

        flow_value, flow = max_flow_edmonds_karp(g, 0, 4)

        assert flow_value > 0
        assert isinstance(flow, dict)

    def test_max_flow_no_path(self):
        """Test max flow when no path exists."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1, 10)
        g.add_node(2)
        g.add_node(3)

        flow_value, _ = max_flow_edmonds_karp(g, 0, 3)

        assert flow_value == 0

    def test_max_flow_single_edge(self):
        """Test max flow on single edge."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1, 5)

        flow_value, _ = max_flow_edmonds_karp(g, 0, 1)

        assert flow_value == 5

    def test_max_flow_bottleneck(self):
        """Test max flow respects bottleneck."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1, 10)
        g.add_edge(1, 2, 5)
        g.add_edge(2, 3, 10)

        flow_value, _ = max_flow_edmonds_karp(g, 0, 3)

        assert flow_value == 5

    def test_max_flow_parallel_paths(self):
        """Test max flow with parallel paths."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1, 10)
        g.add_edge(0, 2, 10)
        g.add_edge(1, 3, 10)
        g.add_edge(2, 3, 10)

        flow_value, _ = max_flow_edmonds_karp(g, 0, 3)

        assert flow_value == 20


class TestMinCut:
    """Tests for minimum cut."""

    def test_min_cut_simple(self):
        """Test minimum cut."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1, 10)
        g.add_edge(0, 2, 10)
        g.add_edge(1, 3, 4)
        g.add_edge(2, 1, 9)
        g.add_edge(2, 4, 10)
        g.add_edge(3, 4, 10)

        cut_value, (source_partition, sink_partition) = min_cut(g, 0, 4)

        assert cut_value > 0
        assert 0 in source_partition
        assert 4 in sink_partition

    def test_min_cut_value_equals_max_flow(self):
        """Test min-cut equals max-flow."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1, 10)
        g.add_edge(0, 2, 10)
        g.add_edge(1, 2, 2)
        g.add_edge(1, 3, 4)
        g.add_edge(2, 4, 10)
        g.add_edge(3, 2, 9)
        g.add_edge(3, 4, 10)

        flow_value, _ = max_flow_edmonds_karp(g, 0, 4)
        cut_value, _ = min_cut(g, 0, 4)

        assert flow_value == cut_value


class TestBipartiteMatching:
    """Tests for bipartite matching."""

    def test_bipartite_matching_simple(self):
        """Test bipartite matching on simple graph."""
        g = Graph(GraphType.UNDIRECTED)

        left = [0, 1, 2]
        right = [3, 4, 5]

        g.add_edge(0, 3)
        g.add_edge(0, 4)
        g.add_edge(1, 4)
        g.add_edge(2, 5)

        matching = maximum_bipartite_matching(g, left, right)

        assert len(matching) <= len(left)
        assert len(matching) <= len(right)

    def test_bipartite_matching_perfect(self):
        """Test perfect matching."""
        g = Graph(GraphType.UNDIRECTED)

        left = [0, 1]
        right = [2, 3]

        g.add_edge(0, 2)
        g.add_edge(0, 3)
        g.add_edge(1, 2)
        g.add_edge(1, 3)

        matching = maximum_bipartite_matching(g, left, right)

        assert len(matching) == 2

    def test_bipartite_matching_no_edges(self):
        """Test matching with no edges."""
        g = Graph(GraphType.UNDIRECTED)

        left = [0, 1]
        right = [2, 3]

        # Add nodes but no edges
        for node in left + right:
            g.add_node(node)

        matching = maximum_bipartite_matching(g, left, right)

        assert len(matching) == 0


class TestMinCostFlow:
    """Tests for minimum cost flow."""

    def test_min_cost_flow_simple(self):
        """Test min cost flow."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1, 1)  # cost = weight
        g.add_edge(0, 2, 2)
        g.add_edge(1, 3, 1)
        g.add_edge(2, 3, 1)

        cost, flow = min_cost_flow(g, 0, 3, required_flow=2)

        # Should send flow through cheaper path
        assert cost >= 0
        assert isinstance(flow, dict)

    def test_min_cost_flow_zero_flow(self):
        """Test min cost flow with zero required flow."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1, 1)

        cost, flow = min_cost_flow(g, 0, 1, required_flow=0)

        assert cost == 0


class TestResidualGraph:
    """Tests for residual graph construction."""

    def test_residual_graph_simple(self):
        """Test residual graph construction."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1, 10)
        g.add_edge(1, 2, 10)

        flow = {(0, 1): 5, (1, 2): 5}
        residual = residual_graph(g, flow)

        # Forward edges should have reduced capacity
        assert residual.has_edge(0, 1)

        # Reverse edges should be added
        assert residual.has_edge(1, 0)


class TestFlowDecomposition:
    """Tests for flow decomposition."""

    def test_flow_decomposition_simple(self):
        """Test flow decomposition."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1, 10)
        g.add_edge(1, 2, 10)

        flow = {(0, 1): 5, (1, 2): 5}
        paths = flow_decomposition(g, flow)

        # Should decompose into paths
        assert len(paths) > 0

    def test_flow_decomposition_multiple_paths(self):
        """Test flow decomposition with multiple paths."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1, 10)
        g.add_edge(0, 2, 10)
        g.add_edge(1, 3, 10)
        g.add_edge(2, 3, 10)

        flow = {(0, 1): 5, (0, 2): 3, (1, 3): 5, (2, 3): 3}
        paths = flow_decomposition(g, flow)

        assert len(paths) > 0


class TestIntegration:
    """Integration tests for flow algorithms."""

    def test_flow_conservation(self):
        """Test flow conservation property."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1, 10)
        g.add_edge(0, 2, 10)
        g.add_edge(1, 3, 10)
        g.add_edge(2, 3, 10)

        flow_value, flow = max_flow_edmonds_karp(g, 0, 3)

        # Check flow conservation for intermediate nodes
        for node in [1, 2]:
            flow_in = sum(f for (src, dst), f in flow.items() if dst == node)
            flow_out = sum(f for (src, dst), f in flow.items() if src == node)

            assert abs(flow_in - flow_out) < 0.01

    def test_large_flow_graph(self):
        """Test flow on larger graph."""
        g = Graph(GraphType.DIRECTED)

        # Grid flow network
        for i in range(3):
            for j in range(3):
                current = i * 3 + j
                if j + 1 < 3:
                    g.add_edge(current, current + 1, 10)
                if i + 1 < 3:
                    g.add_edge(current, current + 3, 10)

        flow_value, _ = max_flow_edmonds_karp(g, 0, 8)

        assert flow_value > 0
