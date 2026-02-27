"""Tests for scatter plot implementation."""

import pytest

from thomas.visualization._exceptions import InvalidDataError
from thomas.visualization._types import (
    DataPoint,
    Series,
)
from thomas.visualization.scales import LinearScale
from thomas.visualization.scatter import ScatterPlot


class TestScatterPlot:
    """Tests for scatter plot rendering."""

    def test_scatter_plot_initialization(self) -> None:
        """Test scatter plot initialization."""
        chart = ScatterPlot()

        assert chart.jitter_strength == 0.0
        assert chart.alpha_transparency == 1.0

    def test_set_jitter_valid(self) -> None:
        """Test setting valid jitter strength."""
        chart = ScatterPlot()
        chart.set_jitter(0.5)

        assert chart.jitter_strength == 0.5

    def test_set_jitter_invalid(self) -> None:
        """Test that invalid jitter strength raises error."""
        chart = ScatterPlot()

        with pytest.raises(InvalidDataError):
            chart.set_jitter(1.5)

    def test_set_alpha_valid(self) -> None:
        """Test setting valid alpha."""
        chart = ScatterPlot()
        chart.set_alpha(0.7)

        assert chart.alpha_transparency == 0.7

    def test_set_alpha_invalid(self) -> None:
        """Test that invalid alpha raises error."""
        chart = ScatterPlot()

        with pytest.raises(InvalidDataError):
            chart.set_alpha(1.5)

    def test_generate_points_basic(self) -> None:
        """Test basic point generation."""
        chart = ScatterPlot()

        points = [
            DataPoint(10.0, 20.0),
            DataPoint(30.0, 40.0),
            DataPoint(50.0, 60.0),
        ]
        series = Series("test", points)

        x_scale = LinearScale((0.0, 100.0), (0.0, 400.0))
        y_scale = LinearScale((0.0, 100.0), (0.0, 300.0))

        result = chart.generate_points(series, x_scale, y_scale, 300.0)

        assert len(result) == 3
        assert all(len(item) == 4 for item in result)

    def test_generate_points_with_jitter(self) -> None:
        """Test point generation with jitter."""
        chart = ScatterPlot()
        chart.set_jitter(0.3)

        points = [
            DataPoint(10.0, 20.0),
            DataPoint(30.0, 40.0),
        ]
        series = Series("test", points)

        x_scale = LinearScale((0.0, 100.0), (0.0, 400.0))
        y_scale = LinearScale((0.0, 100.0), (0.0, 300.0))

        result = chart.generate_points(series, x_scale, y_scale, 300.0)

        assert len(result) == 2

    def test_generate_bubble_points(self) -> None:
        """Test bubble chart point generation."""
        chart = ScatterPlot()

        points = [
            DataPoint(10.0, 20.0, size=5.0),
            DataPoint(30.0, 40.0, size=15.0),
            DataPoint(50.0, 60.0, size=25.0),
        ]
        series = Series("test", points)

        x_scale = LinearScale((0.0, 100.0), (0.0, 400.0))
        y_scale = LinearScale((0.0, 100.0), (0.0, 300.0))
        size_scale = LinearScale((5.0, 25.0), (5.0, 35.0))

        result = chart.generate_bubble_points(series, x_scale, y_scale, size_scale, 300.0)

        assert len(result) == 3
        sizes = [item[2] for item in result]
        assert sizes[0] < sizes[1] < sizes[2]

    def test_density_2d_estimation(self) -> None:
        """Test 2D density estimation."""
        chart = ScatterPlot()

        points = [
            DataPoint(10.0, 10.0),
            DataPoint(15.0, 15.0),
            DataPoint(20.0, 10.0),
            DataPoint(15.0, 5.0),
        ]
        series = Series("test", points)

        grid, bounds = chart.estimate_density_2d(series, grid_size=10)

        assert len(grid) == 10
        assert len(grid[0]) == 10
        assert len(bounds) == 4

    def test_density_empty_series(self) -> None:
        """Test density estimation with empty series."""
        chart = ScatterPlot()

        series = Series("test", [])

        grid, bounds = chart.estimate_density_2d(series)

        assert len(grid) == 0

    def test_contour_path_generation(self) -> None:
        """Test contour path generation."""
        chart = ScatterPlot()

        grid = [[0.1, 0.2, 0.1], [0.2, 0.5, 0.2], [0.1, 0.2, 0.1]]
        bounds = (0.0, 30.0, 0.0, 30.0)

        x_scale = LinearScale((0.0, 30.0), (0.0, 300.0))
        y_scale = LinearScale((0.0, 30.0), (0.0, 300.0))

        paths = chart.generate_contour_paths(grid, bounds, x_scale, y_scale, 300.0, num_levels=3)

        assert isinstance(paths, list)

    def test_hexbin_grid_generation(self) -> None:
        """Test hexagonal binning."""
        chart = ScatterPlot()

        points = [DataPoint(float(i), float(i)) for i in range(20)]
        series = Series("test", points)

        x_scale = LinearScale((0.0, 20.0), (0.0, 400.0))
        y_scale = LinearScale((0.0, 20.0), (0.0, 300.0))

        hexbins = chart.generate_hexbin_grid(series, x_scale, y_scale, 300.0, hexbin_size=20.0)

        assert len(hexbins) > 0
        assert all(len(item) == 4 for item in hexbins)

    def test_regression_line_generation(self) -> None:
        """Test regression line generation."""
        chart = ScatterPlot()

        points = [
            DataPoint(10.0, 20.0),
            DataPoint(20.0, 40.0),
            DataPoint(30.0, 60.0),
            DataPoint(40.0, 80.0),
        ]
        series = Series("test", points)

        x_scale = LinearScale((0.0, 50.0), (0.0, 400.0))
        y_scale = LinearScale((0.0, 100.0), (0.0, 300.0))

        path = chart.generate_regression_line(series, x_scale, y_scale, 300.0)

        assert "M" in path
        assert "L" in path

    def test_regression_line_insufficient_points(self) -> None:
        """Test regression line with insufficient points."""
        chart = ScatterPlot()

        points = [DataPoint(10.0, 20.0)]
        series = Series("test", points)

        x_scale = LinearScale((0.0, 50.0), (0.0, 400.0))
        y_scale = LinearScale((0.0, 100.0), (0.0, 300.0))

        path = chart.generate_regression_line(series, x_scale, y_scale, 300.0)

        assert path == ""

    def test_invalid_points_filtering(self) -> None:
        """Test filtering of invalid points."""
        chart = ScatterPlot()

        points = [
            DataPoint(10.0, 20.0),
            DataPoint(30.0, float("nan")),
            DataPoint(50.0, 60.0),
        ]
        series = Series("test", points)

        x_scale = LinearScale((0.0, 100.0), (0.0, 400.0))
        y_scale = LinearScale((0.0, 100.0), (0.0, 300.0))

        result = chart.generate_points(series, x_scale, y_scale, 300.0)

        assert len(result) == 2

    def test_pseudo_random_consistency(self) -> None:
        """Test pseudo-random number generation consistency."""
        val1 = ScatterPlot._pseudo_random(10.0, 20.0, 0)
        val2 = ScatterPlot._pseudo_random(10.0, 20.0, 0)

        assert val1 == val2
        assert 0.0 <= val1 <= 1.0

    def test_bubble_point_scaling(self) -> None:
        """Test bubble point size scaling."""
        chart = ScatterPlot()

        points = [
            DataPoint(10.0, 10.0, size=10.0),
            DataPoint(20.0, 20.0, size=50.0),
        ]
        series = Series("test", points)

        x_scale = LinearScale((0.0, 50.0), (0.0, 400.0))
        y_scale = LinearScale((0.0, 50.0), (0.0, 300.0))
        size_scale = LinearScale((10.0, 50.0), (5.0, 35.0))

        result = chart.generate_bubble_points(series, x_scale, y_scale, size_scale, 300.0)

        assert result[0][2] < result[1][2]
