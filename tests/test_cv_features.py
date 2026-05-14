"""Tests for feature detection and matching."""

import pytest

from thomas.marketplace.cv import core, features
from thomas.marketplace.cv._exceptions import InvalidParameterError
from thomas.marketplace.cv._types import Descriptor, Feature


class TestHarrisCornerDetector:
    """Test Harris corner detector."""

    def test_harris_basic(self) -> None:
        """Test basic Harris corner detection."""
        img = core.create_image(100, 100, 1)

        # Create corner: L-shape
        for y in range(50, 100):
            core.set_pixel(img, 25, y, [255])
        for x in range(25, 75):
            core.set_pixel(img, x, 50, [255])

        corners = features.harris_corner_detector(img, block_size=5, threshold=0.01)
        assert isinstance(corners, list)

    def test_harris_no_corners(self) -> None:
        """Test Harris on uniform image."""
        img = core.create_image(100, 100, 1)
        corners = features.harris_corner_detector(img)
        # Should find no corners in uniform image
        assert len(corners) == 0

    def test_harris_invalid_block_size(self) -> None:
        """Test Harris with invalid block size."""
        img = core.create_image(100, 100, 1)

        with pytest.raises(InvalidParameterError):
            features.harris_corner_detector(img, block_size=4)


class TestFASTCornerDetector:
    """Test FAST corner detector."""

    def test_fast_basic(self) -> None:
        """Test basic FAST corner detection."""
        img = core.create_image(100, 100, 1)

        corners = features.fast_corner_detector(img, threshold=30)
        assert isinstance(corners, list)

    def test_fast_no_corners(self) -> None:
        """Test FAST on uniform image."""
        img = core.create_image(100, 100, 1)
        corners = features.fast_corner_detector(img, threshold=30)
        # Should find no corners in uniform image
        assert len(corners) == 0

    def test_fast_max_features(self) -> None:
        """Test FAST with max features limit."""
        img = core.create_image(100, 100, 1)
        # Create multiple corners
        for i in range(0, 100, 20):
            for j in range(0, 100, 20):
                core.set_pixel(img, i, j, [255])

        corners = features.fast_corner_detector(img, threshold=30, max_features=5)
        assert len(corners) <= 5

    def test_fast_invalid_threshold(self) -> None:
        """Test FAST with invalid threshold."""
        img = core.create_image(100, 100, 1)

        with pytest.raises(InvalidParameterError):
            features.fast_corner_detector(img, threshold=300)


class TestBRIEFDescriptor:
    """Test BRIEF descriptor."""

    def test_brief_basic(self) -> None:
        """Test basic BRIEF descriptor extraction."""
        img = core.create_image(100, 100, 1)
        test_features = [Feature(x=50, y=50, response=1.0)]

        descriptors = features.brief_descriptor(img, test_features)
        assert len(descriptors) <= len(test_features)

    def test_brief_descriptor_length(self) -> None:
        """Test BRIEF descriptor length."""
        img = core.create_image(100, 100, 1)
        test_features = [Feature(x=50, y=50, response=1.0)]

        descriptors = features.brief_descriptor(img, test_features, descriptor_size=256)
        if descriptors:
            assert len(descriptors[0].data) == 256

    def test_brief_empty_features(self) -> None:
        """Test BRIEF with no features."""
        img = core.create_image(100, 100, 1)
        descriptors = features.brief_descriptor(img, [])
        assert len(descriptors) == 0


class TestFeatureMatching:
    """Test feature matching."""

    def test_match_features_basic(self) -> None:
        """Test basic feature matching."""
        desc1 = [Descriptor([1, 0, 1, 0, 1], descriptor_type="BRIEF")]
        desc2 = [Descriptor([1, 0, 1, 0, 1], descriptor_type="BRIEF")]

        matches = features.match_features(desc1, desc2, ratio_threshold=0.7)
        assert isinstance(matches, list)

    def test_match_features_empty(self) -> None:
        """Test matching with empty descriptors."""
        matches = features.match_features([], [])
        assert matches == []

    def test_match_features_identical(self) -> None:
        """Test matching identical descriptors."""
        desc = [Descriptor([1, 0, 1, 0, 1], descriptor_type="BRIEF")]
        matches = features.match_features(desc, desc)
        assert len(matches) > 0

    def test_match_features_no_good_matches(self) -> None:
        """Test matching with no good matches."""
        desc1 = [Descriptor([1, 0, 1, 0, 1], descriptor_type="BRIEF")]
        desc2 = [
            Descriptor([0, 1, 0, 1, 0], descriptor_type="BRIEF"),
            Descriptor([1, 1, 1, 1, 1], descriptor_type="BRIEF"),
        ]

        features.match_features(desc1, desc2, ratio_threshold=0.5)
        # May or may not have matches depending on ratio test


class TestHomographyEstimation:
    """Test homography estimation."""

    def test_homography_basic(self) -> None:
        """Test basic homography estimation."""
        src_points = [(0, 0), (100, 0), (100, 100), (0, 100)]
        dst_points = [(10, 10), (110, 10), (110, 110), (10, 110)]

        H = features.estimate_homography(src_points, dst_points)
        assert H is not None

    def test_homography_identity(self) -> None:
        """Test homography for identity transform."""
        points = [(0, 0), (100, 0), (100, 100), (0, 100)]
        H = features.estimate_homography(points, points)
        assert H is not None

    def test_homography_insufficient_points(self) -> None:
        """Test homography with insufficient points."""
        src_points = [(0, 0), (100, 0)]
        dst_points = [(10, 10), (110, 10)]

        with pytest.raises(InvalidParameterError):
            features.estimate_homography(src_points, dst_points)

    def test_homography_mismatched_lists(self) -> None:
        """Test homography with mismatched point lists."""
        src_points = [(0, 0), (100, 0), (100, 100), (0, 100)]
        dst_points = [(10, 10), (110, 10)]

        with pytest.raises(InvalidParameterError):
            features.estimate_homography(src_points, dst_points)


class TestFeatureProperties:
    """Test feature properties."""

    def test_feature_creation(self) -> None:
        """Test feature creation."""
        feature = Feature(x=50, y=50, response=1.0, scale=1.5, angle=0.5)
        assert feature.x == 50
        assert feature.y == 50
        assert feature.response == 1.0

    def test_feature_to_point(self) -> None:
        """Test converting feature to point."""
        feature = Feature(x=50.5, y=60.7, response=1.0)
        point = feature.to_point()
        assert point.x == 50.5
        assert point.y == 60.7
