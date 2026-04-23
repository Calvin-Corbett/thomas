import pytest

pytestmark = pytest.mark.xfail(
    reason="Domain skeleton pending implementation (tracking: docs/ops/remediation/DOMAIN_STUB_TRACKING.md)",
    strict=False,
)
"""Tests for irrigation module."""

from thomas.marketplace.agriculture._types import IrrigationType
from thomas.marketplace.agriculture.irrigation import (
    CropWaterRequirement,
    DeficitIrrigationStrategy,
    FerrtigationCalculator,
    IrrigationEfficiency,
    IrrigationScheduler,
    PumpSizing,
    SoilMoistureBalance,
)


class TestCropWaterRequirement:
    """Test crop water requirement calculations."""

    def test_get_crop_coefficient_initial(self) -> None:
        """Test crop coefficient at initial growth stage."""
        cwr = CropWaterRequirement()

        kc = cwr.get_crop_coefficient(gdd_accumulated=100, gdd_required=2700)
        # Early season should be ~0.3
        assert 0.25 < kc < 0.35

    def test_get_crop_coefficient_midseason(self) -> None:
        """Test crop coefficient at mid-season."""
        cwr = CropWaterRequirement()

        kc = cwr.get_crop_coefficient(gdd_accumulated=1400, gdd_required=2700)
        # Mid-season should be ~0.95
        assert 0.85 < kc < 1.0

    def test_calculate_daily_et(self) -> None:
        """Test daily ET calculation."""
        cwr = CropWaterRequirement()

        et = cwr.calculate_daily_et(
            reference_et_in=0.3,
            gdd_accumulated=1400,
            gdd_required=2700,
        )

        # ET should be reference * Kc
        assert et > 0.2


class TestSoilMoistureBalance:
    """Test soil moisture balance calculations."""

    def test_positive_balance(self) -> None:
        """Test positive moisture balance."""
        smb = SoilMoistureBalance()

        moisture = smb.calculate_daily_balance(
            previous_moisture_in=2.0,
            precipitation_in=0.5,
            irrigation_in=0.0,
            et_in=0.3,
            percolation_in=0.1,
        )

        # 2.0 + 0.5 - 0.3 - 0.1 = 2.1
        assert abs(moisture - 2.1) < 0.01

    def test_negative_balance_prevented(self) -> None:
        """Test negative moisture is prevented."""
        smb = SoilMoistureBalance()

        moisture = smb.calculate_daily_balance(
            previous_moisture_in=0.5,
            precipitation_in=0.0,
            irrigation_in=0.0,
            et_in=1.0,
            percolation_in=0.0,
        )

        # Should not go negative
        assert moisture >= 0.0


class TestIrrigationScheduler:
    """Test irrigation scheduling."""

    def setup_method(self) -> None:
        """Setup irrigation scheduler."""
        self.scheduler = IrrigationScheduler(
            available_water_capacity_in=1.5,
            management_allowable_depletion=0.5,
        )

    def test_depletion_threshold(self) -> None:
        """Test depletion threshold calculation."""
        threshold = self.scheduler.calculate_depletion_threshold()

        # Should be 50% of 1.5 = 0.75
        assert abs(threshold - 0.75) < 0.01

    def test_irrigation_needed_below_threshold(self) -> None:
        """Test irrigation needed when below threshold."""
        needed = self.scheduler.is_irrigation_needed(current_moisture_in=0.5)
        assert needed

    def test_no_irrigation_above_threshold(self) -> None:
        """Test no irrigation needed above threshold."""
        needed = self.scheduler.is_irrigation_needed(current_moisture_in=1.0)
        assert not needed

    def test_calculate_irrigation_amount(self) -> None:
        """Test irrigation amount calculation."""
        amount = self.scheduler.calculate_irrigation_amount(
            current_moisture_in=0.5,
            target_moisture_in=1.5,
        )

        # Should be 1.5 - 0.5 = 1.0
        assert abs(amount - 1.0) < 0.01


class TestIrrigationEfficiency:
    """Test irrigation efficiency calculations."""

    def test_efficiency_drip(self) -> None:
        """Test high efficiency for drip."""
        efficiency = IrrigationEfficiency.get_efficiency(IrrigationType.DRIP)
        assert efficiency == 0.95

    def test_efficiency_flood(self) -> None:
        """Test lower efficiency for flood."""
        efficiency = IrrigationEfficiency.get_efficiency(IrrigationType.FLOOD)
        assert efficiency == 0.60

    def test_water_requirement_calculation(self) -> None:
        """Test water requirement accounting for efficiency."""
        needed = IrrigationEfficiency.calculate_water_requirement(
            needed_depth_in=1.0,
            irrigation_type=IrrigationType.DRIP,
        )

        # 1.0 / 0.95 = 1.053
        assert abs(needed - 1.053) < 0.01

    def test_water_requirement_flood_vs_drip(self) -> None:
        """Test flood system needs more water than drip."""
        flood_water = IrrigationEfficiency.calculate_water_requirement(
            needed_depth_in=1.0,
            irrigation_type=IrrigationType.FLOOD,
        )

        drip_water = IrrigationEfficiency.calculate_water_requirement(
            needed_depth_in=1.0,
            irrigation_type=IrrigationType.DRIP,
        )

        assert flood_water > drip_water


class TestFerrtigationCalculator:
    """Test fertigation calculations."""

    def setup_method(self) -> None:
        """Setup fertigation calculator."""
        self.calc = FerrtigationCalculator()

    def test_nutrient_concentration(self) -> None:
        """Test nutrient concentration calculation."""
        concentration = self.calc.calculate_nutrient_concentration(
            nutrient_amount_lbs_acre=50.0,
            irrigation_depth_in=1.0,
        )

        # Should be positive
        assert concentration > 0

    def test_injection_rate_calculation(self) -> None:
        """Test fertilizer injection rate."""
        injection_rate = self.calc.calculate_application_rate(
            desired_ppm=100.0,
            irrigation_rate_gpm=50.0,
            duration_hours=2.0,
        )

        # Should be positive and reasonable
        assert 0 < injection_rate < 10


class TestPumpSizing:
    """Test pump sizing calculations."""

    def test_required_flow_rate(self) -> None:
        """Test required flow rate calculation."""
        gpm = PumpSizing.calculate_required_flow(
            total_area_acres=100.0,
            irrigation_depth_in=1.0,
            application_hours=24.0,
        )

        # 100 acres Ã— 1 in Ã— 27,154 gal/acre/in / (24 hrs Ã— 60 min/hr)
        # = 2,715,400 / 1,440 = 1,887 GPM
        assert 1800 < gpm < 2000

    def test_required_flow_high_application_speed(self) -> None:
        """Test flow for faster application."""
        gpm_24hr = PumpSizing.calculate_required_flow(
            total_area_acres=100.0,
            irrigation_depth_in=1.0,
            application_hours=24.0,
        )

        gpm_12hr = PumpSizing.calculate_required_flow(
            total_area_acres=100.0,
            irrigation_depth_in=1.0,
            application_hours=12.0,
        )

        # 12 hour application needs double the flow
        assert abs(gpm_12hr - (gpm_24hr * 2)) < 100

    def test_total_dynamic_head(self) -> None:
        """Test total dynamic head calculation."""
        head = PumpSizing.calculate_pressure_head_ft(
            elevation_change_ft=50.0,
            friction_loss_psi=10.0,
            operating_pressure_psi=50.0,
        )

        # 50 + (10 Ã— 2.31) + (50 Ã— 2.31)
        # = 50 + 23.1 + 115.5 = 188.6
        assert 185 < head < 195


class TestDeficitIrrigationStrategy:
    """Test deficit irrigation strategy."""

    def test_deficit_with_full_water_available(self) -> None:
        """Test deficit irrigation returns full requirement when water available."""
        recommended = DeficitIrrigationStrategy.calculate_deficit_strategy(
            full_requirement_in=20.0,
            available_water_in=25.0,
            yield_reduction_tolerance=0.10,
        )

        assert abs(recommended - 20.0) < 0.1

    def test_deficit_with_limited_water(self) -> None:
        """Test deficit irrigation with limited water."""
        recommended = DeficitIrrigationStrategy.calculate_deficit_strategy(
            full_requirement_in=20.0,
            available_water_in=10.0,
            yield_reduction_tolerance=0.10,
        )

        # Should be between available water and full requirement
        assert 9 < recommended < 11

    def test_deficit_yield_tolerance_effect(self) -> None:
        """Test yield tolerance affects water recommendation."""
        lower_tolerance = DeficitIrrigationStrategy.calculate_deficit_strategy(
            full_requirement_in=20.0,
            available_water_in=15.0,
            yield_reduction_tolerance=0.05,  # Want to limit yield loss
        )

        higher_tolerance = DeficitIrrigationStrategy.calculate_deficit_strategy(
            full_requirement_in=20.0,
            available_water_in=15.0,
            yield_reduction_tolerance=0.20,  # Accept more yield loss
        )

        # Higher tolerance allows less water application
        assert higher_tolerance <= lower_tolerance
