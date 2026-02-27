"""
Block-level lexer for Markdown.

Tokenizes Markdown source into blocks (headings, paragraphs, code blocks, etc).
Handles ATX and setext headings, indented and fenced code blocks, blockquotes,
lists with proper nesting and continuation, thematic breaks, and tables.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class BlockType(Enum):
    """Types of Markdown blocks."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    CODE_BLOCK = "code_block"
    BLOCKQUOTE = "blockquote"
    LIST = "list"
    THEMATIC_BREAK = "thematic_break"
    LINK_REF = "link_ref"
    HTML_BLOCK = "html_block"
    TABLE = "table"
    BLANK = "blank"


@dataclass
class Block:
    """Represents a block of Markdown content."""

    type: BlockType
    content: str  # Raw block content
    indent: int = 0  # Number of leading spaces
    line_start: int = 0  # Starting line number
    line_end: int = 0  # Ending line number
    meta: dict = None  # Additional metadata

    def __post_init__(self) -> None:
        """Initialize metadata dict if needed."""
        if self.meta is None:
            self.meta = {}

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Block({self.type.value}, lines {self.line_start}-{self.line_end})"


class Lexer:
    """Block-level Markdown lexer."""

    # Regex patterns
    ATX_HEADING_PATTERN = re.compile(r"^(#{1,6})(?:\s*(.*))?$")
    SETEXT_UNDERLINE_PATTERN = re.compile(r"^(=+|-+)\s*$")
    THEMATIC_BREAK_PATTERN = re.compile(r"^(?:[\*\-_]\s*){3,}$")
    FENCED_CODE_PATTERN = re.compile(r"^```+|^~~~+")
    LIST_MARKER_PATTERN = re.compile(r"^([\*\-\+]\s|[0-9]{1,9}[.)]\s)")
    LINK_REF_PATTERN = re.compile(r'^\[([^\]]+)\]:\s*<?([\S]+?)>?(?:\s+["\']([^"\']*)["\'])?\s*$')
    TABLE_PATTERN = re.compile(r"^\|?.+\|.+\|?\s*$")
    HTML_TAG_PATTERN = re.compile(r"^<(?:script|pre|style|!--|[A-Z])")

    def __init__(self, source: str) -> None:
        """Initialize lexer with source text.

        Args:
            source: Markdown source code
        """
        self.source = source
        self.lines = source.split("\n")
        self.pos = 0
        self.blocks: list[Block] = []

    def lex(self) -> list[Block]:
        """Tokenize source into blocks.

        Returns:
            List of Block objects
        """
        while self.pos < len(self.lines):
            self._skip_blank_lines()
            if self.pos >= len(self.lines):
                break

            line = self.lines[self.pos]
            indent = self._get_indent(line)

            # Try to match block types
            if (
                self._try_heading()
                or self._try_thematic_break()
                or self._try_fenced_code()
                or self._try_indented_code()
                or self._try_blockquote()
                or self._try_list()
                or self._try_html_block()
                or self._try_link_ref()
                or self._try_table()
            ):
                continue
            else:
                self._collect_paragraph()

        return self.blocks

    def _skip_blank_lines(self) -> int:
        """Skip blank lines and return count."""
        count = 0
        while self.pos < len(self.lines):
            if self.lines[self.pos].strip() == "":
                self.pos += 1
                count += 1
            else:
                break
        return count

    def _get_indent(self, line: str) -> int:
        """Get leading whitespace count (max 3 spaces)."""
        indent = 0
        for ch in line:
            if ch == " " and indent < 3:
                indent += 1
            elif ch == "\t":
                indent = ((indent // 4) + 1) * 4
                if indent > 3:
                    return 3
            else:
                break
        return min(indent, 3)

    def _try_heading(self) -> bool:
        """Try to match ATX or setext heading."""
        if self.pos >= len(self.lines):
            return False

        line = self.lines[self.pos]
        indent = self._get_indent(line)

        # ATX heading
        if indent <= 3:
            match = self.ATX_HEADING_PATTERN.match(line.lstrip())
            if match:
                level = len(match.group(1))
                content = match.group(2) or ""
                content = content.rstrip("#").rstrip()
                block = Block(BlockType.HEADING, content, indent, self.pos, self.pos)
                block.meta["level"] = level
                block.meta["style"] = "atx"
                self.blocks.append(block)
                self.pos += 1
                return True

        # Setext heading
        if self.pos + 1 < len(self.lines) and indent <= 3:
            next_line = self.lines[self.pos + 1]
            next_indent = self._get_indent(next_line)
            if next_indent <= 3 and self.SETEXT_UNDERLINE_PATTERN.match(next_line.lstrip()):
                level = 1 if next_line.lstrip()[0] == "=" else 2
                block = Block(BlockType.HEADING, line, indent, self.pos, self.pos + 1)
                block.meta["level"] = level
                block.meta["style"] = "setext"
                self.blocks.append(block)
                self.pos += 2
                return True

        return False

    def _try_thematic_break(self) -> bool:
        """Try to match thematic break (---, ___, ***)."""
        if self.pos >= len(self.lines):
            return False

        line = self.lines[self.pos]
        indent = self._get_indent(line)

        if indent <= 3 and self.THEMATIC_BREAK_PATTERN.match(line.lstrip()):
            block = Block(BlockType.THEMATIC_BREAK, "", indent, self.pos, self.pos)
            self.blocks.append(block)
            self.pos += 1
            return True

        return False

    def _try_fenced_code(self) -> bool:
        """Try to match fenced code block (``` or ~~~)."""
        if self.pos >= len(self.lines):
            return False

        line = self.lines[self.pos]
        indent = self._get_indent(line)

        if indent <= 3:
            match = self.FENCED_CODE_PATTERN.match(line.lstrip())
            if match:
                fence_char = line.lstrip()[0]
                fence_len = len(line.lstrip()) - len(line.lstrip().lstrip(fence_char))
                # Extract language identifier
                lang_line = line.lstrip()[fence_len:].strip()
                language = lang_line.split()[0] if lang_line else None

                # Collect code until closing fence
                code_lines = []
                self.pos += 1
                while self.pos < len(self.lines):
                    current = self.lines[self.pos]
                    current_indent = self._get_indent(current)

                    # Check for closing fence
                    if current_indent <= 3:
                        stripped = current.lstrip()
                        if stripped.startswith(fence_char * fence_len):
                            if all(c == fence_char or c.isspace() for c in stripped):
                                self.pos += 1
                                break

                    code_lines.append(current)
                    self.pos += 1

                code = "\n".join(code_lines)
                block = Block(BlockType.CODE_BLOCK, code, indent, self.pos - len(code_lines) - 1, self.pos - 1)
                block.meta["language"] = language
                block.meta["fenced"] = True
                self.blocks.append(block)
                return True

        return False

    def _try_indented_code(self) -> bool:
        """Try to match indented code block (4+ spaces)."""
        if self.pos >= len(self.lines):
            return False

        line = self.lines[self.pos]
        if not line.startswith("    ") and not line.startswith("\t"):
            return False

        # Previous block must not be paragraph continuation
        code_lines = []
        line_start = self.pos

        while self.pos < len(self.lines):
            line = self.lines[self.pos]
            if line.strip() == "":
                # Blank line is allowed within code block
                code_lines.append("")
                self.pos += 1
            elif line.startswith("    ") or line.startswith("\t"):
                # Remove 4 spaces or 1 tab
                if line.startswith("\t"):
                    code_lines.append(line[1:])
                else:
                    code_lines.append(line[4:])
                self.pos += 1
            else:
                break

        # Remove trailing blank lines
        while code_lines and code_lines[-1] == "":
            code_lines.pop()

        if code_lines:
            code = "\n".join(code_lines)
            block = Block(BlockType.CODE_BLOCK, code, 0, line_start, self.pos - 1)
            block.meta["language"] = None
            block.meta["fenced"] = False
            self.blocks.append(block)
            return True

        return False

    def _try_blockquote(self) -> bool:
        """Try to match blockquote."""
        if self.pos >= len(self.lines):
            return False

        line = self.lines[self.pos]
        if not line.lstrip().startswith(">"):
            return False

        quote_lines = []
        line_start = self.pos

        while self.pos < len(self.lines):
            line = self.lines[self.pos]
            stripped = line.lstrip()
            line_indent = self._get_indent(line)

            if stripped.startswith(">"):
                # Remove '>' and up to 1 space after it
                content = stripped[1:]
                if content.startswith(" "):
                    content = content[1:]
                quote_lines.append(content)
                self.pos += 1
            elif line.strip() == "":
                # Lazy continuation: blank line in blockquote
                quote_lines.append("")
                self.pos += 1
            else:
                # Lazy continuation allowed for paragraph text, but stop if this
                # line clearly starts a different block.
                if line_indent <= 3 and (
                    self.ATX_HEADING_PATTERN.match(stripped)
                    or self.LIST_MARKER_PATTERN.match(stripped)
                    or self.THEMATIC_BREAK_PATTERN.match(stripped)
                    or self.FENCED_CODE_PATTERN.match(stripped)
                    or self.HTML_TAG_PATTERN.match(stripped)
                    or self.LINK_REF_PATTERN.match(line)
                ):
                    break
                quote_lines.append(line)
                self.pos += 1

        content = "\n".join(quote_lines)
        block = Block(BlockType.BLOCKQUOTE, content, 0, line_start, self.pos - 1)
        self.blocks.append(block)
        return True

    def _try_list(self) -> bool:
        """Try to match list (ordered or unordered)."""
        if self.pos >= len(self.lines):
            return False

        line = self.lines[self.pos]
        indent = self._get_indent(line)

        if indent > 3:
            return False

        match = self.LIST_MARKER_PATTERN.match(line.lstrip())
        if not match:
            return False

        list_lines = []
        line_start = self.pos
        is_ordered = line.lstrip()[0].isdigit()

        while self.pos < len(self.lines):
            line = self.lines[self.pos]
            stripped = line.lstrip()
            line_indent = self._get_indent(line)

            if line.strip() == "":
                list_lines.append("")
                self.pos += 1
            elif line_indent <= 3 and self.LIST_MARKER_PATTERN.match(stripped):
                marker_match = self.LIST_MARKER_PATTERN.match(stripped)
                marker = marker_match.group(1)
                # Check marker type matches
                is_ordered_line = marker[0].isdigit()
                if is_ordered_line == is_ordered:
                    list_lines.append(line)
                    self.pos += 1
                else:
                    break
            elif line_indent >= 4 or (line.startswith(" ") and list_lines):
                # Continuation line
                list_lines.append(line)
                self.pos += 1
            else:
                break

        content = "\n".join(list_lines)
        block = Block(BlockType.LIST, content, 0, line_start, self.pos - 1)
        block.meta["ordered"] = is_ordered
        self.blocks.append(block)
        return True

    def _try_html_block(self) -> bool:
        """Try to match HTML block."""
        if self.pos >= len(self.lines):
            return False

        line = self.lines[self.pos]
        indent = self._get_indent(line)

        if indent > 3 or not self.HTML_TAG_PATTERN.match(line.lstrip()):
            return False

        html_lines = [line]
        self.pos += 1

        # Collect until blank line or end
        while self.pos < len(self.lines):
            line = self.lines[self.pos]
            if line.strip() == "":
                break
            html_lines.append(line)
            self.pos += 1

        content = "\n".join(html_lines)
        block = Block(BlockType.HTML_BLOCK, content, 0, self.pos - len(html_lines), self.pos - 1)
        self.blocks.append(block)
        return True

    def _try_link_ref(self) -> bool:
        """Try to match link reference definition."""
        if self.pos >= len(self.lines):
            return False

        line = self.lines[self.pos]
        indent = self._get_indent(line)

        if indent > 3:
            return False

        match = self.LINK_REF_PATTERN.match(line)
        if not match:
            return False

        label = match.group(1)
        url = match.group(2)
        title = match.group(3)

        block = Block(BlockType.LINK_REF, "", 0, self.pos, self.pos)
        block.meta["label"] = label
        block.meta["url"] = url
        block.meta["title"] = title
        self.blocks.append(block)
        self.pos += 1
        return True

    def _try_table(self) -> bool:
        """Try to match GFM table."""
        if self.pos >= len(self.lines) or self.pos + 1 >= len(self.lines):
            return False

        header_line = self.lines[self.pos]
        sep_line = self.lines[self.pos + 1]

        if not self.TABLE_PATTERN.match(header_line) or not self.TABLE_PATTERN.match(sep_line):
            return False

        # Check separator line format (| :?---+:? |)
        sep_cells = [cell.strip() for cell in sep_line.split("|")]
        sep_cells = [c for c in sep_cells if c]  # Remove empty strings

        if not all(self._is_valid_table_sep(cell) for cell in sep_cells):
            return False

        table_lines = []
        line_start = self.pos

        # Collect header
        table_lines.append(header_line)
        self.pos += 1

        # Collect separator
        table_lines.append(sep_line)
        self.pos += 1

        # Collect body rows
        while self.pos < len(self.lines):
            line = self.lines[self.pos]
            if not self.TABLE_PATTERN.match(line) or line.strip() == "":
                break
            table_lines.append(line)
            self.pos += 1

        content = "\n".join(table_lines)
        block = Block(BlockType.TABLE, content, 0, line_start, self.pos - 1)
        self.blocks.append(block)
        return True

    def _is_valid_table_sep(self, cell: str) -> bool:
        """Check if cell is valid table separator."""
        cell = cell.strip()
        if not cell or not all(c in ":-" for c in cell):
            return False
        if "-" not in cell:
            return False
        return True

    def _collect_paragraph(self) -> None:
        """Collect paragraph content."""
        para_lines = []
        line_start = self.pos

        while self.pos < len(self.lines):
            line = self.lines[self.pos]

            if line.strip() == "":
                break

            indent = self._get_indent(line)
            if indent >= 4:
                break

            # Don't continue into block structures
            stripped = line.lstrip()
            if (
                self.ATX_HEADING_PATTERN.match(stripped)
                or stripped.startswith(">")
                or self.LIST_MARKER_PATTERN.match(stripped)
                or stripped.startswith("```")
                or stripped.startswith("~~~")
            ):
                break

            para_lines.append(line)
            self.pos += 1

        if para_lines:
            content = "\n".join(para_lines)
            block = Block(BlockType.PARAGRAPH, content, 0, line_start, self.pos - 1)
            self.blocks.append(block)
