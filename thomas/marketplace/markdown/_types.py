"""
Core types for Markdown AST nodes and configuration.

Defines the complete set of block-level and inline nodes that comprise
a Markdown document, along with configuration objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class ListType(Enum):
    """Type of list: ordered or unordered."""

    ORDERED = "ordered"
    UNORDERED = "unordered"


class TableAlignment(Enum):
    """Column alignment in a table."""

    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    NONE = None


@dataclass
class SourcePosition:
    """Position in source document."""

    line: int  # 1-indexed line number
    column: int  # 0-indexed column number
    offset: int  # Character offset from start of document

    def __repr__(self) -> str:
        """Return string representation."""
        return f"SourcePosition(line={self.line}, col={self.column})"


@dataclass
class RenderConfig:
    """Configuration for rendering Markdown documents."""

    unsafe_html: bool = False  # Pass through raw HTML
    xhtml: bool = False  # Use XHTML self-closing tags
    hard_breaks: bool = False  # Convert soft breaks to hard breaks
    table_alignment: bool = True  # Use table alignment CSS
    heading_ids: bool = True  # Auto-generate heading IDs
    wrap_width: int | None = None  # Line wrap width (None=unlimited)
    smart_quotes: bool = False  # Use smart quotes
    footnotes: bool = True  # Render footnote references

    def __repr__(self) -> str:
        """Return string representation."""
        return f"RenderConfig(unsafe_html={self.unsafe_html}, xhtml={self.xhtml})"


@dataclass
class ParseState:
    """Parser state information."""

    in_list: bool = False
    in_blockquote: bool = False
    list_tight: bool = False
    reference_links: dict[str, tuple[str, str | None]] = field(default_factory=dict)
    footnotes: dict[str, str] = field(default_factory=dict)


# Block-level nodes


@dataclass
class MarkdownNode:
    """Base class for all Markdown AST nodes."""

    source_pos: SourcePosition | None = None
    children: List[MarkdownNode | InlineNode] = field(default_factory=list)

    def __repr__(self) -> str:
        """Return string representation."""
        return f"{self.__class__.__name__}(children={len(self.children)})"


@dataclass
class Document(MarkdownNode):
    """Root document node containing all content."""

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Document(children={len(self.children)})"


class Heading(MarkdownNode):
    """Heading block with level 1-6."""

    def __init__(self, level: int, children: List | None = None, source_pos: SourcePosition | None = None) -> None:
        """Initialize heading with level and children."""
        super().__init__(source_pos=source_pos, children=children or [])
        self.level = level

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Heading(level={self.level}, children={len(self.children)})"


@dataclass
class Paragraph(MarkdownNode):
    """Paragraph block containing inline content."""

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Paragraph(children={len(self.children)})"


@dataclass
class BlockQuote(MarkdownNode):
    """Block quote containing nested blocks."""

    def __repr__(self) -> str:
        """Return string representation."""
        return f"BlockQuote(children={len(self.children)})"


class CodeBlock(MarkdownNode):
    """Code block with optional language identifier."""

    def __init__(
        self, code: str, language: str | None = None, fenced: bool = True, source_pos: SourcePosition | None = None
    ) -> None:
        """Initialize code block."""
        super().__init__(source_pos=source_pos)
        self.code = code
        self.language = language
        self.fenced = fenced

    def __repr__(self) -> str:
        """Return string representation."""
        lang = f", lang={self.language}" if self.language else ""
        return f"CodeBlock(code={len(self.code)} chars{lang})"


class List(MarkdownNode):
    """List block containing list items."""

    def __init__(
        self,
        list_type: ListType,
        children: List | None = None,
        tight: bool = True,
        start: int | None = None,
        source_pos: SourcePosition | None = None,
    ) -> None:
        """Initialize list with type."""
        super().__init__(source_pos=source_pos, children=children or [])
        self.list_type = list_type
        self.tight = tight
        self.start = start

    def __repr__(self) -> str:
        """Return string representation."""
        return f"List(type={self.list_type.value}, tight={self.tight}, items={len(self.children)})"


@dataclass
class ListItem(MarkdownNode):
    """List item containing block or inline content."""

    checked: bool | None = None  # For task lists: None, True, or False

    def __repr__(self) -> str:
        """Return string representation."""
        checked_str = f", checked={self.checked}" if self.checked is not None else ""
        return f"ListItem(children={len(self.children)}{checked_str})"


class ThematicBreak(MarkdownNode):
    """Horizontal rule / thematic break."""

    def __init__(self, source_pos: SourcePosition | None = None) -> None:
        """Initialize thematic break."""
        super().__init__(source_pos=source_pos)

    def __repr__(self) -> str:
        """Return string representation."""
        return "ThematicBreak()"


@dataclass
class Table(MarkdownNode):
    """Table containing rows and cells."""

    alignments: List[TableAlignment] = field(default_factory=list)

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Table(cols={len(self.alignments)}, rows={len(self.children)})"


@dataclass
class TableRow(MarkdownNode):
    """Row in a table."""

    def __repr__(self) -> str:
        """Return string representation."""
        return f"TableRow(cells={len(self.children)})"


@dataclass
class TableCell(MarkdownNode):
    """Cell in a table row."""

    is_header: bool = False

    def __repr__(self) -> str:
        """Return string representation."""
        kind = "header" if self.is_header else "data"
        return f"TableCell({kind}, children={len(self.children)})"


class HTMLBlock(MarkdownNode):
    """Raw HTML block."""

    def __init__(self, html: str, source_pos: SourcePosition | None = None) -> None:
        """Initialize HTML block."""
        super().__init__(source_pos=source_pos)
        self.html = html

    def __repr__(self) -> str:
        """Return string representation."""
        return f"HTMLBlock(html={len(self.html)} chars)"


# Inline nodes


@dataclass
class InlineNode:
    """Base class for inline content nodes."""

    source_pos: SourcePosition | None = None

    def __repr__(self) -> str:
        """Return string representation."""
        return f"{self.__class__.__name__}()"


class Text(InlineNode):
    """Plain text content."""

    def __init__(self, content: str, source_pos: SourcePosition | None = None) -> None:
        """Initialize text."""
        super().__init__(source_pos=source_pos)
        self.content = content

    def __repr__(self) -> str:
        """Return string representation."""
        preview = self.content[:20].replace("\n", "\\n")
        if len(self.content) > 20:
            preview += "..."
        return f"Text({repr(preview)})"


class Emphasis(InlineNode):
    """Emphasized (italic) text."""

    def __init__(self, children: List[InlineNode] = None, source_pos: SourcePosition | None = None) -> None:
        """Initialize emphasis."""
        super().__init__(source_pos=source_pos)
        self.children = children or []

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Emphasis(children={len(self.children)})"


class Strong(InlineNode):
    """Strong (bold) text."""

    def __init__(self, children: List[InlineNode] = None, source_pos: SourcePosition | None = None) -> None:
        """Initialize strong."""
        super().__init__(source_pos=source_pos)
        self.children = children or []

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Strong(children={len(self.children)})"


class Code(InlineNode):
    """Inline code span."""

    def __init__(self, content: str, num_backticks: int = 1, source_pos: SourcePosition | None = None) -> None:
        """Initialize code."""
        super().__init__(source_pos=source_pos)
        self.content = content
        self.num_backticks = num_backticks

    def __repr__(self) -> str:
        """Return string representation."""
        preview = self.content[:20].replace("\n", "\\n")
        if len(self.content) > 20:
            preview += "..."
        return f"Code({repr(preview)})"


class Link(InlineNode):
    """Hyperlink."""

    def __init__(
        self,
        children: List[InlineNode] = None,
        url: str = "",
        title: str | None = None,
        source_pos: SourcePosition | None = None,
    ) -> None:
        """Initialize link."""
        super().__init__(source_pos=source_pos)
        self.children = children or []
        self.url = url
        self.title = title

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Link(url={repr(self.url)}, children={len(self.children)})"


class Image(InlineNode):
    """Image."""

    def __init__(
        self, alt: str = "", src: str = "", title: str | None = None, source_pos: SourcePosition | None = None
    ) -> None:
        """Initialize image."""
        super().__init__(source_pos=source_pos)
        self.alt = alt
        self.src = src
        self.title = title

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Image(src={repr(self.src)}, alt={repr(self.alt)})"


class LineBreak(InlineNode):
    """Hard line break (two spaces or backslash)."""

    def __repr__(self) -> str:
        """Return string representation."""
        return "LineBreak()"


class SoftBreak(InlineNode):
    """Soft line break (newline)."""

    def __repr__(self) -> str:
        """Return string representation."""
        return "SoftBreak()"


class HTMLInline(InlineNode):
    """Raw inline HTML."""

    def __init__(self, html: str, source_pos: SourcePosition | None = None) -> None:
        """Initialize inline HTML."""
        super().__init__(source_pos=source_pos)
        self.html = html

    def __repr__(self) -> str:
        """Return string representation."""
        preview = self.html[:20]
        if len(self.html) > 20:
            preview += "..."
        return f"HTMLInline({repr(preview)})"


class Strikethrough(InlineNode):
    """Strikethrough text (extension)."""

    def __init__(self, children: List[InlineNode] = None, source_pos: SourcePosition | None = None) -> None:
        """Initialize strikethrough."""
        super().__init__(source_pos=source_pos)
        self.children = children or []

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Strikethrough(children={len(self.children)})"


class Footnote(InlineNode):
    """Footnote reference."""

    def __init__(self, label: str, source_pos: SourcePosition | None = None) -> None:
        """Initialize footnote."""
        super().__init__(source_pos=source_pos)
        self.label = label

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Footnote(label={repr(self.label)})"


@dataclass
class Reference:
    """Link reference definition."""

    label: str  # Reference label (case-insensitive)
    url: str  # Target URL
    title: str | None = None  # Optional title

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Reference(label={repr(self.label)}, url={repr(self.url)})"
