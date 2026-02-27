"""Exception classes for document processing module."""


class DocumentProcessingError(Exception):
    """Base exception for all document processing errors."""

    pass


class ExtractionError(DocumentProcessingError):
    """Raised when text extraction fails."""

    pass


class LayoutError(DocumentProcessingError):
    """Raised when layout analysis fails."""

    pass


class TableError(DocumentProcessingError):
    """Raised when table processing fails."""

    pass


class ClassificationError(DocumentProcessingError):
    """Raised when document classification fails."""

    pass


class SearchIndexError(DocumentProcessingError):
    """Raised when search indexing operations fail."""

    pass


class ConversionError(DocumentProcessingError):
    """Raised when format conversion fails."""

    pass


class MetadataError(DocumentProcessingError):
    """Raised when metadata extraction fails."""

    pass


class OCRError(DocumentProcessingError):
    """Raised when optical character recognition fails."""

    pass
