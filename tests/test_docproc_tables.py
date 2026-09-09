"""Tests for table processing module."""

from thomas.marketplace.doc_processing._types import Table, TableCell
from thomas.marketplace.doc_processing.tables import (
    CrossTableReferencer,
    TableComparator,
    TableConverter,
    TableDetector,
    TableNormalizer,
    TableStructureRecognizer,
)


class TestTableDetector:
    """Test table detection."""

    def test_is_likely_table(self) -> None:
        """Test table validation."""
        cells = [
            TableCell(text="A", row_index=0, col_index=0),
            TableCell(text="B", row_index=0, col_index=1),
            TableCell(text="C", row_index=1, col_index=0),
            TableCell(text="D", row_index=1, col_index=1),
        ]

        assert TableDetector.is_likely_table(cells)

    def test_invalid_table(self) -> None:
        """Test invalid table detection."""
        cells = [
            TableCell(text="A", row_index=0, col_index=0),
        ]

        assert not TableDetector.is_likely_table(cells)


class TestTableStructureRecognizer:
    """Test table structure recognition."""

    def test_recognize_dimensions(self) -> None:
        """Test dimension recognition."""
        cells = [
            TableCell(text="A", row_index=0, col_index=0),
            TableCell(text="B", row_index=0, col_index=1),
            TableCell(text="C", row_index=1, col_index=0),
            TableCell(text="D", row_index=1, col_index=1),
        ]

        rows, cols = TableStructureRecognizer.recognize(cells)

        assert rows == 2
        assert cols == 2

    def test_extract_headers(self) -> None:
        """Test header extraction."""
        cells = [
            TableCell(text="Name", row_index=0, col_index=0, is_header=True),
            TableCell(text="Age", row_index=0, col_index=1, is_header=True),
            TableCell(text="Alice", row_index=1, col_index=0),
            TableCell(text="30", row_index=1, col_index=1),
        ]
        table = Table(cells=cells, num_rows=2, num_cols=2)

        headers = TableStructureRecognizer.extract_headers(table)

        assert len(headers) == 2
        assert "Name" in headers

    def test_extract_data_rows(self) -> None:
        """Test data row extraction."""
        cells = [
            TableCell(text="Name", row_index=0, col_index=0, is_header=True),
            TableCell(text="Age", row_index=0, col_index=1, is_header=True),
            TableCell(text="Alice", row_index=1, col_index=0),
            TableCell(text="30", row_index=1, col_index=1),
            TableCell(text="Bob", row_index=2, col_index=0),
            TableCell(text="25", row_index=2, col_index=1),
        ]
        table = Table(cells=cells, num_rows=3, num_cols=2)

        data_rows = TableStructureRecognizer.extract_data_rows(table)

        assert len(data_rows) == 2


class TestTableNormalizer:
    """Test table normalization."""

    def test_normalize_table(self) -> None:
        """Test table normalization."""
        cells = [
            TableCell(text="A", row_index=0, col_index=0),
            TableCell(text="B", row_index=0, col_index=1),
            TableCell(text="C", row_index=1, col_index=0),
        ]
        table = Table(cells=cells, num_rows=2, num_cols=2)

        normalized = TableNormalizer.normalize(table)

        assert normalized.num_rows == 2
        assert normalized.num_cols == 2
        assert len(normalized.cells) >= 4  # Should fill gaps


class TestTableConverter:
    """Test table format conversion."""

    def test_to_csv(self) -> None:
        """Test CSV conversion."""
        cells = [
            TableCell(text="Name", row_index=0, col_index=0, is_header=True),
            TableCell(text="Age", row_index=0, col_index=1, is_header=True),
            TableCell(text="Alice", row_index=1, col_index=0),
            TableCell(text="30", row_index=1, col_index=1),
        ]
        table = Table(cells=cells, num_rows=2, num_cols=2)

        csv = TableConverter.to_csv(table)

        assert "Name" in csv
        assert "Alice" in csv

    def test_to_html(self) -> None:
        """Test HTML conversion."""
        cells = [
            TableCell(text="A", row_index=0, col_index=0),
            TableCell(text="B", row_index=0, col_index=1),
            TableCell(text="C", row_index=1, col_index=0),
            TableCell(text="D", row_index=1, col_index=1),
        ]
        table = Table(cells=cells, num_rows=2, num_cols=2)

        html = TableConverter.to_html(table)

        assert "<table>" in html
        assert "<tr>" in html
        assert "A" in html

    def test_to_markdown(self) -> None:
        """Test Markdown conversion."""
        cells = [
            TableCell(text="A", row_index=0, col_index=0, is_header=True),
            TableCell(text="B", row_index=0, col_index=1, is_header=True),
            TableCell(text="C", row_index=1, col_index=0),
            TableCell(text="D", row_index=1, col_index=1),
        ]
        table = Table(cells=cells, num_rows=2, num_cols=2)

        markdown = TableConverter.to_markdown(table)

        assert "|" in markdown
        assert "---" in markdown

    def test_to_dict_list(self) -> None:
        """Test dictionary list conversion."""
        cells = [
            TableCell(text="Name", row_index=0, col_index=0, is_header=True),
            TableCell(text="Age", row_index=0, col_index=1, is_header=True),
            TableCell(text="Alice", row_index=1, col_index=0),
            TableCell(text="30", row_index=1, col_index=1),
        ]
        table = Table(cells=cells, num_rows=2, num_cols=2)

        dicts = TableConverter.to_dict_list(table)

        assert len(dicts) == 1
        assert dicts[0]["Name"] == "Alice"


class TestTableComparator:
    """Test table comparison."""

    def test_diff_identical(self) -> None:
        """Test diff of identical tables."""
        cells = [
            TableCell(text="A", row_index=0, col_index=0),
            TableCell(text="B", row_index=0, col_index=1),
            TableCell(text="C", row_index=1, col_index=0),
            TableCell(text="D", row_index=1, col_index=1),
        ]
        table1 = Table(cells=cells, num_rows=2, num_cols=2)
        table2 = Table(cells=cells, num_rows=2, num_cols=2)

        diff = TableComparator.diff(table1, table2)

        assert len(diff["added"]) == 0
        assert len(diff["removed"]) == 0

    def test_similarity_identical(self) -> None:
        """Test similarity of identical tables."""
        cells = [
            TableCell(text="A", row_index=0, col_index=0),
            TableCell(text="B", row_index=0, col_index=1),
            TableCell(text="C", row_index=1, col_index=0),
            TableCell(text="D", row_index=1, col_index=1),
        ]
        table1 = Table(cells=cells, num_rows=2, num_cols=2)
        table2 = Table(cells=cells, num_rows=2, num_cols=2)

        similarity = TableComparator.similarity(table1, table2)

        assert similarity >= 0.9  # Very similar


class TestCrossTableReferencer:
    """Test cross-table references."""

    def test_register_and_retrieve(self) -> None:
        """Test table registration and retrieval."""
        cells = [
            TableCell(text="A", row_index=0, col_index=0),
            TableCell(text="B", row_index=0, col_index=1),
        ]
        table = Table(cells=cells, num_rows=1, num_cols=2)

        referencer = CrossTableReferencer()
        referencer.register_table("table1", table)

        retrieved = referencer.get_table("table1")

        assert retrieved is not None
        assert retrieved.num_cols == 2

    def test_find_related_tables(self) -> None:
        """Test finding related tables."""
        cells1 = [
            TableCell(text="A", row_index=0, col_index=0),
            TableCell(text="B", row_index=0, col_index=1),
            TableCell(text="C", row_index=1, col_index=0),
            TableCell(text="D", row_index=1, col_index=1),
        ]
        table1 = Table(cells=cells1, num_rows=2, num_cols=2)

        cells2 = [
            TableCell(text="A", row_index=0, col_index=0),
            TableCell(text="B", row_index=0, col_index=1),
            TableCell(text="E", row_index=1, col_index=0),
            TableCell(text="F", row_index=1, col_index=1),
        ]
        table2 = Table(cells=cells2, num_rows=2, num_cols=2)

        referencer = CrossTableReferencer()
        referencer.register_table("table1", table1)
        referencer.register_table("table2", table2)

        related = referencer.find_related_tables(table1, threshold=0.5)

        assert isinstance(related, list)
