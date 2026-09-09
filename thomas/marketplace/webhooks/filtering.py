"""Event filtering and content-based routing."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from thomas.marketplace.webhooks._exceptions import FilterExpressionError


@dataclass
class FilterToken:
    """Token in a filter expression."""

    type: str  # identifier, operator, literal, paren
    value: str


class FilterParser:
    """Parses filter expressions into evaluators.

    Supports JSONPath-like expressions with operators.
    Example: $.order.total > 100 AND $.status == "pending"
    """

    OPERATORS = {
        "==": "equals",
        "!=": "not_equals",
        ">": "greater_than",
        "<": "less_than",
        ">=": "greater_equal",
        "<=": "less_equal",
        "contains": "contains",
        "startsWith": "starts_with",
        "endsWith": "ends_with",
        "in": "in",
        "exists": "exists",
    }

    LOGICAL_OPS = {"AND", "OR", "NOT"}

    def __init__(self) -> None:
        """Initialize the filter parser."""
        pass

    def parse(self, expression: str) -> Callable:
        """Parse a filter expression into an evaluator function.

        Args:
            expression: Filter expression string.

        Returns:
            Callable that takes a data dict and returns bool.

        Raises:
            FilterExpressionError: If expression is invalid.
        """
        if not expression or not isinstance(expression, str):
            raise FilterExpressionError(expression, "Expression must be non-empty string")

        try:
            tokens = self._tokenize(expression)
            return self._compile(tokens)
        except FilterExpressionError:
            raise
        except Exception as e:
            raise FilterExpressionError(expression, str(e))

    def _tokenize(self, expression: str) -> list[FilterToken]:
        """Tokenize a filter expression.

        Args:
            expression: The expression string.

        Returns:
            List of FilterToken objects.
        """
        tokens = []
        i = 0

        while i < len(expression):
            if expression[i].isspace():
                i += 1
                continue

            if expression[i] in ("(", ")"):
                tokens.append(FilterToken("paren", expression[i]))
                i += 1
            elif expression[i] in ("'", '"'):
                quote = expression[i]
                j = i + 1
                while j < len(expression) and expression[j] != quote:
                    j += 1
                if j >= len(expression):
                    raise FilterExpressionError("", "Unclosed string literal")
                tokens.append(FilterToken("literal", expression[i + 1 : j]))
                i = j + 1
            elif expression[i:].startswith("!="):
                tokens.append(FilterToken("operator", "!="))
                i += 2
            elif expression[i:].startswith("=="):
                tokens.append(FilterToken("operator", "=="))
                i += 2
            elif expression[i:].startswith(">="):
                tokens.append(FilterToken("operator", ">="))
                i += 2
            elif expression[i:].startswith("<="):
                tokens.append(FilterToken("operator", "<="))
                i += 2
            elif expression[i] in (">", "<"):
                tokens.append(FilterToken("operator", expression[i]))
                i += 1
            elif expression[i:].startswith("$"):
                # Skip the `$` before scanning continuation chars,
                # otherwise `j` never advances past `$` (since `$` is not
                # in the continuation set) and the outer while loops
                # forever. Caught by pytest-timeout 2026-05-22 in CI run
                # 26302627013 against tests/test_webhooks_filtering.py.
                j = i + 1
                while j < len(expression) and (expression[j].isalnum() or expression[j] in (".", "_", "[", "]")):
                    j += 1
                tokens.append(FilterToken("path", expression[i:j]))
                i = j
            else:
                j = i
                while j < len(expression) and (expression[j].isalnum() or expression[j] in ("_", ".")):
                    j += 1
                if j == i:
                    # Unrecognized character (e.g. lone `!` not followed by `=`).
                    # Without this guard the loop would never advance — the
                    # while on line above doesn't move `j`, `word` is empty,
                    # and none of the type branches advance `i`. The CI run
                    # 26302627013 hit this via pytest-timeout after 5 min
                    # on tests/test_webhooks_filtering.py — the canonical
                    # symptom of this bug class.
                    raise FilterExpressionError(
                        expression,
                        f"Unrecognized character at position {i}: {expression[i]!r}",
                    )
                word = expression[i:j]
                if word.upper() in self.LOGICAL_OPS:
                    tokens.append(FilterToken("logical", word.upper()))
                elif word in self.OPERATORS:
                    tokens.append(FilterToken("operator", word))
                else:
                    try:
                        float(word)
                        tokens.append(FilterToken("number", word))
                    except ValueError:
                        tokens.append(FilterToken("identifier", word))
                i = j
                i = j

        return tokens

    def _compile(self, tokens: list[FilterToken]) -> Callable:
        """Compile tokens into an evaluator function.

        Args:
            tokens: List of tokens.

        Returns:
            Evaluator function.
        """
        if not tokens:
            raise FilterExpressionError("", "Empty expression")

        evaluator, pos = self._parse_or(tokens, 0)
        if pos < len(tokens):
            raise FilterExpressionError("", f"Unexpected token at position {pos}")

        return evaluator

    def _parse_or(self, tokens: list[FilterToken], pos: int) -> tuple:
        """Parse OR expression (lowest precedence).

        Returns:
            Tuple of (evaluator, new_position).
        """
        left, pos = self._parse_and(tokens, pos)

        while pos < len(tokens) and tokens[pos].type == "logical" and tokens[pos].value == "OR":
            pos += 1
            right, pos = self._parse_and(tokens, pos)
            left = self._make_or(left, right)

        return left, pos

    def _parse_and(self, tokens: list[FilterToken], pos: int) -> tuple:
        """Parse AND expression.

        Returns:
            Tuple of (evaluator, new_position).
        """
        left, pos = self._parse_not(tokens, pos)

        while pos < len(tokens) and tokens[pos].type == "logical" and tokens[pos].value == "AND":
            pos += 1
            right, pos = self._parse_not(tokens, pos)
            left = self._make_and(left, right)

        return left, pos

    def _parse_not(self, tokens: list[FilterToken], pos: int) -> tuple:
        """Parse NOT expression.

        Returns:
            Tuple of (evaluator, new_position).
        """
        if pos < len(tokens) and tokens[pos].type == "logical" and tokens[pos].value == "NOT":
            pos += 1
            evaluator, pos = self._parse_primary(tokens, pos)
            return self._make_not(evaluator), pos

        return self._parse_primary(tokens, pos)

    def _parse_primary(self, tokens: list[FilterToken], pos: int) -> tuple:
        """Parse primary expression (path, parenthesis, comparison).

        Returns:
            Tuple of (evaluator, new_position).
        """
        if pos >= len(tokens):
            raise FilterExpressionError("", "Unexpected end of expression")

        if tokens[pos].type == "paren" and tokens[pos].value == "(":
            pos += 1
            evaluator, pos = self._parse_or(tokens, pos)
            if pos >= len(tokens) or tokens[pos].value != ")":
                raise FilterExpressionError("", "Expected closing parenthesis")
            return evaluator, pos + 1

        if tokens[pos].type == "path":
            path = tokens[pos].value
            pos += 1

            if pos >= len(tokens):
                raise FilterExpressionError("", "Expected operator after path")

            if tokens[pos].type != "operator":
                raise FilterExpressionError("", f"Expected operator, got {tokens[pos].value}")

            op = tokens[pos].value
            pos += 1

            if pos >= len(tokens):
                raise FilterExpressionError("", "Expected value after operator")

            if tokens[pos].type == "literal":
                value = tokens[pos].value
                evaluator = self._make_comparison(path, op, value)
                pos += 1
            elif tokens[pos].type == "number":
                value = float(tokens[pos].value)
                evaluator = self._make_comparison(path, op, value)
                pos += 1
            else:
                raise FilterExpressionError("", f"Unexpected value type: {tokens[pos].type}")

            return evaluator, pos

        raise FilterExpressionError("", f"Unexpected token: {tokens[pos].value}")

    def _make_comparison(self, path: str, operator: str, value: Any) -> Callable:
        """Create a comparison evaluator.

        Args:
            path: JSONPath expression.
            operator: Comparison operator.
            value: Value to compare.

        Returns:
            Evaluator function.
        """

        def evaluator(data: dict) -> bool:
            try:
                actual = self._extract_value(data, path)
                return self._compare(actual, operator, value)
            except Exception:  # REVIEWED: broad catch
                return False

        return evaluator

    def _extract_value(self, data: dict, path: str) -> Any:
        """Extract value from data using JSONPath.

        Args:
            data: The data dictionary.
            path: JSONPath expression (e.g., "$.order.total").

        Returns:
            The extracted value.
        """
        if not path.startswith("$."):
            raise FilterExpressionError(path, "Path must start with $.")

        keys = path[2:].split(".")
        current = data

        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
            else:
                return None

            if current is None:
                return None

        return current

    def _compare(self, actual: Any, operator: str, expected: Any) -> bool:
        """Perform a comparison operation.

        Args:
            actual: The actual value.
            operator: The comparison operator.
            expected: The expected value.

        Returns:
            True if comparison succeeds.
        """
        if operator == "==":
            return actual == expected
        elif operator == "!=":
            return actual != expected
        elif operator == ">":
            return actual is not None and actual > expected
        elif operator == "<":
            return actual is not None and actual < expected
        elif operator == ">=":
            return actual is not None and actual >= expected
        elif operator == "<=":
            return actual is not None and actual <= expected
        elif operator == "contains":
            return isinstance(actual, str) and expected in actual
        elif operator == "startsWith":
            return isinstance(actual, str) and actual.startswith(expected)
        elif operator == "endsWith":
            return isinstance(actual, str) and actual.endswith(expected)
        elif operator == "in":
            return actual in expected if isinstance(expected, (list, tuple)) else False
        elif operator == "exists":
            return actual is not None
        else:
            return False

    @staticmethod
    def _make_and(left: Callable, right: Callable) -> Callable:
        """Create AND combinator.

        Args:
            left: Left evaluator.
            right: Right evaluator.

        Returns:
            Combined evaluator.
        """

        def evaluator(data: dict) -> bool:
            return left(data) and right(data)

        return evaluator

    @staticmethod
    def _make_or(left: Callable, right: Callable) -> Callable:
        """Create OR combinator.

        Args:
            left: Left evaluator.
            right: Right evaluator.

        Returns:
            Combined evaluator.
        """

        def evaluator(data: dict) -> bool:
            return left(data) or right(data)

        return evaluator

    @staticmethod
    def _make_not(evaluator: Callable) -> Callable:
        """Create NOT wrapper.

        Args:
            evaluator: The evaluator to negate.

        Returns:
            Negated evaluator.
        """

        def negated(data: dict) -> bool:
            return not evaluator(data)

        return negated


class EventFilter:
    """Applies filters to determine if events match subscriptions."""

    def __init__(self) -> None:
        """Initialize the event filter."""
        self.parser = FilterParser()

    def matches(self, data: dict, expression: str) -> bool:
        """Check if data matches a filter expression.

        Args:
            data: Event data to filter.
            expression: Filter expression.

        Returns:
            True if data matches the expression.
        """
        try:
            evaluator = self.parser.parse(expression)
            return evaluator(data)
        except FilterExpressionError:
            return False

    def test_filter(self, expression: str, sample_data: dict) -> dict:
        """Test a filter expression against sample data.

        Args:
            expression: Filter expression to test.
            sample_data: Sample event data.

        Returns:
            Dictionary with test results.
        """
        try:
            result = self.matches(sample_data, expression)
            return {
                "valid": True,
                "result": result,
                "error": None,
            }
        except FilterExpressionError as e:
            return {
                "valid": False,
                "result": None,
                "error": str(e),
            }
