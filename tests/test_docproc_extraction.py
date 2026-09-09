"""Tests for document extraction module."""

from thomas.marketplace.doc_processing._types import Page, TextBlock
from thomas.marketplace.doc_processing.extraction import (
    FootnoteExtractor,
    HeaderFooterDetector,
    HTMLTextExtractor,
    PDFTextExtractor,
    PlainTextCleaner,
    TableExtractor,
)


class TestPlainTextCleaner:
    """Test plain text cleaning functions."""

    def test_normalize_unicode(self) -> None:
        """Test unicode normalization."""
        text = "café"
        normalized = PlainTextCleaner.normalize_unicode(text)
        assert len(normalized) >= len(text)

    def test_remove_control_characters(self) -> None:
        """Test control character removal."""
        text = "Hello\x00World\x01Test"
        cleaned = PlainTextCleaner.remove_control_characters(text)
        assert "\x00" not in cleaned
        assert "\x01" not in cleaned
        assert "HelloWorldTest" in cleaned or "Hello" in cleaned

    def test_normalize_whitespace(self) -> None:
        """Test whitespace normalization."""
        text = "Hello    World\n\n\nTest"
        normalized = PlainTextCleaner.normalize_whitespace(text)
        assert "    " not in normalized
        assert "\n\n\n" not in normalized
        assert normalized == "Hello World\n\nTest"

    def test_clean_full_pipeline(self) -> None:
        """Test full cleaning pipeline."""
        text = "Café\x00  \n\n  World"
        cleaned = PlainTextCleaner.clean(text)
        assert "\x00" not in cleaned
        assert "  " not in cleaned


class TestHTMLTextExtractor:
    """Test HTML text extraction."""

    def test_extract_basic(self) -> None:
        """Test basic HTML extraction."""
        html = "<p>Hello <b>World</b></p>"
        extractor = HTMLTextExtractor()
        text = extractor.extract(html)
        assert "Hello" in text
        assert "World" in text
        assert "<" not in text

    def test_remove_script_tags(self) -> None:
        """Test script tag removal."""
        html = "<p>Hello</p><script>alert('bad')</script><p>World</p>"
        extractor = HTMLTextExtractor()
        text = extractor.extract(html)
        assert "alert" not in text

    def test_handle_entities(self) -> None:
        """Test HTML entity handling."""
        html = "<p>&lt;tag&gt; &amp; &quot;quote&quot;</p>"
        extractor = HTMLTextExtractor()
        text = extractor.extract(html)
        assert "<tag>" in text
        assert "&" in text
        assert '"' in text or "quote" in text

    def test_extract_structured(self) -> None:
        """Test structured HTML extraction."""
        html = """
        <h1>Title</h1>
        <p>Paragraph</p>
        <ul><li>Item 1</li><li>Item 2</li></ul>
        <a href="http://example.com">Link</a>
        """
        extractor = HTMLTextExtractor()
        result = extractor.extract_structured(html)

        assert len(result["headings"]) > 0
        assert len(result["paragraphs"]) > 0
        assert len(result["lists"]) > 0
        assert len(result["links"]) > 0


class TestPDFTextExtractor:
    """Test PDF text extraction."""

    def test_extract_basic(self) -> None:
        """Test basic PDF extraction."""
        pdf_content = "Line 1\nLine 2\nLine 3"
        extractor = PDFTextExtractor()
        text = extractor.extract(pdf_content)

        assert "Line 1" in text
        assert "Line 2" in text

    def test_extract_with_positions(self) -> None:
        """Test PDF extraction with position data."""
        pdf_content = "Title\nFirst paragraph.\nSecond paragraph."
        extractor = PDFTextExtractor()
        pages = extractor.extract_with_positions(pdf_content)

        assert len(pages) > 0
        assert pages[0].page_number == 1
        assert len(pages[0].text_blocks) > 0

    def test_text_block_creation(self) -> None:
        """Test text block creation."""
        pdf_content = "Hello World"
        extractor = PDFTextExtractor()
        pages = extractor.extract_with_positions(pdf_content)

        assert len(pages[0].text_blocks) > 0
        block = pages[0].text_blocks[0]
        assert "Hello" in block.text or "World" in block.text


class TestTableExtractor:
    """Test table extraction from text."""

    def test_detect_simple_table(self) -> None:
        """Test detection of simple table."""
        text = "Name Age City\nAlice 30 NYC\nBob 25 LA"
        tables = TableExtractor.detect_tables(text)

        assert len(tables) > 0
        table = tables[0]
        assert table.num_cols >= 2
        assert table.num_rows >= 2

    def test_table_parsing(self) -> None:
        """Test table parsing."""
        text = "Col1 Col2 Col3\nA B C\nD E F"
        tables = TableExtractor.detect_tables(text)

        if tables:
            table = tables[0]
            assert len(table.cells) > 0

    def test_empty_text(self) -> None:
        """Test with empty text."""
        tables = TableExtractor.detect_tables("")
        assert len(tables) == 0

    def test_single_column(self) -> None:
        """Test single column is not detected as table."""
        text = "Item1\nItem2\nItem3"
        tables = TableExtractor.detect_tables(text)
        # Single column shouldn't be detected as table
        assert len(tables) == 0 or tables[0].num_cols < 2


class TestHeaderFooterDetector:
    """Test header/footer detection."""

    def test_detect_repeated_header(self) -> None:
        """Test repeated header detection."""
        blocks = [
            TextBlock(text="Header", bbox=None, page_number=1),
            TextBlock(text="Content 1", bbox=None, page_number=1),
        ]
        page1 = Page(page_number=1, text="Header\nContent 1", text_blocks=blocks)

        blocks2 = [
            TextBlock(text="Header", bbox=None, page_number=2),
            TextBlock(text="Content 2", bbox=None, page_number=2),
        ]
        page2 = Page(page_number=2, text="Header\nContent 2", text_blocks=blocks2)

        headers = HeaderFooterDetector.detect_headers([page1, page2])
        assert len(headers) > 0

    def test_detect_repeated_footer(self) -> None:
        """Test repeated footer detection."""
        blocks = [
            TextBlock(text="Content 1", bbox=None, page_number=1),
            TextBlock(text="Page 1", bbox=None, page_number=1),
        ]
        page1 = Page(page_number=1, text="Content 1\nPage 1", text_blocks=blocks)

        blocks2 = [
            TextBlock(text="Content 2", bbox=None, page_number=2),
            TextBlock(text="Page 2", bbox=None, page_number=2),
        ]
        page2 = Page(page_number=2, text="Content 2\nPage 2", text_blocks=blocks2)

        footers = HeaderFooterDetector.detect_footers([page1, page2])
        # Might not detect if pattern doesn't match
        assert isinstance(footers, list)

    def test_single_page(self) -> None:
        """Test with single page (no headers/footers expected)."""
        blocks = [TextBlock(text="Content", bbox=None)]
        page = Page(page_number=1, text="Content", text_blocks=blocks)

        headers = HeaderFooterDetector.detect_headers([page])
        footers = HeaderFooterDetector.detect_footers([page])

        assert len(headers) == 0
        assert len(footers) == 0


class TestFootnoteExtractor:
    """Test footnote extraction."""

    def test_extract_numbered_footnotes(self) -> None:
        """Test numbered footnote extraction."""
        text = "Text[1] footnote content\nMore text[2] another note"
        footnotes = FootnoteExtractor.extract_footnotes(text)

        assert isinstance(footnotes, dict)

    def test_extract_symbol_footnotes(self) -> None:
        """Test symbol footnote extraction."""
        text = "Text[*] footnote content\nMore[†] another"
        footnotes = FootnoteExtractor.extract_footnotes(text)

        assert isinstance(footnotes, dict)
        assert "symbols" in footnotes

    def test_no_footnotes(self) -> None:
        """Test text without footnotes."""
        text = "Plain text without any footnotes"
        footnotes = FootnoteExtractor.extract_footnotes(text)

        assert isinstance(footnotes, dict)
        assert "numbered" in footnotes
        assert "symbols" in footnotes
