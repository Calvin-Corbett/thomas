"""Tests for event filtering and content-based routing."""

import pytest

from thomas.marketplace.webhooks._exceptions import FilterExpressionError
from thomas.marketplace.webhooks.filtering import EventFilter, FilterParser


class TestFilterParser:
    """Test filter expression parsing and compilation."""

    def test_parse_equality_filter(self):
        """Test parsing equality comparison."""
        parser = FilterParser()
        evaluator = parser.parse("$.status == 'pending'")

        assert evaluator({"status": "pending"})
        assert not evaluator({"status": "completed"})

    def test_parse_inequality_filter(self):
        """Test parsing inequality comparison."""
        parser = FilterParser()
        evaluator = parser.parse("$.status != 'pending'")

        assert evaluator({"status": "completed"})
        assert not evaluator({"status": "pending"})

    def test_parse_greater_than(self):
        """Test parsing greater than comparison."""
        parser = FilterParser()
        evaluator = parser.parse("$.total > 100")

        assert evaluator({"total": 150})
        assert not evaluator({"total": 50})

    def test_parse_less_than(self):
        """Test parsing less than comparison."""
        parser = FilterParser()
        evaluator = parser.parse("$.total < 100")

        assert evaluator({"total": 50})
        assert not evaluator({"total": 150})

    def test_parse_greater_equal(self):
        """Test parsing greater-than-or-equal."""
        parser = FilterParser()
        evaluator = parser.parse("$.total >= 100")

        assert evaluator({"total": 100})
        assert evaluator({"total": 150})
        assert not evaluator({"total": 50})

    def test_parse_less_equal(self):
        """Test parsing less-than-or-equal."""
        parser = FilterParser()
        evaluator = parser.parse("$.total <= 100")

        assert evaluator({"total": 100})
        assert evaluator({"total": 50})
        assert not evaluator({"total": 150})

    def test_parse_contains(self):
        """Test parsing contains operator."""
        parser = FilterParser()
        evaluator = parser.parse("$.description contains 'urgent'")

        assert evaluator({"description": "urgent request"})
        assert not evaluator({"description": "normal request"})

    def test_parse_starts_with(self):
        """Test parsing startsWith operator."""
        parser = FilterParser()
        evaluator = parser.parse("$.email startsWith 'admin'")

        assert evaluator({"email": "admin@example.com"})
        assert not evaluator({"email": "user@example.com"})

    def test_parse_and_combinator(self):
        """Test parsing AND logical operator."""
        parser = FilterParser()
        evaluator = parser.parse("$.status == 'pending' AND $.total > 100")

        assert evaluator({"status": "pending", "total": 150})
        assert not evaluator({"status": "completed", "total": 150})
        assert not evaluator({"status": "pending", "total": 50})

    def test_parse_or_combinator(self):
        """Test parsing OR logical operator."""
        parser = FilterParser()
        evaluator = parser.parse("$.status == 'pending' OR $.status == 'urgent'")

        assert evaluator({"status": "pending"})
        assert evaluator({"status": "urgent"})
        assert not evaluator({"status": "completed"})

    def test_parse_not_operator(self):
        """Test parsing NOT logical operator."""
        parser = FilterParser()
        evaluator = parser.parse("NOT $.is_deleted")

        assert not evaluator({"is_deleted": True})
        assert evaluator({"is_deleted": False})

    def test_parse_parentheses(self):
        """Test parsing expressions with parentheses."""
        parser = FilterParser()
        evaluator = parser.parse("($.status == 'pending' OR $.status == 'urgent') AND $.total > 50")

        assert evaluator({"status": "pending", "total": 100})
        assert evaluator({"status": "urgent", "total": 75})
        assert not evaluator({"status": "completed", "total": 100})
        assert not evaluator({"status": "pending", "total": 25})

    def test_parse_nested_objects(self):
        """Test parsing with nested object access."""
        parser = FilterParser()
        evaluator = parser.parse("$.order.total > 100")

        assert evaluator({"order": {"total": 150}})
        assert not evaluator({"order": {"total": 50}})

    def test_parse_missing_field(self):
        """Test that missing fields return false."""
        parser = FilterParser()
        evaluator = parser.parse("$.nonexistent == 'value'")

        assert not evaluator({"other_field": "value"})

    def test_parse_invalid_expression_empty(self):
        """Test that empty expression raises error."""
        parser = FilterParser()

        with pytest.raises(FilterExpressionError):
            parser.parse("")

    def test_parse_invalid_expression_syntax_error(self):
        """Test that syntax errors are caught."""
        parser = FilterParser()

        with pytest.raises(FilterExpressionError):
            parser.parse("$.field > > 100")

    def test_parse_unclosed_string_literal(self):
        """Test that unclosed string raises error."""
        parser = FilterParser()

        with pytest.raises(FilterExpressionError):
            parser.parse("$.field == 'unclosed")

    def test_parse_number_comparison(self):
        """Test parsing numeric literals."""
        parser = FilterParser()
        evaluator = parser.parse("$.quantity == 5")

        assert evaluator({"quantity": 5})
        assert not evaluator({"quantity": 3})


class TestEventFilter:
    """Test event filtering."""

    def test_matches_simple_filter(self):
        """Test filter matching."""
        filter_obj = EventFilter()

        assert filter_obj.matches({"status": "pending"}, "$.status == 'pending'")
        assert not filter_obj.matches({"status": "completed"}, "$.status == 'pending'")

    def test_matches_complex_filter(self):
        """Test matching complex filter."""
        filter_obj = EventFilter()
        data = {"order": {"total": 150, "status": "pending"}}

        assert filter_obj.matches(
            data,
            "$.order.total > 100 AND $.order.status == 'pending'",
        )

    def test_test_filter_valid(self):
        """Test dry-run of filter expression."""
        filter_obj = EventFilter()
        result = filter_obj.test_filter(
            "$.status == 'pending'",
            {"status": "pending"},
        )

        assert result["valid"]
        assert result["result"]
        assert result["error"] is None

    def test_test_filter_invalid_expression(self):
        """Test dry-run with invalid expression."""
        filter_obj = EventFilter()
        result = filter_obj.test_filter(
            "invalid expression",
            {"status": "pending"},
        )

        assert not result["valid"]
        assert result["result"] is None
        assert result["error"] is not None

    def test_test_filter_nonmatching(self):
        """Test dry-run with non-matching data."""
        filter_obj = EventFilter()
        result = filter_obj.test_filter(
            "$.status == 'pending'",
            {"status": "completed"},
        )

        assert result["valid"]
        assert not result["result"]
        assert result["error"] is None


class TestComplexFiltering:
    """Test complex filtering scenarios."""

    def test_order_total_filter(self):
        """Test filtering orders by total."""
        parser = FilterParser()
        evaluator = parser.parse("$.order.total > 100")

        test_cases = [
            ({"order": {"total": 150}}, True),
            ({"order": {"total": 50}}, False),
            ({"order": {"total": 100}}, False),
        ]

        for data, expected in test_cases:
            assert evaluator(data) == expected

    def test_status_priority_filter(self):
        """Test filtering by multiple conditions."""
        parser = FilterParser()
        evaluator = parser.parse("($.status == 'urgent' OR $.priority == 'high') AND $.amount > 1000")

        test_cases = [
            ({"status": "urgent", "priority": "low", "amount": 2000}, True),
            ({"status": "normal", "priority": "high", "amount": 2000}, True),
            ({"status": "normal", "priority": "low", "amount": 2000}, False),
            ({"status": "urgent", "priority": "low", "amount": 500}, False),
        ]

        for data, expected in test_cases:
            assert evaluator(data) == expected

    def test_string_matching_filters(self):
        """Test string-based filtering."""
        parser = FilterParser()
        evaluator = parser.parse("$.email startsWith 'admin'")

        assert evaluator({"email": "admin@example.com"})
        assert evaluator({"email": "admin.user@example.com"})
        assert not evaluator({"email": "user@example.com"})
