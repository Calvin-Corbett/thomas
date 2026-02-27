"""Tests for crops module."""

from datetime import date, timedelta

import pytest

from thomas.agriculture._types import CropFamily, CropVariety, GrowthStage
from thomas.agriculture.crops import (
    CompanionPlanting,
    CropDatabase,
    CropRotationPlanner,
    GrowthTracker,
    PlantingCalendar,
    YieldEstimator,
)


class TestCropDatabase:
    """Test crop database functionality."""

    def test_load_varieties(self) -> None:
        """Test loading crop varieties."""
        db = CropDatabase()
        varieties = db.list_varieties()
        assert len(varieties) > 0
        assert all(isinstance(v, CropVariety) for v in varieties)

    def test_get_variety_success(self) -> None:
        """Test retrieving a variety."""
        db = CropDatabase()
        variety = db.get_variety("corn_p1197am")
        assert variety.name == "Pioneer P1197AM"
        assert variety.crop_type == "Corn"

    def test_get_variety_not_found(self) -> None:
        """Test variety not found error."""
        db = CropDatabase()
        with pytest.raises(Exception):
            db.get_variety("nonexistent_variety")


class TestPlantingCalendar:
    """Test planting calendar."""

    def setup_method(self) -> None:
        """Setup test calendar."""
        self.calendar = PlantingCalendar(
            avg_last_frost_date=date(2024, 5, 1),
            avg_first_frost_date=date(2024, 10, 1),
        )

    def test_recommend_planting_corn(self) -> None:
        """Test corn planting recommendation."""
        db = CropDatabase()
        corn = db.get_variety("corn_p1197am")
        planting_date = self.calendar.recommend_planting_date(corn, 2024)

        # Should be ~1 week after last frost
        expected = date(2024, 5, 1) + timedelta(days=7)
        assert abs((planting_date - expected).days) <= 2

    def test_estimate_harvest_date(self) -> None:
        """Test harvest date estimation."""
        db = CropDatabase()
        corn = db.get_variety("corn_p1197am")
        planting_date = date(2024, 5, 15)
        harvest_date = self.calendar.estimate_harvest_date(planting_date, corn)

        expected_days = corn.days_to_maturity
        actual_days = (harvest_date - planting_date).days
        assert actual_days == expected_days


class TestGrowthTracker:
    """Test crop growth tracking."""

    def test_calculate_gdd(self) -> None:
        """Test GDD calculation."""
        tracker = GrowthTracker(base_temp_f=50.0)
        gdd = tracker.calculate_gdd(temp_max_f=85.0, temp_min_f=65.0)

        # (85+65)/2 - 50 = 75 - 50 = 25 GDD
        assert gdd == 25.0

    def test_calculate_gdd_below_base(self) -> None:
        """Test GDD when below base temperature."""
        tracker = GrowthTracker(base_temp_f=50.0)
        gdd = tracker.calculate_gdd(temp_max_f=40.0, temp_min_f=35.0)

        # GDD should be 0 when below base
        assert gdd == 0.0

    def test_determine_growth_stage(self) -> None:
        """Test growth stage determination."""
        tracker = GrowthTracker()

        stage = tracker._determine_growth_stage(gdd_accumulated=100, gdd_required=2700)
        assert stage == GrowthStage.GERMINATION

        stage = tracker._determine_growth_stage(gdd_accumulated=1000, gdd_required=2700)
        assert stage == GrowthStage.VEGETATIVE


class TestCropRotationPlanner:
    """Test crop rotation planning."""

    def test_can_plant_same_family(self) -> None:
        """Test planting same family too soon."""
        planner = CropRotationPlanner()

        # Can't plant corn after corn in previous year
        can_plant = planner.can_plant(
            desired_crop_family=CropFamily.POACEAE,
            previous_crops=[(CropFamily.POACEAE, 1)],
            years_since_family=2,
        )
        assert not can_plant

    def test_can_plant_different_family(self) -> None:
        """Test planting different family."""
        planner = CropRotationPlanner()

        can_plant = planner.can_plant(
            desired_crop_family=CropFamily.FABACEAE,
            previous_crops=[(CropFamily.POACEAE, 1)],
            years_since_family=2,
        )
        assert can_plant

    def test_nitrogen_benefit_legume(self) -> None:
        """Test nitrogen credit from legumes."""
        planner = CropRotationPlanner()

        credit = planner.get_nitrogen_benefit(CropFamily.FABACEAE)
        assert credit == 50.0

    def test_nitrogen_benefit_non_legume(self) -> None:
        """Test no nitrogen credit from non-legumes."""
        planner = CropRotationPlanner()

        credit = planner.get_nitrogen_benefit(CropFamily.POACEAE)
        assert credit == 0.0


class TestCompanionPlanting:
    """Test companion planting relationships."""

    def setup_method(self) -> None:
        """Setup companion planting."""
        self.companion = CompanionPlanting()

    def test_get_beneficial_companions(self) -> None:
        """Test getting beneficial companions."""
        companions = self.companion.get_beneficial("Corn")
        assert "Beans" in companions
        assert "Squash" in companions

    def test_get_harmful_companions(self) -> None:
        """Test getting harmful companions."""
        harmful = self.companion.get_harmful("Corn")
        assert len(harmful) > 0

    def test_compatible_crops(self) -> None:
        """Test crop compatibility check."""
        # Corn and beans are compatible
        is_compatible = self.companion.are_compatible("Corn", "Beans")
        assert is_compatible

    def test_incompatible_crops(self) -> None:
        """Test incompatible crops."""
        # Beans and onions are not compatible
        is_compatible = self.companion.are_compatible("Beans", "Onions")
        assert not is_compatible


class TestYieldEstimator:
    """Test yield estimation."""

    def test_estimate_yield_full_conditions(self) -> None:
        """Test yield with optimal conditions."""
        estimator = YieldEstimator()

        yield_bu = estimator.estimate_yield(
            gdd_accumulated=2700,
            gdd_required=2700,
            water_availability_in=20.0,
            water_requirement_in=20.0,
            nitrogen_available_lbs=150,
            nitrogen_requirement_lbs=150,
            baseline_yield_bu_acre=150.0,
        )

        # Should be close to baseline
        assert yield_bu >= 140

    def test_estimate_yield_water_stress(self) -> None:
        """Test yield reduction from water stress."""
        estimator = YieldEstimator()

        yield_bu = estimator.estimate_yield(
            gdd_accumulated=2700,
            gdd_required=2700,
            water_availability_in=10.0,  # Only 50% water
            water_requirement_in=20.0,
            nitrogen_available_lbs=150,
            nitrogen_requirement_lbs=150,
            baseline_yield_bu_acre=150.0,
        )

        # Yield should be significantly reduced
        assert yield_bu < 100

    def test_estimate_yield_nitrogen_deficiency(self) -> None:
        """Test yield reduction from N deficiency."""
        estimator = YieldEstimator()

        baseline_yield_bu_acre = 150.0
        yield_bu = estimator.estimate_yield(
            gdd_accumulated=2700,
            gdd_required=2700,
            water_availability_in=20.0,
            water_requirement_in=20.0,
            nitrogen_available_lbs=50,  # Only 33% of requirement
            nitrogen_requirement_lbs=150,
            baseline_yield_bu_acre=baseline_yield_bu_acre,
        )

        # Yield should be reduced
        assert yield_bu < baseline_yield_bu_acre

    def test_estimate_yield_incomplete_season(self) -> None:
        """Test yield with incomplete growing season."""
        estimator = YieldEstimator()

        yield_bu = estimator.estimate_yield(
            gdd_accumulated=2000,  # Only 74% of GDD
            gdd_required=2700,
            water_availability_in=20.0,
            water_requirement_in=20.0,
            nitrogen_available_lbs=150,
            nitrogen_requirement_lbs=150,
            baseline_yield_bu_acre=150.0,
        )

        # Yield should be reduced proportionally to GDD
        assert yield_bu < 125
