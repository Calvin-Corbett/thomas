"""
Tests for graph traversal algorithms.
"""

import pytest

from thomas.graph_analytics._exceptions import CycleDetectedError
from thomas.graph_analytics._types import GraphType
from thomas.graph_analytics.graph import Graph
from thomas.graph_analytics.traversal import (
    bfs_traversal,
    connected_components,
    detect_cycle,
    dfs_traversal,
    eulerian_path_exists,
    hamiltonian_path_backtrack,
    strongly_connected_components,
    topological_sort,
)


class TestBFSTraversal:
    """Tests for BFS traversal."""

    def test_bfs_simple(self):
        """Test BFS traversal."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_edge(0, 2)
        g.add_edge(1, 3)

        order, depths = bfs_traversal(g, 0)

        assert order[0] == 0
        assert depths[0] == 0
        assert depths[1] == 1
        assert depths[3] == 2

    def test_bfs_with_max_depth(self):
        """Test BFS with depth limit."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(2, 3)

        order, depths = bfs_traversal(g, 0, max_depth=1)

        assert 3 not in depths

    def test_bfs_disconnected_graph(self):
        """Test BFS on disconnected graph."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_node(2)

        order, depths = bfs_traversal(g, 0)

        assert 2 not in depths


class TestDFSTraversal:
    """Tests for DFS traversal."""

    def test_dfs_simple(self):
        """Test DFS traversal."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1)
        g.add_edge(0, 2)
        g.add_edge(1, 3)

        order, disc_times, finish_times = dfs_traversal(g, 0)

        assert order[0] == 0
        assert disc_times[0] < disc_times[1]
        assert finish_times[0] > finish_times[1]

    def test_dfs_all_nodes_visited(self):
        """Test DFS visits all reachable nodes."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(2, 3)

        order, _, _ = dfs_traversal(g, 0)

        assert set(order) == {0, 1, 2, 3}


class TestTopologicalSort:
    """Tests for topological sort."""

    def test_topological_sort_simple_dag(self):
        """Test topological sort on simple DAG."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1)
        g.add_edge(0, 2)
        g.add_edge(1, 3)
        g.add_edge(2, 3)

        topo_order = topological_sort(g)

        # Verify ordering: parents before children
        order_idx = {node: i for i, node in enumerate(topo_order)}
        assert order_idx[0] < order_idx[1]
        assert order_idx[0] < order_idx[2]
        assert order_idx[1] < order_idx[3]

    def test_topological_sort_cycle_error(self):
        """Test topological sort detects cycles."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(2, 0)

        with pytest.raises(CycleDetectedError):
            topological_sort(g)

    def test_topological_sort_single_node(self):
        """Test topological sort on single node."""
        g = Graph(GraphType.DIRECTED)
        g.add_node(0)

        topo_order = topological_sort(g)

        assert topo_order == [0]


class TestCycleDetection:
    """Tests for cycle detection."""

    def test_detect_cycle_simple(self):
        """Test cycle detection on simple graph."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(2, 0)

        cycle = detect_cycle(g)

        assert cycle is not None
        assert len(cycle) >= 3

    def test_detect_cycle_no_cycle(self):
        """Test cycle detection on DAG."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1)
        g.add_edge(0, 2)
        g.add_edge(1, 3)

        cycle = detect_cycle(g)

        assert cycle is None

    def test_detect_self_loop(self):
        """Test detection of self-loops."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 0)

        cycle = detect_cycle(g)

        assert cycle is not None


class TestConnectedComponents:
    """Tests for connected components."""

    def test_connected_components_single(self):
        """Test single connected component."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_edge(1, 2)

        components = connected_components(g)

        assert len(components) == 1
        assert {0, 1, 2} in components

    def test_connected_components_multiple(self):
        """Test multiple connected components."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_edge(2, 3)

        components = connected_components(g)

        assert len(components) == 2

    def test_connected_components_isolated_nodes(self):
        """Test with isolated nodes."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_node(2)

        components = connected_components(g)

        assert len(components) == 2


class TestStronglyConnectedComponents:
    """Tests for strongly connected components."""

    def test_scc_simple_directed_cycle(self):
        """Test SCC on simple cycle."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(2, 0)

        sccs = strongly_connected_components(g)

        # All should be in same SCC
        assert len(sccs) == 1
        assert {0, 1, 2} in sccs

    def test_scc_dag_all_separate(self):
        """Test SCC on DAG (each node is own SCC)."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1)
        g.add_edge(1, 2)

        sccs = strongly_connected_components(g)

        assert len(sccs) == 3
        assert all(len(scc) == 1 for scc in sccs)

    def test_scc_multiple_components(self):
        """Test multiple SCCs."""
        g = Graph(GraphType.DIRECTED)
        # Component 1
        g.add_edge(0, 1)
        g.add_edge(1, 0)

        # Component 2
        g.add_edge(2, 3)
        g.add_edge(3, 2)

        sccs = strongly_connected_components(g)

        assert len(sccs) == 2


class TestEulerianPath:
    """Tests for Eulerian path detection."""

    def test_eulerian_circuit_undirected(self):
        """Test Eulerian circuit in undirected graph."""
        g = Graph(GraphType.UNDIRECTED)
        # Square
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(2, 3)
        g.add_edge(3, 0)

        assert eulerian_path_exists(g)

    def test_eulerian_path_undirected(self):
        """Test Eulerian path in undirected graph."""
        g = Graph(GraphType.UNDIRECTED)
        # Path with two odd-degree vertices
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(2, 3)

        assert eulerian_path_exists(g)

    def test_no_eulerian_path(self):
        """Test graph with no Eulerian path."""
        g = Graph(GraphType.UNDIRECTED)
        # Triangle with extra vertex
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(2, 0)
        g.add_edge(0, 3)

        assert not eulerian_path_exists(g)


class TestHamiltonianPath:
    """Tests for Hamiltonian path detection."""

    def test_hamiltonian_path_complete_graph(self):
        """Test Hamiltonian path in complete graph."""
        g = Graph(GraphType.UNDIRECTED)
        for i in range(4):
            for j in range(i + 1, 4):
                g.add_edge(i, j)

        paths = hamiltonian_path_backtrack(g)

        # Should find at least one path
        assert len(paths) > 0

    def test_hamiltonian_path_line_graph(self):
        """Test Hamiltonian path in line graph."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(2, 3)

        paths = hamiltonian_path_backtrack(g)

        # Should find Hamiltonian path
        assert len(paths) > 0
        if paths:
            assert len(paths[0]) == 4

    def test_hamiltonian_path_from_source(self):
        """Test Hamiltonian path from specific source."""
        g = Graph(GraphType.UNDIRECTED)
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(2, 3)

        paths = hamiltonian_path_backtrack(g, source=0)

        if paths:
            assert paths[0][0] == 0

    def test_hamiltonian_path_max_paths(self):
        """Test limiting number of Hamiltonian paths."""
        g = Graph(GraphType.UNDIRECTED)
        for i in range(4):
            for j in range(i + 1, 4):
                g.add_edge(i, j)

        paths = hamiltonian_path_backtrack(g, max_paths=2)

        assert len(paths) <= 2


class TestIntegration:
    """Integration tests for traversal algorithms."""

    def test_all_traversals_on_same_graph(self):
        """Test multiple traversals on same graph."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1)
        g.add_edge(0, 2)
        g.add_edge(1, 3)
        g.add_edge(2, 3)

        bfs_order, _ = bfs_traversal(g, 0)
        dfs_order, _, _ = dfs_traversal(g, 0)
        topo_order = topological_sort(g)

        assert len(bfs_order) == 4
        assert len(dfs_order) == 4
        assert len(topo_order) == 4

    def test_graph_structure_analysis(self):
        """Test analyzing graph structure."""
        g = Graph(GraphType.DIRECTED)
        g.add_edge(0, 1)
        g.add_edge(1, 2)
        g.add_edge(2, 3)

        has_cycle = detect_cycle(g) is not None
        assert not has_cycle

        sccs = strongly_connected_components(g)
        assert len(sccs) == 4
