"""
NFA construction from AST using Thompson's algorithm.

Implements Thompson's construction to build NFA from regex AST.
Includes epsilon closure computation and NFA visualization.
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


class NFAState:
    """Represents a state in the NFA."""

    _counter = 0

    def __init__(self) -> None:
        """Initialize NFA state."""
        self.state_id = NFAState._counter
        NFAState._counter += 1

        # Transitions: (input_symbol or None for epsilon) -> set of NFAState
        self.transitions: dict[str | None, set[NFAState]] = {}

        # Capture group info
        self.group_enter: int | None = None  # Group ID to capture start
        self.group_exit: int | None = None  # Group ID to capture end

    def add_transition(self, symbol: str | None, state: NFAState) -> None:
        """Add a transition from this state."""
        if symbol not in self.transitions:
            self.transitions[symbol] = set()
        self.transitions[symbol].add(state)

    def add_epsilon_transition(self, state: NFAState) -> None:
        """Add an epsilon transition."""
        self.add_transition(None, state)

    def epsilon_closure(self) -> set[NFAState]:
        """Compute epsilon closure of this state."""
        closure = {self}
        stack = [self]

        while stack:
            state = stack.pop()
            if None in state.transitions:
                for next_state in state.transitions[None]:
                    if next_state not in closure:
                        closure.add(next_state)
                        stack.append(next_state)

        return closure

    def __repr__(self) -> str:
        """Return string representation."""
        return f"NFAState({self.state_id})"


class NFA:
    """Non-deterministic finite automaton."""

    def __init__(self, start: NFAState, end: NFAState) -> None:
        """Initialize NFA."""
        self.start = start
        self.end = end

    def all_states(self) -> set[NFAState]:
        """Get all reachable states from start."""
        states = set()
        stack = [self.start]

        while stack:
            state = stack.pop()
            if state not in states:
                states.add(state)
                for next_states in state.transitions.values():
                    stack.extend(next_states)

        return states

    def to_dot(self) -> str:
        """Generate DOT format for visualization."""
        lines = ["digraph NFA {", "rankdir=LR;"]
        states = self.all_states()

        # Mark start and end states
        lines.append(f'"{self.start.state_id}" [shape=circle];')
        lines.append(f'"{self.end.state_id}" [shape=doublecircle];')

        # Add transitions
        for state in states:
            for symbol, next_states in state.transitions.items():
                for next_state in next_states:
                    label = symbol if symbol is not None else "ε"
                    lines.append(f'"{state.state_id}" -> "{next_state.state_id}" [label="{label}"];')

        lines.append("}")
        return "\n".join(lines)


class ThompsonBuilder:
    """Builds NFA using Thompson's construction."""

    def __init__(self) -> None:
        """Initialize builder."""
        pass

    def build(self, ast: ASTNode) -> NFA:
        """Build NFA from AST."""
        return self._build_node(ast)

    def _build_node(self, node: ASTNode) -> NFA:
        """Build NFA for a node."""
        if isinstance(node, Literal):
            return self._build_literal(node)
        elif isinstance(node, Dot):
            return self._build_dot(node)
        elif isinstance(node, CharClass):
            return self._build_char_class(node)
        elif isinstance(node, Anchor):
            return self._build_anchor(node)
        elif isinstance(node, Concatenation):
            return self._build_concatenation(node)
        elif isinstance(node, Alternation):
            return self._build_alternation(node)
        elif isinstance(node, Quantifier):
            return self._build_quantifier(node)
        elif isinstance(node, Group):
            return self._build_group(node)
        elif isinstance(node, Backreference):
            return self._build_backreference(node)
        else:
            raise ValueError(f"Unknown AST node type: {type(node)}")

    def _build_literal(self, node: Literal) -> NFA:
        """Build NFA for literal character."""
        start = NFAState()
        end = NFAState()
        start.add_transition(node.char, end)
        return NFA(start, end)

    def _build_dot(self, node: Dot) -> NFA:
        """Build NFA for . (any character)."""
        start = NFAState()
        end = NFAState()
        # Use special marker for "any character"
        start.add_transition(".", end)
        return NFA(start, end)

    def _build_char_class(self, node: CharClass) -> NFA:
        """Build NFA for character class."""
        start = NFAState()
        end = NFAState()

        # Build set of characters in this class
        chars = build_char_class_set(node.chars, node.ranges, node.escape_classes, node.negated)

        for char in chars:
            start.add_transition(char, end)

        # Store metadata for DFA construction
        start._char_class = chars
        start._negated = node.negated

        return NFA(start, end)

    def _build_anchor(self, node: Anchor) -> NFA:
        """Build NFA for anchors."""
        start = NFAState()
        end = NFAState()
        # Mark anchor type
        start._anchor_type = node.anchor_type
        start.add_epsilon_transition(end)
        return NFA(start, end)

    def _build_concatenation(self, node: Concatenation) -> NFA:
        """Build NFA for concatenation."""
        if not node.nodes:
            start = NFAState()
            return NFA(start, start)

        # Build first node
        nfa = self._build_node(node.nodes[0])

        # Connect remaining nodes
        for child in node.nodes[1:]:
            child_nfa = self._build_node(child)
            nfa.end.add_epsilon_transition(child_nfa.start)
            nfa = NFA(nfa.start, child_nfa.end)

        return nfa

    def _build_alternation(self, node: Alternation) -> NFA:
        """Build NFA for alternation (a|b)."""
        start = NFAState()
        end = NFAState()

        for child in node.nodes:
            child_nfa = self._build_node(child)
            start.add_epsilon_transition(child_nfa.start)
            child_nfa.end.add_epsilon_transition(end)

        return NFA(start, end)

    def _build_quantifier(self, node: Quantifier) -> NFA:
        """Build NFA for quantifier."""
        child_nfa = self._build_node(node.node)

        if node.min_count == 0 and node.max_count is None:
            # * (zero or more)
            start = NFAState()
            end = NFAState()
            start.add_epsilon_transition(child_nfa.start)
            start.add_epsilon_transition(end)
            child_nfa.end.add_epsilon_transition(child_nfa.start)
            child_nfa.end.add_epsilon_transition(end)
            return NFA(start, end)

        elif node.min_count == 1 and node.max_count is None:
            # + (one or more)
            start = NFAState()
            end = NFAState()
            start.add_epsilon_transition(child_nfa.start)
            child_nfa.end.add_epsilon_transition(child_nfa.start)
            child_nfa.end.add_epsilon_transition(end)
            return NFA(start, end)

        elif node.min_count == 0 and node.max_count == 1:
            # ? (zero or one)
            start = NFAState()
            end = NFAState()
            start.add_epsilon_transition(child_nfa.start)
            start.add_epsilon_transition(end)
            child_nfa.end.add_epsilon_transition(end)
            return NFA(start, end)

        else:
            # {n,m} - build by repetition
            return self._build_bounded_quantifier(child_nfa, node)

    def _build_bounded_quantifier(self, child_nfa: NFA, node: Quantifier) -> NFA:
        """Build NFA for bounded quantifier {n,m}."""
        min_count = node.min_count
        max_count = node.max_count if node.max_count is not None else min_count + 10

        # Build min_count mandatory copies
        current_start = NFAState()
        current_end = current_start

        for _ in range(min_count):
            nfa_copy = self._build_node(node.node)
            current_end.add_epsilon_transition(nfa_copy.start)
            current_end = nfa_copy.end

        # Build optional copies up to max_count
        for _ in range(max_count - min_count):
            nfa_copy = self._build_node(node.node)
            optional_end = NFAState()
            current_end.add_epsilon_transition(nfa_copy.start)
            current_end.add_epsilon_transition(optional_end)
            nfa_copy.end.add_epsilon_transition(optional_end)
            current_end = optional_end

        return NFA(current_start, current_end)

    def _build_group(self, node: Group) -> NFA:
        """Build NFA for group."""
        child_nfa = self._build_node(node.node)

        if node.is_capturing:
            # Mark capture boundaries
            child_nfa.start.group_enter = node.group_id
            child_nfa.end.group_exit = node.group_id

        return child_nfa

    def _build_backreference(self, node: Backreference) -> NFA:
        """Build NFA for backreference."""
        start = NFAState()
        end = NFAState()
        # Mark as backreference for later matching
        start._backreference_id = node.group_id
        start.add_epsilon_transition(end)
        return NFA(start, end)


def build_nfa(ast: ASTNode) -> NFA:
    """Build NFA from AST using Thompson's construction."""
    builder = ThompsonBuilder()
    return builder.build(ast)
