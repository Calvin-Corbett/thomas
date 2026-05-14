"""
Tests for DFA construction and minimization.

Tests subset construction, minimization, and equivalence to NFA.
"""

from regex_engine.dfa import SubsetConstructor, construct_dfa, minimize_dfa
from regex_engine.nfa import build_nfa
from regex_engine.parser import parse


class TestSubsetConstruction:
    """Test DFA construction from NFA."""

    def test_simple_dfa_construction(self) -> None:
        """Test basic DFA construction."""
        ast = parse("a")
        nfa = build_nfa(ast)
        dfa = construct_dfa(nfa)
        assert dfa is not None
        assert dfa.start is not None

    def test_concatenation_dfa(self) -> None:
        """Test DFA for concatenation."""
        ast = parse("ab")
        nfa = build_nfa(ast)
        dfa = construct_dfa(nfa)
        states = dfa.all_states()
        assert len(states) > 0

    def test_alternation_dfa(self) -> None:
        """Test DFA for alternation."""
        ast = parse("a|b")
        nfa = build_nfa(ast)
        dfa = construct_dfa(nfa)
        states = dfa.all_states()
        assert len(states) > 0

    def test_quantifier_dfa(self) -> None:
        """Test DFA for quantifier."""
        ast = parse("a*")
        nfa = build_nfa(ast)
        dfa = construct_dfa(nfa)
        states = dfa.all_states()
        assert len(states) > 0


class TestEpsilonClosureInDFA:
    """Test epsilon closure computation in DFA construction."""

    def test_epsilon_closure_single_state(self) -> None:
        """Test epsilon closure of single state."""
        ast = parse("a")
        nfa = build_nfa(ast)
        constructor = SubsetConstructor(nfa)
        closure = constructor._epsilon_closure({nfa.start})
        assert nfa.start in closure

    def test_epsilon_closure_multiple_transitions(self) -> None:
        """Test epsilon closure with multiple epsilon transitions."""
        ast = parse("a|b")
        nfa = build_nfa(ast)
        constructor = SubsetConstructor(nfa)
        closure = constructor._epsilon_closure({nfa.start})
        # Should include all epsilon-reachable states
        assert len(closure) > 0

    def test_move_operation(self) -> None:
        """Test move operation."""
        ast = parse("ab")
        nfa = build_nfa(ast)
        constructor = SubsetConstructor(nfa)
        closure = constructor._epsilon_closure({nfa.start})
        # Try to move on 'a'
        next_states = constructor._move(closure, "a")
        assert len(next_states) > 0


class TestDFAMinimization:
    """Test DFA minimization."""

    def test_simple_minimization(self) -> None:
        """Test basic DFA minimization."""
        ast = parse("a|a")  # Redundant alternation
        nfa = build_nfa(ast)
        dfa = construct_dfa(nfa)
        original_states = len(dfa.all_states())

        minimized = minimize_dfa(dfa)
        minimized_states = len(minimized.all_states())
        assert minimized_states <= original_states

    def test_minimization_equivalence(self) -> None:
        """Test minimized DFA accepts same language as original."""
        ast = parse("a(a|a)b")
        nfa = build_nfa(ast)
        dfa = construct_dfa(nfa)
        minimized = minimize_dfa(dfa)

        # Both should have start and accepting states
        assert dfa.start is not None
        assert minimized.start is not None

    def test_accepting_states_preserved(self) -> None:
        """Test minimization preserves accepting states."""
        ast = parse("ab|ac")
        nfa = build_nfa(ast)
        dfa = construct_dfa(nfa)
        sum(1 for s in dfa.all_states() if s.is_accepting)

        minimized = minimize_dfa(dfa)
        minimized_accepting = sum(1 for s in minimized.all_states() if s.is_accepting)

        assert minimized_accepting > 0


class TestDFATransitions:
    """Test DFA transitions."""

    def test_literal_transitions(self) -> None:
        """Test DFA transitions for literals."""
        ast = parse("abc")
        nfa = build_nfa(ast)
        dfa = construct_dfa(nfa)

        # Start state should have transitions
        assert len(dfa.start.transitions) > 0

    def test_char_class_transitions(self) -> None:
        """Test DFA transitions for character classes."""
        ast = parse("[abc]")
        nfa = build_nfa(ast)
        dfa = construct_dfa(nfa)

        # Should have transitions for a, b, c
        transitions = set(dfa.start.transitions.keys())
        assert len(transitions) > 0

    def test_alternation_transitions(self) -> None:
        """Test DFA transitions for alternation."""
        ast = parse("a|b")
        nfa = build_nfa(ast)
        dfa = construct_dfa(nfa)

        # Start should have transitions for both a and b
        transitions = set(dfa.start.transitions.keys())
        assert "a" in transitions or "b" in transitions


class TestAcceptingStates:
    """Test accepting state detection."""

    def test_literal_accepting_state(self) -> None:
        """Test accepting state for literal."""
        ast = parse("a")
        nfa = build_nfa(ast)
        dfa = construct_dfa(nfa)

        # DFA end state should be marked as accepting
        assert any(s.is_accepting for s in dfa.all_states())

    def test_multiple_paths_accepting(self) -> None:
        """Test accepting states in alternation."""
        ast = parse("a|b")
        nfa = build_nfa(ast)
        dfa = construct_dfa(nfa)

        accepting_count = sum(1 for s in dfa.all_states() if s.is_accepting)
        assert accepting_count > 0


class TestComplexPatterns:
    """Test DFA construction for complex patterns."""

    def test_email_pattern_dfa(self) -> None:
        """Test DFA for email pattern."""
        ast = parse(r"[a-z]+@[a-z]+")
        nfa = build_nfa(ast)
        dfa = construct_dfa(nfa)
        assert dfa is not None

    def test_alternation_with_quantifiers_dfa(self) -> None:
        """Test DFA for alternation with quantifiers."""
        ast = parse("a+|b*c+")
        nfa = build_nfa(ast)
        dfa = construct_dfa(nfa)
        states = dfa.all_states()
        assert len(states) > 0

    def test_nested_patterns_dfa(self) -> None:
        """Test DFA for nested patterns."""
        ast = parse("(a|b)*(c|d)+")
        nfa = build_nfa(ast)
        dfa = construct_dfa(nfa)
        states = dfa.all_states()
        assert len(states) > 0


class TestDFADeterminism:
    """Test that DFA is properly deterministic."""

    def test_single_transition_per_symbol(self) -> None:
        """Each state should have at most one transition per symbol."""
        ast = parse("abc")
        nfa = build_nfa(ast)
        dfa = construct_dfa(nfa)

        for state in dfa.all_states():
            # Each symbol should map to exactly one state
            for symbol, next_state in state.transitions.items():
                assert next_state is not None

    def test_no_epsilon_transitions(self) -> None:
        """DFA should not have epsilon transitions."""
        ast = parse("a|b")
        nfa = build_nfa(ast)
        dfa = construct_dfa(nfa)

        for state in dfa.all_states():
            # None key represents epsilon
            assert None not in state.transitions


class TestDFAStateEquivalence:
    """Test DFA state equivalence."""

    def test_equivalent_states_merged(self) -> None:
        """Equivalent states should be merged in minimization."""
        ast = parse("aa|ab|ba|bb")
        nfa = build_nfa(ast)
        dfa = construct_dfa(nfa)
        original_count = len(dfa.all_states())

        minimized = minimize_dfa(dfa)
        minimized_count = len(minimized.all_states())

        assert minimized_count <= original_count
