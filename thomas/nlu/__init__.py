"""
Natural Language Understanding (NLU) module.

Provides comprehensive NLP/NLU functionality including tokenization, POS tagging,
named entity recognition, dependency parsing, intent classification, sentiment analysis,
slot filling, coreference resolution, and semantic role labeling.
"""

from thomas.nlu._exceptions import (
    ClassificationError,
    EntityExtractionError,
    NLUException,
    ParsingError,
    TokenizationError,
)
from thomas.nlu._types import (
    ClassificationResult,
    Dependency,
    DialogueAct,
    Document,
    Entity,
    ExtractionResult,
    FeatureVector,
    Intent,
    NERTag,
    ParseTree,
    POSTag,
    SemanticRole,
    Sentence,
    SentimentResult,
    Slot,
    Span,
    Token,
)
from thomas.nlu.coreference import CoreferenceResolver
from thomas.nlu.intent import IntentClassifier
from thomas.nlu.ner import GazetteerMatcher, NERTagger
from thomas.nlu.parser import DependencyParser
from thomas.nlu.pos_tagger import POSTagger
from thomas.nlu.semantic_roles import SemanticRoleLabeler
from thomas.nlu.sentiment import SentimentAnalyzer
from thomas.nlu.slot_filling import SlotFiller
from thomas.nlu.tokenizer import BPETokenizer, Tokenizer

__all__ = [
    "Token",
    "Sentence",
    "Document",
    "Intent",
    "Entity",
    "Slot",
    "DialogueAct",
    "SemanticRole",
    "Dependency",
    "POSTag",
    "NERTag",
    "Span",
    "ParseTree",
    "FeatureVector",
    "ClassificationResult",
    "ExtractionResult",
    "SentimentResult",
    "NLUException",
    "TokenizationError",
    "ParsingError",
    "EntityExtractionError",
    "ClassificationError",
    "Tokenizer",
    "BPETokenizer",
    "POSTagger",
    "NERTagger",
    "GazetteerMatcher",
    "DependencyParser",
    "IntentClassifier",
    "SentimentAnalyzer",
    "SlotFiller",
    "CoreferenceResolver",
    "SemanticRoleLabeler",
]

__version__ = "0.1.0"
