"""
Type definitions for the NLU module.

Defines all core data structures used throughout the NLU pipeline including
tokens, sentences, documents, linguistic annotations, and results.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class POSTag(str, Enum):
    """Penn Treebank POS tags."""

    # Nouns
    NN = "NN"  # Noun, singular
    NNS = "NNS"  # Noun, plural
    NNP = "NNP"  # Proper noun, singular
    NNPS = "NNPS"  # Proper noun, plural

    # Verbs
    VB = "VB"  # Verb, base form
    VBD = "VBD"  # Verb, past tense
    VBG = "VBG"  # Verb, gerund/present participle
    VBN = "VBN"  # Verb, past participle
    VBP = "VBP"  # Verb, present tense (non-3rd person)
    VBZ = "VBZ"  # Verb, present tense (3rd person singular)

    # Adjectives and Adverbs
    JJ = "JJ"  # Adjective
    JJR = "JJR"  # Adjective, comparative
    JJS = "JJS"  # Adjective, superlative
    RB = "RB"  # Adverb
    RBR = "RBR"  # Adverb, comparative
    RBS = "RBS"  # Adverb, superlative
    RP = "RP"  # Particle

    # Determiners and Pronouns
    DT = "DT"  # Determiner
    PRP = "PRP"  # Personal pronoun
    PRP_DOLLAR = "PRP$"  # Possessive pronoun
    WP = "WP"  # Wh-pronoun
    WP_DOLLAR = "WP$"  # Possessive wh-pronoun

    # Other
    IN = "IN"  # Preposition/subordinating conjunction
    CC = "CC"  # Coordinating conjunction
    CD = "CD"  # Cardinal number
    MD = "MD"  # Modal
    UH = "UH"  # Interjection
    FW = "FW"  # Foreign word

    # Punctuation
    PERIOD = "."
    COMMA = ","
    COLON = ":"
    SEMICOLON = ";"
    QUOTE = "'"
    DOUBLE_QUOTE = '"'
    LPAREN = "("
    RPAREN = ")"


class NERTag(str, Enum):
    """Named Entity Recognition tags (BIO scheme)."""

    # Standard BIO tags
    O = "O"  # Outside any entity

    # Person
    B_PER = "B-PER"  # Begin person
    I_PER = "I-PER"  # Inside person

    # Location
    B_LOC = "B-LOC"  # Begin location
    I_LOC = "I-LOC"  # Inside location

    # Organization
    B_ORG = "B-ORG"  # Begin organization
    I_ORG = "I-ORG"  # Inside organization

    # Miscellaneous (product, event, etc.)
    B_MISC = "B-MISC"
    I_MISC = "I-MISC"

    # Additional tags for detailed categorization
    B_DATE = "B-DATE"
    I_DATE = "I-DATE"
    B_TIME = "B-TIME"
    I_TIME = "I-TIME"
    B_MONEY = "B-MONEY"
    I_MONEY = "I-MONEY"
    B_PERCENT = "B-PERCENT"
    I_PERCENT = "I-PERCENT"
    B_EMAIL = "B-EMAIL"
    I_EMAIL = "I-EMAIL"
    B_URL = "B-URL"
    I_URL = "I-URL"


@dataclass(frozen=True)
class Span:
    """Represents a text span with start and end character offsets."""

    start: int
    end: int

    def __post_init__(self) -> None:
        """Validate span."""
        if self.start < 0 or self.end < 0 or self.start > self.end:
            raise ValueError(f"Invalid span: start={self.start}, end={self.end}")

    @property
    def length(self) -> int:
        """Get span length."""
        return self.end - self.start

    def overlaps(self, other: "Span") -> bool:
        """Check if this span overlaps with another."""
        return self.start < other.end and other.start < self.end

    def contains(self, other: "Span") -> bool:
        """Check if this span contains another."""
        return self.start <= other.start and other.end <= self.end


@dataclass
class Token:
    """Represents a single token."""

    text: str
    span: Span
    pos: POSTag | None = None
    lemma: str | None = None
    features: dict[str, Any] = field(default_factory=dict)

    @property
    def normalized(self) -> str:
        """Get normalized (lowercased) token text."""
        return self.text.lower()


@dataclass
class Dependency:
    """Represents a dependency relation between two tokens."""

    head_idx: int  # Index of head token
    dependent_idx: int  # Index of dependent token
    label: str  # Dependency label (e.g., "nsubj", "obj")

    def __post_init__(self) -> None:
        """Validate dependency."""
        if self.head_idx < 0 or self.dependent_idx < 0:
            raise ValueError("Token indices must be non-negative")
        if self.head_idx == self.dependent_idx:
            raise ValueError("Head and dependent cannot be the same token")


@dataclass
class ParseTree:
    """Represents a parse tree (constituency or dependency)."""

    root: int  # Index of root token (for dependency trees)
    dependencies: list[Dependency] = field(default_factory=list)
    is_projective: bool = False

    def add_dependency(self, dep: Dependency) -> None:
        """Add a dependency to the tree."""
        self.dependencies.append(dep)

    def get_children(self, idx: int) -> list[int]:
        """Get child indices of a token."""
        return [d.dependent_idx for d in self.dependencies if d.head_idx == idx]

    def get_parent(self, idx: int) -> int | None:
        """Get parent index of a token."""
        for d in self.dependencies:
            if d.dependent_idx == idx:
                return d.head_idx
        return None


@dataclass
class Sentence:
    """Represents a processed sentence with linguistic annotations."""

    text: str
    tokens: list[Token] = field(default_factory=list)
    parse_tree: ParseTree | None = None
    entities: list["Entity"] = field(default_factory=list)
    sentiment: float | None = None  # -1.0 to 1.0

    @property
    def token_texts(self) -> list[str]:
        """Get token texts."""
        return [t.text for t in self.tokens]


@dataclass
class Document:
    """Represents a complete document with multiple sentences."""

    text: str
    sentences: list[Sentence] = field(default_factory=list)
    entities: list["Entity"] = field(default_factory=list)
    intents: list["Intent"] = field(default_factory=list)
    slots: list["Slot"] = field(default_factory=list)
    dialogue_acts: list["DialogueAct"] = field(default_factory=list)
    coreferences: list[list[Span]] = field(default_factory=list)

    @property
    def all_tokens(self) -> list[Token]:
        """Get all tokens from all sentences."""
        return [t for sent in self.sentences for t in sent.tokens]


@dataclass
class Entity:
    """Represents a named entity."""

    text: str
    span: Span
    label: NERTag
    confidence: float = 1.0
    canonical_form: str | None = None  # Normalized/linked form
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate entity."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be in [0, 1], got {self.confidence}")


@dataclass
class Intent:
    """Represents a detected intent."""

    label: str
    confidence: float
    sentence_idx: int | None = None
    parent_intent: str | None = None  # For hierarchical intents
    auxiliary_intents: list[tuple[str, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate intent."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be in [0, 1], got {self.confidence}")


@dataclass
class Slot:
    """Represents a filled slot in dialogue."""

    name: str
    value: Any
    value_type: str  # e.g., "date", "location", "person"
    span: Span | None = None
    confidence: float = 1.0
    normalized_value: str | None = None
    is_confirmed: bool = False

    def __post_init__(self) -> None:
        """Validate slot."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be in [0, 1], got {self.confidence}")


@dataclass
class DialogueAct:
    """Represents a dialogue act (speech act)."""

    type: str  # e.g., "request", "inform", "question"
    slots: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


@dataclass
class SemanticRole:
    """Represents a semantic role (PropBank style)."""

    role: str  # e.g., "ARG0", "ARG1", "ARGM-LOC", "ARGM-TMP"
    span: Span
    text: str
    argument_type: str = ""  # e.g., "agent", "theme", "location"


@dataclass
class FeatureVector:
    """Represents a feature vector for ML models."""

    features: dict[str, float]
    label: str | None = None

    def to_dict(self) -> dict[str, float]:
        """Convert to dictionary."""
        return self.features.copy()

    def dimension(self) -> int:
        """Get feature vector dimension."""
        return len(self.features)


@dataclass
class ClassificationResult:
    """Result of text classification."""

    predictions: dict[str, float]  # label -> confidence
    top_label: str
    top_confidence: float
    all_scores: list[tuple[str, float]] = field(default_factory=list)

    def get_sorted_predictions(self) -> list[tuple[str, float]]:
        """Get predictions sorted by confidence (descending)."""
        return sorted(self.predictions.items(), key=lambda x: x[1], reverse=True)


@dataclass
class ExtractionResult:
    """Result of information extraction."""

    entities: list[Entity] = field(default_factory=list)
    slots: list[Slot] = field(default_factory=list)
    relations: list[tuple[int, int, str]] = field(default_factory=list)  # (entity1_idx, entity2_idx, relation_label)


@dataclass
class SentimentResult:
    """Result of sentiment analysis."""

    polarity: float  # -1.0 (negative) to 1.0 (positive)
    confidence: float  # 0.0 to 1.0
    subjectivity: float  # 0.0 (objective) to 1.0 (subjective)
    emotions: dict[str, float] = field(default_factory=dict)  # emotion -> intensity
    aspect_sentiments: dict[str, float] = field(default_factory=dict)  # aspect -> polarity
    positive_phrases: list[str] = field(default_factory=list)
    negative_phrases: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate sentiment result."""
        if not -1.0 <= self.polarity <= 1.0:
            raise ValueError(f"Polarity must be in [-1, 1], got {self.polarity}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be in [0, 1], got {self.confidence}")
        if not 0.0 <= self.subjectivity <= 1.0:
            raise ValueError(f"Subjectivity must be in [0, 1], got {self.subjectivity}")
