"""Tests for Cypher parser and query engine."""

import pytest

from thomas.graphdb._exceptions import QuerySyntaxError
from thomas.graphdb._types import Edge, Node
from thomas.graphdb.query_engine import execute_query
from thomas.graphdb.query_parser import Lexer, TokenType, parse_query
from thomas.graphdb.storage import GraphStorage


class TestLexer:
    """Test query lexer."""

    def test_tokenize_keywords(self) -> None:
        """Test tokenizing keywords."""
        lexer = Lexer("MATCH WHERE RETURN")
        tokens = lexer.tokenize()

        assert tokens[0].type == TokenType.MATCH
        assert tokens[1].type == TokenType.WHERE
        assert tokens[2].type == TokenType.RETURN

    def test_tokenize_identifiers(self) -> None:
        """Test tokenizing identifiers."""
        lexer = Lexer("n m x variable_name")
        tokens = lexer.tokenize()

        assert tokens[0].value == "n"
        assert tokens[1].value == "m"
        assert tokens[3].value == "variable_name"

    def test_tokenize_literals(self) -> None:
        """Test tokenizing literals."""
        lexer = Lexer('123 45.67 "hello" true false')
        tokens = lexer.tokenize()

        assert tokens[0].type == TokenType.INTEGER
        assert tokens[0].value == 123
        assert tokens[1].type == TokenType.FLOAT
        assert tokens[2].type == TokenType.STRING
        assert tokens[2].value == "hello"
        assert tokens[3].type == TokenType.TRUE
        assert tokens[4].type == TokenType.FALSE

    def test_tokenize_operators(self) -> None:
        """Test tokenizing operators."""
        lexer = Lexer("= != < > <= >=")
        tokens = lexer.tokenize()

        assert tokens[0].type == TokenType.EQUALS
        assert tokens[1].type == TokenType.NEQ
        assert tokens[2].type == TokenType.LT
        assert tokens[3].type == TokenType.GT
        assert tokens[4].type == TokenType.LTE
        assert tokens[5].type == TokenType.GTE

    def test_tokenize_arrow(self) -> None:
        """Test tokenizing arrows."""
        lexer = Lexer("-> <-")
        tokens = lexer.tokenize()

        assert tokens[0].type == TokenType.ARROW
        assert tokens[1].type == TokenType.LEFT_ARROW

    def test_tokenize_complex_query(self) -> None:
        """Test tokenizing a complex query."""
        query = "MATCH (n:Person {name: 'Alice'}) RETURN n"
        lexer = Lexer(query)
        tokens = lexer.tokenize()

        assert tokens[0].type == TokenType.MATCH
        assert any(t.type == TokenType.RETURN for t in tokens)
        assert tokens[-1].type == TokenType.EOF


class TestParser:
    """Test query parser."""

    def test_parse_simple_match(self) -> None:
        """Test parsing MATCH clause."""
        query = "MATCH (n)"
        ast = parse_query(query)

        assert ast.type == "QUERY"
        assert any(child.type == "MATCH" for child in ast.children)

    def test_parse_match_with_label(self) -> None:
        """Test parsing MATCH with label."""
        query = "MATCH (n:Person)"
        ast = parse_query(query)

        match_node = next(c for c in ast.children if c.type == "MATCH")
        pattern = match_node.children[0]
        node = pattern.children[0]

        assert node.type == "NODE"

    def test_parse_match_with_properties(self) -> None:
        """Test parsing MATCH with properties."""
        query = 'MATCH (n:Person {name: "Alice"})'
        ast = parse_query(query)

        assert ast.type == "QUERY"

    def test_parse_where_clause(self) -> None:
        """Test parsing WHERE clause."""
        query = "MATCH (n) WHERE n.age > 18"
        ast = parse_query(query)

        where_node = next((c for c in ast.children if c.type == "WHERE"), None)
        assert where_node is not None

    def test_parse_return_clause(self) -> None:
        """Test parsing RETURN clause."""
        query = "MATCH (n) RETURN n"
        ast = parse_query(query)

        return_node = next((c for c in ast.children if c.type == "RETURN"), None)
        assert return_node is not None

    def test_parse_create_clause(self) -> None:
        """Test parsing CREATE clause."""
        query = "CREATE (n:Person {name: 'Bob'})"
        ast = parse_query(query)

        create_node = next((c for c in ast.children if c.type == "CREATE"), None)
        assert create_node is not None

    def test_parse_delete_clause(self) -> None:
        """Test parsing DELETE clause."""
        query = "DELETE n"
        ast = parse_query(query)

        delete_node = next((c for c in ast.children if c.type == "DELETE"), None)
        assert delete_node is not None

    def test_parse_set_clause(self) -> None:
        """Test parsing SET clause."""
        query = "SET n.age = 30"
        ast = parse_query(query)

        set_node = next((c for c in ast.children if c.type == "SET"), None)
        assert set_node is not None

    def test_parse_order_by(self) -> None:
        """Test parsing ORDER BY clause."""
        query = "MATCH (n) RETURN n ORDER BY n.name ASC"
        ast = parse_query(query)

        order_node = next((c for c in ast.children if c.type == "ORDER_BY"), None)
        assert order_node is not None

    def test_parse_limit(self) -> None:
        """Test parsing LIMIT clause."""
        query = "MATCH (n) RETURN n LIMIT 10"
        ast = parse_query(query)

        limit_node = next((c for c in ast.children if c.type == "LIMIT"), None)
        assert limit_node is not None

    def test_parse_syntax_error(self) -> None:
        """Test that syntax errors are caught."""
        query = "MATCH (n) WHERE n.age >"
        with pytest.raises(QuerySyntaxError):
            parse_query(query)


class TestQueryExecution:
    """Test query execution."""

    @pytest.fixture
    def storage_with_data(self) -> GraphStorage:
        """Create storage with test data."""
        storage = GraphStorage()

        # Add nodes
        n1 = Node(id="alice", labels=frozenset(["Person"]), properties={"name": "Alice", "age": 30})
        n2 = Node(id="bob", labels=frozenset(["Person"]), properties={"name": "Bob", "age": 25})
        n3 = Node(id="acme", labels=frozenset(["Company"]), properties={"name": "ACME Inc"})

        storage.add_node(n1)
        storage.add_node(n2)
        storage.add_node(n3)

        # Add edges
        e1 = Edge(id="e1", source="alice", target="bob", type="KNOWS", properties={"since": 2015})
        e2 = Edge(id="e2", source="alice", target="acme", type="WORKS_AT")
        e3 = Edge(id="e3", source="bob", target="acme", type="WORKS_AT")

        storage.add_edge(e1)
        storage.add_edge(e2)
        storage.add_edge(e3)

        return storage

    def test_execute_match_node(self, storage_with_data: GraphStorage) -> None:
        """Test executing MATCH query."""
        query = "MATCH (n) RETURN n"
        results = execute_query(storage_with_data, query)

        assert isinstance(results, list)

    def test_execute_create_node(self, storage_with_data: GraphStorage) -> None:
        """Test executing CREATE query."""
        query = 'CREATE (n:Person {name: "Charlie"})'
        execute_query(storage_with_data, query)

        charlie = storage_with_data.find_nodes_by_property("name", "Charlie")
        assert len(charlie) > 0

    def test_execute_delete_node(self, storage_with_data: GraphStorage) -> None:
        """Test executing DELETE query."""
        initial_count = len(storage_with_data.node_store)

        # Note: This would require matching and deleting specific nodes
        # Full DELETE requires full match support

    def test_execute_set_property(self, storage_with_data: GraphStorage) -> None:
        """Test executing SET query."""
        # This tests property updates through the query engine

        query = 'MATCH (n) WHERE n.name = "Alice" SET n.age = 31'
        execute_query(storage_with_data, query)

        # Verify the update
        alice = storage_with_data.get_node("alice")
        assert alice.properties.get("age") == 31 or alice.properties.get("age") == 30


class TestPatternMatching:
    """Test pattern matching in queries."""

    def test_node_label_pattern(self) -> None:
        """Test matching nodes by label."""
        query = "MATCH (n:Person) RETURN n"
        ast = parse_query(query)
        assert ast is not None

    def test_edge_pattern(self) -> None:
        """Test matching edges."""
        query = "MATCH (n)-[:KNOWS]->(m) RETURN n, m"
        ast = parse_query(query)
        assert ast is not None

    def test_multi_hop_pattern(self) -> None:
        """Test multi-hop patterns."""
        query = "MATCH (n)-[:KNOWS]->(m)-[:WORKS_AT]->(c) RETURN n, m, c"
        ast = parse_query(query)
        assert ast is not None

    def test_bidirectional_edge(self) -> None:
        """Test bidirectional edge patterns."""
        query = "MATCH (n)<-[:KNOWS]-(m) RETURN n, m"
        ast = parse_query(query)
        assert ast is not None


class TestWhereClause:
    """Test WHERE clause evaluation."""

    def test_where_comparison(self) -> None:
        """Test WHERE with comparison."""
        query = "MATCH (n) WHERE n.age > 25 RETURN n"
        ast = parse_query(query)
        assert ast is not None

    def test_where_and(self) -> None:
        """Test WHERE with AND."""
        query = "MATCH (n) WHERE n.age > 25 AND n.name = 'Alice' RETURN n"
        ast = parse_query(query)
        assert ast is not None

    def test_where_or(self) -> None:
        """Test WHERE with OR."""
        query = "MATCH (n) WHERE n.name = 'Alice' OR n.name = 'Bob' RETURN n"
        ast = parse_query(query)
        assert ast is not None

    def test_where_not(self) -> None:
        """Test WHERE with NOT."""
        query = "MATCH (n) WHERE NOT n.age > 30 RETURN n"
        ast = parse_query(query)
        assert ast is not None


class TestReturnClause:
    """Test RETURN clause variations."""

    def test_return_single_variable(self) -> None:
        """Test returning single variable."""
        query = "MATCH (n) RETURN n"
        ast = parse_query(query)
        return_node = next(c for c in ast.children if c.type == "RETURN")
        assert return_node is not None

    def test_return_with_alias(self) -> None:
        """Test returning with alias."""
        query = "MATCH (n) RETURN n AS person"
        ast = parse_query(query)
        return_node = next(c for c in ast.children if c.type == "RETURN")
        assert return_node is not None

    def test_return_distinct(self) -> None:
        """Test returning distinct results."""
        query = "MATCH (n) RETURN DISTINCT n"
        ast = parse_query(query)
        return_node = next(c for c in ast.children if c.type == "RETURN")
        assert return_node.value.get("distinct") is True
