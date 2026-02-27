"""
Tests for backtracking matcher.

Tests backreferences, catastrophic backtracking protection, and greedy/lazy semantics.
"""

import pytest

from regex_engine.backtracking import BacktrackingMatcher
from regex_engine.parser import parse


class TestBackreferenceMatching:
    """Test backreference matching."""

    def test_simple_backreference(self) -> None:
        """Test simple backreference \\1."""
        ast = parse(r"(a)\1")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("aa")
        assert matched
        assert groups.get(1) == "a"

    def test_backreference_no_match(self) -> None:
        """Test backreference with no match."""
        ast = parse(r"(a)\1")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("ab")
        assert not matched

    def test_backreference_different_group_count(self) -> None:
        """Test backreference matching different count."""
        ast = parse(r"(ab)\1")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("abab")
        assert matched

    def test_multiple_backreferences(self) -> None:
        """Test multiple backreferences."""
        ast = parse(r"(a)(b)\1\2")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("abab")
        assert matched


class TestCatastrophicBacktrackingProtection:
    """Test protection against catastrophic backtracking."""

    def test_step_limit(self) -> None:
        """Test step limit prevents infinite backtracking."""
        # Pattern that could cause exponential backtracking
        ast = parse(r"(a+)+b")
        matcher = BacktrackingMatcher(ast, max_steps=100)

        # Should raise or handle gracefully with a string that doesn't match
        with pytest.raises(RuntimeError):
            matcher.match("aaaaaaaaaaaaaaaaaaaaaaac")

    def test_reasonable_pattern_succeeds(self) -> None:
        """Test reasonable patterns complete."""
        ast = parse(r"a+b")
        matcher = BacktrackingMatcher(ast, max_steps=1000)
        matched, end_pos, groups = matcher.match("aaab")
        assert matched


class TestGreedyVsLazy:
    """Test greedy vs lazy matching behavior."""

    def test_greedy_star(self) -> None:
        """Test greedy * quantifier."""
        ast = parse("a*")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("aaa")
        assert matched
        assert end_pos == 3  # Consumes all

    def test_lazy_star(self) -> None:
        """Test lazy *? quantifier."""
        ast = parse("a*?")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("aaa")
        assert matched
        assert end_pos == 0  # Consumes minimum (zero)

    def test_greedy_plus(self) -> None:
        """Test greedy + quantifier."""
        ast = parse("a+")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("aaa")
        assert matched
        assert end_pos == 3

    def test_lazy_plus(self) -> None:
        """Test lazy +? quantifier."""
        ast = parse("a+?")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("aaa")
        assert matched
        assert end_pos == 1  # Minimum one


class TestCaptureGroups:
    """Test capture group extraction."""

    def test_single_group_capture(self) -> None:
        """Test capturing single group."""
        ast = parse(r"(abc)")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("abc")
        assert matched
        assert groups.get(1) == "abc"

    def test_multiple_group_capture(self) -> None:
        """Test capturing multiple groups."""
        ast = parse(r"(a)(b)(c)")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("abc")
        assert matched
        assert groups.get(1) == "a"
        assert groups.get(2) == "b"
        assert groups.get(3) == "c"

    def test_nested_group_capture(self) -> None:
        """Test capturing nested groups."""
        ast = parse(r"(a(bc)d)")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("abcd")
        assert matched


class TestAlternationBacktracking:
    """Test alternation with backtracking."""

    def test_alternation_first_option(self) -> None:
        """Test alternation trying first option."""
        ast = parse("a|b")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("a")
        assert matched

    def test_alternation_second_option(self) -> None:
        """Test alternation trying second option."""
        ast = parse("a|b")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("b")
        assert matched

    def test_alternation_no_match(self) -> None:
        """Test alternation with no match."""
        ast = parse("a|b")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("c")
        assert not matched


class TestComplexBacktrackingPatterns:
    """Test complex patterns requiring backtracking."""

    def test_complex_quantifier_pattern(self) -> None:
        """Test complex quantifier pattern."""
        ast = parse(r"a*b+c?")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("aaabbc")
        assert matched

    def test_group_with_alternation(self) -> None:
        """Test group containing alternation."""
        ast = parse(r"(a|b)(c|d)")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("ac")
        assert matched

    def test_quantified_group(self) -> None:
        """Test quantified group."""
        ast = parse(r"(ab)+")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("ababab")
        assert matched


class TestSearchAndFindall:
    """Test search and findall with backtracking."""

    def test_search_operation(self) -> None:
        """Test search operation."""
        ast = parse(r"l+o")
        matcher = BacktrackingMatcher(ast)
        matched, start_pos, end_pos, groups = matcher.search("hello world")
        assert matched
        assert start_pos >= 0

    def test_search_no_match(self) -> None:
        """Test search with no match."""
        ast = parse(r"xyz")
        matcher = BacktrackingMatcher(ast)
        matched, start_pos, end_pos, groups = matcher.search("hello")
        assert not matched


class TestCharacterClassBacktracking:
    """Test character class matching with backtracking."""

    def test_char_class_match(self) -> None:
        """Test character class matching."""
        ast = parse(r"[abc]+")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("abaca")
        assert matched

    def test_negated_char_class(self) -> None:
        """Test negated character class."""
        ast = parse(r"[^abc]+")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("xyz")
        assert matched


class TestAnchorMatching:
    """Test anchor matching with backtracking."""

    def test_start_anchor(self) -> None:
        """Test start anchor matching."""
        ast = parse(r"^abc")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("abc")
        assert matched

    def test_end_anchor(self) -> None:
        """Test end anchor matching."""
        ast = parse(r"xyz$")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("xyz")
        assert matched

    def test_word_boundary(self) -> None:
        """Test word boundary matching."""
        ast = parse(r"\bword\b")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.search("the word is here")
        assert matched


class TestEdgeCases:
    """Test edge cases in backtracking."""

    def test_empty_match(self) -> None:
        """Test empty match."""
        ast = parse(r"a*")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("")
        assert matched

    def test_single_char(self) -> None:
        """Test single character."""
        ast = parse("a")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("a")
        assert matched

    def test_position_tracking(self) -> None:
        """Test position tracking."""
        ast = parse(r"abc")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("abc")
        assert matched
        assert end_pos == 3


class TestDotMatching:
    """Test dot matching with backtracking."""

    def test_dot_matches_char(self) -> None:
        """Test dot matches character."""
        ast = parse(".")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("x")
        assert matched

    def test_dot_not_newline(self) -> None:
        """Test dot doesn't match newline."""
        ast = parse(".")
        matcher = BacktrackingMatcher(ast)
        matched, end_pos, groups = matcher.match("\n")
        assert not matched
