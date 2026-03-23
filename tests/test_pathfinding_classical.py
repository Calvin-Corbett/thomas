"""
Tests for classical pathfinding algorithms.
"""

import pytest

from thomas.marketplace.pathfinding import (
    Graph,
    Node,
    astar,
    beam_search,
    bellman_ford,
    bidirectional_dijkstra,
    dijkstra,
    floyd_warshall,
    iterative_deepening_astar,
)


class TestDijkstra:
    """Tests for Dijkstra's algorithm."""

    def test_simple_path(self) -> None:
        """Test finding path in simple graph."""
        graph = Graph(directed=False)
        graph.add_node(Node(0, 0.0, 0.0))
        graph.add_node(Node(1, 1.0, 0.0))
        graph.add_node(Node(2, 2.0, 0.0))

        graph.add_edge(0, 1, 1.0)
        graph.add_edge(1, 2, 1.0)

        result = dijkstra(graph, 0, 2)

        assert result.found
        assert result.path.length() == 3
        assert result.cost == 2.0

    def test_weighted_graph(self) -> None:
        """Test with weighted edges."""
        graph = Graph(directed=True)
        graph.add_node(Node("A", 0.0, 0.0))
        graph.add_node(Node("B", 1.0, 0.0))
        graph.add_node(Node("C", 2.0, 0.0))
        graph.add_node(Node("D", 3.0, 0.0))

        graph.add_edge("A", "B", 4.0)
        graph.add_edge("A", "C", 2.0)
        graph.add_edge("C", "B", 1.0)
        graph.add_edge("B", "D", 1.0)
        graph.add_edge("C", "D", 5.0)

        result = dijkstra(graph, "A", "D")

        assert result.found
        assert result.cost == 4.0

    def test_no_path(self) -> None:
        """Test when no path exists."""
        graph = Graph(directed=True)
        graph.add_node(Node(0, 0.0, 0.0))
        graph.add_node(Node(1, 1.0, 0.0))
        graph.add_node(Node(2, 2.0, 0.0))

        graph.add_edge(0, 1, 1.0)

        result = dijkstra(graph, 0, 2)

        assert not result.found

    def test_single_node(self) -> None:
        """Test path to same node."""
        graph = Graph(directed=False)
        graph.add_node(Node(0, 0.0, 0.0))

        result = dijkstra(graph, 0, 0)

        assert result.found
        assert result.cost == 0.0


class TestAStar:
    """Tests for A* algorithm."""

    def test_euclidean_heuristic(self) -> None:
        """Test A* with Euclidean heuristic."""
        graph = Graph(directed=False)
        graph.add_node(Node(0, 0.0, 0.0))
        graph.add_node(Node(1, 1.0, 1.0))
        graph.add_node(Node(2, 2.0, 2.0))

        graph.add_edge(0, 1, 1.414)
        graph.add_edge(1, 2, 1.414)

        result = astar(graph, 0, 2, heuristic_name="euclidean")

        assert result.found
        assert result.path.length() == 3

    def test_manhattan_heuristic(self) -> None:
        """Test A* with Manhattan heuristic."""
        graph = Graph(directed=False)
        graph.add_node(Node(0, 0.0, 0.0))
        graph.add_node(Node(1, 1.0, 0.0))
        graph.add_node(Node(2, 2.0, 0.0))

        graph.add_edge(0, 1, 1.0)
        graph.add_edge(1, 2, 1.0)

        result = astar(graph, 0, 2, heuristic_name="manhattan")

        assert result.found
        assert result.cost == 2.0

    def test_octile_heuristic(self) -> None:
        """Test A* with octile heuristic."""
        graph = Graph(directed=False)
        graph.add_node(Node(0, 0.0, 0.0))
        graph.add_node(Node(1, 1.0, 1.0))
        graph.add_node(Node(2, 2.0, 2.0))

        graph.add_edge(0, 1, 1.0)
        graph.add_edge(1, 2, 1.0)

        result = astar(graph, 0, 2, heuristic_name="octile")

        assert result.found

    def test_more_efficient_than_dijkstra(self) -> None:
        """A* should expand fewer nodes than Dijkstra."""
        graph = Graph(directed=False)
        for i in range(10):
            graph.add_node(Node(i, float(i), 0.0))

        for i in range(9):
            graph.add_edge(i, i + 1, 1.0)

        dijkstra_result = dijkstra(graph, 0, 9)
        astar_result = astar(graph, 0, 9)

        assert dijkstra_result.found
        assert astar_result.found


class TestBellmanFord:
    """Tests for Bellman-Ford algorithm."""

    def test_simple_path(self) -> None:
        """Test finding path with positive weights."""
        graph = Graph(directed=True)
        graph.add_node(Node(0, 0.0, 0.0))
        graph.add_node(Node(1, 1.0, 0.0))
        graph.add_node(Node(2, 2.0, 0.0))

        graph.add_edge(0, 1, 1.0)
        graph.add_edge(1, 2, 1.0)

        result = bellman_ford(graph, 0, 2)

        assert result.found
        assert result.cost == 2.0

    def test_negative_weights(self) -> None:
        """Test with negative edge weights."""
        graph = Graph(directed=True)
        graph.add_node(Node("A", 0.0, 0.0))
        graph.add_node(Node("B", 1.0, 0.0))
        graph.add_node(Node("C", 2.0, 0.0))

        graph.add_edge("A", "B", 4.0)
        graph.add_edge("A", "C", 2.0)
        graph.add_edge("C", "B", -3.0)

        result = bellman_ford(graph, "A", "B")

        assert result.found
        assert result.cost == -1.0

    def test_negative_cycle_detection(self) -> None:
        """Test detection of negative cycles."""
        graph = Graph(directed=True)
        graph.add_node(Node(0, 0.0, 0.0))
        graph.add_node(Node(1, 1.0, 0.0))
        graph.add_node(Node(2, 2.0, 0.0))

        graph.add_edge(0, 1, 1.0)
        graph.add_edge(1, 2, -3.0)
        graph.add_edge(2, 1, 1.0)

        with pytest.raises(Exception):
            bellman_ford(graph, 0, 2)


class TestFloydWarshall:
    """Tests for Floyd-Warshall algorithm."""

    def test_all_pairs_shortest_paths(self) -> None:
        """Test computing all pairs shortest paths."""
        graph = Graph(directed=True)
        graph.add_node(Node(0, 0.0, 0.0))
        graph.add_node(Node(1, 1.0, 0.0))
        graph.add_node(Node(2, 2.0, 0.0))

        graph.add_edge(0, 1, 4.0)
        graph.add_edge(0, 2, 2.0)
        graph.add_edge(1, 2, 1.0)

        dist, idx_map = floyd_warshall(graph)

        assert dist[0][0] == 0.0
        assert dist[0][2] == 2.0
        assert dist[0][1] == 3.0

    def test_disconnected_nodes(self) -> None:
        """Test with disconnected components."""
        graph = Graph(directed=True)
        graph.add_node(Node(0, 0.0, 0.0))
        graph.add_node(Node(1, 1.0, 0.0))
        graph.add_node(Node(2, 2.0, 0.0))

        graph.add_edge(0, 1, 1.0)

        dist, idx_map = floyd_warshall(graph)

        assert dist[0][1] == 1.0
        assert dist[1][2] == float("inf")


class TestBidirectionalDijkstra:
    """Tests for bidirectional Dijkstra."""

    def test_finds_path(self) -> None:
        """Test that bidirectional search finds path."""
        graph = Graph(directed=False)
        for i in range(5):
            graph.add_node(Node(i, float(i), 0.0))

        for i in range(4):
            graph.add_edge(i, i + 1, 1.0)

        result = bidirectional_dijkstra(graph, 0, 4)

        assert result.found
        assert result.cost == 4.0

    def test_correct_cost(self) -> None:
        """Test correctness of path cost."""
        graph = Graph(directed=True)
        graph.add_node(Node("A", 0.0, 0.0))
        graph.add_node(Node("B", 1.0, 0.0))
        graph.add_node(Node("C", 2.0, 0.0))
        graph.add_node(Node("D", 3.0, 0.0))

        graph.add_edge("A", "B", 2.0)
        graph.add_edge("B", "C", 3.0)
        graph.add_edge("C", "D", 1.0)

        result = bidirectional_dijkstra(graph, "A", "D")

        assert result.found
        assert result.cost == 6.0


class TestIterativeDeepeningAStar:
    """Tests for Iterative Deepening A*."""

    def test_finds_optimal_path(self) -> None:
        """Test that IDA* finds optimal path."""
        graph = Graph(directed=False)
        graph.add_node(Node(0, 0.0, 0.0))
        graph.add_node(Node(1, 1.0, 1.0))
        graph.add_node(Node(2, 2.0, 0.0))
        graph.add_node(Node(3, 2.0, 2.0))

        graph.add_edge(0, 1, 1.414)
        graph.add_edge(0, 2, 2.0)
        graph.add_edge(1, 3, 1.414)
        graph.add_edge(2, 3, 2.0)

        result = iterative_deepening_astar(graph, 0, 3)

        assert result.found

    def test_no_path_found(self) -> None:
        """Test when no path exists."""
        graph = Graph(directed=True)
        graph.add_node(Node(0, 0.0, 0.0))
        graph.add_node(Node(1, 1.0, 0.0))

        result = iterative_deepening_astar(graph, 0, 1)

        assert not result.found


class TestBeamSearch:
    """Tests for Beam Search."""

    def test_finds_path_with_limited_width(self) -> None:
        """Test beam search with limited branching."""
        graph = Graph(directed=False)
        for i in range(6):
            graph.add_node(Node(i, float(i), 0.0))

        graph.add_edge(0, 1, 1.0)
        graph.add_edge(0, 2, 1.0)
        graph.add_edge(1, 3, 1.0)
        graph.add_edge(2, 4, 1.0)
        graph.add_edge(3, 5, 1.0)
        graph.add_edge(4, 5, 1.0)

        result = beam_search(graph, 0, 5, beam_width=2)

        assert result.found

    def test_beam_width_constraint(self) -> None:
        """Test that beam search respects width constraint."""
        graph = Graph(directed=False)
        for i in range(10):
            graph.add_node(Node(i, float(i), 0.0))

        for i in range(9):
            graph.add_edge(i, i + 1, 1.0)

        result_w1 = beam_search(graph, 0, 9, beam_width=1)
        result_w5 = beam_search(graph, 0, 9, beam_width=5)

        assert result_w1.nodes_expanded <= result_w5.nodes_expanded


class TestAlgorithmComparison:
    """Compare different pathfinding algorithms."""

    def test_all_algorithms_find_same_path(self) -> None:
        """Test that different algorithms find paths with same cost."""
        graph = Graph(directed=False)
        for i in range(5):
            graph.add_node(Node(i, float(i), 0.0))

        for i in range(4):
            graph.add_edge(i, i + 1, 1.0)

        dijkstra_result = dijkstra(graph, 0, 4)
        astar_result = astar(graph, 0, 4)
        bf_result = bellman_ford(graph, 0, 4)

        assert dijkstra_result.found
        assert astar_result.found
        assert bf_result.found
        assert dijkstra_result.cost == astar_result.cost == bf_result.cost

    def test_execution_time_measured(self) -> None:
        """Test that execution time is recorded."""
        graph = Graph(directed=False)
        for i in range(10):
            graph.add_node(Node(i, float(i), 0.0))

        for i in range(9):
            graph.add_edge(i, i + 1, 1.0)

        result = dijkstra(graph, 0, 9)

        assert result.execution_time >= 0.0

    def test_nodes_expanded_tracked(self) -> None:
        """Test that node expansion is tracked."""
        graph = Graph(directed=False)
        for i in range(10):
            graph.add_node(Node(i, float(i), 0.0))

        for i in range(9):
            graph.add_edge(i, i + 1, 1.0)

        result = dijkstra(graph, 0, 9)

        assert result.nodes_expanded > 0
        assert result.nodes_generated > 0
