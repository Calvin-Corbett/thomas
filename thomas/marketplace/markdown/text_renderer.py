"""
Plain text renderer for Markdown AST.

Converts Markdown AST to readable plain text output with:
- Heading decoration (underlines or prefix)
- Proper indentation for nested structures
- Table rendering with column alignment
- Code block indentation
- Link rendering
- Configurable line wrapping
"""

from __future__ import annotations

import textwrap
from typing import List

from thomas.marketplace.markdown._exceptions import RenderError
from thomas.marketplace.markdown._types import (
    BlockQuote,
    Code,
    CodeBlock,
    Document,
    Emphasis,
    Footnote,
    Heading,
    HTMLBlock,
    HTMLInline,
    Image,
    InlineNode,
    LineBreak,
    Link,
    List,
    ListItem,
    ListType,
    MarkdownNode,
    Paragraph,
    SoftBreak,
    Strikethrough,
    Strong,
    Table,
    TableAlignment,
    TableCell,
    TableRow,
    Text,
    ThematicBreak,
)


class TextRenderer:
    """Renders Markdown AST to plain text."""

    def __init__(self, wrap_width: int | None = 80, heading_style: str = "underline") -> None:
        """Initialize text renderer.

        Args:
            wrap_width: Line wrap width (None=no wrapping)
            heading_style: 'underline', 'prefix', or 'plain'
        """
        self.wrap_width = wrap_width
        self.heading_style = heading_style
        self.indent_level = 0
        self.footnotes: dict = {}

    def render(self, node: MarkdownNode) -> str:
        """Render AST node to plain text.

        Args:
            node: Root node to render

        Returns:
            Plain text string

        Raises:
            RenderError: If rendering fails
        """
        try:
            return self._render_node(node)
        except Exception as e:
            raise RenderError(f"Render failed: {e}")

    def _render_node(self, node: MarkdownNode | InlineNode) -> str:
        """Dispatch rendering based on node type."""
        if isinstance(node, Document):
            return self._render_document(node)
        elif isinstance(node, Heading):
            return self._render_heading(node)
        elif isinstance(node, Paragraph):
            return self._render_paragraph(node)
        elif isinstance(node, BlockQuote):
            return self._render_blockquote(node)
        elif isinstance(node, CodeBlock):
            return self._render_code_block(node)
        elif isinstance(node, List):
            return self._render_list(node)
        elif isinstance(node, ListItem):
            return self._render_list_item(node)
        elif isinstance(node, ThematicBreak):
            return self._render_thematic_break()
        elif isinstance(node, Table):
            return self._render_table(node)
        elif isinstance(node, TableRow):
            return ""  # Handled by table
        elif isinstance(node, TableCell):
            return self._render_children(node.children)
        elif isinstance(node, HTMLBlock):
            return self._render_html_block(node)
        elif isinstance(node, Text):
            return self._render_text(node)
        elif isinstance(node, Emphasis):
            return self._render_emphasis(node)
        elif isinstance(node, Strong):
            return self._render_strong(node)
        elif isinstance(node, Code):
            return self._render_code(node)
        elif isinstance(node, Link):
            return self._render_link(node)
        elif isinstance(node, Image):
            return self._render_image(node)
        elif isinstance(node, LineBreak):
            return self._render_line_break()
        elif isinstance(node, SoftBreak):
            return self._render_soft_break()
        elif isinstance(node, HTMLInline):
            return self._render_html_inline(node)
        elif isinstance(node, Strikethrough):
            return self._render_strikethrough(node)
        elif isinstance(node, Footnote):
            return self._render_footnote(node)
        else:
            raise RenderError(f"Unknown node type: {type(node)}")

    def _render_document(self, node: Document) -> str:
        """Render document (root)."""
        text_parts = []
        for child in node.children:
            text_parts.append(self._render_node(child))

        text = "\n".join(text_parts)

        # Append footnotes if any
        if self.footnotes:
            text += "\n" + self._render_footnotes()

        return text.rstrip() + "\n"

    def _render_heading(self, node: Heading) -> str:
        """Render heading."""
        children_text = self._render_children(node.children)

        if self.heading_style == "underline" and node.level <= 2:
            # Underline style for h1, h2
            underline = "=" * len(children_text) if node.level == 1 else "-" * len(children_text)
            return f"{children_text}\n{underline}\n\n"
        elif self.heading_style == "prefix" or node.level > 2:
            # Prefix style with #
            prefix = "#" * node.level
            return f"{prefix} {children_text}\n\n"
        else:
            # Plain style
            return f"{children_text}\n\n"

    def _render_paragraph(self, node: Paragraph) -> str:
        """Render paragraph."""
        text = self._render_children(node.children)
        if self.wrap_width:
            text = self._wrap_text(text, self.wrap_width)
        return f"{text}\n\n"

    def _render_blockquote(self, node: BlockQuote) -> str:
        """Render blockquote."""
        self.indent_level += 1
        children_text = "".join(self._render_node(child) for child in node.children)
        self.indent_level -= 1

        # Add > prefix to each line
        lines = children_text.rstrip().split("\n")
        quoted = "\n".join(f"> {line}" if line.strip() else ">" for line in lines)
        return f"{quoted}\n\n"

    def _render_code_block(self, node: CodeBlock) -> str:
        """Render code block."""
        # Indent code by 4 spaces
        lines = node.code.split("\n")
        indented = "\n".join(f"    {line}" for line in lines)
        return f"{indented}\n\n"

    def _render_list(self, node: List) -> str:
        """Render list (ordered or unordered)."""
        text_parts = []
        for i, child in enumerate(node.children):
            if node.list_type == ListType.ORDERED:
                marker = f"{(node.start or 1) + i}. "
            else:
                marker = "- "

            # Render list item
            item_text = self._render_list_item_content(child, marker)
            text_parts.append(item_text)

        return "".join(text_parts) + "\n"

    def _render_list_item(self, node: ListItem) -> str:
        """Render single list item."""
        return self._render_children(node.children)

    def _render_list_item_content(self, node: ListItem, marker: str) -> str:
        """Render list item with marker."""
        # Handle task list
        checkbox = ""
        if node.checked is not None:
            checkbox = "[x] " if node.checked else "[ ] "
            marker = marker.replace("- ", "")

        children_text = self._render_children(node.children).rstrip()

        if not children_text:
            return f"{marker}{checkbox}\n"

        # Wrap with indentation
        lines = children_text.split("\n")
        result = [f"{marker}{checkbox}{lines[0]}"]

        indent = " " * len(marker)
        for line in lines[1:]:
            result.append(f"{indent}{line}")

        return "\n".join(result) + "\n"

    def _render_thematic_break(self) -> str:
        """Render thematic break."""
        return "---\n\n"

    def _render_table(self, node: Table) -> str:
        """Render table with ASCII alignment."""
        if not node.children:
            return ""

        # Collect all rows
        rows = []
        col_widths = []

        for row in node.children:
            row_data = []
            for cell in row.children:
                cell_text = self._render_children(cell.children)
                row_data.append(cell_text)
            rows.append(row_data)

            # Track column widths
            for i, cell_text in enumerate(row_data):
                max_width = max(len(line) for line in cell_text.split("\n")) if cell_text else 0
                if i >= len(col_widths):
                    col_widths.append(max_width)
                else:
                    col_widths[i] = max(col_widths[i], max_width)

        # Render table
        result = []

        # Header row
        if rows:
            header = rows[0]
            separator_top = self._make_table_separator(col_widths)
            result.append(separator_top)

            header_line = self._make_table_row(header, col_widths, node.alignments)
            result.append(header_line)

            separator_bottom = self._make_table_separator(col_widths, True)
            result.append(separator_bottom)

            # Body rows
            for row in rows[1:]:
                row_line = self._make_table_row(row, col_widths, node.alignments)
                result.append(row_line)

            separator_end = self._make_table_separator(col_widths)
            result.append(separator_end)

        return "\n".join(result) + "\n\n"

    def _make_table_separator(self, col_widths: List[int], is_header: bool = False) -> str:
        """Create table row separator."""
        parts = []
        for width in col_widths:
            if is_header:
                parts.append("=" * (width + 2))
            else:
                parts.append("-" * (width + 2))
        return "+" + "+".join(parts) + "+"

    def _make_table_row(self, cells: List[str], col_widths: List[int], alignments: List[TableAlignment]) -> str:
        """Create table row."""
        parts = []
        for i, cell in enumerate(cells):
            width = col_widths[i] if i < len(col_widths) else len(cell)
            alignment = alignments[i] if i < len(alignments) else TableAlignment.NONE

            if alignment == TableAlignment.CENTER:
                cell_str = cell.center(width)
            elif alignment == TableAlignment.RIGHT:
                cell_str = cell.rjust(width)
            else:
                cell_str = cell.ljust(width)

            parts.append(f" {cell_str} ")

        return "|" + "|".join(parts) + "|"

    def _render_html_block(self, node: HTMLBlock) -> str:
        """Render HTML block."""
        return f"{node.html}\n\n"

    def _render_text(self, node: Text) -> str:
        """Render text node."""
        return node.content

    def _render_emphasis(self, node: Emphasis) -> str:
        """Render emphasis (italic) - plain text uses _underscore_."""
        children_text = self._render_children(node.children)
        return f"_{children_text}_"

    def _render_strong(self, node: Strong) -> str:
        """Render strong (bold) - plain text uses **asterisk**."""
        children_text = self._render_children(node.children)
        return f"**{children_text}**"

    def _render_code(self, node: Code) -> str:
        """Render inline code."""
        return f"`{node.content}`"

    def _render_link(self, node: Link) -> str:
        """Render link in reference style."""
        children_text = self._render_children(node.children)
        if node.url.startswith("mailto:"):
            # Email link
            return f"{children_text} <{node.url[7:]}>"
        else:
            # URL link - show in brackets
            return f"{children_text} ({node.url})"

    def _render_image(self, node: Image) -> str:
        """Render image."""
        if node.alt:
            return f"[Image: {node.alt}]"
        else:
            return f"[Image: {node.src}]"

    def _render_line_break(self) -> str:
        """Render hard line break."""
        return "\n"

    def _render_soft_break(self) -> str:
        """Render soft line break."""
        return "\n"

    def _render_html_inline(self, node: HTMLInline) -> str:
        """Render inline HTML."""
        # Strip HTML tags for plain text
        import re

        return re.sub(r"<[^>]+>", "", node.html)

    def _render_strikethrough(self, node: Strikethrough) -> str:
        """Render strikethrough."""
        children_text = self._render_children(node.children)
        return f"~~{children_text}~~"

    def _render_footnote(self, node: Footnote) -> str:
        """Render footnote reference."""
        return f"[{node.label}]"

    def _render_footnotes(self) -> str:
        """Render footnote section."""
        if not self.footnotes:
            return ""

        result = ["Notes:"]
        for label, content in self.footnotes.items():
            result.append(f"[{label}] {content}")

        return "\n".join(result)

    def _render_children(self, children: List[InlineNode]) -> str:
        """Render list of inline children."""
        return "".join(self._render_node(child) for child in children)

    def _wrap_text(self, text: str, width: int) -> str:
        """Wrap text to specified width."""
        wrapper = textwrap.TextWrapper(width=width)
        return "\n".join(wrapper.wrap(text))
