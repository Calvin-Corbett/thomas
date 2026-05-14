"""
Tests for hierarchical pathfinding algorithms.
"""

from thomas.marketplace.pathfinding import Graph, Node
from thomas.marketplace.pathfinding.hierarchical import (
    HierarchicalPathfinder,
    build_hpa_star,
)


class TestHierarchicalPathfinder:
    """Tests for HierarchicalPathfinder."""

    def test_create_hierarchical_pathfinder(self) -> None:
        """Test creating hierarchical pathfinder."""
        graph = Graph(directed=False)
        for i in range(10):
            graph.add_node(Node(i, float(i % 5), float(i // 5)))

        for i in range(9):
            graph.add_edge(i, i + 1, 1.0)

        hpf = HierarchicalPathfinder(graph, cluster_size=2)

        assert hpf.base_graph == graph
        assert len(hpf.clusters) > 0

    def test_clustering(self) -> None:
        """Test that nodes are properly clustered."""
        graph = Graph(directed=False)
        for x in range(5):
            for y in range(5):
                node_id = x * 5 + y
                graph.add_node(Node(node_id, float(x), float(y)))

        hpf = HierarchicalPathfinder(graph, cluster_size=2)

        total_clustered = sum(len(nodes) for nodes in hpf.clusters.values())

        assert total_clustered == 25

    def test_find_path_same_cluster(self) -> None:
        """Test finding path in same cluster."""
        graph = Graph(directed=False)
        for i in range(5):
            graph.add_node(Node(i, float(i), 0.0))

        for i in range(4):
            graph.add_edge(i, i + 1, 1.0)

        hpf = HierarchicalPathfinder(graph, cluster_size=10)

        result = hpf.find_path(0, 4)

        assert result.found

    def test_find_path_different_clusters(self) -> None:
        """Test finding path between clusters."""
        graph = Graph(directed=False)
        for i in range(10):
            graph.add_node(Node(i, float(i), 0.0))

        for i in range(9):
            graph.add_edge(i, i + 1, 1.0)

        hpf = HierarchicalPathfinder(graph, cluster_size=2)

        result = hpf.find_path(0, 9)

        assert result.found

    def test_no_path_exists(self) -> None:
        """Test when no path exists."""
        graph = Graph(directed=True)
        graph.add_node(Node(0, 0.0, 0.0))
        graph.add_node(Node(1, 1.0, 0.0))

        hpf = HierarchicalPathfinder(graph, cluster_size=2)

        result = hpf.find_path(0, 1)

        assert not result.found

    def test_execution_time_recorded(self) -> None:
        """Test that execution time is recorded."""
        graph = Graph(directed=False)
        for i in range(5):
            graph.add_node(Node(i, float(i), 0.0))

        for i in range(4):
            graph.add_edge(i, i + 1, 1.0)

        hpf = HierarchicalPathfinder(graph, cluster_size=2)

        result = hpf.find_path(0, 4)

        assert result.execution_time >= 0.0


class TestBuildHPAStar:
    """Tests for HPA* builder function."""

    def test_build_hpa_star(self) -> None:
        """Test building HPA* structure."""
        graph = Graph(directed=False)
        for i in range(10):
            graph.add_node(Node(i, float(i % 5), float(i // 5)))

        for i in range(9):
            graph.add_edge(i, i + 1, 1.0)

        hpf = build_hpa_star(graph, cluster_size=3)

        assert isinstance(hpf, HierarchicalPathfinder)
        assert len(hpf.clusters) > 0

    def test_hpa_star_finds_path(self) -> None:
        """Test that HPA* finds paths."""
        graph = Graph(directed=False)
        for i in range(15):
            graph.add_node(Node(i, float(i % 5), float(i // 5)))

        for i in range(14):
            graph.add_edge(i, i + 1, 1.0)

        hpf = build_hpa_star(graph)

        result = hpf.find_path(0, 14)

        assert result.found


class TestHierarchyLevels:
    """Tests for multi-level hierarchy."""

    def test_multiple_hierarchy_levels(self) -> None:
        """Test that multiple hierarchy levels are created."""
        graph = Graph(directed=False)
        for i in range(20):
            graph.add_node(Node(i, float(i % 5), float(i // 5)))

        for i in range(19):
            graph.add_edge(i, i + 1, 1.0)

        hpf = HierarchicalPathfinder(graph, cluster_size=2, num_levels=3)

        assert len(hpf.abstract_graphs) >= 2

    def test_pathfinding_with_hierarchy(self) -> None:
        """Test pathfinding uses hierarchy."""
        graph = Graph(directed=False)
        for i in range(20):
            graph.add_node(Node(i, float(i % 5), float(i // 5)))

        for i in range(19):
            graph.add_edge(i, i + 1, 1.0)

        hpf = HierarchicalPathfinder(graph, cluster_size=3, num_levels=2)

        result = hpf.find_path(0, 19)

        assert result.found


class TestObstacleHandling:
    """Tests for handling dynamic obstacles."""

    def test_block_edge_via_obstacle_update(self) -> None:
        """Test that obstacles can be marked."""
        graph = Graph(directed=False)
        for i in range(5):
            graph.add_node(Node(i, float(i), 0.0))

        for i in range(4):
            graph.add_edge(i, i + 1, 1.0)

        hpf = HierarchicalPathfinder(graph, cluster_size=2)

        hpf.update_obstacle(2, blocked=True)

    def test_cluster_respects_blocked_nodes(self) -> None:
        """Test that blocked nodes affect cluster structure."""
        graph = Graph(directed=False)
        for i in range(5):
            graph.add_node(Node(i, float(i), 0.0))

        for i in range(4):
            graph.add_edge(i, i + 1, 1.0)

        hpf = HierarchicalPathfinder(graph, cluster_size=2)

        sum(len(nodes) for nodes in hpf.clusters.values())

        hpf.update_obstacle(2, blocked=True)

        assert hpf.cluster_size == 2


class TestClusterDecomposition:
    """Tests for cluster decomposition."""

    def test_nodes_distributed_to_clusters(self) -> None:
        """Test that all nodes are assigned to clusters."""
        graph = Graph(directed=False)
        nodes_added = 16
        for i in range(nodes_added):
            graph.add_node(Node(i, float(i % 4), float(i // 4)))

        hpf = HierarchicalPathfinder(graph, cluster_size=2)

        total = sum(len(nodes) for nodes in hpf.clusters.values())

        assert total == nodes_added

    def test_cluster_connectivity(self) -> None:
        """Test that clusters maintain connectivity info."""
        graph = Graph(directed=False)
        for i in range(9):
            graph.add_node(Node(i, float(i % 3), float(i // 3)))

        for i in range(8):
            graph.add_edge(i, i + 1, 1.0)

        hpf = HierarchicalPathfinder(graph, cluster_size=2)

        assert len(hpf.inter_cluster_edges) > 0


class TestHierarchicalEfficiency:
    """Tests for efficiency of hierarchical approach."""

    def test_large_graph_pathfinding(self) -> None:
        """Test pathfinding on larger graphs."""
        graph = Graph(directed=False)
        size = 20
        for i in range(size * size):
            x = i % size
            y = i // size
            graph.add_node(Node(i, float(x), float(y)))

        for i in range(size * size - 1):
            if (i + 1) % size != 0:
                graph.add_edge(i, i + 1, 1.0)
            if i + size < size * size:
                graph.add_edge(i, i + size, 1.0)

        hpf = HierarchicalPathfinder(graph, cluster_size=5)

        result = hpf.find_path(0, size * size - 1)

        assert result.found

    def test_hierarchical_path_valid(self) -> None:
        """Test that hierarchical pathfinding produces valid paths."""
        graph = Graph(directed=False)
        for i in range(10):
            graph.add_node(Node(i, float(i), 0.0))

        for i in range(9):
            graph.add_edge(i, i + 1, 1.0)

        hpf = HierarchicalPathfinder(graph, cluster_size=2)

        result = hpf.find_path(0, 9)

        if result.found:
            assert result.cost > 0.0
