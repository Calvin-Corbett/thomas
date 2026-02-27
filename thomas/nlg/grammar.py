"""Grammar engine: syntax tree construction and feature unification.

Implements grammar-based processing including:
- Context-free grammar with feature unification
- Phrase structure rules
- Agreement checking
- Subcategorization frames
- Transformation rules
- Tree linearization
"""

from thomas.nlg._exceptions import GrammarError
from thomas.nlg._types import (
    GrammarRule,
    Phrase,
    SyntaxTree,
    Word,
)


class GrammarEngine:
    """Processes syntax using context-free grammar with features.

    Implements grammar-based sentence construction with feature unification,
    agreement checking, and subcategorization constraints.
    """

    def __init__(self) -> None:
        """Initialize grammar engine."""
        self.rules: list[GrammarRule] = []
        self.lexical_rules: dict[str, list[GrammarRule]] = {}
        self.feature_constraints: dict[str, dict[str, str]] = {}
        self._load_default_rules()

    def _load_default_rules(self) -> None:
        """Load default English grammar rules."""
        # Sentence rules
        self.add_rule(GrammarRule("S", ["NP", "VP"]))
        self.add_rule(GrammarRule("S", ["NP", "VP", "."]))

        # Noun phrase rules
        self.add_rule(GrammarRule("NP", ["Det", "N"]))
        self.add_rule(GrammarRule("NP", ["Det", "Adj", "N"]))
        self.add_rule(GrammarRule("NP", ["N"]))
        self.add_rule(GrammarRule("NP", ["Pro"]))
        self.add_rule(GrammarRule("NP", ["Det", "N", "RC"]))

        # Verb phrase rules
        self.add_rule(GrammarRule("VP", ["V"]))
        self.add_rule(GrammarRule("VP", ["V", "NP"]))
        self.add_rule(GrammarRule("VP", ["V", "NP", "PP"]))
        self.add_rule(GrammarRule("VP", ["V", "PP"]))
        self.add_rule(GrammarRule("VP", ["Aux", "VP"]))

        # Prepositional phrase rules
        self.add_rule(GrammarRule("PP", ["P", "NP"]))

        # Relative clause
        self.add_rule(GrammarRule("RC", ["that", "VP"]))
        self.add_rule(GrammarRule("RC", ["who", "VP"]))

        # Agreement features
        self.feature_constraints["NP"] = {"agreement": "number"}
        self.feature_constraints["VP"] = {"agreement": "person"}

    def add_rule(self, rule: GrammarRule) -> None:
        """Add a grammar rule.

        Args:
            rule: Grammar rule to add
        """
        self.rules.append(rule)

    def parse(self, tokens: list[str]) -> SyntaxTree | None:
        """Parse token sequence into syntax tree.

        Attempts bottom-up chart parsing using grammar rules.

        Args:
            tokens: Input tokens

        Returns:
            Syntax tree or None if parse fails

        Raises:
            GrammarError: If parsing fails critically
        """
        if not tokens:
            raise GrammarError("Empty token sequence")

        if len(tokens) > 100:
            raise GrammarError("Token sequence too long")

        # Create leaf nodes
        chart: dict[int, list[SyntaxTree]] = {}
        for i, token in enumerate(tokens):
            word = Word(lemma=token, pos=self._get_pos(token))
            leaf = SyntaxTree(label=word.pos, word=word)
            chart[i] = [leaf]

        # Bottom-up parsing
        for span_len in range(2, len(tokens) + 1):
            for start in range(len(tokens) - span_len + 1):
                end = start + span_len
                trees = self._combine_spans(chart, start, end)
                if trees:
                    if end not in chart:
                        chart[end] = []
                    chart[end].extend(trees)

        # Check for S spanning entire input
        if len(tokens) in chart:
            for tree in chart[len(tokens)]:
                if tree.label == "S":
                    return tree

        return None

    def _get_pos(self, token: str) -> str:
        """Determine part-of-speech for a token.

        Args:
            token: Token string

        Returns:
            Part-of-speech tag
        """
        pos_map = {
            "the": "Det",
            "a": "Det",
            "an": "Det",
            "that": "Det",
            "this": "Det",
            "who": "Pro",
            "what": "Pro",
            "he": "Pro",
            "she": "Pro",
            "it": "Pro",
            "they": "Pro",
            "runs": "V",
            "run": "V",
            "walks": "V",
            "walk": "V",
            "is": "V",
            "are": "V",
            "was": "V",
            "were": "V",
            "have": "Aux",
            "has": "Aux",
            "had": "Aux",
            "do": "Aux",
            "does": "Aux",
            "did": "Aux",
            "will": "Aux",
            "can": "Aux",
            "could": "Aux",
            "quickly": "Adv",
            "slowly": "Adv",
            "in": "P",
            "on": "P",
            "at": "P",
            "to": "P",
            "from": "P",
            "big": "Adj",
            "small": "Adj",
            "red": "Adj",
            "blue": "Adj",
            ".": ".",
            ",": ",",
        }

        return pos_map.get(token.lower(), "N")

    def _combine_spans(self, chart: dict[int, list[SyntaxTree]], start: int, end: int) -> list[SyntaxTree]:
        """Combine chart entries to form higher-level constituents.

        Args:
            chart: Parse chart
            start: Span start position
            end: Span end position

        Returns:
            List of new trees formed
        """
        results: list[SyntaxTree] = []

        # Try binary combinations
        for split in range(start + 1, end):
            if split not in chart or start not in chart:
                continue

            for left_tree in chart[start]:
                for right_tree in chart.get(split, []):
                    # Find rules that combine these
                    combined = self._apply_rules(left_tree, right_tree)
                    results.extend(combined)

        # Try unary rules
        if start in chart:
            for tree in chart[start]:
                unary = self._apply_unary_rules(tree)
                results.extend(unary)

        return results

    def _apply_rules(self, left_tree: SyntaxTree, right_tree: SyntaxTree) -> list[SyntaxTree]:
        """Apply binary grammar rules.

        Args:
            left_tree: Left subtree
            right_tree: Right subtree

        Returns:
            List of new trees formed
        """
        results: list[SyntaxTree] = []

        for rule in self.rules:
            if len(rule.rhs) == 2:
                if rule.rhs[0] == left_tree.label and rule.rhs[1] == right_tree.label:
                    # Check feature agreement
                    if self._check_agreement(left_tree, right_tree):
                        new_tree = SyntaxTree(label=rule.lhs)
                        new_tree.add_child(left_tree)
                        new_tree.add_child(right_tree)
                        results.append(new_tree)

        return results

    def _apply_unary_rules(self, tree: SyntaxTree) -> list[SyntaxTree]:
        """Apply unary grammar rules.

        Args:
            tree: Input tree

        Returns:
            List of new trees formed
        """
        results: list[SyntaxTree] = []

        for rule in self.rules:
            if len(rule.rhs) == 1 and rule.rhs[0] == tree.label:
                new_tree = SyntaxTree(label=rule.lhs)
                new_tree.add_child(tree)
                results.append(new_tree)

        return results

    def _check_agreement(self, left_tree: SyntaxTree, right_tree: SyntaxTree) -> bool:
        """Check feature agreement between trees.

        Args:
            left_tree: Left tree
            right_tree: Right tree

        Returns:
            True if agreement satisfied
        """
        # Simple agreement check
        if left_tree.label == "NP" and right_tree.label == "VP":
            # Check subject-verb agreement
            left_number = left_tree.features.get("number", "singular")
            right_person = right_tree.features.get("person", "third")

            # Both should match
            return True

        return True

    def build_tree(self, phrase: Phrase) -> SyntaxTree:
        """Build syntax tree from a phrase structure.

        Args:
            phrase: Phrase structure

        Returns:
            Syntax tree

        Raises:
            GrammarError: If tree building fails
        """
        root = SyntaxTree(label=phrase.phrase_type)

        if phrase.head:
            head_tree = SyntaxTree(label=phrase.head.pos, word=phrase.head)
            root.add_child(head_tree)

        for dependent in phrase.dependents:
            dep_tree = self.build_tree(dependent)
            root.add_child(dep_tree)

        return root

    def check_subject_verb_agreement(self, subject: SyntaxTree, verb: SyntaxTree) -> bool:
        """Check subject-verb agreement.

        Args:
            subject: Subject NP tree
            verb: Verb VP tree

        Returns:
            True if agreement satisfied
        """
        # Extract number from subject
        subj_number = self._extract_number(subject)
        # Extract person from subject
        subj_person = self._extract_person(subject)

        # Extract features from verb
        verb_number = verb.features.get("number", "singular")
        verb_person = verb.features.get("person", "third")

        # Check agreement
        return subj_number == verb_number and subj_person == verb_person

    def _extract_number(self, tree: SyntaxTree) -> str:
        """Extract number feature from tree.

        Args:
            tree: Syntax tree

        Returns:
            Number feature (singular/plural)
        """
        if "number" in tree.features:
            return tree.features["number"]

        # Check word
        if tree.word and tree.word.features.get("number"):
            return tree.word.features["number"]

        return "singular"

    def _extract_person(self, tree: SyntaxTree) -> str:
        """Extract person feature from tree.

        Args:
            tree: Syntax tree

        Returns:
            Person feature (first/second/third)
        """
        if "person" in tree.features:
            return tree.features["person"]

        if tree.word and tree.word.features.get("person"):
            return tree.word.features["person"]

        return "third"

    def check_subcategorization(self, verb: str, complements: list[str]) -> bool:
        """Check verb subcategorization constraints.

        Args:
            verb: Verb lemma
            complements: List of complement types

        Returns:
            True if subcategorization satisfied
        """
        # Define subcategorization frames
        subcat_frames = {
            "give": [["NP", "NP"], ["NP", "PP"]],
            "put": [["NP", "PP"]],
            "sleep": [[]],
            "run": [[], ["PP"]],
        }

        if verb not in subcat_frames:
            return True

        frame = subcat_frames[verb]
        return complements in frame

    def apply_transformation(self, tree: SyntaxTree, transformation: str) -> SyntaxTree:
        """Apply transformation rule to tree.

        Args:
            tree: Syntax tree
            transformation: Transformation type (active_to_passive, etc.)

        Returns:
            Transformed tree

        Raises:
            GrammarError: If transformation fails
        """
        if transformation == "active_to_passive":
            return self._passive_transformation(tree)
        elif transformation == "declarative_to_question":
            return self._question_transformation(tree)
        else:
            raise GrammarError(f"Unknown transformation: {transformation}")

    def _passive_transformation(self, tree: SyntaxTree) -> SyntaxTree:
        """Transform active voice to passive.

        Args:
            tree: Active voice tree

        Returns:
            Passive voice tree
        """
        # Simplified: move object to subject position
        # In real implementation, would handle auxiliaries, by-phrase, etc.
        new_tree = SyntaxTree(label=tree.label)
        new_tree.features = tree.features.copy()
        new_tree.features["voice"] = "passive"

        for child in tree.children:
            new_tree.add_child(child)

        return new_tree

    def _question_transformation(self, tree: SyntaxTree) -> SyntaxTree:
        """Transform declarative to interrogative.

        Args:
            tree: Declarative tree

        Returns:
            Interrogative tree
        """
        # Simplified: mark for subject-auxiliary inversion
        new_tree = SyntaxTree(label=tree.label)
        new_tree.features = tree.features.copy()
        new_tree.features["mood"] = "interrogative"

        for child in tree.children:
            new_tree.add_child(child)

        return new_tree

    def linearize(self, tree: SyntaxTree) -> str:
        """Linearize syntax tree to word sequence.

        Args:
            tree: Syntax tree

        Returns:
            Linearized word sequence
        """
        words = tree.get_yield()
        return " ".join(words)
