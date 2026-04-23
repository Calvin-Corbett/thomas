"""Database operations for Notion API.

Utilities for querying, creating, and updating Notion databases.
"""

from __future__ import annotations

from typing import Any

import aiohttp

from .exceptions import NotionAPIError, NotionNotFoundError, NotionValidationError


class DatabaseManager:
    """Manages database operations in Notion."""

    def __init__(self, base_url: str, headers: dict[str, str]) -> None:
        """Initialize database manager.

        Args:
            base_url: Notion API base URL
            headers: HTTP headers (includes auth and version)
        """
        self.base_url = base_url
        self.headers = headers

    async def get_database(self, database_id: str) -> dict[str, Any]:
        """Get a database schema.

        Args:
            database_id: Notion database ID

        Returns:
            Database object with properties

        Raises:
            NotionNotFoundError: Database not found
            NotionAPIError: API error
        """
        normalized_id = database_id.replace("-", "")
        url = f"{self.base_url}/databases/{normalized_id}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as resp:
                if resp.status == 404:
                    raise NotionNotFoundError(f"Database not found: {database_id}")
                if resp.status >= 400:
                    body = await resp.text()
                    raise NotionAPIError(f"Failed to get database: {body}")
                return await resp.json()

    async def query_database(
        self,
        database_id: str,
        filter: dict[str, Any] | None = None,
        sorts: list[dict[str, Any]] | None = None,
        page_size: int = 100,
        start_cursor: str | None = None,
    ) -> dict[str, Any]:
        """Query a database with filters and sorting.

        Args:
            database_id: Notion database ID
            filter: Filter conditions
            sorts: Sort options
            page_size: Number of results (1-100)
            start_cursor: Cursor for pagination

        Returns:
            Query results with pages and has_more

        Raises:
            NotionAPIError: API error
        """
        normalized_id = database_id.replace("-", "")
        url = f"{self.base_url}/databases/{normalized_id}/query"
        page_size = max(1, min(page_size, 100))

        payload: dict[str, Any] = {"page_size": page_size}

        if filter:
            payload["filter"] = filter
        if sorts:
            payload["sorts"] = sorts
        if start_cursor:
            payload["start_cursor"] = start_cursor

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=self.headers, json=payload) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise NotionAPIError(f"Failed to query database: {body}")
                return await resp.json()

    async def create_database(
        self,
        parent_id: str,
        title: str,
        properties: dict[str, Any],
        is_page_parent: bool = True,
    ) -> dict[str, Any]:
        """Create a database.

        Args:
            parent_id: ID of parent page
            title: Database title
            properties: Database property schema
            is_page_parent: Whether parent is a page (True) or workspace (False)

        Returns:
            Created database object

        Raises:
            NotionValidationError: Invalid schema
            NotionAPIError: API error
        """
        normalized_id = parent_id.replace("-", "")
        url = f"{self.base_url}/databases"

        parent: dict[str, Any]
        if is_page_parent:
            parent = {"type": "page_id", "page_id": normalized_id}
        else:
            parent = {"type": "workspace", "workspace": True}

        payload = {
            "parent": parent,
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": properties,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=self.headers, json=payload) as resp:
                if resp.status == 400:
                    body = await resp.text()
                    raise NotionValidationError(f"Invalid database schema: {body}")
                if resp.status >= 400:
                    body = await resp.text()
                    raise NotionAPIError(f"Failed to create database: {body}")
                return await resp.json()

    async def update_database(
        self,
        database_id: str,
        title: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a database schema.

        Args:
            database_id: Notion database ID
            title: New database title
            properties: Property schema updates

        Returns:
            Updated database object

        Raises:
            NotionAPIError: API error
        """
        normalized_id = database_id.replace("-", "")
        url = f"{self.base_url}/databases/{normalized_id}"

        payload: dict[str, Any] = {}

        if title:
            payload["title"] = [{"type": "text", "text": {"content": title}}]

        if properties:
            payload["properties"] = properties

        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=self.headers, json=payload) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise NotionAPIError(f"Failed to update database: {body}")
                return await resp.json()


# Filter builders


def filter_equals(property_name: str, value: Any) -> dict[str, Any]:
    """Build an equals filter."""
    filter_obj: dict[str, Any] = {"property": property_name}

    if isinstance(value, bool):
        filter_obj["checkbox"] = {"equals": value}
    elif isinstance(value, (int, float)):
        filter_obj["number"] = {"equals": value}
    elif isinstance(value, str):
        filter_obj["rich_text"] = {"equals": value}
    else:
        filter_obj["rich_text"] = {"equals": str(value)}

    return {"filter": filter_obj}


def filter_contains(property_name: str, value: str) -> dict[str, Any]:
    """Build a contains filter."""
    return {
        "filter": {
            "property": property_name,
            "rich_text": {"contains": value},
        }
    }


def filter_starts_with(property_name: str, value: str) -> dict[str, Any]:
    """Build a starts_with filter."""
    return {
        "filter": {
            "property": property_name,
            "rich_text": {"starts_with": value},
        }
    }


def filter_greater_than(property_name: str, value: float) -> dict[str, Any]:
    """Build a greater_than filter."""
    return {
        "filter": {
            "property": property_name,
            "number": {"greater_than": value},
        }
    }


def filter_less_than(property_name: str, value: float) -> dict[str, Any]:
    """Build a less_than filter."""
    return {
        "filter": {
            "property": property_name,
            "number": {"less_than": value},
        }
    }


def filter_date_before(property_name: str, date: str) -> dict[str, Any]:
    """Build a date_before filter.

    Args:
        property_name: Property to filter
        date: Date in YYYY-MM-DD format
    """
    return {
        "filter": {
            "property": property_name,
            "date": {"before": date},
        }
    }


def filter_date_after(property_name: str, date: str) -> dict[str, Any]:
    """Build a date_after filter."""
    return {
        "filter": {
            "property": property_name,
            "date": {"after": date},
        }
    }


def filter_and(filters: list[dict[str, Any]]) -> dict[str, Any]:
    """Combine multiple filters with AND.

    Args:
        filters: List of filter dicts
    """
    return {
        "filter": {
            "and": [f.get("filter", f) for f in filters],
        }
    }


def filter_or(filters: list[dict[str, Any]]) -> dict[str, Any]:
    """Combine multiple filters with OR."""
    return {
        "filter": {
            "or": [f.get("filter", f) for f in filters],
        }
    }


# Sort builders


def sort_ascending(property_name: str) -> dict[str, Any]:
    """Build an ascending sort."""
    return {
        "property": property_name,
        "direction": "ascending",
    }


def sort_descending(property_name: str) -> dict[str, Any]:
    """Build a descending sort."""
    return {
        "property": property_name,
        "direction": "descending",
    }


def sort_by_timestamp(direction: str = "descending") -> dict[str, Any]:
    """Build a sort by timestamp (created/last edited)."""
    return {
        "timestamp": "last_edited_time",
        "direction": direction,
    }
