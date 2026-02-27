"""Tests for edge detection and contour finding."""

import pytest

from thomas.cv import core, edges
from thomas.cv._exceptions import InvalidParameterError
from thomas.cv._types import Contour


class TestCannyEdgeDetector:
    """Test Canny edge detector."""

    def test_canny_basic(self) -> None:
        """Test basic Canny edge detection."""
        img = core.create_image(100, 100, 3)
        result = edges.canny_edge_detector(img)
        assert result.shape[0] == img.height
        assert result.shape[1] == img.width

    def test_canny_detects_edges(self) -> None:
        """Test Canny detects edges."""
        img = core.create_image(100, 100, 1)

        # Create edge: vertical line
        for y in range(100):
            core.set_pixel(img, 50, y, [255])

        result = edges.canny_edge_detector(img, low_threshold=50, high_threshold=150)
        # Should detect the edge
        assert result.data[50][50][0] > 127

    def test_canny_invalid_thresholds(self) -> None:
        """Test Canny with invalid thresholds."""
        img = core.create_image(100, 100, 3)

        with pytest.raises(InvalidParameterError):
            edges.canny_edge_detector(img, low_threshold=-1, high_threshold=150)

        with pytest.raises(InvalidParameterError):
            edges.canny_edge_detector(img, low_threshold=150, high_threshold=50)


class TestHoughLineTransform:
    """Test Hough line transform."""

    def test_hough_line_basic(self) -> None:
        """Test basic Hough line transform."""
        img = core.create_image(100, 100, 1)

        # Create horizontal line
        for x in range(100):
            core.set_pixel(img, x, 50, [255])

        lines = edges.hough_line_transform(img, threshold=10)
        assert isinstance(lines, list)

    def test_hough_line_empty_image(self) -> None:
        """Test Hough line on empty image."""
        img = core.create_image(100, 100, 1)
        lines = edges.hough_line_transform(img)
        assert lines == []


class TestHoughCircleTransform:
    """Test Hough circle transform."""

    def test_hough_circle_basic(self) -> None:
        """Test basic Hough circle transform."""
        img = core.create_image(200, 200, 1)

        # Create circle at center
        for y in range(200):
            for x in range(200):
                dx = x - 100
                dy = y - 100
                if 40 <= (dx * dx + dy * dy) ** 0.5 <= 42:
                    core.set_pixel(img, x, y, [255])

        circles = edges.hough_circle_transform(img, radius_min=30, radius_max=60, threshold=5)
        assert isinstance(circles, list)

    def test_hough_circle_invalid_radius(self) -> None:
        """Test Hough circle with invalid radius."""
        img = core.create_image(100, 100, 1)

        with pytest.raises(InvalidParameterError):
            edges.hough_circle_transform(img, radius_min=50, radius_max=40)


class TestContourFinding:
    """Test contour finding."""

    def test_find_contours_basic(self) -> None:
        """Test basic contour finding."""
        img = core.create_image(100, 100, 1)

        # Create white square
        for y in range(20, 80):
            for x in range(20, 80):
                core.set_pixel(img, x, y, [255])

        contours = edges.find_contours(img)
        assert len(contours) > 0

    def test_find_contours_empty_image(self) -> None:
        """Test contour finding on empty image."""
        img = core.create_image(100, 100, 1)
        contours = edges.find_contours(img)
        assert contours == []

    def test_contour_properties(self) -> None:
        """Test contour property calculations."""
        contour = Contour([(0, 0), (10, 0), (10, 10), (0, 10)])

        assert contour.area > 0
        assert contour.perimeter > 0
        assert contour.centroid.x > 0
        assert contour.centroid.y > 0
        assert contour.bounding_box.width == 10


class TestConvexHull:
    """Test convex hull computation."""

    def test_convex_hull_basic(self) -> None:
        """Test basic convex hull."""
        contour = Contour([(0, 0), (10, 0), (5, 5), (10, 10), (0, 10)])
        hull = edges.convex_hull(contour)

        assert len(hull.points) > 0

    def test_convex_hull_triangle(self) -> None:
        """Test convex hull of triangle."""
        contour = Contour([(0, 0), (10, 0), (5, 10)])
        hull = edges.convex_hull(contour)

        assert len(hull.points) >= 3

    def test_convex_hull_single_point(self) -> None:
        """Test convex hull with single point."""
        contour = Contour([(5, 5)])
        hull = edges.convex_hull(contour)

        assert len(hull.points) == 1
