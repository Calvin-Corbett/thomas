"""Thomas Search Engine - A full-text search implementation."""

from ._exceptions import AnalyzerError, IndexError, QueryParseError, SearchError
from ._types import (
    FieldMapping,
    FieldType,
    IndexConfig,
    Posting,
    SearchHit,
    SearchQuery,
    SearchResult,
    TokenInfo,
)
from .aggregations import (
    AggregationManager,
    CardinalityAggregation,
    DateHistogramAggregation,
    DerivativeAggregation,
    HistogramAggregation,
    MovingAverageAggregation,
    NestedAggregation,
    PercentileAggregation,
    StatsAggregation,
    TermsAggregation,
)
from .analyzer import (
    Analyzer,
    AnalyzerFactory,
    EdgeNGramFilter,
    LowercaseFilter,
    NGramFilter,
    PorterStemmer,
    StandardTokenizer,
    StopWordFilter,
    SynonymFilter,
    TokenFilter,
    Tokenizer,
    WhitespaceTokenizer,
)
from .facets import (
    DateHistogramFacet,
    Facet,
    FacetAggregator,
    FacetFilter,
    HierarchicalFacet,
    RangeFacet,
    StatsFacet,
    TermFacet,
)
from .filters import (
    BooleanFilter,
    CachedFilter,
    DateRangeFilter,
    FilterComposition,
    FilteredSearch,
    GeoDistanceFilter,
    RangeFilter,
    SearchFilter,
    TermFilter,
    TermsFilter,
)
from .highlight import Highlighter, UnifiedHighlighter
from .index import DocumentStore, InvertedIndex, SegmentedIndex
from .query import (
    BooleanQuery,
    FuzzyQuery,
    MatchAllQuery,
    PhraseQuery,
    PrefixQuery,
    Query,
    QueryParser,
    RangeQuery,
    TermQuery,
    WildcardQuery,
)
from .scoring import BM25, TFIDF, FieldBoost, QueryTimeBoost, ScoreExplanation, SimilarityModel
from .suggest import (
    CompletionSuggester,
    DidYouMeanSuggester,
    FuzzySuggester,
    PhraseSuggester,
    PrefixTrie,
    WeightedSuggester,
)

__version__ = "0.1.0"

__all__ = [
    # Types
    "FieldMapping",
    "FieldType",
    "IndexConfig",
    "Posting",
    "SearchHit",
    "SearchQuery",
    "SearchResult",
    "TokenInfo",
    # Exceptions
    "SearchError",
    "IndexError",
    "QueryParseError",
    "AnalyzerError",
    # Analyzer
    "Analyzer",
    "AnalyzerFactory",
    "Tokenizer",
    "WhitespaceTokenizer",
    "StandardTokenizer",
    "TokenFilter",
    "LowercaseFilter",
    "StopWordFilter",
    "PorterStemmer",
    "NGramFilter",
    "EdgeNGramFilter",
    "SynonymFilter",
    # Index
    "InvertedIndex",
    "DocumentStore",
    "SegmentedIndex",
    # Query
    "Query",
    "TermQuery",
    "PhraseQuery",
    "BooleanQuery",
    "WildcardQuery",
    "FuzzyQuery",
    "RangeQuery",
    "PrefixQuery",
    "MatchAllQuery",
    "QueryParser",
    # Scoring
    "BM25",
    "TFIDF",
    "SimilarityModel",
    "FieldBoost",
    "QueryTimeBoost",
    "ScoreExplanation",
    # Facets
    "Facet",
    "TermFacet",
    "RangeFacet",
    "DateHistogramFacet",
    "HierarchicalFacet",
    "StatsFacet",
    "FacetFilter",
    "FacetAggregator",
    # Highlight
    "Highlighter",
    "UnifiedHighlighter",
    # Suggest
    "CompletionSuggester",
    "FuzzySuggester",
    "DidYouMeanSuggester",
    "PhraseSuggester",
    "WeightedSuggester",
    "PrefixTrie",
    # Filters
    "SearchFilter",
    "RangeFilter",
    "DateRangeFilter",
    "TermFilter",
    "TermsFilter",
    "BooleanFilter",
    "GeoDistanceFilter",
    "CachedFilter",
    "FilterComposition",
    "FilteredSearch",
    # Aggregations
    "TermsAggregation",
    "HistogramAggregation",
    "DateHistogramAggregation",
    "StatsAggregation",
    "CardinalityAggregation",
    "PercentileAggregation",
    "NestedAggregation",
    "DerivativeAggregation",
    "MovingAverageAggregation",
    "AggregationManager",
]
