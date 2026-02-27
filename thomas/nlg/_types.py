"""Type definitions for NLG system.

Defines core data structures for linguistic representation including:
- Document structures
- Syntactic trees
- Semantic frames
- Discourse structures
- Morphological forms
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Tense(Enum):
    """Verb tense classification."""

    PRESENT = "present"
    PAST = "past"
    FUTURE = "future"
    CONDITIONAL = "conditional"


class Aspect(Enum):
    """Verb aspect classification."""

    SIMPLE = "simple"
    PROGRESSIVE = "progressive"
    PERFECT = "perfect"
    PERFECT_PROGRESSIVE = "perfect_progressive"


class Voice(Enum):
    """Voice classification."""

    ACTIVE = "active"
    PASSIVE = "passive"


class Person(Enum):
    """Person classification for agreement."""

    FIRST = "first"
    SECOND = "second"
    THIRD = "third"


class Number(Enum):
    """Number classification."""

    SINGULAR = "singular"
    PLURAL = "plural"


class Gender(Enum):
    """Gender classification."""

    MASCULINE = "masculine"
    FEMININE = "feminine"
    NEUTER = "neuter"


class RhetoricalRelation(Enum):
    """Rhetorical Structure Theory relations."""

    ELABORATION = "elaboration"
    EXPLANATION = "explanation"
    RESULT = "result"
    CAUSE = "cause"
    CONDITION = "condition"
    CONTRAST = "contrast"
    SEQUENCE = "sequence"
    SUMMARY = "summary"
    BACKGROUND = "background"
    PURPOSE = "purpose"
    ENABLEMENT = "enablement"
    EVIDENCE = "evidence"


@dataclass
class Word:
    """Represents a single word token."""

    lemma: str
    pos: str
    features: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate word data."""
        if not self.lemma or not self.pos:
            raise ValueError("Word must have lemma and part-of-speech")


@dataclass
class MorphologicalForm:
    """Represents a morphologically inflected form."""

    base: str
    tense: Tense | None = None
    aspect: Aspect | None = None
    voice: Voice | None = None
    person: Person | None = None
    number: Number | None = None
    gender: Gender | None = None
    mood: str | None = None
    case: str | None = None

    def get_features(self) -> dict[str, str | None]:
        """Extract morphological features as dictionary."""
        return {
            "tense": self.tense.value if self.tense else None,
            "aspect": self.aspect.value if self.aspect else None,
            "voice": self.voice.value if self.voice else None,
            "person": self.person.value if self.person else None,
            "number": self.number.value if self.number else None,
            "gender": self.gender.value if self.gender else None,
            "mood": self.mood,
            "case": self.case,
        }


@dataclass
class SurfaceForm:
    """Represents the surface realization of a word."""

    form: str
    lemma: str
    morphology: MorphologicalForm
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Slot:
    """Slot in a semantic frame."""

    name: str
    value_type: str
    required: bool = False
    constraints: list[str] = field(default_factory=list)
    filler: Any | None = None

    def validate(self) -> bool:
        """Validate slot constraints."""
        if self.required and self.filler is None:
            return False
        return True


@dataclass
class SemanticFrame:
    """Semantic frame representing a concept or event."""

    predicate: str
    slots: list[Slot] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_slot(self, name: str) -> Slot | None:
        """Get a slot by name."""
        for slot in self.slots:
            if slot.name == name:
                return slot
        return None

    def fill_slot(self, name: str, value: Any) -> None:
        """Fill a slot with a value."""
        slot = self.get_slot(name)
        if slot:
            slot.filler = value

    def is_complete(self) -> bool:
        """Check if all required slots are filled."""
        return all(slot.validate() for slot in self.slots)


@dataclass
class SyntaxTree:
    """Syntax tree node."""

    label: str
    children: list["SyntaxTree"] = field(default_factory=list)
    word: Word | None = None
    surface: SurfaceForm | None = None
    features: dict[str, Any] = field(default_factory=dict)

    def is_leaf(self) -> bool:
        """Check if this is a leaf node."""
        return len(self.children) == 0

    def get_yield(self) -> list[str]:
        """Get terminal yield (sequence of words)."""
        if self.is_leaf() and self.surface:
            return [self.surface.form]
        yield_words: list[str] = []
        for child in self.children:
            yield_words.extend(child.get_yield())
        return yield_words

    def add_child(self, child: "SyntaxTree") -> None:
        """Add a child node."""
        self.children.append(child)

    def get_depth(self) -> int:
        """Get tree depth."""
        if self.is_leaf():
            return 0
        return 1 + max((child.get_depth() for child in self.children), default=0)


@dataclass
class Phrase:
    """Phrase-level structure."""

    phrase_type: str
    head: Word | None = None
    dependents: list["Phrase"] = field(default_factory=list)
    syntax_tree: SyntaxTree | None = None
    semantic_role: str | None = None

    def add_dependent(self, dependent: "Phrase") -> None:
        """Add a dependent phrase."""
        self.dependents.append(dependent)


@dataclass
class Sentence:
    """Sentence-level structure."""

    id: str
    semantic_frames: list[SemanticFrame] = field(default_factory=list)
    syntax_tree: SyntaxTree | None = None
    surface_form: str | None = None
    rhetorical_relations: list[tuple["Sentence", RhetoricalRelation]] = field(default_factory=list)
    salience: float = 1.0
    aggregation_id: str | None = None

    def add_relation(self, target: "Sentence", relation: RhetoricalRelation) -> None:
        """Add rhetorical relation to another sentence."""
        self.rhetorical_relations.append((target, relation))

    def get_content_score(self) -> float:
        """Score content importance (0-1)."""
        score = 0.0
        if self.semantic_frames:
            score += 0.5 * min(len(self.semantic_frames) / 3.0, 1.0)
        score += 0.5 * self.salience
        return min(score, 1.0)


@dataclass
class Document:
    """Top-level document structure."""

    id: str
    sentences: list[Sentence] = field(default_factory=list)
    paragraphs: list[list[Sentence]] = field(default_factory=list)
    discourse_structure: Optional["DiscourseStructure"] = None
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_sentence(self, sentence: Sentence) -> None:
        """Add a sentence to document."""
        self.sentences.append(sentence)

    def add_paragraph(self, sentences: list[Sentence]) -> None:
        """Add a paragraph (group of sentences)."""
        self.paragraphs.append(sentences)

    def get_text(self) -> str:
        """Reconstruct text from surface forms."""
        if self.paragraphs:
            para_texts = [" ".join(s.surface_form or "" for s in para) for para in self.paragraphs]
            return "\n\n".join(para_texts)
        return " ".join(s.surface_form or "" for s in self.sentences)


@dataclass
class DiscourseStructure:
    """RST-style discourse tree."""

    nucleus: Sentence | None = None
    satellites: list[tuple[RhetoricalRelation, "DiscourseStructure"]] = field(default_factory=list)
    left_child: Optional["DiscourseStructure"] = None
    right_child: Optional["DiscourseStructure"] = None

    def add_satellite(self, relation: RhetoricalRelation, satellite: "DiscourseStructure") -> None:
        """Add a satellite with rhetorical relation."""
        self.satellites.append((relation, satellite))

    def get_sentences(self) -> list[Sentence]:
        """Extract all sentences from discourse tree."""
        sentences: list[Sentence] = []
        if self.nucleus:
            sentences.append(self.nucleus)
        for _, satellite in self.satellites:
            sentences.extend(satellite.get_sentences())
        return sentences


@dataclass
class TextPlan:
    """High-level text plan from content selection and structuring."""

    content_items: list[dict[str, Any]] = field(default_factory=list)
    structure: list[int] = field(default_factory=list)
    ordering: list[int] = field(default_factory=list)
    aggregation_groups: list[list[int]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_content(self, item: dict[str, Any]) -> int:
        """Add content item, return its index."""
        self.content_items.append(item)
        return len(self.content_items) - 1

    def get_ordered_content(self) -> list[dict[str, Any]]:
        """Get content items in planned order."""
        if not self.ordering:
            return self.content_items
        return [self.content_items[i] for i in self.ordering]


@dataclass
class GrammarRule:
    """Context-free grammar rule with features."""

    lhs: str
    rhs: list[str] = field(default_factory=list)
    features: dict[str, str] = field(default_factory=dict)
    semantic_action: str | None = None
    obligatory: bool = True
    weight: float = 1.0

    def is_terminal(self) -> bool:
        """Check if RHS contains only terminals."""
        return all(rhs.islower() or rhs in [".", ",", "!", "?"]) if self.rhs else False

    def is_epsilon(self) -> bool:
        """Check if this is an epsilon rule."""
        return len(self.rhs) == 0


@dataclass
class Lexicon:
    """Lexicon entry with morphological and semantic info."""

    lemma: str
    pos: str
    sense_id: str | None = None
    frequency: float = 1.0
    register: str = "neutral"
    synonyms: list[str] = field(default_factory=list)
    antonyms: list[str] = field(default_factory=list)
    morphology: dict[str, list[str]] = field(default_factory=dict)
    collocations: list[str] = field(default_factory=list)
    semantic_properties: dict[str, Any] = field(default_factory=dict)

    def get_variants(self, key: str) -> list[str]:
        """Get morphological variants."""
        return self.morphology.get(key, [self.lemma])

    def get_synonym(self, register: str = "neutral") -> str | None:
        """Get synonym matching register."""
        if not self.synonyms:
            return None
        for syn in self.synonyms:
            return syn
        return self.synonyms[0] if self.synonyms else None
