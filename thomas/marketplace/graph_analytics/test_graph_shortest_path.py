"""
Tests for shortest path algorithms.
"""

import pytest

from thomas.marketplace.graph_analytics._exceptions import NegativeCycleError
from thomas.marketplace.graph_analytics._types import GraphType
from thomas.marketplace.graph_analytics.graph import Graph
from thomas.marketplace.graph_analytics.shortest_path import (
    astar_shortest_path,
    bellman_ford_shortest_path,
    bfs_shortest_path,
    bidirectional_dijkstra,
    dijkstra_shortest_path,
    floyd_warshall_all_pairs,
)


class TestBFS:
    """Tests for BFS shortest path."""

    def test_bfs_simple_path(self):
        """Test BFS on simple graph."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(2, 3)

        result = bfs_shortest_path(g, 0, 3)
        assert result.path == [0, 1, 2, 3]
        assert result.distance == 3

    def test_bfs_no_path(self):
        """Test BFS when no path exists."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_edge(2, 3)

        result = bfs_shortest_path(g, 0, 3)
        assert not result.has_path()
        assert result.distance == float("inf")

    def test_bfs_all_distances(self):
        """Test BFS without target (all distances)."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_edge(0, 2)
        g.add_edge(1, 3)

        result = bfs_shortest_path(g, 0)
        assert result.distances[0] == 0
        assert result.distances[1] == 1
        assert result.distances[2] == 1
        assert result.distances[3] == 2

    def test_bfs_single_node(self):
        """Test BFS on single node graph."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_node(0)

        result = bfs_shortest_path(g, 0, 0)
        assert result.path == [0]
        assert result.distance == 0


class TestDijkstra:
    """Tests for Dijkstra shortest path."""

    def test_dijkstra_weighted_graph(self):
        """Test Dijkstra on weighted graph."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1, 4)
        g.add_edge(0, 2, 2)
        g.add_edge(1, 2, 1)
        g.add_edge(1, 3, 5)
        g.add_edge(2, 3, 8)

        result = dijkstra_shortest_path(g, 0, 3)
        assert result.path == [0, 1, 3]
        assert result.distance == 9

    def test_dijkstra_negative_weight_error(self):
        """Test Dijkstra rejects negative weights."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1, -1)

        with pytest.raises(Exception):
            dijkstra_shortest_path(g, 0, 1)

    def test_dijkstra_no_path(self):
        """Test Dijkstra when no path exists."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1)
        g.add_edge(2, 3)

        result = dijkstra_shortest_path(g, 0, 3)
        assert not result.has_path()

    def test_dijkstra_equal_weights(self):
        """Test Dijkstra with uniform weights."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1, 1)
        g.add_edge(0, 2, 1)
        g.add_edge(1, 3, 1)
        g.add_edge(2, 3, 1)

        result = dijkstra_shortest_path(g, 0, 3)
        assert result.distance == 2


class TestBellmanFord:
    """Tests for Bellman-Ford shortest path."""

    def test_bellman_ford_simple(self):
        """Test Bellman-Ford on simple graph."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1, 4)
        g.add_edge(0, 2, 2)
        g.add_edge(1, 2, -3)

        result = bellman_ford_shortest_path(g, 0, 2)
        assert result.path == [0, 1, 2]
        assert result.distance == 1

    def test_bellman_ford_negative_weights(self):
        """Test Bellman-Ford handles negative weights."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1, -1)
        g.add_edge(1, 2, -2)
        g.add_edge(2, 3, -3)

        result = bellman_ford_shortest_path(g, 0, 3)
        assert result.distance == -6

    def test_bellman_ford_negative_cycle_detection(self):
        """Test Bellman-Ford detects negative cycles."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1, 1)
        g.add_edge(1, 2, -3)
        g.add_edge(2, 1, 1)

        with pytest.raises(NegativeCycleError):
            bellman_ford_shortest_path(g, 0, 2)

    def test_bellman_ford_no_path(self):
        """Test Bellman-Ford when no path exists."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1)
        g.add_edge(2, 3)

        result = bellman_ford_shortest_path(g, 0, 3)
        assert not result.has_path()


class TestFloydWarshall:
    """Tests for Floyd-Warshall all-pairs shortest paths."""

    def test_floyd_warshall_simple(self):
        """Test Floyd-Warshall on simple graph."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1, 4)
        g.add_edge(0, 2, 2)
        g.add_edge(1, 2, 1)
        g.add_edge(1, 3, 5)
        g.add_edge(2, 3, 8)

        dist_dict, pred_dict = floyd_warshall_all_pairs(g)

        assert dist_dict[0][3] == 9
        assert dist_dict[0][2] == 2
        assert dist_dict[1][3] == 5

    def test_floyd_warshall_negative_cycle_detection(self):
        """Test Floyd-Warshall detects negative cycles."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1, 1)
        g.add_edge(1, 2, -3)
        g.add_edge(2, 1, 1)

        with pytest.raises(NegativeCycleError):
            floyd_warshall_all_pairs(g)

    def test_floyd_warshall_unreachable(self):
        """Test Floyd-Warshall with unreachable nodes."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1)
        g.add_node(2)

        dist_dict, _ = floyd_warshall_all_pairs(g)
        assert dist_dict[0][2] == float("inf")


class TestAStar:
    """Tests for A* algorithm."""

    def test_astar_euclidean_heuristic(self):
        """Test A* with Euclidean heuristic."""
        g = Graph(GraphType.DIRECTED)

        # Create grid graph with coordinates
        coords = {
            0: (0, 0),
            1: (1, 0),
            2: (0, 1),
            3: (1, 1),
        }

        g.add_edge(0, 1, 1)
        g.add_edge(0, 2, 1)
        g.add_edge(1, 3, 1)
        g.add_edge(2, 3, 1)

        def euclidean(node, target):
            x1, y1 = coords[node]
            x2, y2 = coords[target]
            return ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5

        result = astar_shortest_path(g, 0, 3, euclidean)
        assert result.distance == 2

    def test_astar_zero_heuristic(self):
        """Test A* with zero heuristic (like Dijkstra)."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1, 4)
        g.add_edge(0, 2, 2)
        g.add_edge(1, 3, 5)
        g.add_edge(2, 3, 8)

        result = astar_shortest_path(g, 0, 3, lambda n, t: 0)
        assert result.distance == 9


class TestBidirectionalDijkstra:
    """Tests for bidirectional Dijkstra."""

    def test_bidirectional_dijkstra_simple(self):
        """Test bidirectional Dijkstra."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1, 4)
        g.add_edge(0, 2, 2)
        g.add_edge(1, 2, 1)
        g.add_edge(1, 3, 5)
        g.add_edge(2, 3, 8)

        result = bidirectional_dijkstra(g, 0, 3)
        assert result.distance == 9

    def test_bidirectional_dijkstra_same_source_target(self):
        """Test bidirectional Dijkstra with same source and target."""
        g = Graph(GraphType.DIRECTED)
        g.add_node(0)

        result = bidirectional_dijkstra(g, 0, 0)
        assert result.path == [0]
        assert result.distance == 0


class TestIntegration:
    """Integration tests comparing different algorithms."""

    def test_all_algorithms_consistent(self):
        """Test that all algorithms give consistent results on simple graph."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1, 1)
        g.add_edge(0, 2, 4)
        g.add_edge(1, 2, 2)
        g.add_edge(1, 3, 1)
        g.add_edge(2, 3, 1)

        bfs_shortest_path(g, 0, 3)
        dij_result = dijkstra_shortest_path(g, 0, 3)
        bf_result = bellman_ford_shortest_path(g, 0, 3)

        assert dij_result.distance == bf_result.distance
        # BFS may differ due to unweighted nature

    def test_large_graph_performance(self):
        """Test algorithms on larger graph."""
        g = Graph(GraphType.DIRECTED)

        # Create grid graph
        size = 10
        for i in range(size):
            for j in range(size):
                node = i * size + j
                g.add_node(node)

                if j + 1 < size:
                    g.add_edge(node, node + 1, 1)
                if i + 1 < size:
                    g.add_edge(node, node + size, 1)

        result = dijkstra_shortest_path(g, 0, size * size - 1)
        assert result.has_path()
        assert result.distance == (size - 1) * 2
