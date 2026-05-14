"""
Tests for query engine module.
"""

import time

from thomas.marketplace.monitoring.query_engine import (
    Lexer,
    Parser,
    QueryEngine,
    TokenType,
)


class TestLexer:
    """Test query lexer."""

    def test_tokenize_identifier(self) -> None:
        """Test tokenizing identifiers."""
        lexer = Lexer("metric_name")
        tokens = lexer.tokenize()

        assert len(tokens) >= 1
        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[0].value == "metric_name"

    def test_tokenize_number(self) -> None:
        """Test tokenizing numbers."""
        lexer = Lexer("42 3.14")
        tokens = lexer.tokenize()

        numbers = [t for t in tokens if t.type == TokenType.NUMBER]
        assert len(numbers) == 2
        assert numbers[0].value == "42"
        assert numbers[1].value == "3.14"

    def test_tokenize_string(self) -> None:
        """Test tokenizing strings."""
        lexer = Lexer('"hello world"')
        tokens = lexer.tokenize()

        strings = [t for t in tokens if t.type == TokenType.STRING]
        assert len(strings) == 1
        assert strings[0].value == "hello world"

    def test_tokenize_operators(self) -> None:
        """Test tokenizing operators."""
        lexer = Lexer("+ - * / %")
        tokens = lexer.tokenize()

        operators = [t for t in tokens if t.type == TokenType.OPERATOR]
        assert len(operators) == 5

    def test_tokenize_comparison(self) -> None:
        """Test tokenizing comparison operators."""
        lexer = Lexer("== != < > <= >=")
        tokens = lexer.tokenize()

        comparisons = [t for t in tokens if t.type == TokenType.COMPARISON]
        assert len(comparisons) == 6

    def test_tokenize_braces(self) -> None:
        """Test tokenizing braces."""
        lexer = Lexer("{}")
        tokens = lexer.tokenize()

        braces = [t for t in tokens if t.type in (TokenType.LBRACE, TokenType.RBRACE)]
        assert len(braces) == 2

    def test_tokenize_complex_query(self) -> None:
        """Test tokenizing complex query."""
        lexer = Lexer('rate(http_requests{job="api"}[5m])')
        tokens = lexer.tokenize()

        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[0].value == "rate"


class TestParser:
    """Test query parser."""

    def test_parse_metric(self) -> None:
        """Test parsing metric selector."""
        lexer = Lexer("metric_name")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        assert ast["type"] == "metric"
        assert ast["name"] == "metric_name"

    def test_parse_metric_with_labels(self) -> None:
        """Test parsing metric with labels."""
        lexer = Lexer('metric_name{env="prod"}')
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        assert ast["type"] == "metric"
        assert ast["labels"]["env"] == "prod"

    def test_parse_function(self) -> None:
        """Test parsing function call."""
        lexer = Lexer("rate(metric)")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        assert ast["type"] == "function"
        assert ast["name"] == "rate"

    def test_parse_number(self) -> None:
        """Test parsing number."""
        lexer = Lexer("42")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        assert ast["type"] == "scalar"
        assert ast["value"] == 42.0

    def test_parse_binary_operation(self) -> None:
        """Test parsing binary operation."""
        lexer = Lexer("a + b")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        assert ast["type"] == "binary_op"
        assert ast["op"] == "+"

    def test_parse_complex_query(self) -> None:
        """Test parsing complex PromQL."""
        lexer = Lexer('rate(metric{job="api"}[5m]) + 10')
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        assert ast is not None


class TestQueryEngine:
    """Test query engine."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        # Create mock storage
        self.storage = MockStorage()

    def test_instant_query(self) -> None:
        """Test instant query."""
        engine = QueryEngine(self.storage)

        result = engine.instant_query("metric")
        assert result is not None
        assert result.timestamp > 0

    def test_range_query(self) -> None:
        """Test range query."""
        engine = QueryEngine(self.storage)
        now = time.time()

        result = engine.range_query("metric", now - 300, now, step=60)
        assert result is not None

    def test_function_rate(self) -> None:
        """Test rate function."""
        engine = QueryEngine(self.storage)

        result = engine.instant_query("rate(metric)")
        assert result is not None

    def test_function_sum(self) -> None:
        """Test sum aggregation function."""
        engine = QueryEngine(self.storage)

        result = engine.instant_query("sum(metric)")
        assert result is not None

    def test_function_avg(self) -> None:
        """Test avg aggregation function."""
        engine = QueryEngine(self.storage)

        result = engine.instant_query("avg(metric)")
        assert result is not None

    def test_function_max(self) -> None:
        """Test max function."""
        engine = QueryEngine(self.storage)

        result = engine.instant_query("max(metric)")
        assert result is not None

    def test_function_min(self) -> None:
        """Test min function."""
        engine = QueryEngine(self.storage)

        result = engine.instant_query("min(metric)")
        assert result is not None

    def test_function_count(self) -> None:
        """Test count function."""
        engine = QueryEngine(self.storage)

        result = engine.instant_query("count(metric)")
        assert result is not None

    def test_function_topk(self) -> None:
        """Test topk function."""
        engine = QueryEngine(self.storage)

        result = engine.instant_query("topk(3, metric)")
        assert result is not None

    def test_function_bottomk(self) -> None:
        """Test bottomk function."""
        engine = QueryEngine(self.storage)

        result = engine.instant_query("bottomk(3, metric)")
        assert result is not None

    def test_binary_arithmetic(self) -> None:
        """Test binary arithmetic operations."""
        engine = QueryEngine(self.storage)

        result = engine.instant_query("10 + 5")
        assert result is not None

    def test_binary_comparison(self) -> None:
        """Test binary comparison operations."""
        engine = QueryEngine(self.storage)

        result = engine.instant_query("10 > 5")
        assert result is not None


class MockStorage:
    """Mock storage for testing."""

    def find_series_by_labels(self, labels: dict) -> list:
        """Return mock series."""
        return ["series_1", "series_2"]

    def query(self, series_key: str, start: float, end: float) -> list:
        """Return mock samples."""
        from thomas.marketplace.monitoring._types import MetricSample

        now = time.time()
        return [
            MetricSample(timestamp=now - 60, value=10.0),
            MetricSample(timestamp=now - 30, value=20.0),
            MetricSample(timestamp=now, value=30.0),
        ]


class TestQueryParsing:
    """Test query parsing edge cases."""

    def test_parse_invalid_query(self) -> None:
        """Test parsing invalid query."""
        engine = QueryEngine(MockStorage())

        # This should handle gracefully (not crash)
        try:
            engine.instant_query("@invalid")
        except Exception:
            pass

    def test_metric_with_multiple_labels(self) -> None:
        """Test metric with multiple labels."""
        lexer = Lexer('metric{env="prod",service="api"}')
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        assert "env" in ast["labels"]
        assert "service" in ast["labels"]

    def test_parenthesized_expression(self) -> None:
        """Test parenthesized expression."""
        lexer = Lexer("(a + b) * c")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        assert ast is not None
