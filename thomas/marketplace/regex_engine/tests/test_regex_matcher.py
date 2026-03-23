"""
Comprehensive tests for regex matching.

Tests all matching features: literals, character classes, quantifiers,
groups, capture groups, anchors, and edge cases.
"""

from regex_engine.matcher import NFAMatcher
from regex_engine.nfa import build_nfa
from regex_engine.parser import parse


class TestLiteralMatching:
    """Test matching of literal patterns."""

    def test_exact_match(self) -> None:
        """Test exact literal match."""
        ast = parse("hello")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        result = matcher.match("hello")
        assert result is not None
        assert result.matched

    def test_no_match(self) -> None:
        """Test no match."""
        ast = parse("hello")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        result = matcher.match("world")
        assert result is None

    def test_partial_match(self) -> None:
        """Test partial match (should not match full string)."""
        ast = parse("hello")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        result = matcher.match("hello world")
        # Match should succeed (matching at start)
        assert result is not None


class TestCharacterClasses:
    """Test character class matching."""

    def test_simple_char_class(self) -> None:
        """Test simple character class [abc]."""
        ast = parse("[abc]")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        assert matcher.match("a") is not None
        assert matcher.match("b") is not None
        assert matcher.match("c") is not None
        assert matcher.match("d") is None

    def test_negated_char_class(self) -> None:
        """Test negated character class [^abc]."""
        ast = parse("[^abc]")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        assert matcher.match("a") is None
        assert matcher.match("d") is not None

    def test_range_char_class(self) -> None:
        """Test character class with range [a-z]."""
        ast = parse("[a-z]")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        assert matcher.match("a") is not None
        assert matcher.match("z") is not None
        assert matcher.match("m") is not None
        assert matcher.match("A") is None

    def test_digit_class(self) -> None:
        """Test digit class \\d."""
        ast = parse(r"\d")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        assert matcher.match("5") is not None
        assert matcher.match("a") is None

    def test_word_class(self) -> None:
        """Test word class \\w."""
        ast = parse(r"\w")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        assert matcher.match("a") is not None
        assert matcher.match("5") is not None
        assert matcher.match("_") is not None


class TestQuantifiers:
    """Test quantifier matching."""

    def test_star_quantifier(self) -> None:
        """Test * quantifier (zero or more)."""
        ast = parse("a*")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        assert matcher.match("") is not None  # Empty
        assert matcher.match("a") is not None
        assert matcher.match("aaa") is not None

    def test_plus_quantifier(self) -> None:
        """Test + quantifier (one or more)."""
        ast = parse("a+")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        assert matcher.match("") is None  # Empty, no match
        assert matcher.match("a") is not None
        assert matcher.match("aaa") is not None

    def test_question_quantifier(self) -> None:
        """Test ? quantifier (zero or one)."""
        ast = parse("a?")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        assert matcher.match("") is not None
        assert matcher.match("a") is not None

    def test_exact_count_quantifier(self) -> None:
        """Test {n} quantifier."""
        ast = parse("a{3}")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        assert matcher.match("aa") is None
        assert matcher.match("aaa") is not None

    def test_range_quantifier(self) -> None:
        """Test {n,m} quantifier."""
        ast = parse("a{2,4}")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        assert matcher.match("a") is None
        assert matcher.match("aa") is not None
        assert matcher.match("aaa") is not None


class TestDot:
    """Test dot (any character) matching."""

    def test_dot_matches_single_char(self) -> None:
        """Test . matches any character."""
        ast = parse(".")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        assert matcher.match("a") is not None
        assert matcher.match("5") is not None
        assert matcher.match(" ") is not None

    def test_dot_not_newline(self) -> None:
        """Test . does not match newline."""
        ast = parse(".")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        assert matcher.match("\n") is None


class TestAnchors:
    """Test anchor matching."""

    def test_start_anchor(self) -> None:
        """Test ^ anchor."""
        ast = parse("^hello")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        assert matcher.match("hello") is not None
        assert matcher.match("xhello") is None

    def test_end_anchor(self) -> None:
        """Test $ anchor."""
        ast = parse("world$")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        assert matcher.match("world") is not None
        assert matcher.match("worldx") is None


class TestGroups:
    """Test group matching."""

    def test_capturing_group(self) -> None:
        """Test capturing group (...)."""
        ast = parse("(abc)")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        result = matcher.match("abc")
        assert result is not None
        assert result.matched

    def test_non_capturing_group(self) -> None:
        """Test non-capturing group (?:...)."""
        ast = parse("(?:abc)")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        result = matcher.match("abc")
        assert result is not None


class TestAlternation:
    """Test alternation matching."""

    def test_simple_alternation(self) -> None:
        """Test a|b alternation."""
        ast = parse("a|b")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        assert matcher.match("a") is not None
        assert matcher.match("b") is not None
        assert matcher.match("c") is None

    def test_alternation_with_quantifiers(self) -> None:
        """Test (a+|b*) alternation."""
        ast = parse("a+|b*")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        assert matcher.match("a") is not None
        assert matcher.match("b") is not None
        assert matcher.match("") is not None  # b* matches empty


class TestSearch:
    """Test search functionality."""

    def test_search_in_middle(self) -> None:
        """Test search finding match in middle of text."""
        ast = parse("world")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        result = matcher.search("hello world")
        assert result is not None
        assert result.matched

    def test_search_at_start(self) -> None:
        """Test search finding match at start."""
        ast = parse("hello")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        result = matcher.search("hello world")
        assert result is not None

    def test_search_no_match(self) -> None:
        """Test search with no match."""
        ast = parse("xyz")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        result = matcher.search("hello world")
        assert result is None


class TestFindall:
    """Test findall functionality."""

    def test_findall_single_match(self) -> None:
        """Test findall with single match."""
        ast = parse(r"\d+")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        results = matcher.findall("The year is 2024")
        assert len(results) > 0

    def test_findall_multiple_matches(self) -> None:
        """Test findall with multiple matches."""
        ast = parse(r"[a-z]+")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        results = matcher.findall("hello world test")
        assert len(results) >= 3

    def test_findall_no_match(self) -> None:
        """Test findall with no matches."""
        ast = parse(r"\d+")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        results = matcher.findall("no digits here")
        assert len(results) == 0


class TestFinditer:
    """Test finditer functionality."""

    def test_finditer_multiple_matches(self) -> None:
        """Test finditer with multiple matches."""
        ast = parse(r"\d+")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        results = list(matcher.finditer("123 456 789"))
        assert len(results) >= 2


class TestComplexPatterns:
    """Test complex pattern matching."""

    def test_email_like_pattern(self) -> None:
        """Test email-like pattern."""
        ast = parse(r"[a-z]+@[a-z]+")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        result = matcher.search("contact: test@example")
        assert result is not None

    def test_phone_like_pattern(self) -> None:
        """Test phone-like pattern."""
        ast = parse(r"\d{3}-\d{3}-\d{4}")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        result = matcher.search("Call: 555-123-4567")
        assert result is not None

    def test_url_like_pattern(self) -> None:
        """Test URL-like pattern."""
        ast = parse(r"[a-z]+://[a-z.]+")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        result = matcher.search("Visit https://example.com")
        assert result is not None


class TestEdgeCases:
    """Test edge cases."""

    def test_empty_string_match(self) -> None:
        """Test matching empty string with a*."""
        ast = parse("a*")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        result = matcher.match("")
        assert result is not None

    def test_single_character(self) -> None:
        """Test single character matching."""
        ast = parse("x")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        assert matcher.match("x") is not None
        assert matcher.match("y") is None

    def test_very_long_string(self) -> None:
        """Test matching with long string."""
        ast = parse("a+")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        long_string = "a" * 1000
        result = matcher.match(long_string)
        assert result is not None

    def test_unicode_characters(self) -> None:
        """Test matching Unicode characters."""
        ast = parse("café")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        result = matcher.search("hello café world")
        assert result is not None


class TestGreedyVsLazy:
    """Test greedy vs lazy matching."""

    def test_greedy_quantifier(self) -> None:
        """Test greedy quantifier (default)."""
        ast = parse("a*")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        result = matcher.match("aaaa")
        assert result is not None
        # Greedy should consume all

    def test_lazy_quantifier(self) -> None:
        """Test lazy quantifier."""
        ast = parse("a*?")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        result = matcher.match("aaaa")
        assert result is not None


class TestPositionalMatching:
    """Test positional matching variations."""

    def test_match_from_position(self) -> None:
        """Test matching from specific position."""
        ast = parse("world")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        result = matcher.match("hello world", pos=6)
        assert result is not None

    def test_match_span(self) -> None:
        """Test match span information."""
        ast = parse(r"[a-z]+")
        nfa = build_nfa(ast)
        matcher = NFAMatcher(nfa)
        result = matcher.search("abc def")
        assert result is not None
        assert result.start >= 0
        assert result.end > result.start
