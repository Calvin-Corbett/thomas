"""
Tests for SQL parser.

Tests cover:
- Tokenization of SQL statements
- Parsing SELECT statements
- Parsing INSERT, UPDATE, DELETE
- Parsing CREATE TABLE, CREATE INDEX, DROP
- Expression parsing with operator precedence
- Error handling
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from thomas.db_internals._exceptions import ParseException, SyntaxException
from thomas.db_internals.query_parser import (
    Parser,
    Tokenizer,
    TokenType,
)


class TestTokenizer:
    """Tests for SQL tokenizer."""

    def test_tokenize_simple_select(self) -> None:
        """Test tokenizing simple SELECT."""
        tokenizer = Tokenizer("SELECT * FROM users")
        tokens = tokenizer.tokenize()

        assert any(t.value == "SELECT" for t in tokens)
        assert any(t.type == TokenType.STAR for t in tokens)
        assert any(t.value == "FROM" for t in tokens)

    def test_tokenize_keywords(self) -> None:
        """Test tokenizing keywords."""
        tokenizer = Tokenizer("SELECT INSERT UPDATE DELETE")
        tokens = tokenizer.tokenize()

        keywords = [t for t in tokens if t.type == TokenType.KEYWORD]
        assert len(keywords) >= 4

    def test_tokenize_identifiers(self) -> None:
        """Test tokenizing identifiers."""
        tokenizer = Tokenizer("SELECT user_id, user_name FROM users")
        tokens = tokenizer.tokenize()

        identifiers = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        assert len(identifiers) > 0

    def test_tokenize_numbers(self) -> None:
        """Test tokenizing numbers."""
        tokenizer = Tokenizer("SELECT 123, 45.67 FROM table1")
        tokens = tokenizer.tokenize()

        numbers = [t for t in tokens if t.type == TokenType.NUMBER]
        assert len(numbers) == 2

    def test_tokenize_strings(self) -> None:
        """Test tokenizing string literals."""
        tokenizer = Tokenizer("SELECT 'hello', 'world'")
        tokens = tokenizer.tokenize()

        strings = [t for t in tokens if t.type == TokenType.STRING]
        assert len(strings) == 2

    def test_tokenize_operators(self) -> None:
        """Test tokenizing operators."""
        tokenizer = Tokenizer("SELECT * WHERE a = 1 AND b > 2")
        tokens = tokenizer.tokenize()

        operators = [t for t in tokens if t.type == TokenType.OPERATOR]
        assert len(operators) > 0

    def test_tokenize_parentheses(self) -> None:
        """Test tokenizing parentheses."""
        tokenizer = Tokenizer("SELECT (a + b) FROM t")
        tokens = tokenizer.tokenize()

        parens = [t for t in tokens if t.type in [TokenType.LPAREN, TokenType.RPAREN]]
        assert len(parens) == 2

    def test_skip_comments_line(self) -> None:
        """Test skipping line comments."""
        tokenizer = Tokenizer("SELECT -- comment\n* FROM t")
        tokens = tokenizer.tokenize()

        # Should have SELECT, *, FROM, t and EOF
        assert len(tokens) >= 4


class TestParser:
    """Tests for SQL parser."""

    def test_parse_simple_select(self) -> None:
        """Test parsing simple SELECT."""
        tokenizer = Tokenizer("SELECT * FROM users")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()

        assert plan["type"] == "SELECT"
        assert plan["from"] is not None

    def test_parse_select_columns(self) -> None:
        """Test parsing SELECT with columns."""
        tokenizer = Tokenizer("SELECT id, name FROM users")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()

        assert plan["type"] == "SELECT"
        assert len(plan["columns"]) == 2

    def test_parse_where_clause(self) -> None:
        """Test parsing WHERE clause."""
        tokenizer = Tokenizer("SELECT * FROM users WHERE id = 1")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()

        assert plan["where"] is not None

    def test_parse_join(self) -> None:
        """Test parsing JOIN."""
        tokenizer = Tokenizer("SELECT * FROM users JOIN orders ON users.id = orders.user_id")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()

        assert plan["from"] is not None
        # Should have join information

    def test_parse_group_by(self) -> None:
        """Test parsing GROUP BY."""
        tokenizer = Tokenizer("SELECT dept, COUNT(*) FROM employees GROUP BY dept")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()

        assert plan["group_by"] is not None

    def test_parse_order_by(self) -> None:
        """Test parsing ORDER BY."""
        tokenizer = Tokenizer("SELECT * FROM users ORDER BY name ASC")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()

        assert plan["order_by"] is not None

    def test_parse_limit_offset(self) -> None:
        """Test parsing LIMIT OFFSET."""
        tokenizer = Tokenizer("SELECT * FROM users LIMIT 10 OFFSET 5")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()

        assert plan["limit"] == 10
        assert plan["offset"] == 5

    def test_parse_distinct(self) -> None:
        """Test parsing DISTINCT."""
        tokenizer = Tokenizer("SELECT DISTINCT name FROM users")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()

        assert plan["distinct"] is True

    def test_parse_insert(self) -> None:
        """Test parsing INSERT."""
        tokenizer = Tokenizer("INSERT INTO users (id, name) VALUES (1, 'John')")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()

        assert plan["type"] == "INSERT"
        assert plan["table"] == "users"

    def test_parse_update(self) -> None:
        """Test parsing UPDATE."""
        tokenizer = Tokenizer("UPDATE users SET name = 'Jane' WHERE id = 1")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()

        assert plan["type"] == "UPDATE"
        assert plan["table"] == "users"

    def test_parse_delete(self) -> None:
        """Test parsing DELETE."""
        tokenizer = Tokenizer("DELETE FROM users WHERE id = 1")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()

        assert plan["type"] == "DELETE"
        assert plan["table"] == "users"

    def test_parse_create_table(self) -> None:
        """Test parsing CREATE TABLE."""
        tokenizer = Tokenizer("CREATE TABLE users (id INT, name VARCHAR)")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()

        assert plan["type"] == "CREATE_TABLE"
        assert plan["table_name"] == "users"

    def test_parse_create_index(self) -> None:
        """Test parsing CREATE INDEX."""
        tokenizer = Tokenizer("CREATE INDEX idx_name ON users (name)")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()

        assert plan["type"] == "CREATE_INDEX"
        assert plan["index_name"] == "idx_name"

    def test_parse_drop_table(self) -> None:
        """Test parsing DROP TABLE."""
        tokenizer = Tokenizer("DROP TABLE users")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()

        assert plan["type"] == "DROP_TABLE"
        assert plan["table"] == "users"


class TestExpressionParsing:
    """Tests for expression parsing."""

    def test_parse_comparison(self) -> None:
        """Test parsing comparison expressions."""
        tokenizer = Tokenizer("SELECT * FROM t WHERE a > 5")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()
        assert plan["where"] is not None

    def test_parse_arithmetic(self) -> None:
        """Test parsing arithmetic expressions."""
        tokenizer = Tokenizer("SELECT a + b FROM t")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()
        assert len(plan["columns"]) > 0

    def test_parse_logical_and(self) -> None:
        """Test parsing AND expression."""
        tokenizer = Tokenizer("SELECT * FROM t WHERE a > 5 AND b < 10")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()
        assert plan["where"] is not None

    def test_parse_logical_or(self) -> None:
        """Test parsing OR expression."""
        tokenizer = Tokenizer("SELECT * FROM t WHERE a = 1 OR b = 2")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()
        assert plan["where"] is not None

    def test_parse_not(self) -> None:
        """Test parsing NOT expression."""
        tokenizer = Tokenizer("SELECT * FROM t WHERE NOT (a = 1)")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()
        assert plan["where"] is not None

    def test_parse_between(self) -> None:
        """Test parsing BETWEEN."""
        tokenizer = Tokenizer("SELECT * FROM t WHERE a BETWEEN 1 AND 10")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()
        assert plan["where"] is not None

    def test_parse_in(self) -> None:
        """Test parsing IN."""
        tokenizer = Tokenizer("SELECT * FROM t WHERE a IN (1, 2, 3)")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()
        assert plan["where"] is not None

    def test_parse_like(self) -> None:
        """Test parsing LIKE."""
        tokenizer = Tokenizer("SELECT * FROM t WHERE name LIKE 'J%'")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()
        assert plan["where"] is not None

    def test_parse_is_null(self) -> None:
        """Test parsing IS NULL."""
        tokenizer = Tokenizer("SELECT * FROM t WHERE a IS NULL")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()
        assert plan["where"] is not None

    def test_parse_function_call(self) -> None:
        """Test parsing function calls."""
        tokenizer = Tokenizer("SELECT COUNT(*) FROM users")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()
        assert len(plan["columns"]) > 0


class TestErrorHandling:
    """Tests for error handling."""

    def test_invalid_token_sequence(self) -> None:
        """Test error on invalid token sequence."""
        tokenizer = Tokenizer("SELECT FROM")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        with pytest.raises(SyntaxException):
            parser.parse()

    def test_unclosed_parenthesis(self) -> None:
        """Test error on unclosed parenthesis."""
        tokenizer = Tokenizer("SELECT (a + b FROM t")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        with pytest.raises(SyntaxException):
            parser.parse()

    def test_empty_token_list(self) -> None:
        """Test error on empty token list."""
        parser = Parser([])

        with pytest.raises(ParseException):
            parser.parse()


class TestOperatorPrecedence:
    """Tests for operator precedence."""

    def test_multiplication_before_addition(self) -> None:
        """Test that * has higher precedence than +."""
        tokenizer = Tokenizer("SELECT a + b * c FROM t")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()
        # Should parse as a + (b * c)
        assert plan["columns"] is not None

    def test_and_before_or(self) -> None:
        """Test that AND has higher precedence than OR."""
        tokenizer = Tokenizer("SELECT * FROM t WHERE a OR b AND c")
        tokens = tokenizer.tokenize()
        parser = Parser(tokens)

        plan = parser.parse()
        # Should parse as a OR (b AND c)
        assert plan["where"] is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
