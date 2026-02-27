"""Tools for markdown module - markdown processing and rendering."""

from __future__ import annotations

import logging
from typing import Any

from thomas.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)


class MarkdownParseaTool(Tool):
    """Parse markdown text."""

    name = "markdown_parse"
    category = "markdown"
    description = "Parse markdown text and extract structure."
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Markdown content to parse",
            },
        },
        "required": ["content"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .parser import parse_markdown

            result = parse_markdown(args["content"])
            return ToolResult(ok=True, data=result or {"parsed": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class MarkdownRenderTool(Tool):
    """Render markdown to HTML."""

    name = "markdown_render"
    category = "markdown"
    description = "Convert markdown to HTML."
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Markdown content",
            },
            "format": {
                "type": "string",
                "description": "Output format (html, pdf, etc.)",
            },
        },
        "required": ["content"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .renderer import render_markdown

            html = render_markdown(args["content"], format=args.get("format", "html"))
            return ToolResult(ok=True, data={"html": html[:500]})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class MarkdownExtractHeadersTool(Tool):
    """Extract headers from markdown."""

    name = "markdown_extract_headers"
    category = "markdown"
    description = "Extract heading hierarchy from markdown."
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Markdown content",
            },
        },
        "required": ["content"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .headers import extract_headers

            headers = extract_headers(args["content"])
            return ToolResult(ok=True, data={"headers": headers or []})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_markdown_tools(registry):
    """Register markdown tools with the tool registry."""
    tools = [
        MarkdownParseaTool(),
        MarkdownRenderTool(),
        MarkdownExtractHeadersTool(),
    ]
    for tool in tools:
        registry.register(tool)
