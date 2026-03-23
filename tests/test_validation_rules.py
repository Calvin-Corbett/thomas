"""
Tests for built-in validation rules.
"""

from thomas.marketplace.validation import rules
from thomas.marketplace.validation._types import SchemaDefinition
from thomas.marketplace.validation.core import Validator


class TestRequiredRule:
    """Test required validation rule."""

    def test_required_with_none(self) -> None:
        """Test required rule with None."""
        rule = rules.required()
        assert not rule.validator(None)

    def test_required_with_empty_string(self) -> None:
        """Test required rule with empty string."""
        rule = rules.required()
        assert not rule.validator("")

    def test_required_with_valid_value(self) -> None:
        """Test required rule with valid value."""
        rule = rules.required()
        assert rule.validator("value")
        assert rule.validator(0)
        assert rule.validator([])


class TestTypeCheckRule:
    """Test type_check rule."""

    def test_type_check_string(self) -> None:
        """Test type check for string."""
        rule = rules.type_check(str)
        assert rule.validator("text")
        assert not rule.validator(123)

    def test_type_check_int(self) -> None:
        """Test type check for integer."""
        rule = rules.type_check(int)
        assert rule.validator(123)
        assert not rule.validator("text")

    def test_type_check_list(self) -> None:
        """Test type check for list."""
        rule = rules.type_check(list)
        assert rule.validator([1, 2, 3])
        assert not rule.validator((1, 2, 3))


class TestMinMaxValue:
    """Test min_value and max_value rules."""

    def test_min_value(self) -> None:
        """Test min_value rule."""
        rule = rules.min_value(10)
        assert rule.validator(10)
        assert rule.validator(15)
        assert not rule.validator(5)

    def test_max_value(self) -> None:
        """Test max_value rule."""
        rule = rules.max_value(100)
        assert rule.validator(100)
        assert rule.validator(50)
        assert not rule.validator(150)

    def test_min_max_together(self) -> None:
        """Test min and max together."""
        min_rule = rules.min_value(10)
        max_rule = rules.max_value(100)
        assert min_rule.validator(50) and max_rule.validator(50)
        assert not min_rule.validator(5)
        assert not max_rule.validator(150)


class TestLengthRules:
    """Test min_length and max_length rules."""

    def test_min_length(self) -> None:
        """Test min_length rule."""
        rule = rules.min_length(3)
        assert rule.validator("abc")
        assert rule.validator("abcd")
        assert not rule.validator("ab")

    def test_max_length(self) -> None:
        """Test max_length rule."""
        rule = rules.max_length(5)
        assert rule.validator("abc")
        assert rule.validator("abcde")
        assert not rule.validator("abcdef")

    def test_length_on_list(self) -> None:
        """Test length rules on lists."""
        min_rule = rules.min_length(2)
        assert min_rule.validator([1, 2])
        assert not min_rule.validator([1])


class TestPatternRule:
    """Test pattern validation rule."""

    def test_pattern_simple(self) -> None:
        """Test simple pattern."""
        rule = rules.pattern(r"^[A-Z][a-z]+$")
        assert rule.validator("John")
        assert not rule.validator("john")
        assert not rule.validator("JOHN")

    def test_pattern_digits(self) -> None:
        """Test digit pattern."""
        rule = rules.pattern(r"^\d{3}-\d{4}$")
        assert rule.validator("123-4567")
        assert not rule.validator("1234567")

    def test_pattern_non_string(self) -> None:
        """Test pattern with non-string input."""
        rule = rules.pattern(r"^\d+$")
        assert not rule.validator(123)


class TestEnumRule:
    """Test enum validation rule."""

    def test_enum_strings(self) -> None:
        """Test enum with strings."""
        rule = rules.enum_rule(["red", "green", "blue"])
        assert rule.validator("red")
        assert not rule.validator("yellow")

    def test_enum_mixed_types(self) -> None:
        """Test enum with mixed types."""
        rule = rules.enum_rule([1, "two", 3.0])
        assert rule.validator(1)
        assert rule.validator("two")
        assert rule.validator(3.0)
        assert not rule.validator(4)


class TestEmailRule:
    """Test email validation rule."""

    def test_valid_emails(self) -> None:
        """Test valid email addresses."""
        rule = rules.email()
        assert rule.validator("user@example.com")
        assert rule.validator("john.doe+tag@company.co.uk")
        assert rule.validator("test_123@test-domain.com")

    def test_invalid_emails(self) -> None:
        """Test invalid email addresses."""
        rule = rules.email()
        assert not rule.validator("invalid.email")
        assert not rule.validator("@example.com")
        assert not rule.validator("user@")
        assert not rule.validator(123)


class TestUrlRule:
    """Test URL validation rule."""

    def test_valid_urls(self) -> None:
        """Test valid URLs."""
        rule = rules.url()
        assert rule.validator("https://example.com")
        assert rule.validator("http://www.example.com/path")
        assert rule.validator("https://example.com:8080/path?query=value")

    def test_invalid_urls(self) -> None:
        """Test invalid URLs."""
        rule = rules.url()
        assert not rule.validator("not a url")
        assert not rule.validator("ftp://example.com")
        assert not rule.validator(123)


class TestUuidRule:
    """Test UUID validation rule."""

    def test_valid_uuids(self) -> None:
        """Test valid UUIDs."""
        rule = rules.uuid_rule()
        assert rule.validator("550e8400-e29b-41d4-a716-446655440000")
        assert rule.validator("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

    def test_invalid_uuids(self) -> None:
        """Test invalid UUIDs."""
        rule = rules.uuid_rule()
        assert not rule.validator("not-a-uuid")
        assert not rule.validator("550e8400-e29b-41d4-a716")
        assert not rule.validator(123)


class TestIpAddressRule:
    """Test IP address validation rule."""

    def test_ipv4_valid(self) -> None:
        """Test valid IPv4 addresses."""
        rule = rules.ip_address(version="4")
        assert rule.validator("192.168.1.1")
        assert rule.validator("0.0.0.0")
        assert rule.validator("255.255.255.255")

    def test_ipv4_invalid(self) -> None:
        """Test invalid IPv4 addresses."""
        rule = rules.ip_address(version="4")
        assert not rule.validator("256.1.1.1")
        assert not rule.validator("192.168.1")
        assert not rule.validator("not.an.ip")

    def test_ipv6_valid(self) -> None:
        """Test valid IPv6 addresses."""
        rule = rules.ip_address(version="6")
        assert rule.validator("2001:0db8:85a3:0000:0000:8a2e:0370:7334")

    def test_ip_both_versions(self) -> None:
        """Test IPv4 or IPv6."""
        rule = rules.ip_address(version="both")
        assert rule.validator("192.168.1.1")
        assert rule.validator("2001:db8::1")


class TestDateFormatRule:
    """Test date format validation rule."""

    def test_valid_date(self) -> None:
        """Test valid date."""
        rule = rules.date_format("%Y-%m-%d")
        assert rule.validator("2024-01-15")
        assert rule.validator("2024-12-31")

    def test_invalid_date(self) -> None:
        """Test invalid date."""
        rule = rules.date_format("%Y-%m-%d")
        assert not rule.validator("2024-13-01")
        assert not rule.validator("2024-01-32")
        assert not rule.validator("01/15/2024")

    def test_custom_date_format(self) -> None:
        """Test custom date format."""
        rule = rules.date_format("%m/%d/%Y")
        assert rule.validator("01/15/2024")
        assert not rule.validator("2024-01-15")


class TestRangeRule:
    """Test range validation rule."""

    def test_valid_range(self) -> None:
        """Test value within range."""
        rule = rules.range_rule(0, 100)
        assert rule.validator(0)
        assert rule.validator(50)
        assert rule.validator(100)

    def test_outside_range(self) -> None:
        """Test value outside range."""
        rule = rules.range_rule(0, 100)
        assert not rule.validator(-1)
        assert not rule.validator(101)


class TestCompositeRules:
    """Test one_of and all_of composite rules."""

    def test_one_of(self) -> None:
        """Test one_of rule."""
        min_rule = rules.min_value(10)
        max_rule = rules.max_value(5)
        rule = rules.one_of([min_rule, max_rule])

        # Should pass either min or max
        assert rule.validator(15)  # Passes min_rule
        assert rule.validator(3)  # Passes max_rule

    def test_all_of(self) -> None:
        """Test all_of rule."""
        min_len = rules.min_length(5)
        max_len = rules.max_length(10)
        rule = rules.all_of([min_len, max_len])

        assert rule.validator("hello")
        assert not rule.validator("hi")
        assert not rule.validator("this is too long")


class TestCustomPredicate:
    """Test custom_predicate rule."""

    def test_custom_predicate(self) -> None:
        """Test custom predicate."""

        def is_even(x):
            return isinstance(x, int) and x % 2 == 0

        rule = rules.custom_predicate(is_even, name="even", message="Must be even")
        assert rule.validator(4)
        assert not rule.validator(5)

    def test_custom_predicate_in_schema(self) -> None:
        """Test custom predicate in schema."""
        schema = SchemaDefinition(
            type="object",
            properties={
                "count": SchemaDefinition(
                    type="integer",
                    rules=[
                        rules.custom_predicate(
                            lambda x: x > 0,
                            name="positive",
                            message="Must be positive",
                        ),
                    ],
                ),
            },
        )

        validator = Validator()
        result = validator.validate({"count": -5}, schema)

        assert not result.is_valid
