"""Exception types for Notion integration."""

from __future__ import annotations


class NotionError(Exception):
    """Base exception for Notion integration."""

    pass


class NotionAPIError(NotionError):
    """General Notion API error."""

    pass


class NotionNotFoundError(NotionError):
    """Resource not found in Notion."""

    pass


class NotionValidationError(NotionError):
    """Request validation failed."""

    pass


class NotionRateLimitError(NotionError):
    """Rate limit exceeded."""

    pass


class NotionAuthError(NotionError):
    """Authentication failed."""

    pass
