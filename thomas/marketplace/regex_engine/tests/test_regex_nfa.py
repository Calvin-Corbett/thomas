"""
Tests for NFA construction using Thompson's algorithm.

Tests epsilon closure, state counting, and Thompson construction.
"""

from regex_engine.nfa import NFAState, build_nfa
from regex_engine.parser import parse


class TestBasicThompsonConstruction:
    """Test basic Thompson construction."""

    def test_literal_nfa(self) -> None:
        """Test NFA construction for literal."""
        ast = parse("a")
        nfa = build_nfa(ast)
        assert nfa is not None
        assert nfa.start is not None
        assert nfa.end is not None
        assert nfa.start != nfa.end

    def test_concatenation_nfa(self) -> None:
        """Test NFA for concatenation."""
        ast = parse("ab")
        nfa = build_nfa(ast)
        states = nfa.all_states()
        # Should have multiple states for two literals
        assert len(states) > 2

    def test_alternation_nfa(self) -> None:
        """Test NFA for alternation."""
        ast = parse("a|b")
        nfa = build_nfa(ast)
        states = nfa.all_states()
        # Alternation creates additional epsilon transitions
        assert len(states) > 2


class TestEpsilonClosure:
    """Test epsilon closure computation."""

    def test_single_state_closure(self) -> None:
        """Test epsilon closure of single state."""
        state = NFAState()
        closure = state.epsilon_closure()
        assert state in closure
        assert len(closure) == 1

    def test_closure_with_epsilon_transitions(self) -> None:
        """Test closure with epsilon transitions."""
        state1 = NFAState()
        state2 = NFAState()
        state3 = NFAState()
        state1.add_epsilon_transition(state2)
        state2.add_epsilon_transition(state3)

        closure = state1.epsilon_closure()
        assert state1 in closure
        assert state2 in closure
        assert state3 in closure
        assert len(closure) == 3

    def test_closure_with_cycle(self) -> None:
        """Test closure with epsilon cycle."""
        state1 = NFAState()
        state2 = NFAState()
        state1.add_epsilon_transition(state2)
        state2.add_epsilon_transition(state1)

        closure = state1.epsilon_closure()
        assert state1 in closure
        assert state2 in closure
        assert len(closure) == 2


class TestQuantifierConstruction:
    """Test NFA construction for quantifiers."""

    def test_star_quantifier(self) -> None:
        """Test * quantifier construction."""
        ast = parse("a*")
        nfa = build_nfa(ast)
        assert nfa.start != nfa.end
        # Should have epsilon transitions for zero or more semantics

    def test_plus_quantifier(self) -> None:
        """Test + quantifier construction."""
        ast = parse("a+")
        nfa = build_nfa(ast)
        assert nfa.start != nfa.end

    def test_question_quantifier(self) -> None:
        """Test ? quantifier construction."""
        ast = parse("a?")
        nfa = build_nfa(ast)
        assert nfa.start != nfa.end

    def test_bounded_quantifier(self) -> None:
        """Test {n,m} quantifier construction."""
        ast = parse("a{2,4}")
        nfa = build_nfa(ast)
        states = nfa.all_states()
        assert len(states) > 0


class TestGroupConstruction:
    """Test NFA construction for groups."""

    def test_capturing_group(self) -> None:
        """Test capturing group construction."""
        ast = parse("(a)")
        nfa = build_nfa(ast)
        states = nfa.all_states()
        # Check for group marking
        has_group_marker = any(s.group_enter is not None or s.group_exit is not None for s in states)
        assert has_group_marker

    def test_non_capturing_group(self) -> None:
        """Test non-capturing group construction."""
        ast = parse("(?:a)")
        nfa = build_nfa(ast)
        assert nfa is not None


class TestCharacterClassConstruction:
    """Test character class construction."""

    def test_simple_char_class(self) -> None:
        """Test simple character class."""
        ast = parse("[abc]")
        nfa = build_nfa(ast)
        assert nfa is not None

    def test_range_char_class(self) -> None:
        """Test character class with range."""
        ast = parse("[a-z]")
        nfa = build_nfa(ast)
        assert nfa is not None

    def test_negated_char_class(self) -> None:
        """Test negated character class."""
        ast = parse("[^abc]")
        nfa = build_nfa(ast)
        assert nfa is not None


class TestAnchorConstruction:
    """Test anchor construction."""

    def test_start_anchor(self) -> None:
        """Test start anchor construction."""
        ast = parse("^a")
        nfa = build_nfa(ast)
        states = nfa.all_states()
        # Should have anchor marker
        assert any(hasattr(s, "_anchor_type") for s in states)

    def test_end_anchor(self) -> None:
        """Test end anchor construction."""
        ast = parse("a$")
        nfa = build_nfa(ast)
        states = nfa.all_states()
        assert any(hasattr(s, "_anchor_type") for s in states)


class TestComplexPatterns:
    """Test complex pattern constructions."""

    def test_email_pattern(self) -> None:
        """Test email-like pattern."""
        ast = parse(r"[a-z]+@[a-z]+\.[a-z]+")
        nfa = build_nfa(ast)
        assert nfa is not None
        states = nfa.all_states()
        assert len(states) > 0

    def test_alternation_with_quantifiers(self) -> None:
        """Test alternation with quantifiers."""
        ast = parse("a+|b*")
        nfa = build_nfa(ast)
        states = nfa.all_states()
        assert len(states) > 0

    def test_nested_groups_and_quantifiers(self) -> None:
        """Test nested groups with quantifiers."""
        ast = parse("(a(b+)c)*")
        nfa = build_nfa(ast)
        states = nfa.all_states()
        assert len(states) > 0


class TestDotConstruction:
    """Test dot (any character) construction."""

    def test_dot_nfa(self) -> None:
        """Test dot construction."""
        ast = parse(".")
        nfa = build_nfa(ast)
        assert nfa is not None

    def test_dot_with_quantifier(self) -> None:
        """Test dot with quantifier."""
        ast = parse(".*")
        nfa = build_nfa(ast)
        states = nfa.all_states()
        assert len(states) > 0


class TestStateCount:
    """Test state counting for various patterns."""

    def test_literal_state_count(self) -> None:
        """Literal should have minimal states."""
        ast = parse("a")
        nfa = build_nfa(ast)
        states = nfa.all_states()
        assert len(states) == 2  # Start and end

    def test_alternation_state_count(self) -> None:
        """Alternation increases state count."""
        ast = parse("a|b")
        nfa = build_nfa(ast)
        states = nfa.all_states()
        # Alternation: 2 start states + 2 end states + 1 new start + 1 new end
        assert len(states) > 2

    def test_quantifier_state_count(self) -> None:
        """Quantifier affects state count."""
        ast = parse("a*")
        nfa = build_nfa(ast)
        states = nfa.all_states()
        # Star needs extra transitions
        assert len(states) > 2


class TestVisualization:
    """Test NFA visualization."""

    def test_dot_output(self) -> None:
        """Test DOT format output."""
        ast = parse("ab")
        nfa = build_nfa(ast)
        dot = nfa.to_dot()
        assert "digraph" in dot
        assert "rankdir=LR" in dot
        assert "->" in dot
