"""Tests for bar chart implementation."""

import pytest

from thomas.marketplace.visualization._exceptions import InvalidDataError
from thomas.marketplace.visualization._types import (
    Color,
    DataPoint,
    Series,
)
from thomas.marketplace.visualization.bar_chart import BarChart, BarGeometry
from thomas.marketplace.visualization.scales import CategoricalScale, LinearScale


class TestBarChart:
    """Tests for bar chart rendering."""

    def test_bar_chart_initialization(self) -> None:
        """Test bar chart initialization."""
        chart = BarChart()

        assert chart.mode == "vertical"
        assert chart.group_mode == "grouped"
        assert chart.bar_width_ratio == 0.8

    def test_set_orientation_vertical(self) -> None:
        """Test setting vertical orientation."""
        chart = BarChart()
        chart.set_orientation("vertical")

        assert chart.mode == "vertical"

    def test_set_orientation_horizontal(self) -> None:
        """Test setting horizontal orientation."""
        chart = BarChart()
        chart.set_orientation("horizontal")

        assert chart.mode == "horizontal"

    def test_set_orientation_invalid(self) -> None:
        """Test that invalid orientation raises error."""
        chart = BarChart()

        with pytest.raises(InvalidDataError):
            chart.set_orientation("diagonal")

    def test_set_group_mode_grouped(self) -> None:
        """Test setting grouped mode."""
        chart = BarChart()
        chart.set_group_mode("grouped")

        assert chart.group_mode == "grouped"

    def test_set_group_mode_stacked(self) -> None:
        """Test setting stacked mode."""
        chart = BarChart()
        chart.set_group_mode("stacked")

        assert chart.group_mode == "stacked"

    def test_set_group_mode_stacked_100(self) -> None:
        """Test setting normalized stacked mode."""
        chart = BarChart()
        chart.set_group_mode("stacked_100")

        assert chart.group_mode == "stacked_100"

    def test_set_bar_width_ratio(self) -> None:
        """Test setting bar width ratio."""
        chart = BarChart()
        chart.set_bar_width_ratio(0.6)

        assert chart.bar_width_ratio == 0.6

    def test_set_bar_width_ratio_invalid(self) -> None:
        """Test that invalid width ratio raises error."""
        chart = BarChart()

        with pytest.raises(InvalidDataError):
            chart.set_bar_width_ratio(1.5)

    def test_grouped_bars_generation(self) -> None:
        """Test grouped bar generation."""
        chart = BarChart()
        chart.set_group_mode("grouped")

        series1 = Series("A", [DataPoint(0, 10.0), DataPoint(1, 20.0)])
        series2 = Series("B", [DataPoint(0, 15.0), DataPoint(1, 25.0)])

        x_scale = CategoricalScale((0, 1), (0.0, 200.0))
        y_scale = LinearScale((0.0, 30.0), (0.0, 300.0))

        bars = chart.generate_bars([series1, series2], x_scale, y_scale, 300.0)

        assert len(bars) == 4
        assert all(isinstance(b, BarGeometry) for b in bars)

    def test_stacked_bars_generation(self) -> None:
        """Test stacked bar generation."""
        chart = BarChart()
        chart.set_group_mode("stacked")

        series1 = Series("A", [DataPoint(0, 10.0), DataPoint(1, 20.0)])
        series2 = Series("B", [DataPoint(0, 15.0), DataPoint(1, 25.0)])

        x_scale = CategoricalScale((0, 1), (0.0, 200.0))
        y_scale = LinearScale((0.0, 100.0), (0.0, 300.0))

        bars = chart.generate_bars([series1, series2], x_scale, y_scale, 300.0)

        assert len(bars) == 4
        assert bars[1].y + bars[1].height == bars[0].y

    def test_normalized_stacked_bars(self) -> None:
        """Test normalized stacked bars."""
        chart = BarChart()
        chart.set_group_mode("stacked_100")

        series1 = Series("A", [DataPoint(0, 30.0)])
        series2 = Series("B", [DataPoint(0, 70.0)])

        x_scale = CategoricalScale((0,), (0.0, 100.0))
        y_scale = LinearScale((0.0, 100.0), (0.0, 300.0))

        bars = chart.generate_bars([series1, series2], x_scale, y_scale, 300.0)

        assert len(bars) == 2

    def test_bar_labels_generation(self) -> None:
        """Test bar label generation."""
        chart = BarChart()

        bars = [
            BarGeometry(10.0, 50.0, 30.0, 100.0, Color(100, 100, 100)),
            BarGeometry(50.0, 30.0, 30.0, 120.0, Color(100, 100, 100)),
        ]

        labels = chart.generate_bar_labels(bars, 300.0)

        assert len(labels) == 2
        assert all(len(label) == 3 for label in labels)

    def test_error_bars_generation(self) -> None:
        """Test error bar generation."""
        chart = BarChart()

        bars = [
            BarGeometry(25.0, 100.0, 30.0, 100.0, Color(100, 100, 100)),
            BarGeometry(75.0, 80.0, 30.0, 120.0, Color(100, 100, 100)),
        ]
        errors = [(50.0, 120.0), (40.0, 140.0)]

        y_scale = LinearScale((0.0, 150.0), (0.0, 300.0))

        error_lines = chart.generate_error_bars(bars, errors, y_scale, 300.0)

        assert len(error_lines) == 6

    def test_waterfall_bars_generation(self) -> None:
        """Test waterfall chart generation."""
        chart = BarChart()

        points = [
            DataPoint(0, 20.0),
            DataPoint(1, 10.0),
            DataPoint(2, -5.0),
            DataPoint(3, 15.0),
        ]
        series = Series("waterfall", points)

        x_scale = CategoricalScale((0, 1, 2, 3), (0.0, 400.0))
        y_scale = LinearScale((-10.0, 50.0), (0.0, 300.0))

        bars = chart.generate_waterfall_bars(series, x_scale, y_scale, 300.0)

        assert len(bars) == 4
        assert bars[2].fill.r == 200 or bars[2].fill.b > bars[2].fill.g

    def test_histogram_generation(self) -> None:
        """Test histogram bin generation."""
        chart = BarChart()

        data = [10.0, 15.0, 20.0, 22.0, 25.0, 30.0, 35.0, 40.0]
        x_scale = LinearScale((10.0, 40.0), (0.0, 300.0))
        y_scale = LinearScale((0.0, 3.0), (0.0, 300.0))

        bars, edges = chart.generate_histogram_bins(data, 3, x_scale, y_scale, 300.0)

        assert len(bars) == 3
        assert len(edges) == 4

    def test_empty_series_list(self) -> None:
        """Test generating bars from empty series list."""
        chart = BarChart()

        x_scale = CategoricalScale((), (0.0, 200.0))
        y_scale = LinearScale((0.0, 100.0), (0.0, 300.0))

        bars = chart.generate_bars([], x_scale, y_scale, 300.0)

        assert len(bars) == 0

    def test_extract_categories(self) -> None:
        """Test category extraction from series."""
        series1 = Series(
            "A",
            [
                DataPoint("cat1", 10.0),
                DataPoint("cat2", 20.0),
            ],
        )
        series2 = Series(
            "B",
            [
                DataPoint("cat2", 15.0),
                DataPoint("cat3", 25.0),
            ],
        )

        categories = BarChart._extract_categories([series1, series2])

        assert "cat1" in categories
        assert "cat2" in categories
        assert "cat3" in categories

    def test_bar_geometry_properties(self) -> None:
        """Test bar geometry properties."""
        color = Color(100, 150, 200)
        bar = BarGeometry(10.0, 20.0, 30.0, 40.0, color)

        assert bar.x == 10.0
        assert bar.y == 20.0
        assert bar.width == 30.0
        assert bar.height == 40.0
        assert bar.fill == color
