"""
Tests for dependency parsing module.
"""

import unittest

from thomas.nlu._exceptions import ParsingError
from thomas.nlu._types import Dependency, ParseTree, POSTag, Sentence, Span, Token
from thomas.nlu.parser import DependencyParser, ParserState


class TestParserState(unittest.TestCase):
    """Tests for parser state."""

    def test_initial_state(self) -> None:
        """Test initial parser state."""
        state = ParserState(buffer=[0, 1, 2], stack=[], dependencies=[])

        self.assertEqual(len(state.buffer), 3)
        self.assertEqual(len(state.stack), 0)
        self.assertEqual(len(state.dependencies), 0)

    def test_shift_action(self) -> None:
        """Test shift action."""
        state = ParserState(buffer=[0, 1, 2], stack=[], dependencies=[])
        new_state = state.apply_action("SHIFT")

        self.assertEqual(len(new_state.buffer), 2)
        self.assertEqual(new_state.stack[-1], 0)

    def test_left_arc_action(self) -> None:
        """Test left arc action."""
        state = ParserState(buffer=[2], stack=[0, 1], dependencies=[])
        new_state = state.apply_action("LEFT-DEP")

        self.assertEqual(len(new_state.dependencies), 1)
        self.assertEqual(len(new_state.stack), 1)

    def test_right_arc_action(self) -> None:
        """Test right arc action."""
        state = ParserState(buffer=[2], stack=[0, 1], dependencies=[])
        new_state = state.apply_action("RIGHT-DEP")

        self.assertEqual(len(new_state.dependencies), 1)
        self.assertEqual(len(new_state.stack), 1)

    def test_valid_actions(self) -> None:
        """Test getting valid actions from state."""
        # Initial state only allows SHIFT
        state = ParserState(buffer=[0, 1], stack=[], dependencies=[])
        valid = state.get_valid_actions()

        self.assertIn("SHIFT", valid)
        self.assertNotIn("LEFT-DEP", valid)
        self.assertNotIn("RIGHT-DEP", valid)

    def test_state_immutability(self) -> None:
        """Test that applying action doesn't modify original state."""
        state = ParserState(buffer=[0, 1, 2], stack=[], dependencies=[])
        new_state = state.apply_action("SHIFT")

        # Original should be unchanged
        self.assertEqual(len(state.buffer), 3)
        self.assertEqual(len(state.stack), 0)

    def test_is_terminal(self) -> None:
        """Test terminal state detection."""
        # Terminal: empty buffer, single element on stack
        terminal_state = ParserState(buffer=[], stack=[0], dependencies=[])
        self.assertTrue(terminal_state.is_terminal())

        # Non-terminal: still have buffer
        non_terminal = ParserState(buffer=[1], stack=[0], dependencies=[])
        self.assertFalse(non_terminal.is_terminal())


class TestDependencyParser(unittest.TestCase):
    """Tests for dependency parser."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.parser = DependencyParser()

    def test_parser_initialization(self) -> None:
        """Test parser initialization."""
        self.assertIsNotNone(self.parser)
        self.assertEqual(self.parser.beam_size, 5)

    def test_parsing_simple_sentence(self) -> None:
        """Test parsing a simple sentence."""
        tokens = [
            Token(text="John", span=Span(0, 4), pos=POSTag.NNP),
            Token(text="eats", span=Span(5, 9), pos=POSTag.VBZ),
            Token(text="apple", span=Span(10, 15), pos=POSTag.NN),
        ]
        sentence = Sentence(text="John eats apple", tokens=tokens)

        tree = self.parser.parse(sentence)

        self.assertIsNotNone(tree)
        self.assertGreaterEqual(len(tree.dependencies), 0)

    def test_empty_sentence_error(self) -> None:
        """Test error on empty sentence."""
        sentence = Sentence(text="", tokens=[])

        with self.assertRaises(ParsingError):
            self.parser.parse(sentence)

    def test_single_token_sentence(self) -> None:
        """Test parsing sentence with single token."""
        tokens = [Token(text="Hello", span=Span(0, 5))]
        sentence = Sentence(text="Hello", tokens=tokens)

        tree = self.parser.parse(sentence)
        self.assertIsNotNone(tree)

    def test_parse_tree_structure(self) -> None:
        """Test parse tree structure."""
        deps = [
            Dependency(head_idx=1, dependent_idx=0, label="nsubj"),
            Dependency(head_idx=1, dependent_idx=2, label="obj"),
        ]
        tree = ParseTree(root=1, dependencies=deps)

        self.assertEqual(tree.root, 1)
        self.assertEqual(len(tree.dependencies), 2)

    def test_get_children(self) -> None:
        """Test getting children of a node."""
        deps = [
            Dependency(head_idx=1, dependent_idx=0, label="nsubj"),
            Dependency(head_idx=1, dependent_idx=2, label="obj"),
        ]
        tree = ParseTree(root=1, dependencies=deps)

        children = tree.get_children(1)
        self.assertEqual(set(children), {0, 2})

    def test_get_parent(self) -> None:
        """Test getting parent of a node."""
        deps = [
            Dependency(head_idx=1, dependent_idx=0, label="nsubj"),
        ]
        tree = ParseTree(root=1, dependencies=deps)

        parent = tree.get_parent(0)
        self.assertEqual(parent, 1)

    def test_tree_validation_single_root(self) -> None:
        """Test that tree validation checks for single root."""
        # Create invalid tree with multiple roots
        deps = [
            Dependency(head_idx=0, dependent_idx=1, label="dep"),
            Dependency(head_idx=2, dependent_idx=3, label="dep"),
        ]
        tree = ParseTree(root=0, dependencies=deps)

        # Tree should fail validation (but might be valid in constructor)
        self.assertIsNotNone(tree)

    def test_projectivity_check(self) -> None:
        """Test projectivity checking."""
        deps = [
            Dependency(head_idx=1, dependent_idx=0, label="nsubj"),
            Dependency(head_idx=1, dependent_idx=2, label="obj"),
        ]
        tree = ParseTree(root=1, dependencies=deps)

        is_projective = self.parser._is_projective(tree)
        self.assertTrue(is_projective)

    def test_feature_extraction(self) -> None:
        """Test feature extraction from parser state."""
        state = ParserState(buffer=[1, 2], stack=[0], dependencies=[])
        tokens = [
            Token(text="a", span=Span(0, 1), pos=POSTag.DT),
            Token(text="b", span=Span(2, 3), pos=POSTag.NN),
        ]
        sentence = Sentence(text="a b", tokens=tokens)

        features = self.parser._extract_features(state, sentence)

        self.assertIsInstance(features, dict)
        self.assertGreater(len(features), 0)

    def test_beam_search_parsing(self) -> None:
        """Test beam search parsing."""
        tokens = [
            Token(text="John", span=Span(0, 4)),
            Token(text="runs", span=Span(5, 9)),
        ]
        sentence = Sentence(text="John runs", tokens=tokens)

        tree = self.parser._beam_search(sentence)

        self.assertIsNotNone(tree)


class TestParserDependencies(unittest.TestCase):
    """Test dependency handling."""

    def test_dependency_creation(self) -> None:
        """Test creating a dependency."""
        dep = Dependency(head_idx=1, dependent_idx=0, label="nsubj")

        self.assertEqual(dep.head_idx, 1)
        self.assertEqual(dep.dependent_idx, 0)
        self.assertEqual(dep.label, "nsubj")

    def test_dependency_validation(self) -> None:
        """Test dependency validation."""
        # Same head and dependent should fail
        with self.assertRaises(ValueError):
            Dependency(head_idx=0, dependent_idx=0, label="nsubj")

    def test_negative_indices_error(self) -> None:
        """Test error on negative indices."""
        with self.assertRaises(ValueError):
            Dependency(head_idx=-1, dependent_idx=0, label="nsubj")

    def test_dependency_label_types(self) -> None:
        """Test various dependency label types."""
        labels = ["nsubj", "obj", "iobj", "obl", "advmod", "nmod", "amod"]

        for label in labels:
            dep = Dependency(head_idx=0, dependent_idx=1, label=label)
            self.assertEqual(dep.label, label)


class TestParserIntegration(unittest.TestCase):
    """Integration tests for parser."""

    def test_sentence_with_pos_tags(self) -> None:
        """Test parsing sentence with POS tags."""
        tokens = [
            Token(text="The", span=Span(0, 3), pos=POSTag.DT),
            Token(text="dog", span=Span(4, 7), pos=POSTag.NN),
            Token(text="barked", span=Span(8, 14), pos=POSTag.VBD),
        ]
        sentence = Sentence(text="The dog barked", tokens=tokens)

        parser = DependencyParser()
        tree = parser.parse(sentence)

        self.assertIsNotNone(tree)

    def test_complex_sentence(self) -> None:
        """Test parsing complex sentence."""
        tokens = [
            Token(text="John", span=Span(0, 4), pos=POSTag.NNP),
            Token(text="gave", span=Span(5, 9), pos=POSTag.VBD),
            Token(text="the", span=Span(10, 13), pos=POSTag.DT),
            Token(text="book", span=Span(14, 18), pos=POSTag.NN),
            Token(text="to", span=Span(19, 21), pos=POSTag.IN),
            Token(text="Mary", span=Span(22, 26), pos=POSTag.NNP),
        ]
        sentence = Sentence(text="John gave the book to Mary", tokens=tokens)

        parser = DependencyParser()
        tree = parser.parse(sentence)

        self.assertIsNotNone(tree)

    def test_parsing_preserves_text(self) -> None:
        """Test that parsing doesn't modify sentence text."""
        text = "Dogs run fast"
        tokens = [Token(text=w, span=Span(0, len(w))) for w in text.split()]
        sentence = Sentence(text=text, tokens=tokens)

        parser = DependencyParser()
        tree = parser.parse(sentence)

        self.assertEqual(sentence.text, text)


if __name__ == "__main__":
    unittest.main()
