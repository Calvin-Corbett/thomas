"""Block operations for Notion API.

Utilities for retrieving, creating, updating, and deleting Notion blocks.
"""

from __future__ import annotations

from typing import Any

import aiohttp

from .exceptions import NotionAPIError, NotionNotFoundError


class BlockManager:
    """Manages block operations in Notion."""

    def __init__(self, base_url: str, headers: dict[str, str]) -> None:
        """Initialize block manager.

        Args:
            base_url: Notion API base URL
            headers: HTTP headers (includes auth and version)
        """
        self.base_url = base_url
        self.headers = headers

    async def get_block(self, block_id: str) -> dict[str, Any]:
        """Get a block by ID.

        Args:
            block_id: Notion block ID

        Returns:
            Block object from API

        Raises:
            NotionNotFoundError: Block not found
            NotionAPIError: API error
        """
        normalized_id = block_id.replace("-", "")
        url = f"{self.base_url}/blocks/{normalized_id}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as resp:
                if resp.status == 404:
                    raise NotionNotFoundError(f"Block not found: {block_id}")
                if resp.status >= 400:
                    body = await resp.text()
                    raise NotionAPIError(f"Failed to get block: {body}")
                return await resp.json()

    async def get_block_children(
        self,
        block_id: str,
        *,
        page_size: int = 100,
        start_cursor: str | None = None,
    ) -> dict[str, Any]:
        """Get child blocks of a block.

        Args:
            block_id: Parent block ID
            page_size: Number of results to return (1-100)
            start_cursor: Cursor for pagination

        Returns:
            Results dict with results and has_more
        """
        normalized_id = block_id.replace("-", "")
        url = f"{self.base_url}/blocks/{normalized_id}/children"
        page_size = max(1, min(page_size, 100))

        params: dict[str, Any] = {"page_size": page_size}
        if start_cursor:
            params["start_cursor"] = start_cursor

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers, params=params) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise NotionAPIError(f"Failed to get block children: {body}")
                return await resp.json()

    async def update_block(
        self,
        block_id: str,
        content: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a block's content.

        Args:
            block_id: Notion block ID
            content: Block type and content (e.g., {"paragraph": {...}})

        Returns:
            Updated block object

        Raises:
            NotionAPIError: API error
        """
        normalized_id = block_id.replace("-", "")
        url = f"{self.base_url}/blocks/{normalized_id}"

        payload = {
            **content,
        }

        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=self.headers, json=payload) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise NotionAPIError(f"Failed to update block: {body}")
                return await resp.json()

    async def delete_block(self, block_id: str) -> dict[str, Any]:
        """Delete a block.

        Args:
            block_id: Notion block ID

        Returns:
            Deleted block object

        Raises:
            NotionAPIError: API error
        """
        normalized_id = block_id.replace("-", "")
        url = f"{self.base_url}/blocks/{normalized_id}"

        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=self.headers) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise NotionAPIError(f"Failed to delete block: {body}")
                return await resp.json()

    async def append_children(
        self,
        block_id: str,
        children: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Append child blocks to a block.

        Args:
            block_id: Parent block ID
            children: List of block objects to append

        Returns:
            Results dict with created blocks

        Raises:
            NotionAPIError: API error
        """
        normalized_id = block_id.replace("-", "")
        url = f"{self.base_url}/blocks/{normalized_id}/children"

        payload = {"children": children}

        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=self.headers, json=payload) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise NotionAPIError(f"Failed to append children: {body}")
                return await resp.json()


# Block type builders


def paragraph(
    text: list[dict[str, Any]],
    color: str = "default",
) -> dict[str, Any]:
    """Build a paragraph block.

    Args:
        text: List of rich text objects
        color: Text color

    Returns:
        Paragraph block dict
    """
    return {
        "type": "paragraph",
        "paragraph": {
            "rich_text": text,
            "color": color,
        },
    }


def heading_1(
    text: list[dict[str, Any]],
    color: str = "default",
    is_toggleable: bool = False,
) -> dict[str, Any]:
    """Build a heading_1 block."""
    return {
        "type": "heading_1",
        "heading_1": {
            "rich_text": text,
            "color": color,
            "is_toggleable": is_toggleable,
        },
    }


def heading_2(
    text: list[dict[str, Any]],
    color: str = "default",
    is_toggleable: bool = False,
) -> dict[str, Any]:
    """Build a heading_2 block."""
    return {
        "type": "heading_2",
        "heading_2": {
            "rich_text": text,
            "color": color,
            "is_toggleable": is_toggleable,
        },
    }


def heading_3(
    text: list[dict[str, Any]],
    color: str = "default",
    is_toggleable: bool = False,
) -> dict[str, Any]:
    """Build a heading_3 block."""
    return {
        "type": "heading_3",
        "heading_3": {
            "rich_text": text,
            "color": color,
            "is_toggleable": is_toggleable,
        },
    }


def bulleted_list(
    text: list[dict[str, Any]],
    color: str = "default",
) -> dict[str, Any]:
    """Build a bulleted_list_item block."""
    return {
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": text,
            "color": color,
        },
    }


def numbered_list(
    text: list[dict[str, Any]],
    color: str = "default",
) -> dict[str, Any]:
    """Build a numbered_list_item block."""
    return {
        "type": "numbered_list_item",
        "numbered_list_item": {
            "rich_text": text,
            "color": color,
        },
    }


def to_do(
    text: list[dict[str, Any]],
    checked: bool = False,
    color: str = "default",
) -> dict[str, Any]:
    """Build a to_do block."""
    return {
        "type": "to_do",
        "to_do": {
            "rich_text": text,
            "checked": checked,
            "color": color,
        },
    }


def toggle(
    text: list[dict[str, Any]],
    color: str = "default",
) -> dict[str, Any]:
    """Build a toggle block."""
    return {
        "type": "toggle",
        "toggle": {
            "rich_text": text,
            "color": color,
        },
    }


def code(
    text: list[dict[str, Any]],
    language: str = "plaintext",
    caption: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a code block."""
    return {
        "type": "code",
        "code": {
            "rich_text": text,
            "language": language,
            "caption": caption or [],
        },
    }


def quote(
    text: list[dict[str, Any]],
    color: str = "default",
) -> dict[str, Any]:
    """Build a quote block."""
    return {
        "type": "quote",
        "quote": {
            "rich_text": text,
            "color": color,
        },
    }


def callout(
    text: list[dict[str, Any]],
    icon: str | None = None,
    color: str = "default",
) -> dict[str, Any]:
    """Build a callout block.

    Args:
        text: Rich text content
        icon: Emoji or file URL
        color: Background color
    """
    callout_obj: dict[str, Any] = {
        "rich_text": text,
        "color": color,
    }
    if icon:
        if icon.startswith("http"):
            callout_obj["icon"] = {"type": "file", "file": {"url": icon}}
        else:
            callout_obj["icon"] = {"type": "emoji", "emoji": icon}

    return {
        "type": "callout",
        "callout": callout_obj,
    }


def divider() -> dict[str, Any]:
    """Build a divider block."""
    return {
        "type": "divider",
        "divider": {},
    }


def table(
    table_width: int,
    has_column_header: bool = False,
    has_row_header: bool = False,
) -> dict[str, Any]:
    """Build a table block.

    Args:
        table_width: Number of columns
        has_column_header: Whether first row is header
        has_row_header: Whether first column is header
    """
    return {
        "type": "table",
        "table": {
            "table_width": int(table_width),
            "has_column_header": bool(has_column_header),
            "has_row_header": bool(has_row_header),
        },
    }


def table_row(cells: list[list[dict[str, Any]]]) -> dict[str, Any]:
    """Build a table_row block.

    Args:
        cells: List of cell contents (each cell is a list of rich text)
    """
    return {
        "type": "table_row",
        "table_row": {
            "cells": cells,
        },
    }


def image(
    url: str,
    caption: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build an image block."""
    return {
        "type": "image",
        "image": {
            "type": "external",
            "external": {"url": url},
            "caption": caption or [],
        },
    }
