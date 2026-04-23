"""
Tests for Markdown lexer (block-level tokenization).
"""

from thomas.marketplace.markdown.lexer import BlockType, Lexer


class TestHeadings:
    """Test heading parsing."""

    def test_atx_heading_h1(self) -> None:
        """Test ATX-style h1 heading."""
        lexer = Lexer("# Hello World")
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].type == BlockType.HEADING
        assert blocks[0].meta["level"] == 1
        assert blocks[0].content == "Hello World"

    def test_atx_heading_h6(self) -> None:
        """Test ATX-style h6 heading."""
        lexer = Lexer("###### Deep Heading")
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].meta["level"] == 6

    def test_atx_heading_no_space(self) -> None:
        """Test ATX heading without space after hashes."""
        lexer = Lexer("#Heading")
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].meta["level"] == 1

    def test_setext_heading_underline_equals(self) -> None:
        """Test setext heading with = underline."""
        lexer = Lexer("Hello\n=====")
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].type == BlockType.HEADING
        assert blocks[0].meta["level"] == 1

    def test_setext_heading_underline_dashes(self) -> None:
        """Test setext heading with - underline."""
        lexer = Lexer("Hello\n-----")
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].meta["level"] == 2

    def test_multiple_headings(self) -> None:
        """Test multiple headings."""
        lexer = Lexer("# H1\n\n## H2\n\n### H3")
        blocks = lexer.lex()
        assert len(blocks) == 3
        assert blocks[0].meta["level"] == 1
        assert blocks[1].meta["level"] == 2
        assert blocks[2].meta["level"] == 3


class TestCodeBlocks:
    """Test code block parsing."""

    def test_fenced_code_backticks(self) -> None:
        """Test fenced code with backticks."""
        source = "```python\nprint('hello')\n```"
        lexer = Lexer(source)
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].type == BlockType.CODE_BLOCK
        assert blocks[0].meta["language"] == "python"
        assert "print('hello')" in blocks[0].content

    def test_fenced_code_tildes(self) -> None:
        """Test fenced code with tildes."""
        source = "~~~javascript\nvar x = 1;\n~~~"
        lexer = Lexer(source)
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].meta["language"] == "javascript"

    def test_fenced_code_no_language(self) -> None:
        """Test fenced code without language tag."""
        source = "```\ncode here\n```"
        lexer = Lexer(source)
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].meta["language"] is None

    def test_indented_code_block(self) -> None:
        """Test indented code block (4 spaces)."""
        source = "    code line 1\n    code line 2"
        lexer = Lexer(source)
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].type == BlockType.CODE_BLOCK
        assert blocks[0].meta["fenced"] is False

    def test_indented_code_with_blank_line(self) -> None:
        """Test indented code with blank line in middle."""
        source = "    line 1\n\n    line 2"
        lexer = Lexer(source)
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert "line 1" in blocks[0].content
        assert "line 2" in blocks[0].content


class TestLists:
    """Test list parsing."""

    def test_unordered_list_dash(self) -> None:
        """Test unordered list with dashes."""
        source = "- item 1\n- item 2"
        lexer = Lexer(source)
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].type == BlockType.LIST
        assert blocks[0].meta["ordered"] is False

    def test_unordered_list_asterisk(self) -> None:
        """Test unordered list with asterisks."""
        source = "* item 1\n* item 2"
        lexer = Lexer(source)
        blocks = lexer.lex()
        assert len(blocks) == 1

    def test_ordered_list(self) -> None:
        """Test ordered list."""
        source = "1. first\n2. second\n3. third"
        lexer = Lexer(source)
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].meta["ordered"] is True

    def test_list_with_multiline_items(self) -> None:
        """Test list with continuation lines."""
        source = "- item 1\n  continuation\n- item 2"
        lexer = Lexer(source)
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert "item 1" in blocks[0].content
        assert "continuation" in blocks[0].content


class TestBlockQuotes:
    """Test blockquote parsing."""

    def test_blockquote_single_line(self) -> None:
        """Test single-line blockquote."""
        lexer = Lexer("> A quote")
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].type == BlockType.BLOCKQUOTE
        assert "A quote" in blocks[0].content

    def test_blockquote_multiline(self) -> None:
        """Test multi-line blockquote."""
        source = "> line 1\n> line 2\n> line 3"
        lexer = Lexer(source)
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].type == BlockType.BLOCKQUOTE

    def test_blockquote_lazy_continuation(self) -> None:
        """Test blockquote with lazy continuation."""
        source = "> quote\nlazy line"
        lexer = Lexer(source)
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].type == BlockType.BLOCKQUOTE

    def test_nested_blockquotes(self) -> None:
        """Test nested blockquotes."""
        source = "> outer\n> > inner"
        lexer = Lexer(source)
        blocks = lexer.lex()
        assert len(blocks) == 1


class TestThematicBreaks:
    """Test thematic break parsing."""

    def test_thematic_break_dashes(self) -> None:
        """Test thematic break with dashes."""
        lexer = Lexer("---")
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].type == BlockType.THEMATIC_BREAK

    def test_thematic_break_asterisks(self) -> None:
        """Test thematic break with asterisks."""
        lexer = Lexer("***")
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].type == BlockType.THEMATIC_BREAK

    def test_thematic_break_underscores(self) -> None:
        """Test thematic break with underscores."""
        lexer = Lexer("___")
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].type == BlockType.THEMATIC_BREAK

    def test_thematic_break_with_spaces(self) -> None:
        """Test thematic break with spaces between markers."""
        lexer = Lexer("- - - - -")
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].type == BlockType.THEMATIC_BREAK


class TestTables:
    """Test table parsing."""

    def test_simple_table(self) -> None:
        """Test simple GFM table."""
        source = "| h1 | h2 |\n|----|----|"
        lexer = Lexer(source)
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].type == BlockType.TABLE

    def test_table_with_alignment(self) -> None:
        """Test table with column alignment."""
        source = "| Left | Center | Right |\n|:----:|:----:|----:|"
        lexer = Lexer(source)
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].type == BlockType.TABLE

    def test_table_with_body_rows(self) -> None:
        """Test table with body rows."""
        source = "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"
        lexer = Lexer(source)
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].type == BlockType.TABLE


class TestParagraphs:
    """Test paragraph parsing."""

    def test_simple_paragraph(self) -> None:
        """Test simple paragraph."""
        lexer = Lexer("This is a paragraph.")
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].type == BlockType.PARAGRAPH

    def test_multiline_paragraph(self) -> None:
        """Test multi-line paragraph."""
        source = "Line 1\nLine 2\nLine 3"
        lexer = Lexer(source)
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].type == BlockType.PARAGRAPH

    def test_paragraph_separated_by_blank_line(self) -> None:
        """Test paragraphs separated by blank line."""
        source = "Para 1\n\nPara 2"
        lexer = Lexer(source)
        blocks = lexer.lex()
        assert len(blocks) == 2
        assert all(b.type == BlockType.PARAGRAPH for b in blocks)


class TestLinkReferences:
    """Test link reference definition parsing."""

    def test_link_reference_simple(self) -> None:
        """Test simple link reference."""
        lexer = Lexer("[ref]: https://example.com")
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].type == BlockType.LINK_REF
        assert blocks[0].meta["label"] == "ref"
        assert blocks[0].meta["url"] == "https://example.com"

    def test_link_reference_with_title(self) -> None:
        """Test link reference with title."""
        lexer = Lexer('[ref]: https://example.com "Example"')
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].meta["title"] == "Example"

    def test_link_reference_with_angle_brackets(self) -> None:
        """Test link reference with angle brackets."""
        lexer = Lexer("[ref]: <https://example.com>")
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].meta["url"] == "https://example.com"


class TestMixedContent:
    """Test parsing mixed content types."""

    def test_heading_paragraph_code(self) -> None:
        """Test document with heading, paragraph, and code."""
        source = "# Title\n\nParagraph text.\n\n```\ncode\n```"
        lexer = Lexer(source)
        blocks = lexer.lex()
        assert len(blocks) == 3
        assert blocks[0].type == BlockType.HEADING
        assert blocks[1].type == BlockType.PARAGRAPH
        assert blocks[2].type == BlockType.CODE_BLOCK

    def test_blockquote_with_nested_blocks(self) -> None:
        """Test blockquote containing multiple blocks."""
        source = "> # Title\n> \n> Paragraph"
        lexer = Lexer(source)
        blocks = lexer.lex()
        assert len(blocks) == 1
        assert blocks[0].type == BlockType.BLOCKQUOTE

    def test_complex_document(self) -> None:
        """Test complex document structure."""
        source = """# Main Title

Introductory paragraph.

## Section 1

- List item 1
- List item 2

## Section 2

```python
code here
```

> A blockquote

Final paragraph.
"""
        lexer = Lexer(source)
        blocks = lexer.lex()
        assert len(blocks) > 0
        # Should have multiple block types
        types = {b.type for b in blocks}
        assert BlockType.HEADING in types
        assert BlockType.PARAGRAPH in types
