"""
Query engine implementing a PromQL subset.

Supports instant queries, range queries, and common aggregation/function operations.
"""

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from thomas.monitoring._exceptions import InvalidQueryError


class TokenType(Enum):
    """Token types for query parsing."""

    NUMBER = "NUMBER"
    STRING = "STRING"
    IDENTIFIER = "IDENTIFIER"
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"
    LBRACE = "LBRACE"
    RBRACE = "RBRACE"
    COMMA = "COMMA"
    COLON = "COLON"
    OPERATOR = "OPERATOR"
    COMPARISON = "COMPARISON"
    EOF = "EOF"


@dataclass
class Token:
    """A query token."""

    type: TokenType
    value: str
    position: int


@dataclass
class InstantResult:
    """Result of an instant query."""

    timestamp: float
    series: dict[str, float]  # series_key -> value


@dataclass
class RangeResult:
    """Result of a range query."""

    series: dict[str, list[tuple[float, float]]]  # series_key -> [(timestamp, value), ...]


class Lexer:
    """Tokenizes PromQL queries."""

    def __init__(self, query: str) -> None:
        self.query = query
        self.pos = 0
        self.tokens: list[Token] = []

    def tokenize(self) -> list[Token]:
        """Tokenize the query."""
        while self.pos < len(self.query):
            self._skip_whitespace()
            if self.pos >= len(self.query):
                break

            char = self.query[self.pos]

            if char.isdigit() or (
                char == "." and self.pos + 1 < len(self.query) and self.query[self.pos + 1].isdigit()
            ):
                self._read_number()
            elif char == '"' or char == "'":
                self._read_string()
            elif char.isalpha() or char == "_":
                self._read_identifier()
            elif char == "(":
                self.tokens.append(Token(TokenType.LPAREN, "(", self.pos))
                self.pos += 1
            elif char == ")":
                self.tokens.append(Token(TokenType.RPAREN, ")", self.pos))
                self.pos += 1
            elif char == "{":
                self.tokens.append(Token(TokenType.LBRACE, "{", self.pos))
                self.pos += 1
            elif char == "}":
                self.tokens.append(Token(TokenType.RBRACE, "}", self.pos))
                self.pos += 1
            elif char == ",":
                self.tokens.append(Token(TokenType.COMMA, ",", self.pos))
                self.pos += 1
            elif char == ":":
                self.tokens.append(Token(TokenType.COLON, ":", self.pos))
                self.pos += 1
            elif char in "+-*/%^":
                self.tokens.append(Token(TokenType.OPERATOR, char, self.pos))
                self.pos += 1
            elif char in "<>=!":
                self._read_comparison()
            else:
                self.pos += 1

        self.tokens.append(Token(TokenType.EOF, "", self.pos))
        return self.tokens

    def _skip_whitespace(self) -> None:
        """Skip whitespace characters."""
        while self.pos < len(self.query) and self.query[self.pos].isspace():
            self.pos += 1

    def _read_number(self) -> None:
        """Read a number token."""
        start = self.pos
        while self.pos < len(self.query) and (self.query[self.pos].isdigit() or self.query[self.pos] == "."):
            self.pos += 1
        self.tokens.append(Token(TokenType.NUMBER, self.query[start : self.pos], start))

    def _read_string(self) -> None:
        """Read a string token."""
        quote = self.query[self.pos]
        start = self.pos
        self.pos += 1
        while self.pos < len(self.query) and self.query[self.pos] != quote:
            if self.query[self.pos] == "\\":
                self.pos += 2
            else:
                self.pos += 1
        if self.pos < len(self.query):
            self.pos += 1
        self.tokens.append(Token(TokenType.STRING, self.query[start + 1 : self.pos - 1], start))

    def _read_identifier(self) -> None:
        """Read an identifier or keyword."""
        start = self.pos
        while self.pos < len(self.query) and (self.query[self.pos].isalnum() or self.query[self.pos] == "_"):
            self.pos += 1
        self.tokens.append(Token(TokenType.IDENTIFIER, self.query[start : self.pos], start))

    def _read_comparison(self) -> None:
        """Read comparison operators."""
        start = self.pos
        if self.pos + 1 < len(self.query):
            two_char = self.query[self.pos : self.pos + 2]
            if two_char in ("==", "!=", "<=", ">="):
                self.tokens.append(Token(TokenType.COMPARISON, two_char, start))
                self.pos += 2
                return

        self.tokens.append(Token(TokenType.COMPARISON, self.query[self.pos], start))
        self.pos += 1


class Parser:
    """Parses PromQL queries into AST."""

    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def parse(self) -> dict[str, Any]:
        """Parse tokens into AST."""
        return self._parse_expression()

    def _parse_expression(self) -> dict[str, Any]:
        """Parse an expression."""
        left = self._parse_primary()

        while self.pos < len(self.tokens) and self.tokens[self.pos].type in (
            TokenType.OPERATOR,
            TokenType.COMPARISON,
        ):
            op_token = self.tokens[self.pos]
            self.pos += 1
            right = self._parse_primary()
            left = {
                "type": "binary_op",
                "op": op_token.value,
                "left": left,
                "right": right,
            }

        return left

    def _parse_primary(self) -> dict[str, Any]:
        """Parse a primary expression."""
        token = self.tokens[self.pos]

        if token.type == TokenType.IDENTIFIER:
            func_name = token.value
            self.pos += 1

            if self.pos < len(self.tokens) and self.tokens[self.pos].type == TokenType.LPAREN:
                # Function call
                self.pos += 1
                args = []
                while self.pos < len(self.tokens) and self.tokens[self.pos].type != TokenType.RPAREN:
                    args.append(self._parse_expression())
                    if self.pos < len(self.tokens) and self.tokens[self.pos].type == TokenType.COMMA:
                        self.pos += 1
                if self.pos < len(self.tokens):
                    self.pos += 1  # Skip )

                return {"type": "function", "name": func_name, "args": args}
            else:
                # Metric selector
                labels = {}
                if self.pos < len(self.tokens) and self.tokens[self.pos].type == TokenType.LBRACE:
                    self.pos += 1
                    while self.pos < len(self.tokens) and self.tokens[self.pos].type != TokenType.RBRACE:
                        if self.tokens[self.pos].type == TokenType.IDENTIFIER:
                            label_name = self.tokens[self.pos].value
                            self.pos += 1
                            if (
                                self.pos < len(self.tokens)
                                and self.tokens[self.pos].type == TokenType.COMPARISON
                                and self.tokens[self.pos].value == "="
                            ):
                                self.pos += 1
                                if self.tokens[self.pos].type == TokenType.STRING:
                                    label_value = self.tokens[self.pos].value
                                    self.pos += 1
                                    labels[label_name] = label_value
                        if self.pos < len(self.tokens) and self.tokens[self.pos].type == TokenType.COMMA:
                            self.pos += 1
                    if self.pos < len(self.tokens):
                        self.pos += 1  # Skip }

                return {"type": "metric", "name": func_name, "labels": labels}

        elif token.type == TokenType.NUMBER:
            self.pos += 1
            return {"type": "scalar", "value": float(token.value)}

        elif token.type == TokenType.LPAREN:
            self.pos += 1
            expr = self._parse_expression()
            if self.pos < len(self.tokens) and self.tokens[self.pos].type == TokenType.RPAREN:
                self.pos += 1
            return expr

        raise InvalidQueryError(f"Unexpected token: {token.value}")


class QueryEngine:
    """Executes PromQL queries against metric data."""

    def __init__(self, storage: any) -> None:
        self.storage = storage

    def instant_query(self, query: str, timestamp: float | None = None) -> InstantResult:
        """Execute an instant query."""
        if timestamp is None:
            timestamp = time.time()

        ast = self._parse_query(query)
        results = self._evaluate(ast, timestamp)

        series = {}
        for series_key, values in results.items():
            if values:
                series[series_key] = values[-1][1]  # Last value

        return InstantResult(timestamp=timestamp, series=series)

    def range_query(
        self,
        query: str,
        start: float,
        end: float,
        step: float = 60.0,
    ) -> RangeResult:
        """Execute a range query."""
        ast = self._parse_query(query)
        all_series: dict[str, list[tuple[float, float]]] = {}

        ts = start
        while ts <= end:
            results = self._evaluate(ast, ts)
            for series_key, values in results.items():
                if series_key not in all_series:
                    all_series[series_key] = []
                if values:
                    all_series[series_key].append((ts, values[-1][1]))
            ts += step

        return RangeResult(series=all_series)

    def _parse_query(self, query: str) -> dict[str, Any]:
        """Parse a PromQL query."""
        lexer = Lexer(query)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        return parser.parse()

    def _evaluate(self, ast: dict[str, Any], timestamp: float) -> dict[str, list[tuple[float, float]]]:
        """Evaluate AST against metric data."""
        if ast["type"] == "metric":
            return self._evaluate_metric(ast, timestamp)
        elif ast["type"] == "function":
            return self._evaluate_function(ast, timestamp)
        elif ast["type"] == "scalar":
            return {"scalar": [(timestamp, ast["value"])]}
        elif ast["type"] == "binary_op":
            return self._evaluate_binary_op(ast, timestamp)

        return {}

    def _evaluate_metric(self, ast: dict[str, Any], timestamp: float) -> dict[str, list[tuple[float, float]]]:
        """Evaluate a metric selector."""
        results = {}
        labels = ast.get("labels", {})

        # Find matching series
        series_keys = self.storage.find_series_by_labels(labels)

        for series_key in series_keys:
            samples = self.storage.query(series_key, timestamp - 300, timestamp + 300)
            if samples:
                results[series_key] = [(s.timestamp, s.value) for s in samples[-10:]]

        return results

    def _evaluate_function(self, ast: dict[str, Any], timestamp: float) -> dict[str, list[tuple[float, float]]]:
        """Evaluate a function call."""
        func_name = ast["name"]
        args = ast.get("args", [])

        if func_name == "rate":
            return self._function_rate(args[0], timestamp)
        elif func_name == "increase":
            return self._function_increase(args[0], timestamp)
        elif func_name == "sum":
            return self._function_sum(args[0], timestamp)
        elif func_name == "avg":
            return self._function_avg(args[0], timestamp)
        elif func_name == "max":
            return self._function_max(args[0], timestamp)
        elif func_name == "min":
            return self._function_min(args[0], timestamp)
        elif func_name == "count":
            return self._function_count(args[0], timestamp)
        elif func_name == "topk":
            return self._function_topk(args, timestamp)
        elif func_name == "bottomk":
            return self._function_bottomk(args, timestamp)

        return {}

    def _evaluate_binary_op(self, ast: dict[str, Any], timestamp: float) -> dict[str, list[tuple[float, float]]]:
        """Evaluate binary operation."""
        left = self._evaluate(ast["left"], timestamp)
        right = self._evaluate(ast["right"], timestamp)
        op = ast["op"]

        results = {}
        for series_key, left_values in left.items():
            if series_key in right:
                right_values = right[series_key]
                if left_values and right_values:
                    left_val = left_values[-1][1]
                    right_val = right_values[-1][1]

                    if op == "+":
                        result_val = left_val + right_val
                    elif op == "-":
                        result_val = left_val - right_val
                    elif op == "*":
                        result_val = left_val * right_val
                    elif op == "/":
                        result_val = left_val / right_val if right_val != 0 else 0
                    elif op == ">":
                        result_val = 1.0 if left_val > right_val else 0.0
                    elif op == "<":
                        result_val = 1.0 if left_val < right_val else 0.0
                    elif op == "==":
                        result_val = 1.0 if left_val == right_val else 0.0
                    elif op == "!=":
                        result_val = 1.0 if left_val != right_val else 0.0
                    else:
                        result_val = 0.0

                    results[series_key] = [(timestamp, result_val)]

        return results

    def _function_rate(self, expr: dict[str, Any], timestamp: float) -> dict[str, list[tuple[float, float]]]:
        """rate(counter_metric[5m])"""
        series_data = self._evaluate(expr, timestamp)
        results = {}

        for series_key, values in series_data.items():
            if len(values) >= 2:
                time_delta = values[-1][0] - values[0][0]
                value_delta = values[-1][1] - values[0][1]
                if time_delta > 0:
                    rate = value_delta / time_delta
                    results[series_key] = [(timestamp, rate)]

        return results

    def _function_increase(self, expr: dict[str, Any], timestamp: float) -> dict[str, list[tuple[float, float]]]:
        """increase(counter_metric[5m])"""
        series_data = self._evaluate(expr, timestamp)
        results = {}

        for series_key, values in series_data.items():
            if len(values) >= 2:
                increase = values[-1][1] - values[0][1]
                results[series_key] = [(timestamp, increase)]

        return results

    def _function_sum(self, expr: dict[str, Any], timestamp: float) -> dict[str, list[tuple[float, float]]]:
        """sum(metric)"""
        series_data = self._evaluate(expr, timestamp)
        total = 0.0

        for values in series_data.values():
            if values:
                total += values[-1][1]

        return {"sum": [(timestamp, total)]}

    def _function_avg(self, expr: dict[str, Any], timestamp: float) -> dict[str, list[tuple[float, float]]]:
        """avg(metric)"""
        series_data = self._evaluate(expr, timestamp)
        values = [v[-1][1] for v in series_data.values() if v]

        avg = sum(values) / len(values) if values else 0.0
        return {"avg": [(timestamp, avg)]}

    def _function_max(self, expr: dict[str, Any], timestamp: float) -> dict[str, list[tuple[float, float]]]:
        """max(metric)"""
        series_data = self._evaluate(expr, timestamp)
        values = [v[-1][1] for v in series_data.values() if v]

        max_val = max(values) if values else 0.0
        return {"max": [(timestamp, max_val)]}

    def _function_min(self, expr: dict[str, Any], timestamp: float) -> dict[str, list[tuple[float, float]]]:
        """min(metric)"""
        series_data = self._evaluate(expr, timestamp)
        values = [v[-1][1] for v in series_data.values() if v]

        min_val = min(values) if values else 0.0
        return {"min": [(timestamp, min_val)]}

    def _function_count(self, expr: dict[str, Any], timestamp: float) -> dict[str, list[tuple[float, float]]]:
        """count(metric)"""
        series_data = self._evaluate(expr, timestamp)
        count = len([v for v in series_data.values() if v])
        return {"count": [(timestamp, float(count))]}

    def _function_topk(self, args: list[dict[str, Any]], timestamp: float) -> dict[str, list[tuple[float, float]]]:
        """topk(k, metric)"""
        k = int(args[0]["value"]) if args[0]["type"] == "scalar" else 5
        series_data = self._evaluate(args[1], timestamp)

        sorted_series = sorted(
            series_data.items(),
            key=lambda x: x[1][-1][1] if x[1] else 0,
            reverse=True,
        )

        return dict(sorted_series[:k])

    def _function_bottomk(self, args: list[dict[str, Any]], timestamp: float) -> dict[str, list[tuple[float, float]]]:
        """bottomk(k, metric)"""
        k = int(args[0]["value"]) if args[0]["type"] == "scalar" else 5
        series_data = self._evaluate(args[1], timestamp)

        sorted_series = sorted(
            series_data.items(),
            key=lambda x: x[1][-1][1] if x[1] else 0,
        )

        return dict(sorted_series[:k])
