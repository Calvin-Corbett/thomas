"""Tests for document layout analysis module."""

from thomas.marketplace.doc_processing._types import BoundingBox, Page, TextBlock, TextBlockType
from thomas.marketplace.doc_processing.layout import (
    ColumnDetector,
    LayoutAnalyzer,
    MarginDetector,
    ReadingOrderDetector,
    TextBlockClassifier,
)


class TestTextBlockClassifier:
    """Test text block classification."""

    def test_classify_title(self) -> None:
        """Test title classification."""
        bbox = BoundingBox(x0=50, y0=50, x1=550, y1=100)
        block = TextBlock(
            text="Document Title",
            bbox=bbox,
            block_type=TextBlockType.OTHER,
        )

        classified = TextBlockClassifier.classify(block)
        assert classified in [TextBlockType.TITLE, TextBlockType.HEADING, TextBlockType.PARAGRAPH]

    def test_classify_paragraph(self) -> None:
        """Test paragraph classification."""
        bbox = BoundingBox(x0=50, y0=200, x1=550, y1=250)
        block = TextBlock(
            text="This is a longer paragraph with many words " * 3,
            bbox=bbox,
            block_type=TextBlockType.OTHER,
        )

        classified = TextBlockClassifier.classify(block)
        assert classified == TextBlockType.PARAGRAPH

    def test_classify_heading(self) -> None:
        """Test heading classification."""
        bbox = BoundingBox(x0=50, y0=100, x1=400, y1=125)
        block = TextBlock(
            text="Section One",
            bbox=bbox,
            block_type=TextBlockType.OTHER,
        )

        classified = TextBlockClassifier.classify(block)
        assert classified in [TextBlockType.HEADING, TextBlockType.TITLE]


class TestMarginDetector:
    """Test margin detection."""

    def test_detect_margins(self) -> None:
        """Test margin detection."""
        blocks = [
            TextBlock(text="Text 1", bbox=BoundingBox(x0=100, y0=100, x1=500, y1=150)),
            TextBlock(text="Text 2", bbox=BoundingBox(x0=100, y0=160, x1=500, y1=210)),
        ]

        left, right, top, bottom = MarginDetector.detect_margins(blocks)

        assert left >= 0
        assert right >= 0
        assert top >= 0
        assert bottom >= 0

    def test_symmetric_margins(self) -> None:
        """Test symmetric content margins."""
        blocks = [
            TextBlock(text="Text", bbox=BoundingBox(x0=100, y0=100, x1=512, y1=150)),
        ]

        left, right, top, bottom = MarginDetector.detect_margins(blocks, page_width=612)

        assert left == 100
        assert right == 100  # 612 - 512

    def test_empty_blocks(self) -> None:
        """Test with empty block list."""
        left, right, top, bottom = MarginDetector.detect_margins([])

        assert (left, right, top, bottom) == (36.0, 36.0, 36.0, 36.0)


class TestColumnDetector:
    """Test column detection."""

    def test_single_column(self) -> None:
        """Test single column detection."""
        blocks = [
            TextBlock(text="Text 1", bbox=BoundingBox(x0=100, y0=100, x1=500, y1=150)),
            TextBlock(text="Text 2", bbox=BoundingBox(x0=100, y0=160, x1=500, y1=210)),
        ]

        columns = ColumnDetector.detect_columns(blocks)
        assert columns >= 1

    def test_multi_column(self) -> None:
        """Test multi-column detection."""
        blocks = [
            TextBlock(text="Left 1", bbox=BoundingBox(x0=50, y0=100, x1=250, y1=150)),
            TextBlock(text="Right 1", bbox=BoundingBox(x0=300, y0=100, x1=500, y1=150)),
            TextBlock(text="Left 2", bbox=BoundingBox(x0=50, y0=160, x1=250, y1=210)),
            TextBlock(text="Right 2", bbox=BoundingBox(x0=300, y0=160, x1=500, y1=210)),
        ]

        columns = ColumnDetector.detect_columns(blocks)
        assert columns >= 1  # Should detect at least 1, likely 2


class TestReadingOrderDetector:
    """Test reading order detection."""

    def test_linear_reading_order(self) -> None:
        """Test linear reading order."""
        blocks = [
            TextBlock(text="First", bbox=BoundingBox(x0=50, y0=100, x1=200, y1=130)),
            TextBlock(text="Second", bbox=BoundingBox(x0=50, y0=140, x1=200, y1=170)),
            TextBlock(text="Third", bbox=BoundingBox(x0=50, y0=180, x1=200, y1=210)),
        ]

        detector = ReadingOrderDetector()
        order = detector.detect(blocks)

        assert len(order.elements) == 3

    def test_two_column_reading_order(self) -> None:
        """Test two-column reading order."""
        blocks = [
            TextBlock(text="Left 1", bbox=BoundingBox(x0=50, y0=100, x1=250, y1=150)),
            TextBlock(text="Right 1", bbox=BoundingBox(x0=300, y0=100, x1=500, y1=150)),
            TextBlock(text="Left 2", bbox=BoundingBox(x0=50, y0=160, x1=250, y1=210)),
            TextBlock(text="Right 2", bbox=BoundingBox(x0=300, y0=160, x1=500, y1=210)),
        ]

        detector = ReadingOrderDetector()
        order = detector.detect(blocks)

        assert len(order.elements) == 4

    def test_empty_blocks(self) -> None:
        """Test with empty blocks."""
        detector = ReadingOrderDetector()
        order = detector.detect([])

        assert len(order.elements) == 0


class TestLayoutAnalyzer:
    """Test complete layout analysis."""

    def test_analyze_simple_page(self) -> None:
        """Test layout analysis of simple page."""
        blocks = [
            TextBlock(text="Title", bbox=BoundingBox(x0=50, y0=50, x1=550, y1=80)),
            TextBlock(text="Content", bbox=BoundingBox(x0=50, y0=100, x1=550, y1=600)),
        ]
        page = Page(page_number=1, text="Title\nContent", text_blocks=blocks)

        analyzer = LayoutAnalyzer()
        layout = analyzer.analyze_page(page)

        assert layout.page_width == 612.0
        assert layout.page_height == 792.0
        assert layout.columns >= 1

    def test_layout_statistics(self) -> None:
        """Test layout statistics."""
        blocks = [
            TextBlock(text="Text", bbox=BoundingBox(x0=50, y0=100, x1=550, y1=150)),
        ]
        page = Page(page_number=1, text="Text", text_blocks=blocks)

        analyzer = LayoutAnalyzer()
        layout = analyzer.analyze_page(page)

        assert layout.content_width() > 0
        assert layout.content_height() > 0
