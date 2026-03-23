"""Tests for heatmap implementation."""

from datetime import datetime, timedelta

from thomas.marketplace.visualization._types import (
    Color,
    ColorMap,
    DataPoint,
    Series,
)
from thomas.marketplace.visualization.heatmap import Heatmap
from thomas.marketplace.visualization.scales import LinearScale


class TestHeatmap:
    """Tests for heatmap rendering."""

    def test_heatmap_initialization(self) -> None:
        """Test heatmap initialization."""
        color_map = ColorMap(
            name="viridis",
            colors=[Color(0, 0, 255), Color(0, 255, 0), Color(255, 0, 0)],
            value_range=(0.0, 100.0),
        )
        heatmap = Heatmap(color_map)

        assert heatmap.color_map == color_map
        assert heatmap.show_values is False
        assert heatmap.font_size == 10

    def test_set_show_values(self) -> None:
        """Test enabling value annotations."""
        color_map = ColorMap(
            name="test",
            colors=[Color(0, 0, 255)],
            value_range=(0.0, 100.0),
        )
        heatmap = Heatmap(color_map)

        heatmap.set_show_values(True)
        assert heatmap.show_values is True

    def test_set_font_size(self) -> None:
        """Test setting font size."""
        color_map = ColorMap(
            name="test",
            colors=[Color(0, 0, 255)],
            value_range=(0.0, 100.0),
        )
        heatmap = Heatmap(color_map)

        heatmap.set_font_size(14)
        assert heatmap.font_size == 14

    def test_generate_cells_basic(self) -> None:
        """Test basic cell generation."""
        color_map = ColorMap(
            name="test",
            colors=[Color(0, 0, 255), Color(255, 0, 0)],
            value_range=(0.0, 100.0),
        )
        heatmap = Heatmap(color_map)

        data = [
            [10.0, 20.0, 30.0],
            [40.0, 50.0, 60.0],
            [70.0, 80.0, 90.0],
        ]

        x_scale = LinearScale((0.0, 3.0), (0.0, 300.0))
        y_scale = LinearScale((0.0, 3.0), (0.0, 300.0))

        cells = heatmap.generate_cells(data, x_scale, y_scale, 300.0, 300.0)

        assert len(cells) == 9

    def test_generate_cells_empty(self) -> None:
        """Test cell generation with empty data."""
        color_map = ColorMap(
            name="test",
            colors=[Color(0, 0, 255)],
            value_range=(0.0, 100.0),
        )
        heatmap = Heatmap(color_map)

        data: list = []

        x_scale = LinearScale((0.0, 1.0), (0.0, 100.0))
        y_scale = LinearScale((0.0, 1.0), (0.0, 100.0))

        cells = heatmap.generate_cells(data, x_scale, y_scale, 100.0, 100.0)

        assert len(cells) == 0

    def test_calendar_heatmap_generation(self) -> None:
        """Test calendar heatmap generation."""
        color_map = ColorMap(
            name="test",
            colors=[Color(0, 0, 255), Color(0, 255, 0)],
            value_range=(0.0, 10.0),
        )
        heatmap = Heatmap(color_map)

        start_date = datetime(2024, 1, 1)
        points = [DataPoint(start_date + timedelta(days=i), float((i + 1) % 10)) for i in range(30)]
        series = Series("activity", points)

        x_scale = LinearScale((0.0, 30.0), (0.0, 400.0))
        y_scale = LinearScale((0.0, 7.0), (0.0, 105.0))

        cells = heatmap.generate_calendar_heatmap(series, start_date, x_scale, y_scale, cell_size=15.0)

        assert len(cells) > 0
        assert all(len(cell) == 6 for cell in cells)

    def test_correlation_matrix_generation(self) -> None:
        """Test correlation matrix generation."""
        color_map = ColorMap(
            name="test",
            colors=[Color(0, 0, 255)],
            value_range=(-1.0, 1.0),
        )
        heatmap = Heatmap(color_map)

        series1 = Series("A", [DataPoint(i, float(i)) for i in range(10)])
        series2 = Series("B", [DataPoint(i, float(i * 2)) for i in range(10)])
        series3 = Series("C", [DataPoint(i, float(-i)) for i in range(10)])

        corr_matrix, names = heatmap.generate_correlation_matrix([series1, series2, series3])

        assert len(corr_matrix) == 3
        assert len(corr_matrix[0]) == 3
        assert corr_matrix[0][0] == 1.0
        assert corr_matrix[1][1] == 1.0
        assert len(names) == 3

    def test_correlation_calculation(self) -> None:
        """Test correlation coefficient calculation."""
        series1 = Series("A", [DataPoint(i, float(i)) for i in range(10)])
        series2 = Series("B", [DataPoint(i, float(i)) for i in range(10)])

        color_map = ColorMap(
            name="test",
            colors=[Color(0, 0, 255)],
            value_range=(-1.0, 1.0),
        )
        heatmap = Heatmap(color_map)

        corr = heatmap._calculate_correlation(series1, series2)

        assert 0.99 < corr <= 1.0

    def test_negative_correlation(self) -> None:
        """Test negative correlation detection."""
        series1 = Series("A", [DataPoint(i, float(i)) for i in range(10)])
        series2 = Series("B", [DataPoint(i, float(10 - i)) for i in range(10)])

        color_map = ColorMap(
            name="test",
            colors=[Color(0, 0, 255)],
            value_range=(-1.0, 1.0),
        )
        heatmap = Heatmap(color_map)

        corr = heatmap._calculate_correlation(series1, series2)

        assert -1.0 <= corr < -0.9

    def test_dendrogram_tree_generation(self) -> None:
        """Test dendrogram generation."""
        color_map = ColorMap(
            name="test",
            colors=[Color(0, 0, 255)],
            value_range=(0.0, 100.0),
        )
        heatmap = Heatmap(color_map)

        data = [
            [1.0, 2.0, 3.0],
            [2.0, 3.0, 4.0],
            [10.0, 11.0, 12.0],
        ]

        linkages = heatmap.generate_dendrogram_tree(data, max_depth=5)

        assert len(linkages) > 0

    def test_euclidean_distance(self) -> None:
        """Test Euclidean distance calculation."""
        color_map = ColorMap(
            name="test",
            colors=[Color(0, 0, 255)],
            value_range=(0.0, 100.0),
        )
        heatmap = Heatmap(color_map)

        v1 = [0.0, 0.0, 0.0]
        v2 = [3.0, 4.0, 0.0]

        dist = heatmap._euclidean_distance(v1, v2)

        assert dist == 5.0

    def test_annotated_heatmap(self) -> None:
        """Test annotated heatmap generation."""
        color_map = ColorMap(
            name="test",
            colors=[Color(0, 0, 255)],
            value_range=(0.0, 100.0),
        )
        heatmap = Heatmap(color_map)
        heatmap.set_show_values(True)

        data = [
            [10.0, 20.0],
            [30.0, 40.0],
        ]
        x_labels = ["col1", "col2"]
        y_labels = ["row1", "row2"]

        x_scale = LinearScale((0.0, 2.0), (0.0, 200.0))
        y_scale = LinearScale((0.0, 2.0), (0.0, 200.0))

        cells, annotations = heatmap.generate_annotated_heatmap(
            data, x_labels, y_labels, x_scale, y_scale, 200.0, 200.0
        )

        assert len(cells) == 4
        assert len(annotations) == 4

    def test_data_range_extraction(self) -> None:
        """Test data range extraction."""
        color_map = ColorMap(
            name="test",
            colors=[Color(0, 0, 255)],
            value_range=(0.0, 100.0),
        )
        heatmap = Heatmap(color_map)

        data = [
            [10.0, 20.0, 30.0],
            [40.0, 50.0, 60.0],
        ]

        min_val, max_val = heatmap._get_data_range(data)

        assert min_val == 10.0
        assert max_val == 60.0

    def test_average_cluster(self) -> None:
        """Test cluster averaging."""
        color_map = ColorMap(
            name="test",
            colors=[Color(0, 0, 255)],
            value_range=(0.0, 100.0),
        )
        heatmap = Heatmap(color_map)

        data = [
            [1.0, 2.0, 3.0],
            [4.0, 5.0, 6.0],
            [7.0, 8.0, 9.0],
        ]

        average = heatmap._average_cluster(data, [0, 1])

        assert len(average) == 3
        assert average[0] == 2.5
        assert average[1] == 3.5
