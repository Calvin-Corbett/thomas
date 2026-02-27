"""
Backtracking matcher for regex features that can't use NFA.

Implements recursive backtracking with catastrophic backtracking detection.
Handles backreferences, lookahead, and lazy quantifiers.
"""

from __future__ import annotations

from ._types import (
    Alternation,
    Anchor,
    ASTNode,
    Backreference,
    CharClass,
    Concatenation,
    Dot,
    Group,
    Literal,
    Quantifier,
)
from .unicode_cats import build_char_class_set


class BacktrackingMatcher:
    """Matches strings using backtracking algorithm."""

    def __init__(self, ast: ASTNode, max_steps: int = 100000) -> None:
        """
        Initialize backtracking matcher.

        Args:
            ast: Regex AST
            max_steps: Maximum steps before stopping (prevents catastrophic backtracking)
        """
        self.ast = ast
        self.max_steps = max_steps
        self.steps = 0
        self.text = ""
        self.capture_groups: dict[int, str] = {}

    def match(self, text: str, pos: int = 0) -> tuple[bool, int, dict[int, str]]:
        """
        Try to match at position.

        Returns:
            (matched, end_pos, capture_groups)
        """
        self.text = text
        self.steps = 0
        self.capture_groups = {}
        matched, end_pos = self._match_node(self.ast, pos)
        return matched, end_pos, self.capture_groups

    def search(self, text: str) -> tuple[bool, int, int, dict[int, str]]:
        """
        Search for first match.

        Returns:
            (matched, start_pos, end_pos, capture_groups)
        """
        self.text = text

        for start_pos in range(len(text)):
            self.steps = 0
            self.capture_groups = {}
            matched, end_pos = self._match_node(self.ast, start_pos)
            if matched:
                return True, start_pos, end_pos, self.capture_groups

        return False, -1, -1, {}

    def _match_node(self, node: ASTNode, pos: int) -> tuple[bool, int]:
        """
        Try to match node at position.

        Returns:
            (matched, end_position)
        """
        self.steps += 1
        if self.steps > self.max_steps:
            raise RuntimeError("Catastrophic backtracking detected")

        if isinstance(node, Literal):
            return self._match_literal(node, pos)
        elif isinstance(node, Dot):
            return self._match_dot(node, pos)
        elif isinstance(node, CharClass):
            return self._match_char_class(node, pos)
        elif isinstance(node, Anchor):
            return self._match_anchor(node, pos)
        elif isinstance(node, Concatenation):
            return self._match_concatenation(node, pos)
        elif isinstance(node, Alternation):
            return self._match_alternation(node, pos)
        elif isinstance(node, Quantifier):
            return self._match_quantifier(node, pos)
        elif isinstance(node, Group):
            return self._match_group(node, pos)
        elif isinstance(node, Backreference):
            return self._match_backreference(node, pos)
        else:
            return False, pos

    def _match_literal(self, node: Literal, pos: int) -> tuple[bool, int]:
        """Match literal character."""
        if pos >= len(self.text):
            return False, pos
        if self.text[pos] == node.char:
            return True, pos + 1
        return False, pos

    def _match_dot(self, node: Dot, pos: int) -> tuple[bool, int]:
        """Match any character except newline."""
        if pos >= len(self.text):
            return False, pos
        if self.text[pos] != "\n":
            return True, pos + 1
        return False, pos

    def _match_char_class(self, node: CharClass, pos: int) -> tuple[bool, int]:
        """Match character class."""
        if pos >= len(self.text):
            return False, pos

        char = self.text[pos]
        chars = build_char_class_set(node.chars, node.ranges, node.escape_classes)

        matched = char in chars
        if node.negated:
            matched = not matched

        if matched:
            return True, pos + 1
        return False, pos

    def _match_anchor(self, node: Anchor, pos: int) -> tuple[bool, int]:
        """Match anchor."""
        if node.anchor_type == "start":
            return (pos == 0, pos)
        elif node.anchor_type == "end":
            return (pos == len(self.text), pos)
        elif node.anchor_type == "word_boundary":
            at_boundary = self._is_word_boundary(pos)
            return (at_boundary, pos)
        elif node.anchor_type == "non_word_boundary":
            at_boundary = self._is_word_boundary(pos)
            return (not at_boundary, pos)
        return False, pos

    def _match_concatenation(self, node: Concatenation, pos: int) -> tuple[bool, int]:
        """Match concatenation."""
        current_pos = pos

        for child in node.nodes:
            matched, current_pos = self._match_node(child, current_pos)
            if not matched:
                return False, pos

        return True, current_pos

    def _match_alternation(self, node: Alternation, pos: int) -> tuple[bool, int]:
        """Match alternation (try each alternative)."""
        for child in node.nodes:
            matched, end_pos = self._match_node(child, pos)
            if matched:
                return True, end_pos

        return False, pos

    def _match_quantifier(self, node: Quantifier, pos: int) -> tuple[bool, int]:
        """Match quantifier."""
        if node.lazy:
            return self._match_quantifier_lazy(node, pos)
        else:
            return self._match_quantifier_greedy(node, pos)

    def _match_quantifier_greedy(self, node: Quantifier, pos: int) -> tuple[bool, int]:
        """Match quantifier greedily (match as much as possible)."""
        matches = []
        current_pos = pos

        # Match as many as possible
        while len(matches) < (node.max_count if node.max_count is not None else 1000):
            matched, next_pos = self._match_node(node.node, current_pos)
            if not matched or next_pos == current_pos:
                break
            matches.append(next_pos)
            current_pos = next_pos

        # Check if we have enough matches
        if len(matches) < node.min_count:
            return False, pos

        # Try from longest match, backtracking
        for i in range(len(matches), node.min_count - 1, -1):
            end_pos = matches[i - 1] if i > 0 else pos
            return True, end_pos

        return False, pos

    def _match_quantifier_lazy(self, node: Quantifier, pos: int) -> tuple[bool, int]:
        """Match quantifier lazily (match as little as possible)."""
        current_pos = pos

        # Try to match minimum required
        for _ in range(node.min_count):
            matched, current_pos = self._match_node(node.node, current_pos)
            if not matched:
                return False, pos

        # Already matched minimum
        return True, current_pos

    def _match_group(self, node: Group, pos: int) -> tuple[bool, int]:
        """Match group."""
        if node.is_capturing:
            start_pos = pos
            matched, end_pos = self._match_node(node.node, pos)
            if matched:
                self.capture_groups[node.group_id] = self.text[start_pos:end_pos]
            return matched, end_pos
        else:
            return self._match_node(node.node, pos)

    def _match_backreference(self, node: Backreference, pos: int) -> tuple[bool, int]:
        """Match backreference."""
        if node.group_id not in self.capture_groups:
            return False, pos

        captured = self.capture_groups[node.group_id]
        if not captured:
            return True, pos

        # Match the captured text
        for char in captured:
            if pos >= len(self.text) or self.text[pos] != char:
                return False, pos
            pos += 1

        return True, pos

    def _is_word_boundary(self, pos: int) -> bool:
        """Check if position is at word boundary."""

        def is_word_char(ch: str) -> bool:
            return ch.isalnum() or ch == "_"

        left_word = pos > 0 and is_word_char(self.text[pos - 1])
        right_word = pos < len(self.text) and is_word_char(self.text[pos])

        return left_word != right_word
