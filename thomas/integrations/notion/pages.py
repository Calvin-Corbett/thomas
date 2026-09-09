"""Page operations for Notion API.

Utilities for retrieving, creating, updating, and searching Notion pages.
"""

from __future__ import annotations

from typing import Any

import aiohttp

from .exceptions import NotionAPIError, NotionNotFoundError, NotionValidationError


class PageManager:
    """Manages page operations in Notion."""

    def __init__(self, base_url: str, headers: dict[str, str]) -> None:
        """Initialize page manager.

        Args:
            base_url: Notion API base URL
            headers: HTTP headers (includes auth and version)
        """
        self.base_url = base_url
        self.headers = headers

    async def get_page(self, page_id: str) -> dict[str, Any]:
        """Get a page by ID.

        Args:
            page_id: Notion page ID

        Returns:
            Page object from API

        Raises:
            NotionNotFoundError: Page not found
            NotionAPIError: API error
        """
        normalized_id = page_id.replace("-", "")
        url = f"{self.base_url}/pages/{normalized_id}"

        async with aiohttp.ClientSession() as session, session.get(url, headers=self.headers) as resp:
            if resp.status == 404:
                raise NotionNotFoundError(f"Page not found: {page_id}")
            if resp.status >= 400:
                body = await resp.text()
                raise NotionAPIError(f"Failed to get page: {body}")
            return await resp.json()

    async def create_page(
        self,
        parent_id: str,
        properties: dict[str, Any],
        children: list[dict[str, Any]] | None = None,
        is_database: bool = False,
    ) -> dict[str, Any]:
        """Create a page in a database or as a child of another page.

        Args:
            parent_id: ID of parent database or page
            properties: Page properties (database entries)
            children: Optional child blocks
            is_database: Whether parent_id is a database

        Returns:
            Created page object

        Raises:
            NotionValidationError: Invalid properties
            NotionAPIError: API error
        """
        normalized_id = parent_id.replace("-", "")
        url = f"{self.base_url}/pages"

        payload: dict[str, Any] = {
            "parent": ({"database_id": normalized_id} if is_database else {"page_id": normalized_id}),
            "properties": properties,
        }

        if children:
            payload["children"] = children

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=self.headers, json=payload) as resp:
                if resp.status == 400:
                    body = await resp.text()
                    raise NotionValidationError(f"Invalid page properties: {body}")
                if resp.status >= 400:
                    body = await resp.text()
                    raise NotionAPIError(f"Failed to create page: {body}")
                return await resp.json()

    async def update_page(
        self,
        page_id: str,
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a page's properties.

        Args:
            page_id: Notion page ID
            properties: Properties to update

        Returns:
            Updated page object

        Raises:
            NotionAPIError: API error
        """
        normalized_id = page_id.replace("-", "")
        url = f"{self.base_url}/pages/{normalized_id}"

        payload = {"properties": properties}

        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=self.headers, json=payload) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise NotionAPIError(f"Failed to update page: {body}")
                return await resp.json()

    async def archive_page(self, page_id: str) -> dict[str, Any]:
        """Archive a page (soft delete).

        Args:
            page_id: Notion page ID

        Returns:
            Archived page object

        Raises:
            NotionAPIError: API error
        """
        normalized_id = page_id.replace("-", "")
        url = f"{self.base_url}/pages/{normalized_id}"

        payload = {"archived": True}

        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=self.headers, json=payload) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise NotionAPIError(f"Failed to archive page: {body}")
                return await resp.json()

    async def get_page_content(
        self,
        page_id: str,
        *,
        page_size: int = 100,
        start_cursor: str | None = None,
    ) -> dict[str, Any]:
        """Get all blocks (content) of a page.

        Args:
            page_id: Notion page ID
            page_size: Number of blocks to return (1-100)
            start_cursor: Cursor for pagination

        Returns:
            Results dict with blocks and has_more
        """
        normalized_id = page_id.replace("-", "")
        url = f"{self.base_url}/blocks/{normalized_id}/children"
        page_size = max(1, min(page_size, 100))

        params: dict[str, Any] = {"page_size": page_size}
        if start_cursor:
            params["start_cursor"] = start_cursor

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers, params=params) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise NotionAPIError(f"Failed to get page content: {body}")
                return await resp.json()

    async def append_blocks(
        self,
        page_id: str,
        blocks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Append content blocks to a page.

        Args:
            page_id: Notion page ID
            blocks: List of block objects to append

        Returns:
            Results dict with created blocks

        Raises:
            NotionAPIError: API error
        """
        normalized_id = page_id.replace("-", "")
        url = f"{self.base_url}/blocks/{normalized_id}/children"

        payload = {"children": blocks}

        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=self.headers, json=payload) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise NotionAPIError(f"Failed to append blocks: {body}")
                return await resp.json()

    async def search_pages(
        self,
        query: str,
        filter_type: str | None = None,
        sort: dict[str, Any] | None = None,
        page_size: int = 100,
        start_cursor: str | None = None,
    ) -> dict[str, Any]:
        """Search for pages.

        Args:
            query: Search query string
            filter_type: Filter type ("page", "database")
            sort: Sort options ({"direction": "ascending", "timestamp": "last_edited_time"})
            page_size: Number of results (1-100)
            start_cursor: Cursor for pagination

        Returns:
            Search results with pages and has_more

        Raises:
            NotionAPIError: API error
        """
        url = f"{self.base_url}/search"
        page_size = max(1, min(page_size, 100))

        payload: dict[str, Any] = {
            "query": query,
            "page_size": page_size,
        }

        if filter_type:
            payload["filter"] = {"value": filter_type, "property": "object"}

        if sort:
            payload["sort"] = sort

        if start_cursor:
            payload["start_cursor"] = start_cursor

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=self.headers, json=payload) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise NotionAPIError(f"Failed to search pages: {body}")
                return await resp.json()
