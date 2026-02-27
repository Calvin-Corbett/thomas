"""Tests for line chart implementation."""

import math

import pytest

from thomas.visualization._exceptions import InvalidDataError
from thomas.visualization._types import (
    Color,
    DataPoint,
    Figure,
    Fill,
    Series,
)
from thomas.visualization.line_chart import LineChart
from thomas.visualization.scales import LinearScale


class TestLineChart:
    """Tests for line chart rendering."""

    def test_line_chart_initialization(self) -> None:
        """Test line chart initialization."""
        figure = Figure()
        chart = LineChart(figure)

        assert chart.interpolation == "linear"
        assert chart.area_fill is None

    def test_set_interpolation_valid(self) -> None:
        """Test setting valid interpolation mode."""
        figure = Figure()
        chart = LineChart(figure)

        chart.set_interpolation("step")
        assert chart.interpolation == "step"

        chart.set_interpolation("monotone")
        assert chart.interpolation == "monotone"

    def test_set_interpolation_invalid(self) -> None:
        """Test that invalid interpolation mode raises error."""
        figure = Figure()
        chart = LineChart(figure)

        with pytest.raises(InvalidDataError):
            chart.set_interpolation("cubic")

    def test_set_area_fill(self) -> None:
        """Test setting area fill."""
        figure = Figure()
        chart = LineChart(figure)
        fill = Fill(color=Color(100, 150, 200), opacity=0.5)

        chart.set_area_fill(fill)
        assert chart.area_fill == fill

    def test_linear_interpolation(self) -> None:
        """Test linear interpolation."""
        figure = Figure()
        chart = LineChart(figure)

        points = [
            DataPoint(0.0, 10.0),
            DataPoint(100.0, 90.0),
        ]
        series = Series("test", points)

        x_scale = LinearScale((0.0, 100.0), (0.0, 400.0))
        y_scale = LinearScale((0.0, 100.0), (0.0, 300.0))

        path = chart.generate_path_data(series, x_scale, y_scale, 300.0)

        assert "M" in path
        assert "L" in path

    def test_step_interpolation(self) -> None:
        """Test step interpolation."""
        figure = Figure()
        chart = LineChart(figure)
        chart.set_interpolation("step")

        points = [
            DataPoint(0.0, 10.0),
            DataPoint(50.0, 50.0),
            DataPoint(100.0, 90.0),
        ]
        series = Series("test", points)

        x_scale = LinearScale((0.0, 100.0), (0.0, 400.0))
        y_scale = LinearScale((0.0, 100.0), (0.0, 300.0))

        path = chart.generate_path_data(series, x_scale, y_scale, 300.0)

        assert path.count("L") >= 2

    def test_monotone_interpolation(self) -> None:
        """Test monotone cubic interpolation."""
        figure = Figure()
        chart = LineChart(figure)
        chart.set_interpolation("monotone")

        points = [
            DataPoint(0.0, 10.0),
            DataPoint(50.0, 80.0),
            DataPoint(100.0, 30.0),
        ]
        series = Series("test", points)

        x_scale = LinearScale((0.0, 100.0), (0.0, 400.0))
        y_scale = LinearScale((0.0, 100.0), (0.0, 300.0))

        path = chart.generate_path_data(series, x_scale, y_scale, 300.0)

        assert "M" in path
        assert len(path) > 0

    def test_empty_series_path(self) -> None:
        """Test path generation for empty series."""
        figure = Figure()
        chart = LineChart(figure)

        series = Series("test", [])
        x_scale = LinearScale((0.0, 100.0), (0.0, 400.0))
        y_scale = LinearScale((0.0, 100.0), (0.0, 300.0))

        path = chart.generate_path_data(series, x_scale, y_scale, 300.0)

        assert path == ""

    def test_single_point_series(self) -> None:
        """Test path generation for single point."""
        figure = Figure()
        chart = LineChart(figure)

        points = [DataPoint(50.0, 50.0)]
        series = Series("test", points)

        x_scale = LinearScale((0.0, 100.0), (0.0, 400.0))
        y_scale = LinearScale((0.0, 100.0), (0.0, 300.0))

        path = chart.generate_path_data(series, x_scale, y_scale, 300.0)

        assert path == ""

    def test_area_path_generation(self) -> None:
        """Test area path generation."""
        figure = Figure()
        chart = LineChart(figure)

        points = [
            DataPoint(0.0, 10.0),
            DataPoint(50.0, 50.0),
            DataPoint(100.0, 30.0),
        ]
        series = Series("test", points)

        x_scale = LinearScale((0.0, 100.0), (0.0, 400.0))
        y_scale = LinearScale((0.0, 100.0), (0.0, 300.0))

        path = chart.generate_area_path_data(series, x_scale, y_scale, 400.0, 300.0, 0.0)

        assert "M" in path
        assert "Z" in path

    def test_confidence_band_generation(self) -> None:
        """Test confidence band generation."""
        figure = Figure()
        chart = LineChart(figure)

        main_points = [DataPoint(0.0, 50.0), DataPoint(100.0, 50.0)]
        upper_points = [DataPoint(0.0, 60.0), DataPoint(100.0, 60.0)]
        lower_points = [DataPoint(0.0, 40.0), DataPoint(100.0, 40.0)]

        main_series = Series("main", main_points)
        upper_series = Series("upper", upper_points)
        lower_series = Series("lower", lower_points)

        x_scale = LinearScale((0.0, 100.0), (0.0, 400.0))
        y_scale = LinearScale((0.0, 100.0), (0.0, 300.0))

        path = chart.generate_confidence_band(main_series, upper_series, lower_series, x_scale, y_scale, 300.0)

        assert "M" in path
        assert "Z" in path

    def test_reference_line_horizontal(self) -> None:
        """Test horizontal reference line generation."""
        figure = Figure()
        chart = LineChart(figure)

        x_scale = LinearScale((0.0, 100.0), (0.0, 400.0))
        y_scale = LinearScale((0.0, 100.0), (0.0, 300.0))

        path, stroke = chart.generate_reference_line(50.0, "y", x_scale, y_scale, 400.0, 300.0)

        assert "M" in path
        assert "L" in path

    def test_reference_line_vertical(self) -> None:
        """Test vertical reference line generation."""
        figure = Figure()
        chart = LineChart(figure)

        x_scale = LinearScale((0.0, 100.0), (0.0, 400.0))
        y_scale = LinearScale((0.0, 100.0), (0.0, 300.0))

        path, stroke = chart.generate_reference_line(50.0, "x", x_scale, y_scale, 400.0, 300.0)

        assert "M" in path
        assert "L" in path

    def test_trend_line_generation(self) -> None:
        """Test trend line (regression) generation."""
        figure = Figure()
        chart = LineChart(figure)

        points = [
            DataPoint(0.0, 10.0),
            DataPoint(25.0, 25.0),
            DataPoint(50.0, 50.0),
            DataPoint(75.0, 75.0),
            DataPoint(100.0, 90.0),
        ]
        series = Series("test", points)

        x_scale = LinearScale((0.0, 100.0), (0.0, 400.0))
        y_scale = LinearScale((0.0, 100.0), (0.0, 300.0))

        path = chart.generate_trend_line(series, x_scale, y_scale, 300.0)

        assert "M" in path
        assert "L" in path

    def test_invalid_points_filtering(self) -> None:
        """Test that invalid points are filtered."""
        figure = Figure()
        chart = LineChart(figure)

        points = [
            DataPoint(0.0, 10.0),
            DataPoint(50.0, float("inf")),
            DataPoint(100.0, 90.0),
        ]
        series = Series("test", points)

        x_scale = LinearScale((0.0, 100.0), (0.0, 400.0))
        y_scale = LinearScale((0.0, 100.0), (0.0, 300.0))

        valid = chart._filter_valid_points(series.points)

        assert len(valid) == 2
        assert all(math.isfinite(x) and math.isfinite(y) for x, y in valid)

    def test_path_continuity(self) -> None:
        """Test that generated paths are continuous."""
        figure = Figure()
        chart = LineChart(figure)

        points = [DataPoint(float(i), float(i * 2)) for i in range(10)]
        series = Series("test", points)

        x_scale = LinearScale((0.0, 10.0), (0.0, 100.0))
        y_scale = LinearScale((0.0, 20.0), (0.0, 100.0))

        path = chart.generate_path_data(series, x_scale, y_scale, 100.0)

        assert path.count("M") == 1
        assert path.count("L") >= len(points) - 2
