"""
Thomas Markdown Parser and Toolchain.

A complete, spec-compliant Markdown parser with HTML and text rendering,
extensions, linting, and transformation utilities.
"""

from thomas.marketplace.markdown._exceptions import (
    MarkdownError,
    ParseError,
    RenderError,
)
from thomas.marketplace.markdown._types import (
    BlockQuote,
    Code,
    CodeBlock,
    Document,
    Emphasis,
    Footnote,
    Heading,
    HTMLInline,
    Image,
    InlineNode,
    LineBreak,
    Link,
    List,
    ListItem,
    MarkdownNode,
    Paragraph,
    RenderConfig,
    SoftBreak,
    Strikethrough,
    Strong,
    Table,
    TableCell,
    TableRow,
    Text,
    ThematicBreak,
)
from thomas.marketplace.markdown.html_renderer import HTMLRenderer
from thomas.marketplace.markdown.linting import Linter
from thomas.marketplace.markdown.parser import Parser
from thomas.marketplace.markdown.text_renderer import TextRenderer

__version__ = "1.0.0"

__all__ = [
    "Parser",
    "HTMLRenderer",
    "TextRenderer",
    "Linter",
    "MarkdownNode",
    "InlineNode",
    "Document",
    "Heading",
    "Paragraph",
    "BlockQuote",
    "CodeBlock",
    "List",
    "ListItem",
    "ThematicBreak",
    "Table",
    "TableRow",
    "TableCell",
    "Text",
    "Emphasis",
    "Strong",
    "Code",
    "Link",
    "Image",
    "LineBreak",
    "SoftBreak",
    "HTMLInline",
    "Strikethrough",
    "Footnote",
    "RenderConfig",
    "MarkdownError",
    "ParseError",
    "RenderError",
]
