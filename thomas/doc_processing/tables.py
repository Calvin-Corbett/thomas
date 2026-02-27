"""Table processing and analysis.

Detects table structures, parses content, handles merged cells,
and converts between table formats.
"""

import csv
from io import StringIO

from thomas.doc_processing._exceptions import TableError
from thomas.doc_processing._types import Table, TableCell


class TableDetector:
    """Detects tables in documents using cell alignment patterns."""

    @staticmethod
    def is_likely_table(cells: list[TableCell], min_cols: int = 2) -> bool:
        """Check if cells represent a valid table.

        Args:
            cells: List of cells.
            min_cols: Minimum columns required.

        Returns:
            True if cells form a table.
        """
        if not cells or len(cells) < min_cols:
            return False

        # Check alignment in grid
        col_indices = {c.col_index for c in cells}
        row_indices = {c.row_index for c in cells}

        return len(col_indices) >= min_cols and len(row_indices) >= 2


class TableStructureRecognizer:
    """Recognizes table structure from cell positions."""

    @staticmethod
    def recognize(cells: list[TableCell]) -> tuple[int, int]:
        """Recognize table dimensions.

        Args:
            cells: List of cells with row/col indices.

        Returns:
            Tuple of (num_rows, num_cols).
        """
        if not cells:
            return 0, 0

        max_row = max(c.row_index for c in cells)
        max_col = max(c.col_index for c in cells)

        return max_row + 1, max_col + 1

    @staticmethod
    def extract_headers(table: Table) -> list[str]:
        """Extract header row from table.

        Args:
            table: Table object.

        Returns:
            List of header texts.
        """
        header_cells = [c for c in table.cells if c.row_index == 0]
        header_cells.sort(key=lambda c: c.col_index)
        return [c.text for c in header_cells]

    @staticmethod
    def extract_data_rows(table: Table) -> list[list[str]]:
        """Extract data rows from table.

        Args:
            table: Table object.

        Returns:
            List of rows, each a list of cell texts.
        """
        data_rows: list[list[str]] = []

        for row_idx in range(1, table.num_rows):
            row_cells = [c for c in table.cells if c.row_index == row_idx]
            row_cells.sort(key=lambda c: c.col_index)
            row_data = [c.text for c in row_cells]
            data_rows.append(row_data)

        return data_rows


class TableNormalizer:
    """Normalizes table structure (handles merged cells, fills gaps)."""

    @staticmethod
    def normalize(table: Table) -> Table:
        """Normalize table structure.

        Handles merged cells and fills implied values.

        Args:
            table: Input table.

        Returns:
            Normalized table.

        Raises:
            TableError: If normalization fails.
        """
        try:
            normalized_cells: list[TableCell] = []

            for row_idx in range(table.num_rows):
                for col_idx in range(table.num_cols):
                    # Find cell covering this position
                    cell = TableNormalizer._find_cell(table.cells, row_idx, col_idx)

                    if cell:
                        normalized_cells.append(cell)
                    else:
                        # Create empty cell for missing position
                        new_cell = TableCell(
                            text="",
                            row_index=row_idx,
                            col_index=col_idx,
                            row_span=1,
                            col_span=1,
                        )
                        normalized_cells.append(new_cell)

            return Table(
                cells=normalized_cells,
                num_rows=table.num_rows,
                num_cols=table.num_cols,
                caption=table.caption,
                bbox=table.bbox,
                page_number=table.page_number,
            )

        except Exception as e:
            raise TableError(f"Table normalization failed: {e}")

    @staticmethod
    def _find_cell(cells: list[TableCell], row_idx: int, col_idx: int) -> TableCell | None:
        """Find cell covering given position.

        Args:
            cells: List of cells.
            row_idx: Row index.
            col_idx: Column index.

        Returns:
            Cell or None if not found.
        """
        for cell in cells:
            row_range = range(cell.row_index, cell.row_index + cell.row_span)
            col_range = range(cell.col_index, cell.col_index + cell.col_span)

            if row_idx in row_range and col_idx in col_range:
                return cell

        return None


class TableConverter:
    """Converts tables to various formats."""

    @staticmethod
    def to_csv(table: Table) -> str:
        """Convert table to CSV format.

        Args:
            table: Table to convert.

        Returns:
            CSV string.

        Raises:
            TableError: If conversion fails.
        """
        try:
            output = StringIO()
            writer = csv.writer(output)

            # Write header row
            headers = TableStructureRecognizer.extract_headers(table)
            writer.writerow(headers)

            # Write data rows
            data_rows = TableStructureRecognizer.extract_data_rows(table)
            for row in data_rows:
                writer.writerow(row)

            return output.getvalue()

        except Exception as e:
            raise TableError(f"CSV conversion failed: {e}")

    @staticmethod
    def to_html(table: Table) -> str:
        """Convert table to HTML.

        Args:
            table: Table to convert.

        Returns:
            HTML string.
        """
        html_parts: list[str] = ["<table>"]

        # Add caption if present
        if table.caption:
            html_parts.append(f"<caption>{table.caption}</caption>")

        # Add header row
        headers = TableStructureRecognizer.extract_headers(table)
        html_parts.append("<tr>")
        for header in headers:
            html_parts.append(f"<th>{header}</th>")
        html_parts.append("</tr>")

        # Add data rows
        data_rows = TableStructureRecognizer.extract_data_rows(table)
        for row in data_rows:
            html_parts.append("<tr>")
            for cell_text in row:
                html_parts.append(f"<td>{cell_text}</td>")
            html_parts.append("</tr>")

        html_parts.append("</table>")
        return "\n".join(html_parts)

    @staticmethod
    def to_markdown(table: Table) -> str:
        """Convert table to Markdown format.

        Args:
            table: Table to convert.

        Returns:
            Markdown string.
        """
        headers = TableStructureRecognizer.extract_headers(table)
        data_rows = TableStructureRecognizer.extract_data_rows(table)

        lines: list[str] = []

        # Header row
        header_line = "| " + " | ".join(headers) + " |"
        lines.append(header_line)

        # Separator
        separator = "|" + "|".join([" --- " for _ in headers]) + "|"
        lines.append(separator)

        # Data rows
        for row in data_rows:
            row_line = "| " + " | ".join(row) + " |"
            lines.append(row_line)

        return "\n".join(lines)

    @staticmethod
    def to_dict_list(table: Table) -> list[dict[str, str]]:
        """Convert table to list of dictionaries.

        Args:
            table: Table to convert.

        Returns:
            List of dictionaries (header keys, row values).
        """
        headers = TableStructureRecognizer.extract_headers(table)
        data_rows = TableStructureRecognizer.extract_data_rows(table)

        result: list[dict[str, str]] = []
        for row in data_rows:
            row_dict: dict[str, str] = {}
            for i, header in enumerate(headers):
                value = row[i] if i < len(row) else ""
                row_dict[header] = value
            result.append(row_dict)

        return result


class TableComparator:
    """Compares and diffs tables."""

    @staticmethod
    def diff(table1: Table, table2: Table) -> dict[str, any]:
        """Compare two tables and return differences.

        Args:
            table1: First table.
            table2: Second table.

        Returns:
            Dictionary with differences (added, removed, modified rows).
        """
        dict1 = TableConverter.to_dict_list(table1)
        dict2 = TableConverter.to_dict_list(table2)

        added: list[dict[str, str]] = []
        removed: list[dict[str, str]] = []
        modified: list[tuple[dict[str, str], dict[str, str]]] = []

        # Find removed rows
        for row in dict1:
            if row not in dict2:
                removed.append(row)

        # Find added rows
        for row in dict2:
            if row not in dict1:
                added.append(row)

        # Find modified rows (same primary key, different values)
        if dict1 and dict2:
            first_key = list(dict1[0].keys())[0]
            for row1 in dict1:
                for row2 in dict2:
                    if row1.get(first_key) == row2.get(first_key) and row1 != row2:
                        modified.append((row1, row2))

        return {
            "added": added,
            "removed": removed,
            "modified": modified,
            "structure_changed": (table1.num_rows != table2.num_rows or table1.num_cols != table2.num_cols),
        }

    @staticmethod
    def similarity(table1: Table, table2: Table) -> float:
        """Calculate similarity between two tables (0-1).

        Args:
            table1: First table.
            table2: Second table.

        Returns:
            Similarity score.
        """
        diff = TableComparator.diff(table1, table2)

        dict1 = TableConverter.to_dict_list(table1)
        dict2 = TableConverter.to_dict_list(table2)

        if not dict1 or not dict2:
            return 1.0 if dict1 == dict2 else 0.0

        total_rows = max(len(dict1), len(dict2))
        matching_rows = len(dict1) + len(dict2) - len(diff["added"]) - len(diff["removed"])

        return matching_rows / (total_rows * 2)


class CrossTableReferencer:
    """Manages references between tables in a document."""

    def __init__(self) -> None:
        """Initialize referencer."""
        self.table_index: dict[str, Table] = {}

    def register_table(self, table_id: str, table: Table) -> None:
        """Register a table for reference.

        Args:
            table_id: Unique table identifier.
            table: Table object.
        """
        self.table_index[table_id] = table

    def get_table(self, table_id: str) -> Table | None:
        """Get table by ID.

        Args:
            table_id: Table identifier.

        Returns:
            Table or None if not found.
        """
        return self.table_index.get(table_id)

    def find_related_tables(self, table: Table, threshold: float = 0.7) -> list[tuple[str, float]]:
        """Find tables similar to given table.

        Args:
            table: Reference table.
            threshold: Similarity threshold.

        Returns:
            List of (table_id, similarity) tuples.
        """
        related: list[tuple[str, float]] = []

        for table_id, other_table in self.table_index.items():
            similarity = TableComparator.similarity(table, other_table)
            if similarity >= threshold:
                related.append((table_id, similarity))

        related.sort(key=lambda x: x[1], reverse=True)
        return related
