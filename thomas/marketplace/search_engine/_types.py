"""Core type definitions for the search engine."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FieldType(Enum):
    """Field data types."""

    TEXT = "text"
    KEYWORD = "keyword"
    NUMERIC = "numeric"
    DATE = "date"
    BOOLEAN = "boolean"


@dataclass
class FieldMapping:
    """Configuration for a single field in the index."""

    name: str
    type: FieldType
    indexed: bool = True
    stored: bool = True
    analyzed: bool = True
    boost: float = 1.0

    def __post_init__(self) -> None:
        """Validate field mapping."""
        if self.type in (FieldType.KEYWORD, FieldType.NUMERIC, FieldType.DATE, FieldType.BOOLEAN):
            self.analyzed = False


@dataclass
class TokenInfo:
    """Information about a token in a document."""

    term: str
    position: int
    offset_start: int
    offset_end: int


@dataclass
class Posting:
    """A single posting in the inverted index."""

    doc_id: int
    term_frequency: int = 1
    positions: list[int] = field(default_factory=list)


@dataclass
class SearchHit:
    """A single search result hit."""

    doc_id: int
    score: float
    highlights: dict[str, list[str]] = field(default_factory=dict)
    stored_fields: dict[str, Any] = field(default_factory=dict)
    explanation: str | None = None


@dataclass
class SearchResult:
    """Complete search results."""

    hits: list[SearchHit] = field(default_factory=list)
    total_hits: int = 0
    time_ms: float = 0.0
    facets: dict[str, dict[str, Any]] = field(default_factory=dict)
    query: str | None = None
    took_ms: float | None = None


@dataclass
class SearchQuery:
    """Structured search query."""

    query_string: str
    fields: list[str] | None = None
    default_operator: str = "OR"
    limit: int = 10
    offset: int = 0
    boost: dict[str, float] = field(default_factory=dict)
    filters: dict[str, Any] | None = None
    facets: dict[str, dict[str, Any]] | None = None
    explain: bool = False


@dataclass
class IndexConfig:
    """Configuration for the search index."""

    field_mappings: dict[str, FieldMapping] = field(default_factory=dict)
    default_analyzer: str | None = None
    analyzers: dict[str, dict[str, Any]] = field(default_factory=dict)
    similarity: str = "bm25"
    bm25_k1: float = 1.2
    bm25_b: float = 0.75
    segment_size: int = 10000
    enable_positions: bool = True
    enable_offsets: bool = True
