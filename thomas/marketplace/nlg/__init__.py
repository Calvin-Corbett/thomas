"""Natural Language Generation (NLG) Engine.

A comprehensive NLG pipeline for converting structured data to natural language text.
"""

from thomas.marketplace.nlg._exceptions import (
    ContentSelectionError,
    DocumentPlanningError,
    GrammarError,
    MorphologyError,
    NLGException,
    RealizationError,
    SentencePlanningError,
)
from thomas.marketplace.nlg._types import (
    Aspect,
    DiscourseStructure,
    Document,
    Gender,
    GrammarRule,
    Lexicon,
    MorphologicalForm,
    Number,
    Person,
    Phrase,
    RhetoricalRelation,
    SemanticFrame,
    Sentence,
    Slot,
    SurfaceForm,
    SyntaxTree,
    Tense,
    TextPlan,
    Voice,
    Word,
)
from thomas.marketplace.nlg.data_to_text import DataToTextGenerator
from thomas.marketplace.nlg.dialogue import DialogueGenerator
from thomas.marketplace.nlg.grammar import GrammarEngine
from thomas.marketplace.nlg.morphology import MorphologyEngine
from thomas.marketplace.nlg.planning import DocumentPlanner
from thomas.marketplace.nlg.realization import Realizer
from thomas.marketplace.nlg.sentence_planning import SentencePlanner
from thomas.marketplace.nlg.style import StyleController
from thomas.marketplace.nlg.templates import TemplateEngine

__all__ = [
    "Document",
    "Sentence",
    "Phrase",
    "Word",
    "Lexicon",
    "GrammarRule",
    "SyntaxTree",
    "SemanticFrame",
    "Slot",
    "RhetoricalRelation",
    "DiscourseStructure",
    "TextPlan",
    "SurfaceForm",
    "MorphologicalForm",
    "Tense",
    "Aspect",
    "Voice",
    "Person",
    "Number",
    "Gender",
    "NLGException",
    "ContentSelectionError",
    "DocumentPlanningError",
    "SentencePlanningError",
    "GrammarError",
    "MorphologyError",
    "RealizationError",
    "DocumentPlanner",
    "SentencePlanner",
    "GrammarEngine",
    "MorphologyEngine",
    "TemplateEngine",
    "Realizer",
    "DataToTextGenerator",
    "StyleController",
    "DialogueGenerator",
]
