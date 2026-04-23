"""
HTML renderer for Markdown AST.

Converts Markdown AST nodes to HTML output with support for:
- Proper escaping of special characters
- Auto-generated heading IDs
- Code block language classes
- Table alignment
- Footnote rendering
- Configurable unsafe HTML pass-through
"""

from __future__ import annotations

import html as html_module
import re
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
    RenderConfig,
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


class HTMLRenderer:
    """Renders Markdown AST to HTML."""

    def __init__(self, config: RenderConfig | None = None) -> None:
        """Initialize HTML renderer.

        Args:
            config: Render configuration
        """
        self.config = config or RenderConfig()
        self.footnote_refs: dict[str, str] = {}
        self.heading_ids: dict[int, int] = {}

    def render(self, node: MarkdownNode) -> str:
        """Render AST node to HTML.

        Args:
            node: Root node to render

        Returns:
            HTML string

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
            return self._render_table_row(node)
        elif isinstance(node, TableCell):
            return self._render_table_cell(node)
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
        html_parts = []
        for child in node.children:
            html_parts.append(self._render_node(child))

        html = "\n".join(html_parts)

        # Append footnotes if any
        if self.footnote_refs:
            html += self._render_footnotes()

        return html

    def _render_heading(self, node: Heading) -> str:
        """Render heading."""
        level = node.level
        children_html = self._render_children(node.children)

        # Generate heading ID if enabled
        heading_id = ""
        if self.config.heading_ids:
            heading_id_str = self._generate_heading_id(children_html)
            heading_id = f' id="{heading_id_str}"'

        return f"<h{level}{heading_id}>{children_html}</h{level}>\n"

    def _generate_heading_id(self, text: str) -> str:
        """Generate slug-format ID from heading text."""
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", "", text)
        # Lowercase and replace spaces/punctuation with hyphens
        text = re.sub(r"[^\w\s-]", "", text).strip()
        text = re.sub(r"[-\s]+", "-", text).lower()
        return text

    def _render_paragraph(self, node: Paragraph) -> str:
        """Render paragraph."""
        children_html = self._render_children(node.children)
        return f"<p>{children_html}</p>\n"

    def _render_blockquote(self, node: BlockQuote) -> str:
        """Render blockquote."""
        children_html = "".join(self._render_node(child) for child in node.children)
        return f"<blockquote>\n{children_html}</blockquote>\n"

    def _render_code_block(self, node: CodeBlock) -> str:
        """Render code block."""
        escaped = self._escape_html(node.code)

        # Add language class if present
        if node.language:
            class_attr = f' class="language-{self._escape_attr(node.language)}"'
        else:
            class_attr = ""

        if self.config.xhtml:
            return f"<pre><code{class_attr}>{escaped}</code></pre>\n"
        else:
            return f"<pre><code{class_attr}>{escaped}</code></pre>\n"

    def _render_list(self, node: List) -> str:
        """Render list (ordered or unordered)."""
        tag = "ol" if node.list_type == ListType.ORDERED else "ul"

        start_attr = ""
        if node.list_type == ListType.ORDERED and node.start and node.start != 1:
            start_attr = f' start="{node.start}"'

        items_html = "".join(self._render_node(child) for child in node.children)
        return f"<{tag}{start_attr}>\n{items_html}</{tag}>\n"

    def _render_list_item(self, node: ListItem) -> str:
        """Render list item."""
        # Handle task list checkbox
        checkbox = ""
        if node.checked is not None:
            checked_str = "checked disabled" if node.checked else "disabled"
            checkbox = f'<input type="checkbox" {checked_str} /> '

        children_html = "".join(self._render_node(child) for child in node.children)
        return f"<li>{checkbox}{children_html}</li>\n"

    def _render_thematic_break(self) -> str:
        """Render thematic break."""
        if self.config.xhtml:
            return "<hr />\n"
        else:
            return "<hr>\n"

    def _render_table(self, node: Table) -> str:
        """Render table."""
        html = "<table>\n<thead>\n"

        # Render header row (first child)
        if node.children:
            header_row = node.children[0]
            html += "<tr>\n"
            for child in header_row.children:
                cell_html = self._render_node(child)
                html += f"  <th>{cell_html}</th>\n"
            html += "</tr>\n"

        html += "</thead>\n<tbody>\n"

        # Render body rows
        for row in node.children[1:]:
            html += "<tr>\n"
            for i, cell in enumerate(row.children):
                cell_html = self._render_node(cell)
                # Add alignment if configured
                align_str = ""
                if self.config.table_alignment and i < len(node.alignments):
                    alignment = node.alignments[i]
                    if alignment != TableAlignment.NONE:
                        align_str = f' style="text-align: {alignment.value}"'
                html += f"  <td{align_str}>{cell_html}</td>\n"
            html += "</tr>\n"

        html += "</tbody>\n</table>\n"
        return html

    def _render_table_row(self, node: TableRow) -> str:
        """Render table row (handled by table)."""
        # This is handled by the table renderer
        return ""

    def _render_table_cell(self, node: TableCell) -> str:
        """Render table cell."""
        # Return just the content, tag is added by table renderer
        return "".join(self._render_node(child) for child in node.children)

    def _render_html_block(self, node: HTMLBlock) -> str:
        """Render HTML block."""
        if self.config.unsafe_html:
            return node.html + "\n"
        else:
            return self._escape_html(node.html) + "\n"

    def _render_text(self, node: Text) -> str:
        """Render text node."""
        return self._escape_html(node.content)

    def _render_emphasis(self, node: Emphasis) -> str:
        """Render emphasis (italic)."""
        children_html = self._render_children(node.children)
        return f"<em>{children_html}</em>"

    def _render_strong(self, node: Strong) -> str:
        """Render strong (bold)."""
        children_html = self._render_children(node.children)
        return f"<strong>{children_html}</strong>"

    def _render_code(self, node: Code) -> str:
        """Render inline code."""
        escaped = self._escape_html(node.content)
        return f"<code>{escaped}</code>"

    def _render_link(self, node: Link) -> str:
        """Render link."""
        children_html = self._render_children(node.children)
        url = self._escape_attr(node.url)
        link_html = f'<a href="{url}"'

        if node.title:
            title = self._escape_attr(node.title)
            link_html += f' title="{title}"'

        link_html += f">{children_html}</a>"
        return link_html

    def _render_image(self, node: Image) -> str:
        """Render image."""
        src = self._escape_attr(node.src)
        alt = self._escape_attr(node.alt)
        img_html = f'<img src="{src}" alt="{alt}"'

        if node.title:
            title = self._escape_attr(node.title)
            img_html += f' title="{title}"'

        if self.config.xhtml:
            img_html += " />"
        else:
            img_html += ">"

        return img_html

    def _render_line_break(self) -> str:
        """Render hard line break."""
        if self.config.xhtml:
            return "<br />"
        else:
            return "<br>"

    def _render_soft_break(self) -> str:
        """Render soft line break."""
        if self.config.hard_breaks:
            if self.config.xhtml:
                return "<br />"
            else:
                return "<br>"
        else:
            return "\n"

    def _render_html_inline(self, node: HTMLInline) -> str:
        """Render inline HTML."""
        if self.config.unsafe_html:
            return node.html
        else:
            return self._escape_html(node.html)

    def _render_strikethrough(self, node: Strikethrough) -> str:
        """Render strikethrough."""
        children_html = self._render_children(node.children)
        return f"<del>{children_html}</del>"

    def _render_footnote(self, node: Footnote) -> str:
        """Render footnote reference."""
        label = self._escape_attr(node.label)
        return f'<sup><a href="#fn-{label}" id="fnref-{label}">[{label}]</a></sup>'

    def _render_footnotes(self) -> str:
        """Render footnote section."""
        if not self.footnote_refs:
            return ""

        html = '<div class="footnotes">\n<ol>\n'
        for label, content in self.footnote_refs.items():
            html += f'<li id="fn-{label}">{content} '
            html += f'<a href="#fnref-{label}" class="footnote-backref">↩</a></li>\n'
        html += "</ol>\n</div>\n"
        return html

    def _render_children(self, children: List[InlineNode]) -> str:
        """Render list of inline children."""
        return "".join(self._render_node(child) for child in children)

    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters."""
        return html_module.escape(text)

    def _escape_attr(self, text: str) -> str:
        """Escape HTML attribute value."""
        return html_module.escape(text, quote=True)
