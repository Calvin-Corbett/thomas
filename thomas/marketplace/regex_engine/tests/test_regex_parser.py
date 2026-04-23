"""
Tests for regex parser.

Tests all regex syntax including literals, character classes, quantifiers,
groups, anchors, and escape sequences.
"""

import pytest

from regex_engine._exceptions import ParseError
from regex_engine._types import (
    Alternation,
    Anchor,
    CharClass,
    Concatenation,
    Dot,
    Group,
    Literal,
    Quantifier,
)
from regex_engine.parser import parse


class TestLiterals:
    """Test parsing of literal characters."""

    def test_single_literal(self) -> None:
        """Parse single literal character."""
        ast = parse("a")
        assert isinstance(ast, Literal)
        assert ast.char == "a"

    def test_multiple_literals(self) -> None:
        """Parse multiple literals as concatenation."""
        ast = parse("abc")
        assert isinstance(ast, Concatenation)
        assert len(ast.nodes) == 3
        assert all(isinstance(node, Literal) for node in ast.nodes)

    def test_special_characters(self) -> None:
        """Parse special literal characters."""
        ast = parse("!@#$%")
        assert isinstance(ast, Concatenation)
        assert len(ast.nodes) == 5


class TestCharacterClasses:
    """Test parsing of character classes."""

    def test_simple_char_class(self) -> None:
        """Parse simple character class [abc]."""
        ast = parse("[abc]")
        assert isinstance(ast, CharClass)
        assert "a" in ast.chars
        assert "b" in ast.chars
        assert "c" in ast.chars
        assert not ast.negated

    def test_negated_char_class(self) -> None:
        """Parse negated character class [^abc]."""
        ast = parse("[^abc]")
        assert isinstance(ast, CharClass)
        assert ast.negated

    def test_char_class_range(self) -> None:
        """Parse character class with range [a-z]."""
        ast = parse("[a-z]")
        assert isinstance(ast, CharClass)
        assert ("a", "z") in ast.ranges

    def test_char_class_multiple_ranges(self) -> None:
        """Parse character class with multiple ranges."""
        ast = parse("[a-zA-Z0-9]")
        assert isinstance(ast, CharClass)
        assert len(ast.ranges) == 3

    def test_char_class_with_dash(self) -> None:
        """Parse character class containing dash."""
        ast = parse("[a-]")
        assert isinstance(ast, CharClass)
        assert "a" in ast.chars or ("a", "-") in ast.ranges

    def test_char_class_escape_sequences(self) -> None:
        """Parse character class with escape sequences."""
        ast = parse(r"[\d\w\s]")
        assert isinstance(ast, CharClass)
        assert "d" in ast.escape_classes
        assert "w" in ast.escape_classes
        assert "s" in ast.escape_classes


class TestQuantifiers:
    """Test parsing of quantifiers."""

    def test_star_quantifier(self) -> None:
        """Parse * quantifier."""
        ast = parse("a*")
        assert isinstance(ast, Quantifier)
        assert ast.min_count == 0
        assert ast.max_count is None
        assert not ast.lazy

    def test_plus_quantifier(self) -> None:
        """Parse + quantifier."""
        ast = parse("a+")
        assert isinstance(ast, Quantifier)
        assert ast.min_count == 1
        assert ast.max_count is None
        assert not ast.lazy

    def test_question_quantifier(self) -> None:
        """Parse ? quantifier."""
        ast = parse("a?")
        assert isinstance(ast, Quantifier)
        assert ast.min_count == 0
        assert ast.max_count == 1
        assert not ast.lazy

    def test_lazy_star(self) -> None:
        """Parse lazy *? quantifier."""
        ast = parse("a*?")
        assert isinstance(ast, Quantifier)
        assert ast.lazy

    def test_lazy_plus(self) -> None:
        """Parse lazy +? quantifier."""
        ast = parse("a+?")
        assert isinstance(ast, Quantifier)
        assert ast.lazy

    def test_lazy_question(self) -> None:
        """Parse lazy ?? quantifier."""
        ast = parse("a??")
        assert isinstance(ast, Quantifier)
        assert ast.lazy

    def test_exact_count(self) -> None:
        """Parse exact count {n}."""
        ast = parse("a{3}")
        assert isinstance(ast, Quantifier)
        assert ast.min_count == 3
        assert ast.max_count == 3

    def test_range_count(self) -> None:
        """Parse range count {n,m}."""
        ast = parse("a{2,5}")
        assert isinstance(ast, Quantifier)
        assert ast.min_count == 2
        assert ast.max_count == 5

    def test_unbounded_count(self) -> None:
        """Parse unbounded count {n,}."""
        ast = parse("a{2,}")
        assert isinstance(ast, Quantifier)
        assert ast.min_count == 2
        assert ast.max_count is None


class TestAnchors:
    """Test parsing of anchors."""

    def test_start_anchor(self) -> None:
        """Parse ^ anchor."""
        ast = parse("^a")
        assert isinstance(ast, Concatenation)
        first = ast.nodes[0]
        assert isinstance(first, Anchor)
        assert first.anchor_type == "start"

    def test_end_anchor(self) -> None:
        """Parse $ anchor."""
        ast = parse("a$")
        assert isinstance(ast, Concatenation)
        last = ast.nodes[-1]
        assert isinstance(last, Anchor)
        assert last.anchor_type == "end"

    def test_word_boundary(self) -> None:
        """Parse \\b word boundary."""
        ast = parse(r"\ba\b")
        assert isinstance(ast, Concatenation)
        assert len(ast.nodes) == 3


class TestGroups:
    """Test parsing of groups."""

    def test_capturing_group(self) -> None:
        """Parse capturing group (...)."""
        ast = parse("(abc)")
        assert isinstance(ast, Group)
        assert ast.is_capturing
        assert ast.group_id == 1

    def test_non_capturing_group(self) -> None:
        """Parse non-capturing group (?:...)."""
        ast = parse("(?:abc)")
        assert isinstance(ast, Group)
        assert not ast.is_capturing

    def test_nested_groups(self) -> None:
        """Parse nested groups."""
        ast = parse("(a(bc)d)")
        assert isinstance(ast, Group)
        assert isinstance(ast.node, Concatenation)

    def test_multiple_groups(self) -> None:
        """Parse multiple groups."""
        ast = parse("(a)(b)")
        assert isinstance(ast, Concatenation)
        assert len(ast.nodes) == 2
        assert all(isinstance(node, Group) for node in ast.nodes)


class TestAlternation:
    """Test parsing of alternation."""

    def test_simple_alternation(self) -> None:
        """Parse alternation a|b."""
        ast = parse("a|b")
        assert isinstance(ast, Alternation)
        assert len(ast.nodes) == 2

    def test_multiple_alternation(self) -> None:
        """Parse multiple alternation a|b|c."""
        ast = parse("a|b|c")
        assert isinstance(ast, Alternation)
        assert len(ast.nodes) == 3

    def test_alternation_with_groups(self) -> None:
        """Parse alternation with groups."""
        ast = parse("(ab)|(cd)")
        assert isinstance(ast, Alternation)
        assert all(isinstance(node, Group) for node in ast.nodes)


class TestEscapeSequences:
    """Test parsing of escape sequences."""

    def test_escape_digit_class(self) -> None:
        """Parse \\d digit class."""
        ast = parse(r"\d")
        assert isinstance(ast, CharClass)
        assert "d" in ast.escape_classes

    def test_escape_word_class(self) -> None:
        """Parse \\w word class."""
        ast = parse(r"\w")
        assert isinstance(ast, CharClass)
        assert "w" in ast.escape_classes

    def test_escape_whitespace_class(self) -> None:
        """Parse \\s whitespace class."""
        ast = parse(r"\s")
        assert isinstance(ast, CharClass)
        assert "s" in ast.escape_classes

    def test_escape_special_chars(self) -> None:
        """Parse escaped special characters."""
        ast = parse(r"\.\*\+\?")
        assert isinstance(ast, Concatenation)
        assert len(ast.nodes) == 4
        assert all(isinstance(node, Literal) for node in ast.nodes)

    def test_escape_newline(self) -> None:
        """Parse \\n newline."""
        ast = parse(r"\n")
        assert isinstance(ast, Literal)
        assert ast.char == "\n"

    def test_escape_tab(self) -> None:
        """Parse \\t tab."""
        ast = parse(r"\t")
        assert isinstance(ast, Literal)
        assert ast.char == "\t"


class TestDot:
    """Test parsing of dot."""

    def test_dot(self) -> None:
        """Parse . (any character)."""
        ast = parse(".")
        assert isinstance(ast, Dot)

    def test_dot_in_concatenation(self) -> None:
        """Parse dot in concatenation."""
        ast = parse("a.b")
        assert isinstance(ast, Concatenation)
        assert isinstance(ast.nodes[1], Dot)


class TestPrecedence:
    """Test operator precedence."""

    def test_quantifier_before_concatenation(self) -> None:
        """Quantifier binds tighter than concatenation."""
        ast = parse("ab*c")
        assert isinstance(ast, Concatenation)
        assert len(ast.nodes) == 3
        assert isinstance(ast.nodes[1], Quantifier)

    def test_concatenation_before_alternation(self) -> None:
        """Concatenation binds tighter than alternation."""
        ast = parse("ab|cd")
        assert isinstance(ast, Alternation)
        assert len(ast.nodes) == 2
        assert all(isinstance(node, Concatenation) for node in ast.nodes)

    def test_complex_precedence(self) -> None:
        """Test complex precedence."""
        ast = parse("a*|b+")
        assert isinstance(ast, Alternation)
        assert isinstance(ast.nodes[0], Quantifier)
        assert isinstance(ast.nodes[1], Quantifier)


class TestEdgeCases:
    """Test edge cases."""

    def test_empty_alternation_branches(self) -> None:
        """Test alternation with empty branches."""
        # This should raise or handle gracefully
        with pytest.raises(ParseError):
            parse("|a")

    def test_unclosed_group(self) -> None:
        """Test unclosed group."""
        with pytest.raises(ParseError):
            parse("(a")

    def test_unclosed_bracket(self) -> None:
        """Test unclosed bracket."""
        with pytest.raises(ParseError):
            parse("[abc")

    def test_invalid_quantifier(self) -> None:
        """Test invalid quantifier at start."""
        with pytest.raises(ParseError):
            parse("*a")

    def test_complex_pattern(self) -> None:
        """Test complex pattern."""
        ast = parse(r"^[a-zA-Z_]\w*@[a-z]+\.[a-z]+$")
        assert ast is not None
