"""Tests for precision agriculture module."""

import pytest

from thomas.agriculture.precision import (
    AsAppliedVsAsPresc,
    GPSFieldBoundary,
    NDVICalculator,
    Point2D,
    SiteSpcMgmtZones,
    VariableRateMap,
    YieldMonitorProcessing,
    ZoneManagement,
)


class TestNDVICalculator:
    """Test NDVI calculations."""

    def test_calculate_ndvi_dense_vegetation(self) -> None:
        """Test NDVI for dense vegetation."""
        ndvi = NDVICalculator.calculate_ndvi(
            near_infrared_reflectance=0.5,
            red_reflectance=0.1,
        )

        # (0.5 - 0.1) / (0.5 + 0.1) = 0.4 / 0.6 = 0.667
        assert 0.6 < ndvi < 0.7

    def test_calculate_ndvi_sparse_vegetation(self) -> None:
        """Test NDVI for sparse vegetation."""
        ndvi = NDVICalculator.calculate_ndvi(
            near_infrared_reflectance=0.25,
            red_reflectance=0.15,
        )

        # (0.25 - 0.15) / (0.25 + 0.15) = 0.1 / 0.4 = 0.25
        assert 0.2 < ndvi < 0.3

    def test_calculate_ndvi_water(self) -> None:
        """Test NDVI for water."""
        ndvi = NDVICalculator.calculate_ndvi(
            near_infrared_reflectance=0.05,
            red_reflectance=0.1,
        )

        # Negative NDVI for water
        assert ndvi < 0

    def test_interpret_ndvi_dense(self) -> None:
        """Test NDVI interpretation for dense vegetation."""
        interpretation = NDVICalculator.interpret_ndvi(0.7)
        assert "Dense" in interpretation

    def test_interpret_ndvi_sparse(self) -> None:
        """Test NDVI interpretation for sparse vegetation."""
        interpretation = NDVICalculator.interpret_ndvi(0.25)
        assert "Low" in interpretation


class TestZoneManagement:
    """Test zone management functionality."""

    def test_kmeans_clustering_simple(self) -> None:
        """Test simple k-means clustering."""
        data = [
            [0.8, 150],  # High NDVI, high yield
            [0.75, 145],
            [0.5, 120],  # Medium
            [0.45, 115],
            [0.2, 80],  # Low NDVI, low yield
            [0.25, 85],
        ]

        zones = ZoneManagement.kmeans_clustering(data, k=3)

        # Should create 3 zones
        assert len(zones) == 3

    def test_kmeans_converges(self) -> None:
        """Test that kmeans produces valid clustering."""
        data = [[i, i * 2] for i in range(10)]

        zones = ZoneManagement.kmeans_clustering(data, k=2)

        # All points should be assigned
        total_points = sum(len(points) for points in zones.values())
        assert total_points == 10

    def test_invalid_k_raises_error(self) -> None:
        """Test invalid k value raises error."""
        data = [[1, 2], [2, 3]]

        with pytest.raises(Exception):
            ZoneManagement.kmeans_clustering(data, k=0)


class TestVariableRateMap:
    """Test variable rate map generation."""

    def test_create_vr_nitrogen_map(self) -> None:
        """Test VR nitrogen map creation."""
        zones = {
            0: [0, 1, 2],  # Low yield zone
            1: [3, 4, 5],  # Medium yield zone
            2: [6, 7, 8],  # High yield zone
        }

        yield_data = [100, 105, 110, 140, 145, 150, 170, 175, 180]

        vr_map = VariableRateMap.create_vr_nitrogen_map(
            zones=zones,
            yield_data=yield_data,
            base_rate_lbs_acre=150.0,
        )

        # High zone should get more N
        assert vr_map[2] > vr_map[1]
        # Low zone should get less N
        assert vr_map[0] < vr_map[1]


class TestYieldMonitorProcessing:
    """Test yield monitor data processing."""

    def test_clean_yield_data_removes_outliers(self) -> None:
        """Test outlier removal from yield data."""
        yield_data = [140, 145, 142, 148, 146, 50, 144, 147, 145]  # 50 is outlier

        cleaned = YieldMonitorProcessing.clean_yield_data(
            yield_values=yield_data,
            std_dev_threshold=2.0,
        )

        # Outlier should be removed
        assert 50 not in cleaned
        assert len(cleaned) < len(yield_data)

    def test_clean_yield_data_keeps_valid(self) -> None:
        """Test that valid data is kept."""
        yield_data = [140, 145, 142, 148, 146, 144, 147, 145]

        cleaned = YieldMonitorProcessing.clean_yield_data(
            yield_values=yield_data,
            std_dev_threshold=2.0,
        )

        # No outliers, all should be kept
        assert len(cleaned) == len(yield_data)

    def test_interpolate_missing_values(self) -> None:
        """Test interpolation of missing values."""
        yield_data = {
            Point2D(0, 0): 140,
            Point2D(100, 0): 150,
            Point2D(0, 100): 145,
        }

        missing = [Point2D(50, 50)]

        result = YieldMonitorProcessing.interpolate_missing_values(
            yield_data=yield_data,
            missing_points=missing,
            search_radius=100.0,
        )

        # Missing point should be interpolated
        assert Point2D(50, 50) in result
        assert result[Point2D(50, 50)] > 0


class TestGPSFieldBoundary:
    """Test GPS field boundary management."""

    def setup_method(self) -> None:
        """Setup GPS boundary manager."""
        self.boundary = GPSFieldBoundary()

    def test_add_boundary_point(self) -> None:
        """Test adding boundary points."""
        self.boundary.add_boundary_point(40.0, -93.0)
        self.boundary.add_boundary_point(40.01, -93.0)
        self.boundary.add_boundary_point(40.01, -92.99)
        self.boundary.add_boundary_point(40.0, -92.99)

        assert len(self.boundary.boundary_points) == 4

    def test_invalid_latitude_raises_error(self) -> None:
        """Test invalid latitude raises error."""
        with pytest.raises(Exception):
            self.boundary.add_boundary_point(91.0, -93.0)

    def test_invalid_longitude_raises_error(self) -> None:
        """Test invalid longitude raises error."""
        with pytest.raises(Exception):
            self.boundary.add_boundary_point(40.0, 181.0)

    def test_calculate_field_area(self) -> None:
        """Test field area calculation."""
        # Create 1 degree × 1 degree square
        self.boundary.add_boundary_point(40.0, -93.0)
        self.boundary.add_boundary_point(41.0, -93.0)
        self.boundary.add_boundary_point(41.0, -92.0)
        self.boundary.add_boundary_point(40.0, -92.0)

        area = self.boundary.calculate_field_area_acres()

        # Should be approximately 640 acres (1 degree square)
        assert 600 < area < 700

    def test_insufficient_boundary_points(self) -> None:
        """Test error with insufficient points."""
        self.boundary.add_boundary_point(40.0, -93.0)
        self.boundary.add_boundary_point(40.01, -93.0)

        with pytest.raises(Exception):
            self.boundary.calculate_field_area_acres()


class TestAsAppliedVsAsPresc:
    """Test as-applied vs as-prescribed comparison."""

    def test_calculate_deviation_over_applied(self) -> None:
        """Test deviation when over-applied."""
        deviation = AsAppliedVsAsPresc.calculate_deviation(
            as_prescribed_lbs=150.0,
            as_applied_lbs=165.0,
        )

        # Should be 10% over
        assert 9 < deviation["percent_error"] < 11

    def test_calculate_deviation_under_applied(self) -> None:
        """Test deviation when under-applied."""
        deviation = AsAppliedVsAsPresc.calculate_deviation(
            as_prescribed_lbs=150.0,
            as_applied_lbs=135.0,
        )

        # Should be -10% (under)
        assert -11 < deviation["percent_error"] < -9

    def test_field_compliance_report_good(self) -> None:
        """Test compliance report for good compliance."""
        deviations = [
            {"percent_error": 2.0},
            {"percent_error": 3.0},
            {"percent_error": 1.5},
            {"percent_error": 2.5},
        ]

        report = AsAppliedVsAsPrec.field_compliance_report(
            deviations=deviations,
            tolerance_percent=5.0,
        )

        # All within tolerance
        assert report["compliance_pct"] == 100.0
        assert report["passes"]

    def test_field_compliance_report_poor(self) -> None:
        """Test compliance report for poor compliance."""
        deviations = [
            {"percent_error": 8.0},
            {"percent_error": 12.0},
            {"percent_error": 2.0},
            {"percent_error": 15.0},
        ]

        report = AsAppliedVsAsPrec.field_compliance_report(
            deviations=deviations,
            tolerance_percent=5.0,
        )

        # Not all within tolerance
        assert report["compliance_pct"] < 100
        assert not report["passes"]


class TestSiteSpcMgmtZones:
    """Test site-specific management zones."""

    def test_define_zones_from_layers(self) -> None:
        """Test zone definition from multiple layers."""
        ndvi = [0.2, 0.4, 0.6, 0.5, 0.3, 0.7, 0.8]
        yield_data = [80, 100, 140, 130, 90, 160, 170]
        soil_cec = [5, 8, 12, 11, 6, 15, 16]

        zones = SiteSpcMgmtZones.define_zones_from_layers(
            ndvi_data=ndvi,
            yield_data=yield_data,
            soil_cec_data=soil_cec,
        )

        # Should have three zones
        assert "Low" in zones
        assert "Medium" in zones
        assert "High" in zones

        # All points should be assigned
        total_assigned = sum(len(points) for points in zones.values())
        assert total_assigned == len(ndvi)
