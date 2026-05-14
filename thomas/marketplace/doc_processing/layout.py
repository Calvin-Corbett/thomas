"""Document layout analysis and page segmentation.

Analyzes page structure, reading order, columns, margins, and
text block classification using projection profiling and XY-cut.
"""

from thomas.marketplace.doc_processing._exceptions import LayoutError
from thomas.marketplace.doc_processing._types import (
    Layout,
    Page,
    ReadingOrder,
    TextBlock,
    TextBlockType,
)


class ConnectedComponentAnalyzer:
    """Analyzes connected components of text blocks for page segmentation."""

    def __init__(self, page_width: float = 612.0, page_height: float = 792.0):
        """Initialize analyzer.

        Args:
            page_width: Page width in points.
            page_height: Page height in points.
        """
        self.page_width = page_width
        self.page_height = page_height

    def segment(self, text_blocks: list[TextBlock]) -> list[list[TextBlock]]:
        """Segment text blocks into connected components.

        Args:
            text_blocks: List of text blocks.

        Returns:
            List of connected component groups.
        """
        if not text_blocks:
            return []

        visited: set[int] = set()
        components: list[list[TextBlock]] = []

        for i, block in enumerate(text_blocks):
            if i not in visited:
                component = self._bfs(text_blocks, i, visited)
                components.append(component)

        return components

    def _bfs(self, blocks: list[TextBlock], start_idx: int, visited: set[int]) -> list[TextBlock]:
        """Breadth-first search to find connected component.

        Args:
            blocks: All blocks.
            start_idx: Starting block index.
            visited: Set of visited indices.

        Returns:
            Blocks in this component.
        """
        component: list[TextBlock] = []
        queue: list[int] = [start_idx]
        visited.add(start_idx)

        while queue:
            idx = queue.pop(0)
            component.append(blocks[idx])

            # Find neighbors (overlapping or adjacent blocks)
            for j, other_block in enumerate(blocks):
                if j not in visited and self._are_adjacent(blocks[idx], other_block):
                    visited.add(j)
                    queue.append(j)

        return component

    @staticmethod
    def _are_adjacent(block1: TextBlock, block2: TextBlock) -> bool:
        """Check if two blocks are adjacent or overlapping.

        Args:
            block1: First block.
            block2: Second block.

        Returns:
            True if blocks are adjacent.
        """
        bbox1 = block1.bbox
        bbox2 = block2.bbox

        # Check overlap or small gap (within 10 points)
        x_gap = max(0, bbox2.x0 - bbox1.x1, bbox1.x0 - bbox2.x1)
        y_gap = max(0, bbox2.y0 - bbox1.y1, bbox1.y0 - bbox2.y1)

        return x_gap < 10 and y_gap < 10


class ReadingOrderDetector:
    """Detects reading order using XY-cut algorithm.

    XY-cut performs recursive horizontal and vertical cuts based on
    whitespace gaps to establish reading order.
    """

    def detect(self, text_blocks: list[TextBlock]) -> ReadingOrder:
        """Detect reading order of text blocks.

        Uses XY-cut algorithm to recursively partition blocks and
        establish natural reading order.

        Args:
            text_blocks: List of text blocks on page.

        Returns:
            ReadingOrder object with ordered element indices.

        Raises:
            LayoutError: If detection fails.
        """
        try:
            if not text_blocks:
                return ReadingOrder(elements=[])

            # Build block index mapping
            block_indices = list(range(len(text_blocks)))

            # Recursively partition blocks
            ordered = self._xy_cut(text_blocks, block_indices)

            return ReadingOrder(elements=ordered)

        except (OSError, RuntimeError, ValueError, AttributeError, TypeError, ImportError, KeyError) as e:
            raise LayoutError(f"Reading order detection failed: {e}")

    def _xy_cut(self, blocks: list[TextBlock], indices: list[int], depth: int = 0) -> list[int]:
        """Recursive XY-cut algorithm.

        Args:
            blocks: Text blocks.
            indices: Indices in this partition.
            depth: Recursion depth.

        Returns:
            Ordered indices.
        """
        if len(indices) <= 1:
            return indices

        # Limit recursion depth
        if depth > 10:
            return sorted(indices, key=lambda i: (blocks[i].bbox.y0, blocks[i].bbox.x0))

        # Find vertical gaps
        v_cuts = self._find_vertical_cuts(blocks, indices)
        if v_cuts:
            result: list[int] = []
            for segment in self._partition_by_cuts(blocks, indices, v_cuts, "vertical"):
                result.extend(self._xy_cut(blocks, segment, depth + 1))
            return result

        # Find horizontal gaps
        h_cuts = self._find_horizontal_cuts(blocks, indices)
        if h_cuts:
            result = []
            for segment in self._partition_by_cuts(blocks, indices, h_cuts, "horizontal"):
                result.extend(self._xy_cut(blocks, segment, depth + 1))
            return result

        # No cuts found, sort by position
        return sorted(indices, key=lambda i: (blocks[i].bbox.y0, blocks[i].bbox.x0))

    @staticmethod
    def _find_vertical_cuts(blocks: list[TextBlock], indices: list[int]) -> list[float]:
        """Find vertical cut positions (x-coordinates with gaps).

        Args:
            blocks: All blocks.
            indices: Block indices in partition.

        Returns:
            List of x-coordinates with significant gaps.
        """
        if not indices:
            return []

        # Get x-coordinates of edges
        partition_blocks = [blocks[i] for i in indices]

        min_x = min(b.bbox.x0 for b in partition_blocks)
        max_x = max(b.bbox.x1 for b in partition_blocks)

        # Create projection histogram
        histogram: dict[int, int] = {}
        for block in partition_blocks:
            for x in range(int(block.bbox.x0), int(block.bbox.x1)):
                histogram[x] = histogram.get(x, 0) + 1

        # Find gaps (zero or low values)
        cuts: list[float] = []
        gap_threshold = len(partition_blocks) * 0.3

        in_gap = False
        gap_start = 0

        for x in range(int(min_x), int(max_x) + 1):
            if histogram.get(x, 0) < gap_threshold:
                if not in_gap:
                    gap_start = x
                    in_gap = True
            else:
                if in_gap:
                    gap_center = (gap_start + x) / 2
                    cuts.append(gap_center)
                    in_gap = False

        return cuts

    @staticmethod
    def _find_horizontal_cuts(blocks: list[TextBlock], indices: list[int]) -> list[float]:
        """Find horizontal cut positions (y-coordinates with gaps).

        Args:
            blocks: All blocks.
            indices: Block indices in partition.

        Returns:
            List of y-coordinates with significant gaps.
        """
        if not indices:
            return []

        partition_blocks = [blocks[i] for i in indices]

        min_y = min(b.bbox.y0 for b in partition_blocks)
        max_y = max(b.bbox.y1 for b in partition_blocks)

        # Create projection histogram
        histogram: dict[int, int] = {}
        for block in partition_blocks:
            for y in range(int(block.bbox.y0), int(block.bbox.y1)):
                histogram[y] = histogram.get(y, 0) + 1

        # Find gaps
        cuts: list[float] = []
        gap_threshold = len(partition_blocks) * 0.3

        in_gap = False
        gap_start = 0

        for y in range(int(min_y), int(max_y) + 1):
            if histogram.get(y, 0) < gap_threshold:
                if not in_gap:
                    gap_start = y
                    in_gap = True
            else:
                if in_gap:
                    gap_center = (gap_start + y) / 2
                    cuts.append(gap_center)
                    in_gap = False

        return cuts

    @staticmethod
    def _partition_by_cuts(
        blocks: list[TextBlock],
        indices: list[int],
        cuts: list[float],
        direction: str,
    ) -> list[list[int]]:
        """Partition blocks by cut positions.

        Args:
            blocks: All blocks.
            indices: Block indices to partition.
            cuts: Cut positions.
            direction: "vertical" or "horizontal".

        Returns:
            List of partitions (each is a list of indices).
        """
        partitions: list[list[int]] = []
        current_partition: list[int] = []

        sorted_indices = sorted(
            indices,
            key=lambda i: (blocks[i].bbox.x0 if direction == "vertical" else blocks[i].bbox.y0),
        )

        for idx in sorted_indices:
            block = blocks[idx]

            # Check if block crosses any cut
            in_new_partition = False
            for cut in cuts:
                if direction == "vertical":
                    if block.bbox.x1 <= cut:
                        in_new_partition = False
                    elif block.bbox.x0 >= cut:
                        in_new_partition = True
                        break
                else:
                    if block.bbox.y1 <= cut:
                        in_new_partition = False
                    elif block.bbox.y0 >= cut:
                        in_new_partition = True
                        break

            if in_new_partition and current_partition:
                partitions.append(current_partition)
                current_partition = []

            current_partition.append(idx)

        if current_partition:
            partitions.append(current_partition)

        return partitions if partitions else [indices]


class ColumnDetector:
    """Detects column layout using projection profile analysis."""

    @staticmethod
    def detect_columns(blocks: list[TextBlock], page_width: float = 612.0) -> int:
        """Detect number of columns in text.

        Uses horizontal projection profile to identify column boundaries.

        Args:
            blocks: Text blocks.
            page_width: Page width in points.

        Returns:
            Estimated number of columns (1-3 typically).
        """
        if not blocks:
            return 1

        # Create x-projection histogram
        histogram: dict[int, int] = {}
        for block in blocks:
            for x in range(int(block.bbox.x0), int(block.bbox.x1)):
                histogram[x] = histogram.get(x, 0) + 1

        # Find valleys (gaps between columns)
        valleys: list[int] = []
        threshold = len(blocks) * 0.2

        in_valley = False
        valley_start = 0

        for x in sorted(histogram.keys()):
            if histogram[x] < threshold:
                if not in_valley:
                    valley_start = x
                    in_valley = True
            else:
                if in_valley and x - valley_start > 20:
                    valleys.append((valley_start + x) // 2)
                in_valley = False

        # Number of columns = number of valleys + 1
        num_columns = min(len(valleys) + 1, 3)
        return max(1, num_columns)


class TextBlockClassifier:
    """Classifies text blocks by type (title, heading, paragraph, etc)."""

    @staticmethod
    def classify(block: TextBlock, page_height: float = 792.0) -> TextBlockType:
        """Classify a text block.

        Args:
            block: Text block to classify.
            page_height: Page height for position-based heuristics.

        Returns:
            Classified block type.
        """
        # Title heuristic: top of page, larger font, short text
        if block.bbox.y0 < page_height * 0.15:
            if block.bbox.height() > 18:
                return TextBlockType.TITLE

        # Heading heuristic: medium font size, short text
        if block.bbox.height() > 14:
            if len(block.text.split()) < 10:
                return TextBlockType.HEADING

        # List heuristic: lines starting with bullets or numbers
        if re.match(r"^(\s*[-•*]|\s*\d+\.)", block.text, re.MULTILINE):
            return TextBlockType.LIST

        # Paragraph: default for substantial text
        if len(block.text.split()) > 3:
            return TextBlockType.PARAGRAPH

        return TextBlockType.OTHER


class MarginDetector:
    """Detects document margins."""

    @staticmethod
    def detect_margins(
        blocks: list[TextBlock], page_width: float = 612.0, page_height: float = 792.0
    ) -> tuple[float, float, float, float]:
        """Detect page margins.

        Args:
            blocks: Text blocks on page.
            page_width: Page width.
            page_height: Page height.

        Returns:
            Tuple of (left, right, top, bottom) margins.
        """
        if not blocks:
            return (36.0, 36.0, 36.0, 36.0)

        min_x = min(b.bbox.x0 for b in blocks)
        max_x = max(b.bbox.x1 for b in blocks)
        min_y = min(b.bbox.y0 for b in blocks)
        max_y = max(b.bbox.y1 for b in blocks)

        left = max(0.0, min_x)
        right = max(0.0, page_width - max_x)
        top = max(0.0, min_y)
        bottom = max(0.0, page_height - max_y)

        return (left, right, top, bottom)


class LayoutAnalyzer:
    """Complete layout analysis for documents."""

    def __init__(self, page_width: float = 612.0, page_height: float = 792.0):
        """Initialize analyzer.

        Args:
            page_width: Default page width.
            page_height: Default page height.
        """
        self.page_width = page_width
        self.page_height = page_height

    def analyze_page(self, page: Page) -> Layout:
        """Analyze complete page layout.

        Args:
            page: Page to analyze.

        Returns:
            Layout information.
        """
        # Classify blocks
        for block in page.text_blocks:
            if block.block_type == TextBlockType.OTHER:
                block.block_type = TextBlockClassifier.classify(block, page.height)

        # Detect margins
        left, right, top, bottom = MarginDetector.detect_margins(page.text_blocks, page.width, page.height)

        # Detect columns
        num_cols = ColumnDetector.detect_columns(page.text_blocks, page.width)

        # Detect reading order
        detector = ReadingOrderDetector()
        reading_order = detector.detect(page.text_blocks)

        layout = Layout(
            page_width=page.width,
            page_height=page.height,
            margin_left=left,
            margin_right=right,
            margin_top=top,
            margin_bottom=bottom,
            columns=num_cols,
            reading_order=reading_order,
        )

        return layout


# Import re for regex in TextBlockClassifier
import re
