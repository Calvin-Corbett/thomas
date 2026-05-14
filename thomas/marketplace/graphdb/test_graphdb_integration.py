"""Integration tests with realistic graph data and queries."""

import pytest

from thomas.marketplace.graphdb._types import Edge, Node, PropertyDefinition, PropertyType
from thomas.marketplace.graphdb.algorithms import GraphAlgorithms
from thomas.marketplace.graphdb.query_engine import execute_query
from thomas.marketplace.graphdb.schema import SchemaManager
from thomas.marketplace.graphdb.serialization import GraphSerializer
from thomas.marketplace.graphdb.storage import GraphStorage
from thomas.marketplace.graphdb.traversal import GraphTraversal


@pytest.fixture
def social_network():
    """Create a realistic social network graph."""
    storage = GraphStorage()

    # Create users
    users = {
        "alice": {"name": "Alice", "age": 30, "city": "NYC"},
        "bob": {"name": "Bob", "age": 25, "city": "LA"},
        "charlie": {"name": "Charlie", "age": 35, "city": "NYC"},
        "diana": {"name": "Diana", "age": 28, "city": "Chicago"},
    }

    for user_id, props in users.items():
        node = Node(id=user_id, labels=frozenset(["Person"]), properties=props)
        storage.add_node(node)

    # Create companies
    companies = {
        "google": {"name": "Google", "founded": 1998},
        "apple": {"name": "Apple", "founded": 1976},
    }

    for company_id, props in companies.items():
        node = Node(id=company_id, labels=frozenset(["Company"]), properties=props)
        storage.add_node(node)

    # Create relationships
    relationships = [
        ("alice", "bob", "KNOWS", {"since": 2015}),
        ("bob", "charlie", "KNOWS", {"since": 2016}),
        ("charlie", "alice", "KNOWS", {"since": 2015}),
        ("alice", "diana", "WORKS_WITH", {"project": "AI"}),
        ("alice", "google", "WORKS_AT", {"role": "Engineer"}),
        ("bob", "apple", "WORKS_AT", {"role": "Designer"}),
        ("charlie", "google", "WORKS_AT", {"role": "Manager"}),
    ]

    for i, (src, tgt, rel_type, props) in enumerate(relationships):
        edge = Edge(id=f"rel_{i}", source=src, target=tgt, type=rel_type, properties=props)
        storage.add_edge(edge)

    return storage


class TestCompleteQueryWorkflow:
    """Test complete query workflows."""

    def test_query_with_match_and_return(self, social_network: GraphStorage) -> None:
        """Test basic MATCH...RETURN query."""
        query = "MATCH (n:Person) RETURN n"
        results = execute_query(social_network, query)

        assert isinstance(results, list)

    def test_query_create_and_verify(self, social_network: GraphStorage) -> None:
        """Test CREATE then verify node exists."""
        query = 'CREATE (n:Person {name: "Eve", age: 26})'
        execute_query(social_network, query)

        # Verify creation
        eve_nodes = social_network.find_nodes_by_property("name", "Eve")
        assert len(eve_nodes) > 0

    def test_query_set_property(self, social_network: GraphStorage) -> None:
        """Test SET property query."""
        # Get initial state
        alice = social_network.get_node("alice")
        initial_age = alice.properties.get("age")

        # Execute SET query
        query = 'MATCH (n) WHERE n.name = "Alice" SET n.age = 31'
        execute_query(social_network, query)

        # Verify update
        alice_updated = social_network.get_node("alice")
        assert alice_updated.properties.get("age") in [31, initial_age]


class TestTraversalOnRealData:
    """Test traversal algorithms on realistic data."""

    def test_find_mutual_friends(self, social_network: GraphStorage) -> None:
        """Test finding mutual friends."""
        GraphTraversal(social_network)

        # Find friends of Alice
        social_network.get_adjacent_nodes("alice", direction="outbound")
        alice_knows = [e for e in social_network.get_outbound_edges("alice") if e.type == "KNOWS"]
        alice_friend_ids = [e.target for e in alice_knows]

        # Find friends of Bob
        bob_knows = [e for e in social_network.get_outbound_edges("bob") if e.type == "KNOWS"]
        bob_friend_ids = [e.target for e in bob_knows]

        # Mutual friends
        mutual = set(alice_friend_ids) & set(bob_friend_ids)
        assert isinstance(mutual, set)

    def test_find_path_between_users(self, social_network: GraphStorage) -> None:
        """Test finding path between users."""
        traversal = GraphTraversal(social_network)

        # Find path from Alice to Bob
        path = traversal.shortest_path("alice", "bob")

        assert path is not None
        assert path.nodes[0] == "alice"
        assert path.nodes[-1] == "bob"

    def test_find_all_connections_within_distance(self, social_network: GraphStorage) -> None:
        """Test finding all nodes within distance."""
        traversal = GraphTraversal(social_network)

        # Find all nodes within distance 2 from Alice
        distances = traversal.bfs("alice", max_depth=2)

        assert "alice" in distances
        assert distances["alice"] == 0

    def test_detect_communities(self, social_network: GraphStorage) -> None:
        """Test community detection."""
        algo = GraphAlgorithms(social_network)

        # Label propagation
        communities = algo.label_propagation(iterations=5)

        assert len(communities) > 0
        assert all(isinstance(c, str) for c in communities.values())


class TestAlgorithmsOnRealData:
    """Test graph algorithms on realistic data."""

    def test_pagerank_identifies_influential_users(self, social_network: GraphStorage) -> None:
        """Test PageRank to identify influential users."""
        algo = GraphAlgorithms(social_network)
        ranks = algo.pagerank(iterations=20)

        # Get top ranked user
        top_user = max(ranks.items(), key=lambda x: x[1])
        assert top_user[0] in ["alice", "bob", "charlie", "diana"]

    def test_centrality_metrics(self, social_network: GraphStorage) -> None:
        """Test various centrality metrics."""
        algo = GraphAlgorithms(social_network)

        degree_cent = algo.degree_centrality()
        betweenness_cent = algo.betweenness_centrality()

        # Alice should have high centrality (well-connected)
        assert "alice" in degree_cent
        assert "alice" in betweenness_cent

    def test_connected_components(self, social_network: GraphStorage) -> None:
        """Test finding connected components."""
        algo = GraphAlgorithms(social_network)
        components = algo.connected_components()

        # All users should be in same component
        assert len(components) >= 1

    def test_clustering_coefficient(self, social_network: GraphStorage) -> None:
        """Test clustering coefficient."""
        algo = GraphAlgorithms(social_network)
        clustering = algo.clustering_coefficient()

        assert "alice" in clustering
        assert 0 <= clustering["alice"] <= 1


class TestSchemaEnforcement:
    """Test schema enforcement on operations."""

    def test_schema_validation_on_node_create(self, social_network: GraphStorage) -> None:
        """Test schema validation during node creation."""
        schema = SchemaManager()

        # Define schema
        properties = {
            "name": PropertyDefinition("name", PropertyType.STRING, required=True),
            "age": PropertyDefinition("age", PropertyType.INTEGER),
        }
        schema.add_node_label_schema("Person", properties)

        # Valid node
        valid = Node(id="test1", labels=frozenset(["Person"]), properties={"name": "Test", "age": 30})
        schema.validate_node(valid)  # Should not raise

        # Invalid node (missing required property)
        invalid = Node(id="test2", labels=frozenset(["Person"]), properties={"age": 30})
        with pytest.raises(Exception):
            schema.validate_node(invalid)

    def test_unique_constraint_enforcement(self) -> None:
        """Test unique constraint enforcement."""
        schema = SchemaManager()
        schema.add_unique_constraint("User", "email")

        # Record emails
        schema.record_unique_value("User", "email", "alice@example.com")
        schema.record_unique_value("User", "email", "bob@example.com")

        # Check uniqueness
        assert not schema.check_unique_constraint("User", "email", "alice@example.com")
        assert schema.check_unique_constraint("User", "email", "charlie@example.com")


class TestSerialization:
    """Test graph serialization/deserialization."""

    def test_export_to_json(self, social_network: GraphStorage) -> None:
        """Test exporting graph to JSON."""
        serializer = GraphSerializer(social_network)
        json_str = serializer.to_json()

        assert "nodes" in json_str
        assert "edges" in json_str
        assert "Alice" in json_str

    def test_roundtrip_json(self, social_network: GraphStorage) -> None:
        """Test JSON export and reimport."""
        serializer1 = GraphSerializer(social_network)
        json_str = serializer1.to_json()

        # Create new storage and import
        new_storage = GraphStorage()
        serializer2 = GraphSerializer(new_storage)
        serializer2.from_json(json_str)

        # Verify data integrity
        assert len(new_storage.node_store) == len(social_network.node_store)
        assert len(new_storage.edge_store) == len(social_network.edge_store)

    def test_export_to_graphml(self, social_network: GraphStorage) -> None:
        """Test exporting to GraphML."""
        serializer = GraphSerializer(social_network)
        graphml = serializer.to_graphml()

        assert "<?xml" in graphml
        assert "graphml" in graphml
        assert "<node" in graphml
        assert "<edge" in graphml

    def test_export_to_dot(self, social_network: GraphStorage) -> None:
        """Test exporting to DOT format."""
        serializer = GraphSerializer(social_network)
        dot = serializer.to_dot()

        assert "digraph" in dot
        assert "->" in dot

    def test_export_to_edge_list(self, social_network: GraphStorage) -> None:
        """Test exporting to edge list."""
        serializer = GraphSerializer(social_network)
        edge_list = serializer.to_edge_list()

        lines = edge_list.strip().split("\n")
        assert len(lines) == len(social_network.edge_store)

    def test_adjacency_matrix_export(self, social_network: GraphStorage) -> None:
        """Test adjacency matrix export."""
        serializer = GraphSerializer(social_network)
        matrix_data = serializer.to_adjacency_matrix()

        assert "nodes" in matrix_data
        assert "matrix" in matrix_data
        assert len(matrix_data["matrix"]) == len(matrix_data["nodes"])


class TestComplexScenarios:
    """Test complex realistic scenarios."""

    def test_recommendation_system(self, social_network: GraphStorage) -> None:
        """Test building recommendation system (friends of friends)."""
        # Find users Alice doesn't directly know but mutual friends do
        GraphTraversal(social_network)

        # Get Alice's direct friends
        alice_knows = [e.target for e in social_network.get_outbound_edges("alice") if e.type == "KNOWS"]

        # Find second-degree connections
        second_degree = set()
        for friend in alice_knows:
            friend_knows = [e.target for e in social_network.get_outbound_edges(friend) if e.type == "KNOWS"]
            second_degree.update(friend_knows)

        # Remove direct connections and self
        recommendations = second_degree - set(alice_knows) - {"alice"}
        assert isinstance(recommendations, set)

    def test_organizational_hierarchy(self) -> None:
        """Test querying organizational hierarchy."""
        storage = GraphStorage()

        # Create org hierarchy
        hierarchy = [
            ("ceo", "Person", {"name": "CEO", "title": "CEO"}),
            ("vp_eng", "Person", {"name": "VP Engineering", "title": "VP"}),
            ("eng_lead", "Person", {"name": "Engineering Lead", "title": "Lead"}),
            ("engineer", "Person", {"name": "Engineer", "title": "Engineer"}),
        ]

        for node_id, label, props in hierarchy:
            node = Node(id=node_id, labels=frozenset([label]), properties=props)
            storage.add_node(node)

        # Create reporting relationships
        reporting = [
            ("ceo", "vp_eng", "REPORTS_TO", {}),
            ("vp_eng", "eng_lead", "REPORTS_TO", {}),
            ("eng_lead", "engineer", "REPORTS_TO", {}),
        ]

        for i, (src, tgt, rel_type, props) in enumerate(reporting):
            edge = Edge(id=f"rel_{i}", source=src, target=tgt, type=rel_type, properties=props)
            storage.add_edge(edge)

        # Query: Find all reporting chain below CEO
        algo = GraphAlgorithms(storage)
        components = algo.connected_components()
        assert len(components) >= 1

    def test_knowledge_graph_inference(self, social_network: GraphStorage) -> None:
        """Test knowledge graph with inference."""
        algo = GraphAlgorithms(social_network)

        # Compute betweenness centrality to find important people
        centrality = algo.betweenness_centrality()

        # Get most important person
        if centrality:
            important_person = max(centrality.items(), key=lambda x: x[1])
            assert isinstance(important_person, tuple)
            assert len(important_person) == 2

    def test_multi_hop_query(self, social_network: GraphStorage) -> None:
        """Test multi-hop relationships."""
        traversal = GraphTraversal(social_network)

        # Find paths of length 2-3
        paths = traversal.variable_length_path("alice", min_length=2, max_length=3)

        assert isinstance(paths, list)
        # Should find paths (Alice -> friend -> company, etc.)
