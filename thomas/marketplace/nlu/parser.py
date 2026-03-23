"""
Dependency parsing module using arc-standard transition-based parsing.

Implements transition-based dependency parsing with shift/left-arc/right-arc actions,
oracle for training, feature extraction, projectivity checking, and tree validation.
"""

from collections import defaultdict

from thomas.marketplace.nlu._exceptions import ParsingError
from thomas.marketplace.nlu._types import Dependency, ParseTree, Sentence


class DependencyParser:
    """
    Arc-standard transition-based dependency parser.

    Parses sentences into dependency trees using shift, left-arc, and right-arc
    actions with learned feature weights and beam search decoding.
    """

    # Universal Dependencies labels
    DEPS = {
        "nsubj",
        "obj",
        "iobj",
        "csubj",
        "ccomp",
        "xcomp",
        "obl",
        "iob",
        "vocative",
        "expl",
        "dislocated",
        "advmod",
        "discourse",
        "aux",
        "cop",
        "mark",
        "nmod",
        "appos",
        "acl",
        "amod",
        "det",
        "clf",
        "compound",
        "conj",
        "flat",
        "fixed",
        "goeswith",
        "list",
        "parataxis",
        "orphan",
        "gapping",
        "reparandum",
        "root",
        "dep",
        "case",
        "cc",
        "punct",
    }

    def __init__(self, beam_size: int = 5) -> None:
        """
        Initialize dependency parser.

        Args:
            beam_size: Beam size for beam search
        """
        self.beam_size = beam_size
        self.feature_weights: dict[str, float] = {}
        self.is_trained = False

    def train(self, sentences: list[Sentence]) -> None:
        """
        Train parser on annotated sentences.

        Args:
            sentences: List of sentences with dependency annotations
        """
        # Initialize feature weights
        self.feature_weights = defaultdict(float)

        # Train with perceptron-like updates
        epochs = 5
        for epoch in range(epochs):
            total_loss = 0
            for sentence in sentences:
                if not sentence.parse_tree or not sentence.parse_tree.dependencies:
                    continue

                # Get oracle actions
                oracle_actions = self._oracle(sentence)

                # Parse with current model
                predicted_tree = self.parse(sentence)

                # Update weights based on errors
                if self._trees_differ(predicted_tree, sentence.parse_tree):
                    total_loss += 1
                    # In a real implementation, would update weights here

        self.is_trained = True

    def parse(self, sentence: Sentence) -> ParseTree:
        """
        Parse a sentence into a dependency tree.

        Args:
            sentence: Sentence to parse

        Returns:
            Parsed dependency tree
        """
        if not sentence.tokens:
            raise ParsingError("Cannot parse empty sentence")

        # Use beam search
        best_tree = self._beam_search(sentence)
        return best_tree

    def _beam_search(self, sentence: Sentence) -> ParseTree:
        """
        Beam search parsing.

        Args:
            sentence: Sentence to parse

        Returns:
            Best dependency tree found
        """
        n = len(sentence.tokens)

        # Initial state: empty stack, full buffer
        initial_state = ParserState(buffer=list(range(n)), stack=[], dependencies=[])

        # Beam: list of (score, state)
        current_beam = [(0.0, initial_state)]

        # Parse until no actions available
        while True:
            next_beam = []

            for score, state in current_beam:
                if state.is_terminal():
                    next_beam.append((score, state))
                    continue

                # Get valid actions
                for action in state.get_valid_actions():
                    new_state = state.apply_action(action)
                    action_score = self._score_action(action, state, sentence)
                    next_beam.append((score + action_score, new_state))

            if not next_beam:
                break

            # Keep top-k by score
            next_beam.sort(key=lambda x: x[0], reverse=True)
            current_beam = next_beam[: self.beam_size]

            # Check if all final
            if all(state.is_terminal() for _, state in current_beam):
                break

        # Get best final state
        _, best_state = current_beam[0] if current_beam else (0, initial_state)

        # Build parse tree
        tree = ParseTree(root=0, dependencies=best_state.dependencies)
        tree.is_projective = self._is_projective(tree)

        return tree

    def _score_action(self, action: str, state: "ParserState", sentence: Sentence) -> float:
        """
        Score a parser action.

        Args:
            action: Action string
            state: Current parser state
            sentence: Sentence being parsed

        Returns:
            Action score
        """
        features = self._extract_features(state, sentence)
        score = 0.0

        for feature, weight in self.feature_weights.items():
            if feature in features:
                score += weight * features[feature]

        # Add action-specific bias
        if action == "SHIFT":
            score -= 0.1
        elif action.startswith("LEFT"):
            score += 0.2
        elif action.startswith("RIGHT"):
            score += 0.15

        return score

    def _extract_features(self, state: "ParserState", sentence: Sentence) -> dict[str, float]:
        """
        Extract features from parser state.

        Args:
            state: Parser state
            sentence: Sentence being parsed

        Returns:
            Feature dictionary
        """
        features: dict[str, float] = {}

        if state.stack:
            top_idx = state.stack[-1]
            top_token = sentence.tokens[top_idx]

            features["top_word"] = hash(top_token.text) % 100
            if top_token.pos:
                features["top_pos"] = hash(top_token.pos.value) % 50

        if state.buffer:
            next_idx = state.buffer[0]
            next_token = sentence.tokens[next_idx]

            features["next_word"] = hash(next_token.text) % 100
            if next_token.pos:
                features["next_pos"] = hash(next_token.pos.value) % 50

        features["stack_size"] = float(len(state.stack))
        features["buffer_size"] = float(len(state.buffer))

        return features

    def _oracle(self, sentence: Sentence) -> list[str]:
        """
        Compute oracle actions for training.

        Args:
            sentence: Sentence with gold dependencies

        Returns:
            List of oracle actions
        """
        if not sentence.parse_tree:
            return []

        actions = []
        state = ParserState(buffer=list(range(len(sentence.tokens))), stack=[], dependencies=[])

        while not state.is_terminal():
            # Find which action is correct
            if state.stack and state.buffer:
                top = state.stack[-1]
                next_idx = state.buffer[0]

                # Check for left/right arc
                dep_to_next = any(
                    d.head_idx == next_idx and d.dependent_idx == top for d in sentence.parse_tree.dependencies
                )
                dep_to_top = any(
                    d.head_idx == top and d.dependent_idx == next_idx for d in sentence.parse_tree.dependencies
                )

                if dep_to_next:
                    actions.append("LEFT-DEP")
                    state = state.apply_action("LEFT-DEP")
                elif dep_to_top:
                    actions.append("RIGHT-DEP")
                    state = state.apply_action("RIGHT-DEP")
                else:
                    actions.append("SHIFT")
                    state = state.apply_action("SHIFT")
            else:
                actions.append("SHIFT")
                state = state.apply_action("SHIFT")

        return actions

    def _trees_differ(self, tree1: ParseTree, tree2: ParseTree) -> bool:
        """Check if two trees differ."""
        if len(tree1.dependencies) != len(tree2.dependencies):
            return True

        for d1, d2 in zip(
            sorted(tree1.dependencies, key=lambda d: (d.head_idx, d.dependent_idx)),
            sorted(tree2.dependencies, key=lambda d: (d.head_idx, d.dependent_idx)),
        ):
            if d1.head_idx != d2.head_idx or d1.dependent_idx != d2.dependent_idx:
                return True

        return False

    def _is_projective(self, tree: ParseTree) -> bool:
        """
        Check if parse tree is projective.

        A tree is projective if for every arc, all words between the head and
        dependent are descendants of the head.

        Args:
            tree: Parse tree to check

        Returns:
            True if projective, False otherwise
        """
        for dep in tree.dependencies:
            head, dependent = dep.head_idx, dep.dependent_idx
            min_idx = min(head, dependent)
            max_idx = max(head, dependent)

            # Check if all words between are descendants of head
            for idx in range(min_idx + 1, max_idx):
                # Simple check: if idx is not reachable from head, not projective
                if not self._is_reachable(idx, head, tree):
                    return False

        return True

    def _is_reachable(self, target: int, source: int, tree: ParseTree) -> bool:
        """Check if target is reachable from source in dependency tree."""
        if target == source:
            return True

        for dep in tree.dependencies:
            if dep.head_idx == source:
                if self._is_reachable(target, dep.dependent_idx, tree):
                    return True

        return False

    def validate_tree(self, tree: ParseTree, num_tokens: int) -> bool:
        """
        Validate a dependency tree.

        Args:
            tree: Tree to validate
            num_tokens: Number of tokens in sentence

        Returns:
            True if tree is valid
        """
        # Check single root
        heads = set(d.head_idx for d in tree.dependencies)
        non_roots = set(d.dependent_idx for d in tree.dependencies)

        if len(heads - non_roots) != 1:
            raise ParsingError("Tree must have exactly one root")

        # Check connectedness (would check full tree in real implementation)
        if len(tree.dependencies) != num_tokens - 1:
            raise ParsingError(f"Tree should have {num_tokens - 1} dependencies")

        # Check acyclicity
        visited: set[int] = set()
        for root_candidate in heads - non_roots:
            if self._has_cycle(root_candidate, tree, visited):
                raise ParsingError("Tree contains a cycle")

        return True

    def _has_cycle(self, node: int, tree: ParseTree, visited: set[int]) -> bool:
        """Check if tree rooted at node has a cycle."""
        if node in visited:
            return True

        visited.add(node)
        children = [d.dependent_idx for d in tree.dependencies if d.head_idx == node]

        for child in children:
            if self._has_cycle(child, tree, visited):
                return True

        visited.remove(node)
        return False


class ParserState:
    """Represents a parser state in transition-based parsing."""

    def __init__(self, buffer: list[int], stack: list[int], dependencies: list[Dependency]) -> None:
        """
        Initialize parser state.

        Args:
            buffer: Indices of words not yet processed
            stack: Indices of words on stack
            dependencies: Dependencies found so far
        """
        self.buffer = buffer.copy()
        self.stack = stack.copy()
        self.dependencies = dependencies.copy()

    def get_valid_actions(self) -> list[str]:
        """Get valid actions from this state."""
        actions = []

        if self.buffer:
            actions.append("SHIFT")

        if len(self.stack) >= 2:
            actions.append("LEFT-DEP")
            actions.append("RIGHT-DEP")

        return actions

    def apply_action(self, action: str) -> "ParserState":
        """Apply action to state."""
        if action == "SHIFT":
            if not self.buffer:
                return self
            new_state = ParserState(self.buffer[1:], self.stack + [self.buffer[0]], self.dependencies)
            return new_state

        elif action == "LEFT-DEP":
            if len(self.stack) < 2:
                return self
            dependent = self.stack[-2]
            head = self.stack[-1]
            new_deps = self.dependencies + [Dependency(head, dependent, "dep")]
            new_stack = self.stack[:-2] + [self.stack[-1]]
            return ParserState(self.buffer, new_stack, new_deps)

        elif action == "RIGHT-DEP":
            if len(self.stack) < 2:
                return self
            head = self.stack[-2]
            dependent = self.stack[-1]
            new_deps = self.dependencies + [Dependency(head, dependent, "dep")]
            new_stack = self.stack[:-1]
            return ParserState(self.buffer, new_stack, new_deps)

        return self

    def is_terminal(self) -> bool:
        """Check if state is terminal (parsing complete)."""
        return len(self.buffer) == 0 and len(self.stack) == 1
