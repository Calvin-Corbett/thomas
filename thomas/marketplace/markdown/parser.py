"""
Main Markdown parser combining block and inline parsing.

Constructs a complete AST from Markdown source, handling:
- Block-level structure (headings, paragraphs, lists, etc.)
- Inline content (emphasis, links, code, etc.)
- Link reference resolution
- List tightness detection
- Error recovery
"""

from __future__ import annotations

from typing import List

from thomas.marketplace.markdown._types import (
    BlockQuote,
    CodeBlock,
    Document,
    Heading,
    List,
    ListItem,
    ListType,
    MarkdownNode,
    Paragraph,
    SourcePosition,
    Table,
    TableAlignment,
    TableCell,
    TableRow,
    ThematicBreak,
)
from thomas.marketplace.markdown.inline_parser import InlineParser
from thomas.marketplace.markdown.lexer import Block, BlockType, Lexer


class Parser:
    """Main Markdown parser."""

    def __init__(self) -> None:
        """Initialize parser."""
        self.references: dict[str, tuple[str, str | None]] = {}
        self.footnotes: dict[str, str] = {}

    def parse(self, source: str) -> Document:
        """Parse Markdown source into AST.

        Args:
            source: Markdown source code

        Returns:
            Document node (root of AST)

        Raises:
            ParseError: If parsing fails catastrophically
        """
        # Lexical analysis
        lexer = Lexer(source)
        blocks = lexer.lex()

        # Extract reference definitions
        self._extract_references(blocks)

        # Parse blocks
        ast = self._parse_blocks(blocks)

        return ast

    def _extract_references(self, blocks: List[Block]) -> None:
        """Extract link reference definitions."""
        for block in blocks:
            if block.type == BlockType.LINK_REF:
                label = block.meta.get("label", "")
                url = block.meta.get("url", "")
                title = block.meta.get("title")
                self.references[label] = (url, title)

    def _parse_blocks(self, blocks: List[Block]) -> Document:
        """Parse block list into AST."""
        doc = Document()
        i = 0

        while i < len(blocks):
            block = blocks[i]

            # Skip reference definitions
            if block.type == BlockType.LINK_REF:
                i += 1
                continue

            node = self._parse_block(block)
            if node:
                doc.children.append(node)

            i += 1

        return doc

    def _parse_block(self, block: Block) -> MarkdownNode | None:
        """Parse single block into AST node."""
        if block.type == BlockType.HEADING:
            return self._parse_heading(block)
        elif block.type == BlockType.PARAGRAPH:
            return self._parse_paragraph(block)
        elif block.type == BlockType.CODE_BLOCK:
            return self._parse_code_block(block)
        elif block.type == BlockType.BLOCKQUOTE:
            return self._parse_blockquote(block)
        elif block.type == BlockType.LIST:
            return self._parse_list(block)
        elif block.type == BlockType.THEMATIC_BREAK:
            return ThematicBreak(source_pos=self._make_source_pos(block))
        elif block.type == BlockType.TABLE:
            return self._parse_table(block)
        elif block.type == BlockType.HTML_BLOCK:
            from thomas.marketplace.markdown._types import HTMLBlock

            html_block = HTMLBlock(block.content, source_pos=self._make_source_pos(block))
            return html_block
        elif block.type == BlockType.BLANK:
            return None

        return None

    def _parse_heading(self, block: Block) -> Heading:
        """Parse heading block."""
        level = block.meta.get("level", 1)
        heading = Heading(level, source_pos=self._make_source_pos(block))

        # Parse inline content
        parser = InlineParser()
        parser.references = self.references
        inline_nodes = parser.parse(block.content)
        heading.children = inline_nodes

        return heading

    def _parse_paragraph(self, block: Block) -> Paragraph:
        """Parse paragraph block."""
        para = Paragraph(source_pos=self._make_source_pos(block))

        # Parse inline content
        parser = InlineParser()
        parser.references = self.references
        inline_nodes = parser.parse(block.content)
        para.children = inline_nodes

        return para

    def _parse_code_block(self, block: Block) -> CodeBlock:
        """Parse code block."""
        language = block.meta.get("language")
        fenced = block.meta.get("fenced", True)

        code_block = CodeBlock(
            code=block.content, language=language, fenced=fenced, source_pos=self._make_source_pos(block)
        )
        return code_block

    def _parse_blockquote(self, block: Block) -> BlockQuote:
        """Parse blockquote block."""
        blockquote = BlockQuote(source_pos=self._make_source_pos(block))

        # Recursively parse blockquote content
        lexer = Lexer(block.content)
        inner_blocks = lexer.lex()

        for inner_block in inner_blocks:
            if inner_block.type != BlockType.LINK_REF:
                node = self._parse_block(inner_block)
                if node:
                    blockquote.children.append(node)

        return blockquote

    def _parse_list(self, block: Block) -> List:
        """Parse list block."""
        is_ordered = block.meta.get("ordered", False)
        list_type = ListType.ORDERED if is_ordered else ListType.UNORDERED

        # Determine if list is tight (no blank lines between items)
        tight = self._is_tight_list(block.content)

        list_node = List(list_type=list_type, tight=tight, source_pos=self._make_source_pos(block))

        # Parse list items
        items = self._split_list_items(block.content)
        for item_content in items:
            item = self._parse_list_item(item_content, tight)
            if item:
                list_node.children.append(item)

        return list_node

    def _is_tight_list(self, content: str) -> bool:
        """Check if list is tight (no blank lines between items)."""
        lines = content.split("\n")
        for line in lines:
            if line.strip() == "":
                return False
        return True

    def _split_list_items(self, content: str) -> List[str]:
        """Split list content into individual items."""
        items = []
        current_item: List[str] = []
        lines = content.split("\n")

        for line in lines:
            stripped = line.lstrip()

            # Check if this is a new list item marker
            if self._is_list_marker(stripped):
                if current_item:
                    items.append("\n".join(current_item))
                current_item = [line]
            else:
                current_item.append(line)

        if current_item:
            items.append("\n".join(current_item))

        return items

    def _is_list_marker(self, line: str) -> bool:
        """Check if line starts with list marker."""
        import re

        return bool(re.match(r"^([\*\-\+]\s|[0-9]{1,9}[.)]\s)", line))

    def _parse_list_item(self, content: str, tight: bool) -> ListItem | None:
        """Parse single list item."""
        item = ListItem()

        # Check for task list checkbox
        content = content.strip()
        if content.startswith("- [ ]"):
            item.checked = False
            content = content[5:].strip()
        elif content.startswith("- [x]") or content.startswith("- [X]"):
            item.checked = True
            content = content[5:].strip()

        # Remove list marker
        import re

        content = re.sub(r"^([\*\-\+]\s|[0-9]{1,9}[.)]\s)", "", content)

        # Parse content
        if tight:
            # Single line item
            parser = InlineParser()
            parser.references = self.references
            inline_nodes = parser.parse(content)
            item.children = inline_nodes
        else:
            # Multi-line item - may contain blocks
            lexer = Lexer(content)
            blocks = lexer.lex()
            for block in blocks:
                if block.type != BlockType.LINK_REF:
                    node = self._parse_block(block)
                    if node:
                        item.children.append(node)

        return item

    def _parse_table(self, block: Block) -> Table | None:
        """Parse GFM table."""
        lines = block.content.split("\n")
        if len(lines) < 2:
            return None

        header_line = lines[0]
        sep_line = lines[1]

        # Parse alignments from separator line
        alignments = self._parse_table_alignments(sep_line)
        if not alignments:
            return None

        table = Table(alignments=alignments, source_pos=self._make_source_pos(block))

        # Parse header row
        header_cells = self._parse_table_row(header_line)
        header_row = TableRow()
        for i, cell_text in enumerate(header_cells):
            cell = TableCell(is_header=True)
            parser = InlineParser()
            parser.references = self.references
            cell.children = parser.parse(cell_text)
            header_row.children.append(cell)
        table.children.append(header_row)

        # Parse body rows
        for line in lines[2:]:
            if line.strip():
                cells = self._parse_table_row(line)
                row = TableRow()
                for i, cell_text in enumerate(cells):
                    cell = TableCell(is_header=False)
                    parser = InlineParser()
                    parser.references = self.references
                    cell.children = parser.parse(cell_text)
                    row.children.append(cell)
                table.children.append(row)

        return table

    def _parse_table_alignments(self, sep_line: str) -> List[TableAlignment]:
        """Parse table column alignments."""
        cells = [cell.strip() for cell in sep_line.split("|")]
        cells = [c for c in cells if c]

        alignments = []
        for cell in cells:
            if not cell or not all(c in ":-" for c in cell):
                return []
            if "-" not in cell:
                return []

            left = cell.startswith(":")
            right = cell.endswith(":")

            if left and right:
                alignments.append(TableAlignment.CENTER)
            elif right:
                alignments.append(TableAlignment.RIGHT)
            elif left:
                alignments.append(TableAlignment.LEFT)
            else:
                alignments.append(TableAlignment.NONE)

        return alignments if alignments else []

    def _parse_table_row(self, line: str) -> List[str]:
        """Parse table row into cells."""
        cells = line.split("|")
        # Remove leading/trailing empty cells if line starts/ends with |
        if cells[0].strip() == "":
            cells = cells[1:]
        if cells and cells[-1].strip() == "":
            cells = cells[:-1]
        return [cell.strip() for cell in cells]

    def _make_source_pos(self, block: Block) -> SourcePosition:
        """Create SourcePosition from block."""
        return SourcePosition(line=block.line_start + 1, column=0, offset=block.line_start)
