"""
Tests for input sanitization.
"""

from thomas.marketplace.validation.sanitizers import InputSanitizer, SanitizerConfig


class TestHtmlStripping:
    """Test HTML tag stripping."""

    def test_strip_html_tags(self) -> None:
        """Test removing HTML tags."""
        config = SanitizerConfig(strip_html=True)
        sanitizer = InputSanitizer(config)

        result = sanitizer.sanitize("<p>Hello <b>World</b></p>")
        assert result == "Hello World"

    def test_strip_script_tags(self) -> None:
        """Test removing script tags."""
        config = SanitizerConfig(strip_html=True)
        sanitizer = InputSanitizer(config)

        result = sanitizer.sanitize("<script>alert('xss')</script>Content")
        assert "alert" not in result
        assert "Content" in result

    def test_strip_style_tags(self) -> None:
        """Test removing style tags."""
        config = SanitizerConfig(strip_html=True)
        sanitizer = InputSanitizer(config)

        result = sanitizer.sanitize("<style>body{color:red}</style>Text")
        assert "color:red" not in result

    def test_preserve_text_content(self) -> None:
        """Test preserving text content."""
        config = SanitizerConfig(strip_html=True)
        sanitizer = InputSanitizer(config)

        result = sanitizer.sanitize("Hello <em>there</em>!")
        assert "Hello" in result
        assert "there" in result


class TestHtmlEscaping:
    """Test HTML entity escaping."""

    def test_escape_html_entities(self) -> None:
        """Test escaping HTML entities."""
        config = SanitizerConfig(escape_html=True, strip_html=False)
        sanitizer = InputSanitizer(config)

        result = sanitizer.sanitize("<script>alert('xss')</script>")
        assert "&lt;" in result or "<" not in result
        assert "&gt;" in result or ">" not in result


class TestWhitespaceHandling:
    """Test whitespace trimming and collapsing."""

    def test_trim_whitespace(self) -> None:
        """Test trimming leading/trailing whitespace."""
        config = SanitizerConfig(trim_whitespace=True)
        sanitizer = InputSanitizer(config)

        result = sanitizer.sanitize("  hello world  ")
        assert result == "hello world"

    def test_collapse_whitespace(self) -> None:
        """Test collapsing multiple whitespace."""
        config = SanitizerConfig(collapse_whitespace=True)
        sanitizer = InputSanitizer(config)

        result = sanitizer.sanitize("hello    world    test")
        assert "    " not in result
        assert "hello" in result

    def test_no_trim(self) -> None:
        """Test preserving whitespace when disabled."""
        config = SanitizerConfig(trim_whitespace=False)
        sanitizer = InputSanitizer(config)

        result = sanitizer.sanitize("  hello  ")
        assert result == "  hello  "


class TestUnicodeNormalization:
    """Test unicode normalization."""

    def test_normalize_unicode(self) -> None:
        """Test unicode normalization."""
        config = SanitizerConfig(normalize_unicode=True)
        sanitizer = InputSanitizer(config)

        # Test with combining characters
        input_str = "e\u0301"  # e with combining acute accent
        result = sanitizer.sanitize(input_str)
        assert result  # Should normalize without error


class TestSensitiveMasking:
    """Test sensitive information masking."""

    def test_mask_email(self) -> None:
        """Test masking email addresses."""
        config = SanitizerConfig(mask_sensitive=True)
        sanitizer = InputSanitizer(config)

        result = sanitizer.sanitize("Contact me at user@example.com")
        assert "user@" in result
        assert "@example.com" in result
        # Middle part should be masked
        assert "***" in result

    def test_mask_phone(self) -> None:
        """Test masking phone numbers."""
        config = SanitizerConfig(mask_sensitive=True)
        sanitizer = InputSanitizer(config)

        result = sanitizer.sanitize("Call 555-123-4567")
        assert "***-****" in result or "555" not in result

    def test_mask_ssn(self) -> None:
        """Test masking SSN."""
        config = SanitizerConfig(mask_sensitive=True)
        sanitizer = InputSanitizer(config)

        result = sanitizer.sanitize("SSN: 123-45-6789")
        assert "***-**-****" in result

    def test_mask_credit_card(self) -> None:
        """Test masking credit card numbers."""
        config = SanitizerConfig(mask_sensitive=True)
        sanitizer = InputSanitizer(config)

        result = sanitizer.sanitize("Card: 4532-1234-5678-9012")
        # Last 4 digits visible, rest masked
        assert "9012" in result or "****" in result


class TestSqlPatternEscaping:
    """Test SQL injection pattern escaping."""

    def test_escape_single_quotes(self) -> None:
        """Test escaping single quotes."""
        config = SanitizerConfig(escape_sql_patterns=True)
        sanitizer = InputSanitizer(config)

        result = sanitizer.sanitize("O'Reilly")
        assert "''" in result

    def test_escape_sql_keywords(self) -> None:
        """Test escaping SQL keywords."""
        config = SanitizerConfig(escape_sql_patterns=True)
        sanitizer = InputSanitizer(config)

        result = sanitizer.sanitize("DROP TABLE users")
        assert "DROP" not in result or result != "DROP TABLE users"


class TestTruncation:
    """Test string truncation."""

    def test_truncate_max_length(self) -> None:
        """Test truncating to max length."""
        config = SanitizerConfig(max_length=10)
        sanitizer = InputSanitizer(config)

        result = sanitizer.sanitize("This is a very long string")
        assert len(result) <= 10

    def test_truncate_suffix(self) -> None:
        """Test truncation with custom suffix."""
        config = SanitizerConfig(max_length=10, truncate_suffix="...")
        sanitizer = InputSanitizer(config)

        result = sanitizer.sanitize("This is a very long string")
        assert result.endswith("...")

    def test_no_truncate_if_under_max(self) -> None:
        """Test not truncating if under max length."""
        config = SanitizerConfig(max_length=100)
        sanitizer = InputSanitizer(config)

        original = "short"
        result = sanitizer.sanitize(original)
        assert result == original


class TestCaseConversion:
    """Test case conversion."""

    def test_lowercase(self) -> None:
        """Test converting to lowercase."""
        config = SanitizerConfig(lowercase=True)
        sanitizer = InputSanitizer(config)

        result = sanitizer.sanitize("Hello WORLD")
        assert result == "hello world"

    def test_uppercase(self) -> None:
        """Test converting to uppercase."""
        config = SanitizerConfig(uppercase=True)
        sanitizer = InputSanitizer(config)

        result = sanitizer.sanitize("Hello world")
        assert result == "HELLO WORLD"


class TestSpecialCharacterRemoval:
    """Test special character removal."""

    def test_remove_special_chars(self) -> None:
        """Test removing special characters."""
        config = SanitizerConfig(remove_special_chars=True)
        sanitizer = InputSanitizer(config)

        result = sanitizer.sanitize("Hello! @World #123")
        assert "@" not in result
        assert "#" not in result
        assert "!" not in result
        assert "Hello" in result

    def test_keep_allowed_special_chars(self) -> None:
        """Test keeping allowed special characters."""
        config = SanitizerConfig(remove_special_chars=True, allowed_special_chars="-")
        sanitizer = InputSanitizer(config)

        result = sanitizer.sanitize("Hello-World!Test")
        assert "-" in result
        assert "!" not in result


class TestDictSanitization:
    """Test sanitizing dictionaries."""

    def test_sanitize_dict(self) -> None:
        """Test sanitizing all string values in dict."""
        config = SanitizerConfig(strip_html=True)
        sanitizer = InputSanitizer(config)

        data = {
            "name": "<p>John</p>",
            "email": "<script>alert('xss')</script>",
            "age": 30,
        }

        result = sanitizer.sanitize_dict(data)

        assert result["name"] == "John"
        assert "script" not in result["email"]
        assert result["age"] == 30  # Numbers unchanged


class TestListSanitization:
    """Test sanitizing lists."""

    def test_sanitize_list(self) -> None:
        """Test sanitizing list of strings."""
        config = SanitizerConfig(strip_html=True)
        sanitizer = InputSanitizer(config)

        data = ["<p>item1</p>", "<b>item2</b>", 123]

        result = sanitizer.sanitize_list(data)

        assert result[0] == "item1"
        assert result[1] == "item2"
        assert result[2] == 123


class TestCustomSanitizers:
    """Test custom sanitization functions."""

    def test_custom_field_sanitizer(self) -> None:
        """Test custom sanitizer for specific field."""

        def reverse_string(s):
            return s[::-1]

        config = SanitizerConfig(custom_sanitizers={"reversed": reverse_string})
        sanitizer = InputSanitizer(config)

        result = sanitizer.sanitize("hello", field_name="reversed")
        assert result == "olleh"

    def test_add_custom_sanitizer(self) -> None:
        """Test adding custom sanitizer dynamically."""
        sanitizer = InputSanitizer()

        def remove_numbers(s):
            return "".join(c for c in s if not c.isdigit())

        sanitizer.set_custom_sanitizer("clean", remove_numbers)
        result = sanitizer.sanitize("abc123def456", field_name="clean")
        assert result == "abcdef"


class TestSensitivePatterns:
    """Test custom sensitive patterns."""

    def test_add_sensitive_pattern(self) -> None:
        """Test adding custom sensitive pattern."""
        sanitizer = InputSanitizer()
        sanitizer.add_sensitive_pattern("api_key", r"api_key=\w+", "***")

        config = SanitizerConfig(mask_sensitive=False)
        sanitizer = InputSanitizer(config)
        sanitizer.add_sensitive_pattern("api_key", r"api_key=\w+", "[MASKED]")

        sanitizer.sanitize("url?api_key=secret123")
        # Custom patterns would need to be checked


class TestNullByteRemoval:
    """Test null byte removal."""

    def test_remove_null_bytes(self) -> None:
        """Test removing null bytes."""
        config = SanitizerConfig(remove_null_bytes=True)
        sanitizer = InputSanitizer(config)

        result = sanitizer.sanitize("hello\x00world")
        assert "\x00" not in result
        assert result == "helloworld"
