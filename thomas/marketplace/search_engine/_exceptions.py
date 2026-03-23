"""Exception types for the search engine."""


class SearchError(Exception):
    """Base exception for search engine errors."""

    pass


class IndexError(SearchError):
    """Raised when index operation fails."""

    pass


class QueryParseError(SearchError):
    """Raised when query parsing fails."""

    pass


class AnalyzerError(SearchError):
    """Raised when text analysis fails."""

    pass
