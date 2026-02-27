"""Natural Language Generation (NLG) Engine.

A comprehensive NLG pipeline for converting structured data to natural language text.
"""

from thomas.nlg._exceptions import (
    ContentSelectionError,
    DocumentPlanningError,
    GrammarError,
    MorphologyError,
    NLGException,
    RealizationError,
    SentencePlanningError,
)
from thomas.nlg._types import (
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
from thomas.nlg.data_to_text import DataToTextGenerator
from thomas.nlg.dialogue import DialogueGenerator
from thomas.nlg.grammar import GrammarEngine
from thomas.nlg.morphology import MorphologyEngine
from thomas.nlg.planning import DocumentPlanner
from thomas.nlg.realization import Realizer
from thomas.nlg.sentence_planning import SentencePlanner
from thomas.nlg.style import StyleController
from thomas.nlg.templates import TemplateEngine

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
