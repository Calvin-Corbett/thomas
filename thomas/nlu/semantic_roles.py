"""
Semantic role labeling module.

Implements predicate identification, argument identification, role classification
using PropBank roles and frame semantics, with path features from parse trees.
"""

from typing import Any

from thomas.nlu._types import POSTag, SemanticRole, Sentence, Span


class SemanticRoleLabeler:
    """
    Semantic role labeler for identifying predicate-argument structures.

    Identifies predicates (typically verbs), finds arguments, and assigns
    semantic roles following PropBank conventions.
    """

    # PropBank core argument roles
    CORE_ROLES = {
        "ARG0": "agent",
        "ARG1": "theme",
        "ARG2": "instrument/beneficiary/attribute",
        "ARG3": "start point/beneficiary/attribute",
        "ARG4": "end point",
        "ARG5": "modal/negation",
    }

    # PropBank modifier roles
    MODIFIER_ROLES = {
        "ARGM-TMP": "temporal",
        "ARGM-LOC": "locative",
        "ARGM-DIR": "direction",
        "ARGM-MNR": "manner",
        "ARGM-CAU": "cause",
        "ARGM-ADV": "adverbial",
        "ARGM-PRP": "purpose",
        "ARGM-REC": "reciprocal",
        "ARGM-NEG": "negation",
        "ARGM-MOD": "modal",
    }

    def __init__(self) -> None:
        """Initialize semantic role labeler."""
        self.predicates: set[str] = self._load_predicates()
        self.frames: dict[str, dict[str, Any]] = self._load_frames()

    def _load_predicates(self) -> set[str]:
        """Load common predicates."""
        return {
            "give",
            "take",
            "make",
            "use",
            "find",
            "know",
            "think",
            "see",
            "tell",
            "become",
            "leave",
            "feel",
            "bring",
            "begin",
            "show",
            "hear",
            "help",
            "talk",
            "watch",
            "want",
            "mean",
            "call",
            "ask",
            "need",
            "try",
            "break",
            "spend",
            "cut",
            "reach",
            "kill",
            "buy",
            "remember",
            "mention",
            "get",
            "go",
            "come",
            "say",
            "do",
            "have",
            "be",
            "can",
            "will",
            "may",
            "must",
            "should",
            "would",
            "could",
            "might",
        }

    def _load_frames(self) -> dict[str, dict[str, Any]]:
        """Load predicate frames (simplified)."""
        return {
            "give": {"roles": ["ARG0", "ARG1", "ARG2"], "descriptions": ["giver", "thing given", "recipient"]},
            "take": {"roles": ["ARG0", "ARG1", "ARG2"], "descriptions": ["taker", "thing taken", "source"]},
            "use": {"roles": ["ARG0", "ARG1", "ARG2"], "descriptions": ["user", "thing used", "purpose"]},
        }

    def label(self, sentence: Sentence) -> list[tuple[int, list[SemanticRole]]]:
        """
        Assign semantic roles to arguments of predicates.

        Args:
            sentence: Sentence to process

        Returns:
            List of (predicate_idx, roles) tuples for each predicate
        """
        if not sentence.tokens or not sentence.parse_tree:
            return []

        result = []

        # Identify predicates (typically verbs)
        predicate_indices = self._identify_predicates(sentence)

        for pred_idx in predicate_indices:
            predicate_token = sentence.tokens[pred_idx]

            # Find arguments
            arguments = self._find_arguments(pred_idx, sentence)

            # Classify roles
            roles = self._classify_roles(predicate_token.text.lower(), arguments, sentence)

            result.append((pred_idx, roles))

        return result

    def _identify_predicates(self, sentence: Sentence) -> list[int]:
        """
        Identify predicate positions (typically verbs).

        Args:
            sentence: Sentence to process

        Returns:
            List of predicate indices
        """
        predicates = []

        for i, token in enumerate(sentence.tokens):
            # Check if verb
            if token.pos and token.pos.value.startswith("V") or token.text.lower() in self.predicates:
                predicates.append(i)

        return predicates

    def _find_arguments(self, pred_idx: int, sentence: Sentence) -> list[tuple[Span, str, int]]:
        """
        Find arguments of a predicate using parse tree.

        Returns list of (span, text, role_candidate) tuples.

        Args:
            pred_idx: Index of predicate
            sentence: Sentence context

        Returns:
            List of argument candidates
        """
        arguments = []

        if not sentence.parse_tree:
            return arguments

        # Simple heuristic: collect nouns in nearby positions
        # In production, would walk parse tree more carefully

        # Subject (typically precedes predicate)
        for i in range(max(0, pred_idx - 5), pred_idx):
            token = sentence.tokens[i]
            if token.pos and token.pos.value.startswith("N"):
                span = token.span
                arguments.append((span, token.text, "ARG0"))

        # Direct object (typically follows predicate)
        for i in range(pred_idx + 1, min(len(sentence.tokens), pred_idx + 6)):
            token = sentence.tokens[i]
            if token.pos and token.pos.value.startswith("N"):
                span = token.span
                arguments.append((span, token.text, "ARG1"))

        # Modifiers (adverbs, prepositional phrases)
        for i in range(len(sentence.tokens)):
            token = sentence.tokens[i]
            if token.pos in (POSTag.RB, POSTag.RBR, POSTag.RBS, POSTag.IN):
                span = token.span
                if token.pos == POSTag.IN:
                    role = "ARGM-LOC"  # Prepositions often mark locatives
                else:
                    role = "ARGM-MNR"  # Adverbs are manner

                arguments.append((span, token.text, role))

        return arguments

    def _classify_roles(
        self, predicate: str, arguments: list[tuple[Span, str, int]], sentence: Sentence
    ) -> list[SemanticRole]:
        """
        Classify argument roles for predicate.

        Args:
            predicate: Predicate lemma
            arguments: Argument candidates
            sentence: Sentence context

        Returns:
            List of classified semantic roles
        """
        roles = []

        # Get frame if available
        frame = self.frames.get(predicate)

        for i, (span, text, candidate_role) in enumerate(arguments):
            # Use candidate role or refine
            if candidate_role == "ARG0" and predicate in self.frames:
                final_role = "ARG0"
            elif candidate_role == "ARG1" and predicate in self.frames:
                final_role = "ARG1"
            else:
                final_role = candidate_role

            # Get role description
            description = self._get_role_description(final_role)

            roles.append(SemanticRole(role=final_role, span=span, text=text, argument_type=description))

        return roles

    def _get_role_description(self, role: str) -> str:
        """Get description for semantic role."""
        if role in self.CORE_ROLES:
            return self.CORE_ROLES[role]
        elif role in self.MODIFIER_ROLES:
            return self.MODIFIER_ROLES[role]
        else:
            return "unknown"

    def extract_predicate_argument_structure(self, sentence: Sentence) -> dict[int, dict[str, str]]:
        """
        Extract predicate-argument structures in sentence.

        Returns dictionary mapping predicate index to role-argument pairs.

        Args:
            sentence: Sentence to process

        Returns:
            Structured predicate-argument information
        """
        structure: dict[int, dict[str, str]] = {}

        role_assignments = self.label(sentence)

        for pred_idx, roles in role_assignments:
            pred_structure: dict[str, str] = {}

            for role in roles:
                pred_structure[role.role] = role.text

            structure[pred_idx] = pred_structure

        return structure

    def get_path_features(self, argument_idx: int, predicate_idx: int, sentence: Sentence) -> list[str]:
        """
        Extract path features from parse tree between predicate and argument.

        Args:
            argument_idx: Index of argument token
            predicate_idx: Index of predicate token
            sentence: Sentence with parse tree

        Returns:
            List of path features
        """
        if not sentence.parse_tree:
            return []

        features = []

        # Simple distance feature
        distance = abs(argument_idx - predicate_idx)
        features.append(f"distance_{distance}")

        # Direction feature
        if argument_idx < predicate_idx:
            features.append("direction_before")
        else:
            features.append("direction_after")

        # POS path
        arg_pos = sentence.tokens[argument_idx].pos
        pred_pos = sentence.tokens[predicate_idx].pos

        if arg_pos and pred_pos:
            features.append(f"pos_path_{arg_pos.value}_{pred_pos.value}")

        # Check for intervening punctuation/conjunctions
        intervening = sentence.tokens[min(argument_idx, predicate_idx) + 1 : max(argument_idx, predicate_idx)]
        for token in intervening:
            if token.pos == POSTag.CC:
                features.append("has_conjunction")
                break
            elif token.pos == POSTag.COMMA:
                features.append("has_comma")

        return features
