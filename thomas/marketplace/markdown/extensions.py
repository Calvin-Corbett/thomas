"""
Markdown extensions for advanced parsing and processing.

Implements:
- Table of Contents generation from headings
- Task lists (- [ ] and - [x])
- Strikethrough (~~text~~)
- Footnotes ([^1] definitions and references)
- Definition lists (term: definition)
- Abbreviations
- Smart quotes and dashes
- Attribute lists ({.class #id})
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from thomas.marketplace.markdown._types import (
    Document,
    Emphasis,
    Heading,
    InlineNode,
    ListItem,
    MarkdownNode,
    Paragraph,
    Text,
)


@dataclass
class TocEntry:
    """Table of contents entry."""

    level: int
    title: str
    anchor: str  # Heading ID/anchor


class TableOfContentsExtension:
    """Generate table of contents from headings."""

    @staticmethod
    def generate(doc: Document) -> list[TocEntry]:
        """Generate TOC from document.

        Args:
            doc: Markdown document

        Returns:
            List of TOC entries
        """
        toc = []
        for child in doc.children:
            if isinstance(child, Heading):
                title = TableOfContentsExtension._extract_text(child.children)
                anchor = TableOfContentsExtension._generate_anchor(title)
                toc.append(TocEntry(level=child.level, title=title, anchor=anchor))
        return toc

    @staticmethod
    def _extract_text(nodes: list[InlineNode]) -> str:
        """Extract plain text from inline nodes."""
        text = []
        for node in nodes:
            if isinstance(node, Text):
                text.append(node.content)
            elif isinstance(node, Emphasis) or hasattr(node, "children"):
                text.append(TableOfContentsExtension._extract_text(node.children))
        return "".join(text)

    @staticmethod
    def _generate_anchor(text: str) -> str:
        """Generate anchor from heading text."""
        text = re.sub(r"[^\w\s-]", "", text).strip()
        text = re.sub(r"[-\s]+", "-", text).lower()
        return text


class TaskListExtension:
    """Parse and process task lists."""

    @staticmethod
    def extract_tasks(doc: Document) -> list[tuple[str, bool]]:
        """Extract all task list items.

        Args:
            doc: Markdown document

        Returns:
            List of (text, is_checked) tuples
        """
        tasks = []

        def visit(node: MarkdownNode) -> None:
            """Recursively visit nodes."""
            if isinstance(node, ListItem):
                if node.checked is not None:
                    text = TaskListExtension._extract_text(node.children)
                    tasks.append((text, node.checked))
            elif hasattr(node, "children"):
                for child in node.children:
                    visit(child)

        visit(doc)
        return tasks

    @staticmethod
    def _extract_text(nodes: list) -> str:
        """Extract plain text from nodes."""
        text = []
        for node in nodes:
            if isinstance(node, Text):
                text.append(node.content)
            elif isinstance(node, Emphasis) or hasattr(node, "children"):
                text.append(TaskListExtension._extract_text(node.children))
        return "".join(text)


class FootnoteExtension:
    """Parse and process footnotes."""

    @staticmethod
    def extract_footnotes(doc: Document) -> dict[str, str]:
        """Extract footnote definitions from document.

        Args:
            doc: Markdown document

        Returns:
            Dictionary of label -> content
        """
        footnotes: dict[str, str] = {}

        # Look for patterns like:
        # [^1]: Footnote content
        for child in doc.children:
            if isinstance(child, Paragraph):
                text_content = FootnoteExtension._extract_text(child.children)
                match = re.match(r"^\[\^([^\]]+)\]:\s*(.+)$", text_content)
                if match:
                    label = match.group(1)
                    content = match.group(2)
                    footnotes[label] = content

        return footnotes

    @staticmethod
    def _extract_text(nodes: list) -> str:
        """Extract plain text from nodes."""
        text = []
        for node in nodes:
            if isinstance(node, Text):
                text.append(node.content)
            elif hasattr(node, "children"):
                text.append(FootnoteExtension._extract_text(node.children))
        return "".join(text)


class DefinitionListExtension:
    """Parse definition lists (term: definition)."""

    @staticmethod
    def is_definition_list_syntax(text: str) -> bool:
        """Check if text looks like definition list.

        Args:
            text: Text to check

        Returns:
            True if matches definition list pattern
        """
        lines = text.strip().split("\n")
        for line in lines:
            if re.match(r"^[^:]+:\s+", line):
                return True
        return False

    @staticmethod
    def parse_definitions(text: str) -> list[tuple[str, str]]:
        """Parse definition list.

        Args:
            text: Definition list text

        Returns:
            List of (term, definition) tuples
        """
        definitions = []
        lines = text.strip().split("\n")

        for line in lines:
            match = re.match(r"^([^:]+):\s+(.+)$", line)
            if match:
                term = match.group(1).strip()
                definition = match.group(2).strip()
                definitions.append((term, definition))

        return definitions


class AbbreviationExtension:
    """Parse abbreviations.

    Syntax:
    *[HTML]: HyperText Markup Language
    """

    @staticmethod
    def extract_abbreviations(doc: Document) -> dict[str, str]:
        """Extract abbreviation definitions.

        Args:
            doc: Markdown document

        Returns:
            Dictionary of abbreviation -> expansion
        """
        abbreviations: dict[str, str] = {}

        for child in doc.children:
            if isinstance(child, Paragraph):
                text = AbbreviationExtension._extract_text(child.children)
                match = re.match(r"^\*\[([^\]]+)\]:\s*(.+)$", text)
                if match:
                    abbr = match.group(1)
                    expansion = match.group(2)
                    abbreviations[abbr] = expansion

        return abbreviations

    @staticmethod
    def _extract_text(nodes: list) -> str:
        """Extract plain text from nodes."""
        text = []
        for node in nodes:
            if isinstance(node, Text):
                text.append(node.content)
            elif hasattr(node, "children"):
                text.append(AbbreviationExtension._extract_text(node.children))
        return "".join(text)


class SmartTypographyExtension:
    """Apply smart typography transformations.

    Converts:
    - --- to em dash
    - -- to en dash
    - ... to ellipsis
    - "quotes" to smart quotes
    """

    @staticmethod
    def apply(text: str) -> str:
        """Apply smart typography.

        Args:
            text: Text to process

        Returns:
            Text with smart typography applied
        """
        # Em dash (---) -> em dash
        text = re.sub(r"\s+---\s+", " \u2014 ", text)

        # En dash (--) -> en dash
        text = re.sub(r"\s+--\s+", " \u2013 ", text)

        # Ellipsis (...) -> ellipsis
        text = text.replace("...", "\u2026")

        # Smart quotes - opening
        text = re.sub(r'(^|\s|[([{])"', lambda m: f"{m.group(1)}\u201c", text)
        text = re.sub(r"(^|\s|[([{])'", lambda m: f"{m.group(1)}\u2018", text)

        # Smart quotes - closing
        text = re.sub(r'"(\s|$|[)\]}])', lambda m: f"\u201d{m.group(1)}", text)
        text = re.sub(r"'(\s|$|[)\]}])", lambda m: f"\u2019{m.group(1)}", text)

        return text


class AttributeListExtension:
    """Parse attribute lists {.class #id}.

    These can be attached to blocks or inline elements.
    """

    @staticmethod
    def parse_attributes(text: str) -> tuple[str, dict[str, str]]:
        """Parse attributes from text.

        Args:
            text: Text possibly ending with {attrs}

        Returns:
            Tuple of (text, attributes_dict)
        """
        match = re.search(r"\{(.+?)\}\s*$", text)
        if not match:
            return text, {}

        attr_str = match.group(1)
        text = text[: match.start()].rstrip()
        attributes = AttributeListExtension._parse_attr_string(attr_str)

        return text, attributes

    @staticmethod
    def _parse_attr_string(attr_str: str) -> dict[str, str]:
        """Parse attribute string.

        Args:
            attr_str: String like ".class1 .class2 #id key=value"

        Returns:
            Dictionary of attributes
        """
        attrs: dict[str, str] = {}
        classes = []

        tokens = attr_str.split()
        for token in tokens:
            if token.startswith("."):
                classes.append(token[1:])
            elif token.startswith("#"):
                attrs["id"] = token[1:]
            elif "=" in token:
                key, value = token.split("=", 1)
                attrs[key] = value.strip("\"'")
            else:
                # Treat as key=value with value=token
                attrs[token] = token

        if classes:
            attrs["class"] = " ".join(classes)

        return attrs


class AutoLinkExtension:
    """Auto-detect and linkify URLs."""

    URL_PATTERN = re.compile(r"https?://[^\s<>\[\]()]+", re.IGNORECASE)

    @staticmethod
    def linkify(text: str) -> str:
        """Find and convert URLs to links.

        Args:
            text: Text to process

        Returns:
            Text with URLs converted to [url](url) links
        """

        def replace_url(match):
            url = match.group(0)
            return f"[{url}]({url})"

        return AutoLinkExtension.URL_PATTERN.sub(replace_url, text)


class MathExtension:
    """Parse math blocks ($$...$$) and inline math ($...$)."""

    @staticmethod
    def is_math_block(text: str) -> bool:
        """Check if text is math block.

        Args:
            text: Text to check

        Returns:
            True if matches $$ ... $$ pattern
        """
        return text.strip().startswith("$$") and text.strip().endswith("$$")

    @staticmethod
    def extract_math(text: str) -> str | None:
        """Extract math from delimiters.

        Args:
            text: Text with math delimiters

        Returns:
            Math content without delimiters
        """
        if text.startswith("$$") and text.endswith("$$"):
            return text[2:-2].strip()
        elif text.startswith("$") and text.endswith("$"):
            return text[1:-1].strip()
        return None


class AdmonitionExtension:
    """Parse admonitions (!!!note, !!!warning, etc.)."""

    ADMONITION_TYPES = {"note", "warning", "danger", "success", "info"}

    @staticmethod
    def is_admonition(text: str) -> bool:
        """Check if text starts with admonition marker.

        Args:
            text: Text to check

        Returns:
            True if matches !!! marker
        """
        return bool(re.match(r"^!!!\s*\w+", text))

    @staticmethod
    def parse_admonition(text: str) -> tuple[str | None, str | None]:
        """Parse admonition type and title.

        Args:
            text: Admonition text

        Returns:
            Tuple of (admonition_type, title)
        """
        match = re.match(r"^!!!\s*(\w+)\s*(.*)$", text)
        if match:
            admon_type = match.group(1).lower()
            title = match.group(2).strip() or None
            if admon_type in AdmonitionExtension.ADMONITION_TYPES:
                return admon_type, title
        return None, None
