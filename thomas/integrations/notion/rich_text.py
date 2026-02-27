"""Rich text helpers for Notion API.

Utilities for building and converting Notion rich text objects.
"""

from __future__ import annotations

from typing import Any


def text(
    content: str,
    *,
    bold: bool = False,
    italic: bool = False,
    strikethrough: bool = False,
    underline: bool = False,
    code: bool = False,
    color: str = "default",
) -> dict[str, Any]:
    """Build a rich text object with formatting.

    Args:
        content: Text content
        bold: Apply bold formatting
        italic: Apply italic formatting
        strikethrough: Apply strikethrough
        underline: Apply underline
        code: Apply code formatting
        color: Text color (default, blue, blue_background, brown, brown_background, etc.)

    Returns:
        Rich text object dict
    """
    return {
        "type": "text",
        "text": {"content": content},
        "annotations": {
            "bold": bool(bold),
            "italic": bool(italic),
            "strikethrough": bool(strikethrough),
            "underline": bool(underline),
            "code": bool(code),
            "color": str(color),
        },
    }


def mention_page(page_id: str) -> dict[str, Any]:
    """Create a page mention rich text object.

    Args:
        page_id: Notion page ID (with or without dashes)

    Returns:
        Page mention rich text object
    """
    # Normalize page ID to remove dashes if present
    normalized_id = page_id.replace("-", "")
    return {
        "type": "mention",
        "mention": {
            "type": "page",
            "page": {"id": normalized_id},
        },
    }


def mention_user(user_id: str) -> dict[str, Any]:
    """Create a user mention rich text object.

    Args:
        user_id: Notion user ID

    Returns:
        User mention rich text object
    """
    return {
        "type": "mention",
        "mention": {
            "type": "user",
            "user": {"id": user_id},
        },
    }


def mention_date(
    start: str,
    end: str | None = None,
) -> dict[str, Any]:
    """Create a date mention rich text object.

    Args:
        start: Start date (YYYY-MM-DD format)
        end: Optional end date (YYYY-MM-DD format)

    Returns:
        Date mention rich text object
    """
    date_obj: dict[str, Any] = {"start": start}
    if end:
        date_obj["end"] = end
    return {
        "type": "mention",
        "mention": {
            "type": "date",
            "date": date_obj,
        },
    }


def equation(expression: str) -> dict[str, Any]:
    """Create an inline equation rich text object.

    Args:
        expression: LaTeX equation expression

    Returns:
        Equation rich text object
    """
    return {
        "type": "equation",
        "equation": {"expression": expression},
    }


def to_plain_text(rich_text_list: list[dict[str, Any]]) -> str:
    """Convert Notion rich text list to plain text string.

    Args:
        rich_text_list: List of rich text objects from Notion API

    Returns:
        Plain text string
    """
    parts = []
    for item in rich_text_list:
        if not isinstance(item, dict):
            continue

        item_type = item.get("type")

        if item_type == "text":
            text_obj = item.get("text", {})
            if isinstance(text_obj, dict):
                content = text_obj.get("content", "")
                parts.append(str(content))

        elif item_type == "mention":
            mention = item.get("mention", {})
            if isinstance(mention, dict):
                mention_type = mention.get("type")
                if mention_type == "page":
                    parts.append(f"[page:{mention.get('page', {}).get('id', '')}]")
                elif mention_type == "user":
                    parts.append(f"[user:{mention.get('user', {}).get('id', '')}]")
                elif mention_type == "date":
                    date = mention.get("date", {})
                    if isinstance(date, dict):
                        start = date.get("start", "")
                        end = date.get("end")
                        if end:
                            parts.append(f"[{start} to {end}]")
                        else:
                            parts.append(f"[{start}]")

        elif item_type == "equation":
            equation = item.get("equation", {})
            if isinstance(equation, dict):
                expr = equation.get("expression", "")
                parts.append(f"[{expr}]")

    return "".join(parts)


def to_markdown(rich_text_list: list[dict[str, Any]]) -> str:
    """Convert Notion rich text list to markdown string.

    Args:
        rich_text_list: List of rich text objects from Notion API

    Returns:
        Markdown string
    """
    parts = []
    for item in rich_text_list:
        if not isinstance(item, dict):
            continue

        item_type = item.get("type")

        if item_type == "text":
            text_obj = item.get("text", {})
            if isinstance(text_obj, dict):
                content = str(text_obj.get("content", ""))
                annotations = item.get("annotations", {})

                if isinstance(annotations, dict):
                    if annotations.get("code"):
                        content = f"`{content}`"
                    if annotations.get("bold"):
                        content = f"**{content}**"
                    if annotations.get("italic"):
                        content = f"*{content}*"
                    if annotations.get("strikethrough"):
                        content = f"~~{content}~~"

                parts.append(content)

        elif item_type == "mention":
            mention = item.get("mention", {})
            if isinstance(mention, dict):
                mention_type = mention.get("type")
                if mention_type == "page":
                    page_id = mention.get("page", {}).get("id", "")
                    parts.append(f"[page]({page_id})")
                elif mention_type == "user":
                    user_id = mention.get("user", {}).get("id", "")
                    parts.append(f"[@user]({user_id})")
                elif mention_type == "date":
                    date = mention.get("date", {})
                    if isinstance(date, dict):
                        start = date.get("start", "")
                        end = date.get("end")
                        if end:
                            parts.append(f"`{start}` to `{end}`")
                        else:
                            parts.append(f"`{start}`")

        elif item_type == "equation":
            equation = item.get("equation", {})
            if isinstance(equation, dict):
                expr = equation.get("expression", "")
                parts.append(f"`{expr}`")

    return "".join(parts)
