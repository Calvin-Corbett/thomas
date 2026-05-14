"""Sentence planning: transforming semantic frames to sentence structures.

Implements sentence planning including:
- Sentence aggregation
- Lexicalization
- Referring expression generation
- Sentence splitting for readability
"""

from typing import Any

from thomas.marketplace.nlg._exceptions import SentencePlanningError
from thomas.marketplace.nlg._types import (
    Lexicon,
    Phrase,
    SemanticFrame,
    Sentence,
)


class SentencePlanner:
    """Plans sentences from semantic frames.

    Transforms semantic content into sentence-level structures through
    aggregation, lexicalization, and referring expression generation.
    """

    def __init__(self) -> None:
        """Initialize sentence planner."""
        self.max_sentence_length: int = 30
        self.aggregation_distance: int = 3
        self.lexicon: dict[str, Lexicon] = {}
        self._build_default_lexicon()

    def _build_default_lexicon(self) -> None:
        """Build default lexicon for common concepts."""
        common_words = {
            "person": Lexicon("person", "NN", synonyms=["individual", "human"]),
            "move": Lexicon(
                "move",
                "VB",
                synonyms=["go", "travel", "journey"],
                morphology={"past": ["moved"], "ing": ["moving"]},
            ),
            "fast": Lexicon("fast", "JJ", synonyms=["quick", "rapid"], register="neutral"),
            "good": Lexicon("good", "JJ", synonyms=["excellent", "fine", "well"], register="neutral"),
        }
        self.lexicon = common_words

    def aggregate_sentences(self, frames: list[SemanticFrame]) -> list[list[SemanticFrame]]:
        """Group semantic frames for sentence aggregation.

        Identifies frames that can be combined into single sentences through
        conjunction (and, or), relative clauses, or participial phrases.

        Args:
            frames: Semantic frames to aggregate

        Returns:
            List of frame groups for aggregation
        """
        if not frames:
            return []

        groups: list[list[SemanticFrame]] = []

        for frame in frames:
            # Try to add to existing group
            added = False
            for group in groups:
                if self._can_aggregate(frame, group[-1]):
                    group.append(frame)
                    added = True
                    break

            if not added:
                groups.append([frame])

        return groups

    def _can_aggregate(self, frame1: SemanticFrame, frame2: SemanticFrame) -> bool:
        """Check if two frames can be aggregated.

        Args:
            frame1: First frame
            frame2: Second frame

        Returns:
            True if frames can be combined
        """
        # Same predicate -> conjunction
        if frame1.predicate == frame2.predicate:
            return True

        # Shared arguments -> relative clause potential
        args1 = self._get_slot_fillers(frame1)
        args2 = self._get_slot_fillers(frame2)

        shared = len(set(args1) & set(args2))
        all_args = len(set(args1) | set(args2))

        if all_args > 0 and shared / all_args > 0.5:
            return True

        return False

    def _get_slot_fillers(self, frame: SemanticFrame) -> list[Any]:
        """Extract all slot fillers from a frame.

        Args:
            frame: Semantic frame

        Returns:
            List of filler values
        """
        fillers: list[Any] = []
        for slot in frame.slots:
            if slot.filler is not None:
                fillers.append(slot.filler)
        return fillers

    def lexicalize(self, frame: SemanticFrame, register: str = "neutral") -> dict[str, str]:
        """Choose words (lexical items) for frame concepts.

        Selects lexical items for the predicate and arguments, considering
        register (formality level), synonymy, and collocation patterns.

        Args:
            frame: Semantic frame to lexicalize
            register: Register level (formal, neutral, informal)

        Returns:
            Dictionary mapping frame elements to word choices

        Raises:
            SentencePlanningError: If lexicalization fails
        """
        if not frame.predicate:
            raise SentencePlanningError("Frame has no predicate")

        lexical_choices: dict[str, str] = {}

        # Lexicalize predicate
        lexical_choices["predicate"] = self._choose_word(frame.predicate, register)

        # Lexicalize arguments
        for slot in frame.slots:
            if slot.filler:
                lexical_choices[slot.name] = self._choose_word(str(slot.filler), register)

        return lexical_choices

    def _choose_word(self, concept: str, register: str = "neutral") -> str:
        """Choose a word for a concept.

        Args:
            concept: Concept to lexicalize
            register: Register level

        Returns:
            Chosen word
        """
        # Look up in lexicon
        if concept in self.lexicon:
            lex_entry = self.lexicon[concept]

            # Choose based on register
            if register == "formal" and lex_entry.synonyms:
                return lex_entry.synonyms[0]
            elif register == "informal" and len(lex_entry.synonyms) > 1:
                return lex_entry.synonyms[-1]

            return lex_entry.lemma

        # Default: use concept as-is
        return concept

    def generate_referring_expressions(
        self, entities: list[dict[str, Any]], context: set[str] | None = None
    ) -> dict[str, str]:
        """Generate referring expressions for entities.

        Generates appropriate referring expressions that evolve through discourse:
        full name → pronoun → definite description based on context and salience.

        Args:
            entities: List of entities to refer to
            context: Set of previously mentioned entity IDs

        Returns:
            Dictionary mapping entity IDs to referring expressions

        Raises:
            SentencePlanningError: If expression generation fails
        """
        if context is None:
            context = set()

        if not entities:
            raise SentencePlanningError("No entities to generate references for")

        expressions: dict[str, str] = {}

        for entity in entities:
            entity_id = entity.get("id", "unknown")
            name = entity.get("name", "entity")
            entity.get("category", "object")
            gender = entity.get("gender", "neuter")

            if entity_id in context:
                # Previously mentioned -> use pronoun or definite description
                if gender == "masculine":
                    expressions[entity_id] = "he"
                elif gender == "feminine":
                    expressions[entity_id] = "she"
                else:
                    expressions[entity_id] = "it"
            else:
                # First mention -> use full name
                expressions[entity_id] = name
                context.add(entity_id)

        return expressions

    def split_sentences(self, tokens: list[str], max_length: int = 20) -> list[list[str]]:
        """Split long sentences for readability.

        Splits sentences at natural boundaries (conjunctions, clauses) to improve
        readability while maintaining semantic coherence.

        Args:
            tokens: Token sequence
            max_length: Maximum tokens per sentence

        Returns:
            List of token sequences (sentences)

        Raises:
            SentencePlanningError: If splitting fails
        """
        if not tokens:
            raise SentencePlanningError("No tokens to split")

        if len(tokens) <= max_length:
            return [tokens]

        sentences: list[list[str]] = []
        current_sent: list[str] = []

        # Split points: and, or, but, semicolon, period
        split_markers = {"and", "or", "but", ";", "."}

        for token in tokens:
            current_sent.append(token)

            # Check if we should split
            if (token in split_markers and len(current_sent) > max_length // 2) or len(current_sent) >= max_length:
                sentences.append(current_sent)
                current_sent = []

        if current_sent:
            sentences.append(current_sent)

        return sentences

    def plan_sentence(self, frame: SemanticFrame, discourse_context: dict[str, Any] | None = None) -> Sentence:
        """Plan a complete sentence from a semantic frame.

        Args:
            frame: Semantic frame to realize
            discourse_context: Discourse context (previous content)

        Returns:
            Planned sentence

        Raises:
            SentencePlanningError: If planning fails
        """
        if not frame.predicate:
            raise SentencePlanningError("Frame has no predicate")

        sent_id = frame.metadata.get("id", "S0")
        sentence = Sentence(id=sent_id)
        sentence.semantic_frames = [frame]

        # Set default salience
        sentence.salience = frame.metadata.get("salience", 0.5)

        return sentence

    def aggregate_frames(self, frames: list[SemanticFrame]) -> list[list[SemanticFrame]]:
        """Aggregate similar semantic frames.

        Combines frames with shared predicates or arguments for sentence
        aggregation through coordination and relative clauses.

        Args:
            frames: Frames to aggregate

        Returns:
            Grouped frames
        """
        if not frames:
            return []

        groups: list[list[SemanticFrame]] = []

        for frame in frames:
            added = False
            for group in groups:
                if self._frames_similar(frame, group[0]):
                    group.append(frame)
                    added = True
                    break

            if not added:
                groups.append([frame])

        return groups

    def _frames_similar(self, f1: SemanticFrame, f2: SemanticFrame) -> bool:
        """Check if two frames are similar.

        Args:
            f1: First frame
            f2: Second frame

        Returns:
            True if similar
        """
        # Same predicate
        if f1.predicate == f2.predicate:
            return True

        # Check for shared arguments
        fillers1 = set(str(s.filler) for s in f1.slots if s.filler)
        fillers2 = set(str(s.filler) for s in f2.slots if s.filler)

        if fillers1 and fillers2:
            overlap = len(fillers1 & fillers2)
            total = len(fillers1 | fillers2)
            return overlap / total > 0.3 if total > 0 else False

        return False

    def order_constituents(self, constituents: list[Phrase], sentence_type: str = "declarative") -> list[Phrase]:
        """Order sentence constituents based on grammar and pragmatics.

        Args:
            constituents: Sentence constituents to order
            sentence_type: Type of sentence (declarative, interrogative, etc.)

        Returns:
            Ordered constituents
        """
        if not constituents:
            return []

        # For declarative: subject before verb, verb before object
        # For interrogative: auxiliary before subject
        # For imperative: verb first

        sorted_constituents = sorted(
            constituents,
            key=lambda c: self._constituent_position_score(c, sentence_type),
        )

        return sorted_constituents

    def _constituent_position_score(self, constituent: Phrase, sentence_type: str) -> float:
        """Score optimal position for a constituent.

        Args:
            constituent: Constituent to score
            sentence_type: Sentence type

        Returns:
            Position score (lower = earlier in sentence)
        """
        scores = {
            "NP": 0,  # Subject typically first
            "VP": 1,  # Verb typically second
            "PP": 2,  # Prepositional phrase typically later
            "ADVP": 2,  # Adverbial phrase typically later
        }

        base_score = scores.get(constituent.phrase_type, 1)

        # Adjust for sentence type
        if sentence_type == "interrogative" and constituent.phrase_type == "VP":
            base_score = -0.5  # Auxiliary fronts in questions

        return base_score
