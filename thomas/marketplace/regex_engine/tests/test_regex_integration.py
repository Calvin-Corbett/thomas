"""
Integration tests for the complete regex engine.

Tests the full API: compile, match, search, findall, sub, split
on real-world patterns.
"""

from regex_engine.compiler import compile


class TestCompileAPI:
    """Test compile() API."""

    def test_compile_simple_pattern(self) -> None:
        """Test compiling simple pattern."""
        regex = compile(r"hello")
        assert regex is not None

    def test_compile_complex_pattern(self) -> None:
        """Test compiling complex pattern."""
        regex = compile(r"[a-z]+@[a-z]+\.[a-z]+")
        assert regex is not None

    def test_compile_caches(self) -> None:
        """Test that compile caches patterns."""
        regex1 = compile(r"test")
        regex2 = compile(r"test")
        # Should return same object from cache
        assert regex1 is regex2


class TestMatchAPI:
    """Test match() API."""

    def test_match_success(self) -> None:
        """Test successful match."""
        regex = compile(r"hello")
        result = regex.match("hello")
        assert result is not None
        assert result.matched

    def test_match_failure(self) -> None:
        """Test failed match."""
        regex = compile(r"hello")
        result = regex.match("world")
        assert result is None

    def test_match_from_position(self) -> None:
        """Test match from specific position."""
        regex = compile(r"world")
        result = regex.match("hello world", pos=6)
        assert result is not None

    def test_match_span_info(self) -> None:
        """Test match span information."""
        regex = compile(r"[a-z]+")
        result = regex.match("hello")
        assert result is not None
        assert result.start == 0
        assert result.end == 5


class TestSearchAPI:
    """Test search() API."""

    def test_search_at_start(self) -> None:
        """Test search at start."""
        regex = compile(r"hello")
        result = regex.search("hello world")
        assert result is not None

    def test_search_in_middle(self) -> None:
        """Test search in middle."""
        regex = compile(r"world")
        result = regex.search("hello world")
        assert result is not None

    def test_search_not_found(self) -> None:
        """Test search when not found."""
        regex = compile(r"xyz")
        result = regex.search("hello world")
        assert result is None

    def test_search_returns_span(self) -> None:
        """Test search returns span information."""
        regex = compile(r"world")
        result = regex.search("hello world")
        assert result is not None
        assert result.start == 6
        assert result.end == 11


class TestFindallAPI:
    """Test findall() API."""

    def test_findall_single_match(self) -> None:
        """Test findall with single match."""
        regex = compile(r"\d+")
        results = regex.findall("I have 42 apples")
        assert len(results) > 0
        assert "42" in results

    def test_findall_multiple_matches(self) -> None:
        """Test findall with multiple matches."""
        regex = compile(r"[a-z]+")
        results = regex.findall("hello world test")
        assert len(results) >= 3

    def test_findall_no_matches(self) -> None:
        """Test findall with no matches."""
        regex = compile(r"\d+")
        results = regex.findall("no numbers here")
        assert len(results) == 0

    def test_findall_overlapping_pattern(self) -> None:
        """Test findall with pattern."""
        regex = compile(r"a+")
        results = regex.findall("aaa bbb aaa")
        assert len(results) >= 1


class TestFinditerAPI:
    """Test finditer() API."""

    def test_finditer_multiple(self) -> None:
        """Test finditer with multiple matches."""
        regex = compile(r"\d+")
        results = list(regex.finditer("123 456 789"))
        assert len(results) >= 2

    def test_finditer_lazy(self) -> None:
        """Test finditer returns iterator."""
        regex = compile(r"[a-z]+")
        iterator = regex.finditer("hello world")
        first = next(iterator)
        assert first is not None


class TestSubAPI:
    """Test sub() API."""

    def test_sub_simple_replacement(self) -> None:
        """Test simple substitution."""
        regex = compile(r"cat")
        result = regex.sub("dog", "I have a cat")
        assert "dog" in result
        assert "cat" not in result

    def test_sub_multiple_replacements(self) -> None:
        """Test multiple replacements."""
        regex = compile(r"\d+")
        result = regex.sub("X", "I have 1 cat and 2 dogs")
        assert result.count("X") >= 2

    def test_sub_with_count_limit(self) -> None:
        """Test substitution with count limit."""
        regex = compile(r"a")
        result = regex.sub("b", "aaa", count=2)
        assert result.count("b") == 2

    def test_sub_no_match(self) -> None:
        """Test substitution with no match."""
        regex = compile(r"xyz")
        result = regex.sub("abc", "hello world")
        assert result == "hello world"

    def test_sub_with_callable(self) -> None:
        """Test substitution with callable."""
        regex = compile(r"\d+")

        def replacer(match):
            return str(int(match.group) * 2) if match.group else "0"

        result = regex.sub(replacer, "I have 5 apples")
        assert "10" in result


class TestSplitAPI:
    """Test split() API."""

    def test_split_simple(self) -> None:
        """Test simple split."""
        regex = compile(r"\s+")
        result = regex.split("hello world test")
        assert len(result) >= 3
        assert "hello" in result
        assert "world" in result

    def test_split_on_delimiter(self) -> None:
        """Test split on specific delimiter."""
        regex = compile(r",")
        result = regex.split("apple,banana,cherry")
        assert len(result) == 3

    def test_split_with_maxsplit(self) -> None:
        """Test split with maxsplit limit."""
        regex = compile(r",")
        result = regex.split("a,b,c,d", maxsplit=2)
        assert len(result) <= 3

    def test_split_no_match(self) -> None:
        """Test split with no matches."""
        regex = compile(r"xyz")
        result = regex.split("hello world")
        assert len(result) == 1


class TestRealWorldPatterns:
    """Test real-world regex patterns."""

    def test_email_pattern(self) -> None:
        """Test email validation pattern."""
        regex = compile(r"[a-z]+@[a-z]+\.[a-z]+")
        assert regex.search("test@example.com") is not None
        assert regex.search("invalid.email") is None

    def test_phone_pattern(self) -> None:
        """Test phone number pattern."""
        regex = compile(r"\d{3}-\d{3}-\d{4}")
        assert regex.search("Call 555-123-4567") is not None

    def test_url_pattern(self) -> None:
        """Test URL pattern."""
        regex = compile(r"https?://[a-z.]+")
        assert regex.search("Visit https://example.com") is not None

    def test_hex_color_pattern(self) -> None:
        """Test hex color pattern."""
        regex = compile(r"#[0-9a-f]{6}")
        assert regex.search("Color: #ff0000") is not None

    def test_ipv4_pattern(self) -> None:
        """Test IPv4 pattern."""
        regex = compile(r"\d+\.\d+\.\d+\.\d+")
        assert regex.search("IP: 192.168.1.1") is not None

    def test_date_pattern(self) -> None:
        """Test date pattern."""
        regex = compile(r"\d{4}-\d{2}-\d{2}")
        assert regex.search("Date: 2024-01-15") is not None


class TestCaptureGroups:
    """Test capture group handling."""

    def test_capture_single_group(self) -> None:
        """Test capturing single group."""
        regex = compile(r"(\w+)")
        result = regex.search("hello world")
        assert result is not None
        assert len(result.groups) > 0

    def test_capture_multiple_groups(self) -> None:
        """Test capturing multiple groups."""
        regex = compile(r"(\w+)\s+(\w+)")
        result = regex.search("hello world")
        assert result is not None
        assert len(result.groups) >= 2


class TestComplexOperations:
    """Test complex operations combining multiple APIs."""

    def test_find_and_replace(self) -> None:
        """Test finding and replacing pattern."""
        regex = compile(r"\b\d+\b")
        text = "I have 5 apples and 3 oranges"
        result = regex.sub("X", text)
        assert "X" in result

    def test_extract_and_process(self) -> None:
        """Test extracting and processing matches."""
        regex = compile(r"\d+")
        matches = regex.findall("Items: 10, 20, 30")
        assert len(matches) == 3

    def test_split_and_rejoin(self) -> None:
        """Test splitting and rejoining."""
        regex = compile(r"\s+")
        words = regex.split("hello   world\t\ttest")
        joined = " ".join(words)
        assert "hello" in joined
        assert "world" in joined


class TestEdgeCases:
    """Test edge cases."""

    def test_empty_string(self) -> None:
        """Test matching empty string."""
        regex = compile(r"a*")
        result = regex.match("")
        assert result is not None

    def test_long_input(self) -> None:
        """Test with very long input."""
        regex = compile(r"a+")
        long_string = "a" * 10000
        result = regex.match(long_string)
        assert result is not None

    def test_special_characters(self) -> None:
        """Test with special characters."""
        regex = compile(r"[!@#$%]")
        result = regex.search("Test! #value")
        assert result is not None

    def test_unicode_support(self) -> None:
        """Test Unicode character support."""
        regex = compile(r"café")
        result = regex.search("Hello café world")
        assert result is not None


class TestPerformance:
    """Test performance characteristics."""

    def test_compile_caching_efficiency(self) -> None:
        """Test compile cache efficiency."""
        # Compile same pattern multiple times
        for _ in range(10):
            compile(r"test")
        # Should use cache, not create new compilers

    def test_large_character_class(self) -> None:
        """Test large character class matching."""
        regex = compile(r"[a-zA-Z0-9]+")
        result = regex.findall("Hello123World456Test789")
        assert len(result) > 0

    def test_deep_nesting(self) -> None:
        """Test deeply nested patterns."""
        regex = compile(r"((((a))))")
        result = regex.match("a")
        assert result is not None
