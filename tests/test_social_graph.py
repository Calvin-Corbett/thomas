"""Tests for social graph algorithms."""

from uuid import uuid4

from thomas.social_platform import SocialGraphAnalyzer


class TestSocialGraphAnalyzer:
    """Test suite for SocialGraphAnalyzer."""

    def setup_method(self) -> None:
        """Setup test fixtures."""
        self.analyzer = SocialGraphAnalyzer()
        self.user1 = uuid4()
        self.user2 = uuid4()
        self.user3 = uuid4()
        self.user4 = uuid4()
        self.user5 = uuid4()

    def test_add_edge(self) -> None:
        """Test adding edge to graph."""
        self.analyzer.add_edge(self.user1, self.user2)

        assert self.user2 in self.analyzer.graph[self.user1]

    def test_remove_edge(self) -> None:
        """Test removing edge from graph."""
        self.analyzer.add_edge(self.user1, self.user2)
        self.analyzer.remove_edge(self.user1, self.user2)

        assert self.user2 not in self.analyzer.graph[self.user1]

    def test_friends_of_friends(self) -> None:
        """Test friends-of-friends recommendations."""
        # user1 -> user2 -> user3
        self.analyzer.add_edge(self.user1, self.user2)
        self.analyzer.add_edge(self.user2, self.user3)
        self.analyzer.add_edge(self.user2, self.user4)

        recommendations = self.analyzer.get_friends_of_friends(self.user1)

        rec_ids = [uid for uid, _ in recommendations]
        assert self.user3 in rec_ids
        assert self.user4 in rec_ids

    def test_community_detection(self) -> None:
        """Test community detection using label propagation."""
        # Create two clusters
        # Cluster 1: user1-user2-user3
        self.analyzer.add_edge(self.user1, self.user2)
        self.analyzer.add_edge(self.user2, self.user3)
        self.analyzer.add_edge(self.user3, self.user1)

        # Cluster 2: user4-user5
        self.analyzer.add_edge(self.user4, self.user5)
        self.analyzer.add_edge(self.user5, self.user4)

        communities = self.analyzer.detect_communities()

        assert self.user1 in communities
        assert self.user4 in communities
        # Users in same cluster should have same label
        assert communities[self.user1] == communities[self.user2]

    def test_influence_scores(self) -> None:
        """Test PageRank-based influence scoring."""
        # Create star graph (user1 is hub)
        self.analyzer.add_edge(self.user1, self.user2)
        self.analyzer.add_edge(self.user1, self.user3)
        self.analyzer.add_edge(self.user1, self.user4)
        self.analyzer.add_edge(self.user2, self.user3)

        scores = self.analyzer.calculate_influence_scores()

        assert self.user1 in scores
        # Hub should have high influence
        assert scores[self.user1] > 0

    def test_shortest_path(self) -> None:
        """Test finding shortest path between users."""
        # Create chain: user1-user2-user3-user4
        self.analyzer.add_edge(self.user1, self.user2)
        self.analyzer.add_edge(self.user2, self.user3)
        self.analyzer.add_edge(self.user3, self.user4)

        path = self.analyzer.find_shortest_path(self.user1, self.user4)

        assert path is not None
        assert len(path) == 4
        assert path[0] == self.user1
        assert path[-1] == self.user4

    def test_shortest_path_not_found(self) -> None:
        """Test shortest path when no path exists."""
        self.analyzer.add_edge(self.user1, self.user2)
        self.analyzer.add_edge(self.user3, self.user4)

        path = self.analyzer.find_shortest_path(self.user1, self.user3)

        assert path is None

    def test_shortest_path_same_node(self) -> None:
        """Test shortest path to self."""
        path = self.analyzer.find_shortest_path(self.user1, self.user1)

        assert path == [self.user1]

    def test_clustering_coefficient(self) -> None:
        """Test clustering coefficient calculation."""
        # Triangle: user1-user2-user3
        self.analyzer.add_edge(self.user1, self.user2)
        self.analyzer.add_edge(self.user2, self.user3)
        self.analyzer.add_edge(self.user3, self.user1)

        coeff = self.analyzer.calculate_clustering_coefficient(self.user1)

        assert coeff > 0

    def test_clustering_coefficient_no_neighbors(self) -> None:
        """Test clustering coefficient for isolated node."""
        coeff = self.analyzer.calculate_clustering_coefficient(self.user1)

        assert coeff == 0

    def test_degree_distribution(self) -> None:
        """Test degree distribution."""
        # Star graph
        self.analyzer.add_edge(self.user1, self.user2)
        self.analyzer.add_edge(self.user1, self.user3)
        self.analyzer.add_edge(self.user2, self.user3)

        distribution = self.analyzer.get_degree_distribution()

        assert len(distribution) > 0

    def test_classify_ties_strong(self) -> None:
        """Test classifying strong ties."""
        # user1 and user2 share many mutual connections
        for user in [self.user3, self.user4, self.user5]:
            self.analyzer.add_edge(self.user1, user)
            self.analyzer.add_edge(self.user2, user)

        self.analyzer.add_edge(self.user1, self.user2)

        tie_type = self.analyzer.classify_ties(self.user1, self.user2)

        assert tie_type == "strong"

    def test_classify_ties_weak(self) -> None:
        """Test classifying weak ties."""
        # user1 and user2 few mutual connections
        self.analyzer.add_edge(self.user1, self.user2)

        tie_type = self.analyzer.classify_ties(self.user1, self.user2)

        assert tie_type == "weak"

    def test_bridge_nodes(self) -> None:
        """Test finding bridge nodes."""
        # Create two clusters connected by user3
        # Cluster 1: user1-user2
        self.analyzer.add_edge(self.user1, self.user2)
        self.analyzer.add_edge(self.user2, self.user1)

        # Bridge: user3 connects clusters
        self.analyzer.add_edge(self.user2, self.user3)
        self.analyzer.add_edge(self.user3, self.user2)

        # Cluster 2: user4-user5
        self.analyzer.add_edge(self.user3, self.user4)
        self.analyzer.add_edge(self.user4, self.user5)
        self.analyzer.add_edge(self.user5, self.user4)

        bridges = self.analyzer.get_bridge_nodes()

        # Should identify bridges
        assert len(bridges) > 0

    def test_graph_density(self) -> None:
        """Test graph density calculation."""
        # Create complete graph (triangle)
        self.analyzer.add_edge(self.user1, self.user2)
        self.analyzer.add_edge(self.user1, self.user3)
        self.analyzer.add_edge(self.user2, self.user3)

        density = self.analyzer.get_graph_density()

        assert 0 <= density <= 1

    def test_avg_clustering_coefficient(self) -> None:
        """Test average clustering coefficient."""
        # Create mixed graph
        self.analyzer.add_edge(self.user1, self.user2)
        self.analyzer.add_edge(self.user2, self.user3)
        self.analyzer.add_edge(self.user3, self.user1)

        avg_coeff = self.analyzer.get_avg_clustering_coefficient()

        assert 0 <= avg_coeff <= 1

    def test_ego_network(self) -> None:
        """Test ego network extraction."""
        # Create network around user1
        self.analyzer.add_edge(self.user1, self.user2)
        self.analyzer.add_edge(self.user2, self.user3)
        self.analyzer.add_edge(self.user1, self.user4)

        ego = self.analyzer.find_ego_network(self.user1, depth=1)

        assert self.user1 in ego
        assert self.user2 in ego
        assert self.user4 in ego
        assert self.user3 not in ego  # Distance 2

    def test_ego_network_depth_2(self) -> None:
        """Test ego network with depth 2."""
        self.analyzer.add_edge(self.user1, self.user2)
        self.analyzer.add_edge(self.user2, self.user3)
        self.analyzer.add_edge(self.user3, self.user4)

        ego = self.analyzer.find_ego_network(self.user1, depth=2)

        assert self.user1 in ego
        assert self.user2 in ego
        assert self.user3 in ego
        assert self.user4 not in ego  # Distance 3

    def test_assortativity(self) -> None:
        """Test assortativity calculation."""
        # Create graph with some structure
        self.analyzer.add_edge(self.user1, self.user2)
        self.analyzer.add_edge(self.user2, self.user3)
        self.analyzer.add_edge(self.user3, self.user4)

        assortativity = self.analyzer.calculate_assortativity()

        assert -1 <= assortativity <= 1

    def test_graph_metrics(self) -> None:
        """Test overall graph metrics."""
        self.analyzer.add_edge(self.user1, self.user2)
        self.analyzer.add_edge(self.user2, self.user3)
        self.analyzer.add_edge(self.user3, self.user1)

        metrics = self.analyzer.get_graph_metrics()

        assert "node_count" in metrics
        assert "edge_count" in metrics
        assert "density" in metrics
        assert "avg_clustering_coefficient" in metrics
        assert "assortativity" in metrics
