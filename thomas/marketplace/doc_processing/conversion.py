"""Format conversion between document representations.

Converts between Markdown, HTML, reStructuredText, and plain text
with structure preservation.
"""

import re

from thomas.marketplace.doc_processing._exceptions import ConversionError
from thomas.marketplace.doc_processing._types import Document, Page, TextBlock, TextBlockType


class MarkdownParser:
    """Parse Markdown to HTML."""

    @staticmethod
    def parse(markdown: str) -> str:
        """Convert Markdown to HTML.

        Args:
            markdown: Markdown text.

        Returns:
            HTML string.

        Raises:
            ConversionError: If parsing fails.
        """
        try:
            html = markdown

            # Headers (h1-h6)
            for level in range(6, 0, -1):
                pattern = rf"^{'#' * level}\s+(.+)$"
                html = re.sub(
                    pattern,
                    rf"<h{level}>\1</h{level}>",
                    html,
                    flags=re.MULTILINE,
                )

            # Bold and italic
            html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
            html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)
            html = re.sub(r"__(.+?)__", r"<strong>\1</strong>", html)
            html = re.sub(r"_(.+?)_", r"<em>\1</em>", html)

            # Links
            html = re.sub(
                r"\[(.+?)\]\((.+?)\)",
                r'<a href="\2">\1</a>',
                html,
            )

            # Code
            html = re.sub(r"`([^`]+)`", r"<code>\1</code>", html)

            # Code blocks
            html = re.sub(
                r"```(.+?)```",
                r"<pre><code>\1</code></pre>",
                html,
                flags=re.DOTALL,
            )

            # Lists
            html = MarkdownParser._convert_lists(html)

            # Tables
            html = MarkdownParser._convert_tables(html)

            # Paragraphs
            paragraphs = re.split(r"\n\n+", html)
            html = "\n".join(f"<p>{p}</p>" if p and not p.startswith("<") else p for p in paragraphs)

            return html

        except Exception as e:
            raise ConversionError(f"Markdown parsing failed: {e}")

    @staticmethod
    def _convert_lists(html: str) -> str:
        """Convert Markdown lists to HTML.

        Args:
            html: HTML with Markdown lists.

        Returns:
            HTML with converted lists.
        """
        # Unordered lists
        html = re.sub(
            r"(^\s*[-*+]\s+.+$)+",
            lambda m: "<ul>\n" + m.group(0) + "\n</ul>",
            html,
            flags=re.MULTILINE,
        )
        html = re.sub(r"^\s*[-*+]\s+(.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)

        # Ordered lists
        html = re.sub(
            r"(^\s*\d+\.\s+.+$)+",
            lambda m: "<ol>\n" + m.group(0) + "\n</ol>",
            html,
            flags=re.MULTILINE,
        )
        html = re.sub(r"^\s*\d+\.\s+(.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)

        return html

    @staticmethod
    def _convert_tables(html: str) -> str:
        """Convert Markdown tables to HTML.

        Args:
            html: HTML with Markdown tables.

        Returns:
            HTML with converted tables.
        """
        # Match Markdown tables: rows with | separators
        table_pattern = r"(\|.+\|\n)+\|[-:\s|]+\|\n((\|.+\|\n)*)"

        def convert_table(match: re.Match) -> str:
            table_text = match.group(0)
            rows = [r for r in table_text.split("\n") if r.strip() and "|" in r]

            html_rows = ["<table>"]

            for i, row in enumerate(rows):
                cells = [c.strip() for c in row.split("|") if c.strip()]

                if i == 0:
                    html_rows.append("<tr>")
                    for cell in cells:
                        html_rows.append(f"<th>{cell}</th>")
                    html_rows.append("</tr>")
                else:
                    if "-" not in row:  # Skip separator row
                        html_rows.append("<tr>")
                        for cell in cells:
                            html_rows.append(f"<td>{cell}</td>")
                        html_rows.append("</tr>")

            html_rows.append("</table>")
            return "\n".join(html_rows)

        return re.sub(table_pattern, convert_table, html, flags=re.MULTILINE)


class HTMLtoMarkdownConverter:
    """Convert HTML back to Markdown."""

    @staticmethod
    def convert(html: str) -> str:
        """Convert HTML to Markdown.

        Args:
            html: HTML content.

        Returns:
            Markdown string.

        Raises:
            ConversionError: If conversion fails.
        """
        try:
            markdown = html

            # Headers
            for level in range(1, 7):
                pattern = rf"<h{level}[^>]*>(.+?)</h{level}>"
                markdown = re.sub(
                    pattern,
                    rf"{'#' * level} \1",
                    markdown,
                    flags=re.IGNORECASE,
                )

            # Strong and emphasis
            markdown = re.sub(r"<strong[^>]*>(.+?)</strong>", r"**\1**", markdown, flags=re.IGNORECASE)
            markdown = re.sub(r"<b[^>]*>(.+?)</b>", r"**\1**", markdown, flags=re.IGNORECASE)
            markdown = re.sub(r"<em[^>]*>(.+?)</em>", r"*\1*", markdown, flags=re.IGNORECASE)
            markdown = re.sub(r"<i[^>]*>(.+?)</i>", r"*\1*", markdown, flags=re.IGNORECASE)

            # Links
            markdown = re.sub(
                r'<a[^>]*href="([^"]*)"[^>]*>(.+?)</a>',
                r"[\2](\1)",
                markdown,
                flags=re.IGNORECASE,
            )

            # Code
            markdown = re.sub(
                r"<code[^>]*>(.+?)</code>",
                r"`\1`",
                markdown,
                flags=re.IGNORECASE,
            )

            # Code blocks
            markdown = re.sub(
                r"<pre[^>]*><code[^>]*>(.+?)</code></pre>",
                r"```\1```",
                markdown,
                flags=re.IGNORECASE | re.DOTALL,
            )

            # Lists
            markdown = HTMLtoMarkdownConverter._convert_lists(markdown)

            # Tables
            markdown = HTMLtoMarkdownConverter._convert_tables(markdown)

            # Paragraphs
            markdown = re.sub(
                r"<p[^>]*>(.+?)</p>",
                r"\1\n\n",
                markdown,
                flags=re.IGNORECASE,
            )

            # Remove remaining tags
            markdown = re.sub(r"<[^>]+>", "", markdown)

            return markdown

        except Exception as e:
            raise ConversionError(f"HTML to Markdown conversion failed: {e}")

    @staticmethod
    def _convert_lists(markdown: str) -> str:
        """Convert HTML lists to Markdown."""
        # Unordered lists
        markdown = re.sub(
            r"<li[^>]*>(.+?)</li>",
            r"- \1\n",
            markdown,
            flags=re.IGNORECASE,
        )

        markdown = re.sub(r"<[ou]l[^>]*>|</[ou]l>", "", markdown, flags=re.IGNORECASE)

        return markdown

    @staticmethod
    def _convert_tables(markdown: str) -> str:
        """Convert HTML tables to Markdown."""
        # Simple table conversion
        table_pattern = r"<table[^>]*>(.+?)</table>"

        def convert_table(match: re.Match) -> str:
            table_html = match.group(1)

            rows = re.findall(
                r"<tr[^>]*>(.+?)</tr>",
                table_html,
                re.IGNORECASE | re.DOTALL,
            )

            md_rows = []
            for i, row_html in enumerate(rows):
                cells = re.findall(
                    r"<t[dh][^>]*>(.+?)</t[dh]>",
                    row_html,
                    re.IGNORECASE | re.DOTALL,
                )
                cells = [re.sub(r"<[^>]+>", "", c) for c in cells]

                md_rows.append("| " + " | ".join(cells) + " |")

                if i == 0:
                    separators = ["---"] * len(cells)
                    md_rows.append("| " + " | ".join(separators) + " |")

            return "\n".join(md_rows) + "\n\n"

        return re.sub(table_pattern, convert_table, markdown, flags=re.IGNORECASE | re.DOTALL)


class PlainTextStructurer:
    """Convert plain text to structured document."""

    @staticmethod
    def structure(text: str) -> Document:
        """Parse plain text and extract structure.

        Args:
            text: Plain text content.

        Returns:
            Structured Document.
        """
        lines = text.split("\n")

        text_blocks: list[TextBlock] = []
        current_block_lines: list[str] = []
        block_type = TextBlockType.PARAGRAPH

        for line in lines:
            if not line.strip():
                if current_block_lines:
                    block_text = "\n".join(current_block_lines)
                    text_block = TextBlock(
                        text=block_text,
                        bbox=None,
                        block_type=block_type,
                    )
                    text_blocks.append(text_block)
                    current_block_lines = []
                continue

            # Detect block type
            if PlainTextStructurer._is_heading(line):
                if current_block_lines:
                    text = "\n".join(current_block_lines)
                    text_blocks.append(TextBlock(text=text, bbox=None))
                    current_block_lines = []

                block_type = TextBlockType.HEADING
                current_block_lines.append(line)
            elif PlainTextStructurer._is_list_item(line):
                block_type = TextBlockType.LIST
                current_block_lines.append(line)
            else:
                block_type = TextBlockType.PARAGRAPH
                current_block_lines.append(line)

        if current_block_lines:
            text = "\n".join(current_block_lines)
            text_blocks.append(TextBlock(text=text, bbox=None, block_type=block_type))

        doc = Document(
            text=text,
        )

        page = Page(page_number=1, text=text, text_blocks=text_blocks)
        doc.pages.append(page)

        return doc

    @staticmethod
    def _is_heading(line: str) -> bool:
        """Check if line is a heading."""
        # Heuristics: short line, ends with colon, all caps, etc.
        stripped = line.strip()
        return (
            (len(stripped) < 60 and stripped.isupper() and len(stripped) > 5)
            or stripped.endswith(":")
            or re.match(r"^(Chapter|Section|Part)\s+\d+", stripped, re.IGNORECASE)
        )

    @staticmethod
    def _is_list_item(line: str) -> bool:
        """Check if line is a list item."""
        stripped = line.strip()
        return bool(re.match(r"^([-•*]|\d+\.|\w\))\s+", stripped))


class DocumentMerger:
    """Merge multiple documents with section renumbering."""

    @staticmethod
    def merge(documents: list[Document]) -> Document:
        """Merge documents.

        Args:
            documents: Documents to merge.

        Returns:
            Merged document.
        """
        merged = Document()
        merged.text = ""

        page_offset = 0

        for doc in documents:
            merged.text += doc.extract_text() + "\n\n"

            for page in doc.pages:
                new_page = Page(
                    page_number=page.page_number + page_offset,
                    text=page.text,
                    text_blocks=page.text_blocks,
                    width=page.width,
                    height=page.height,
                )
                merged.pages.append(new_page)

            page_offset += len(doc.pages)

        return merged


class TemplateDocumentGenerator:
    """Generate documents from templates."""

    @staticmethod
    def generate(template: str, variables: dict[str, str]) -> str:
        """Generate document from template.

        Args:
            template: Template string with {variable} placeholders.
            variables: Variable values.

        Returns:
            Generated document text.

        Raises:
            ConversionError: If generation fails.
        """
        try:
            result = template

            for key, value in variables.items():
                placeholder = "{" + key + "}"
                result = result.replace(placeholder, value)

            return result

        except Exception as e:
            raise ConversionError(f"Template generation failed: {e}")
