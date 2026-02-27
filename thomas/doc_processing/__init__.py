"""Document processing and analysis engine.

A comprehensive module for extracting, analyzing, and processing documents
in various formats (PDF, HTML, plain text, etc.).
"""

from thomas.doc_processing._exceptions import (
    ClassificationError,
    ConversionError,
    DocumentProcessingError,
    ExtractionError,
    LayoutError,
    MetadataError,
    OCRError,
    SearchIndexError,
    TableError,
)
from thomas.doc_processing._types import (
    Annotation,
    Bookmark,
    BoundingBox,
    Document,
    Figure,
    FontInfo,
    Footer,
    Header,
    Layout,
    Metadata,
    Page,
    Paragraph,
    ReadingOrder,
    Sentence,
    Style,
    Table,
    TableCell,
    TextBlock,
    TOCEntry,
    Token,
)

__all__ = [
    "BoundingBox",
    "Document",
    "FontInfo",
    "Header",
    "Footer",
    "Annotation",
    "Layout",
    "Metadata",
    "Page",
    "Paragraph",
    "Sentence",
    "Style",
    "Table",
    "TableCell",
    "TextBlock",
    "Token",
    "Figure",
    "Bookmark",
    "TOCEntry",
    "ReadingOrder",
    "DocumentProcessingError",
    "ExtractionError",
    "LayoutError",
    "TableError",
    "ClassificationError",
    "SearchIndexError",
    "ConversionError",
    "MetadataError",
    "OCRError",
]

__version__ = "0.1.0"
