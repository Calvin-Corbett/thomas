"""Tests for nutrients module."""

import pytest

pytestmark = pytest.mark.xfail(
    reason="Domain skeleton pending implementation (tracking: docs/ops/remediation/DOMAIN_STUB_TRACKING.md)",
    strict=False,
)

from thomas.agriculture.nutrients import (
    FertilizerBlendCalculator,
    FertilizerRecommendation,
    ManureCrediting,
    NutrientBudget,
    SoilTestInterpretation,
    VariableRatePrescription,
)


class TestSoilTestInterpretation:
    """Test soil test result interpretation."""

    def test_interpret_nitrogen_low(self) -> None:
        """Test low nitrogen interpretation."""
        result = SoilTestInterpretation.interpret_nutrient_level(
            nutrient="nitrogen",
            crop="corn",
            test_value=5.0,
        )
        assert result == "Low"

    def test_interpret_nitrogen_medium(self) -> None:
        """Test medium nitrogen interpretation."""
        result = SoilTestInterpretation.interpret_nutrient_level(
            nutrient="nitrogen",
            crop="corn",
            test_value=30.0,
        )
        assert "Medium" in result

    def test_interpret_phosphorus_high(self) -> None:
        """Test high phosphorus interpretation."""
        result = SoilTestInterpretation.interpret_nutrient_level(
            nutrient="phosphorus",
            crop="corn",
            test_value=60.0,
        )
        assert result == "High"

    def test_unknown_nutrient_raises_error(self) -> None:
        """Test unknown nutrient raises error."""
        with pytest.raises(Exception):
            SoilTestInterpretation.interpret_nutrient_level(
                nutrient="unknown",
                crop="corn",
                test_value=20.0,
            )

    def test_unknown_crop_raises_error(self) -> None:
        """Test unknown crop raises error."""
        with pytest.raises(Exception):
            SoilTestInterpretation.interpret_nutrient_level(
                nutrient="nitrogen",
                crop="unknown_crop",
                test_value=20.0,
            )


class TestFertilizerRecommendation:
    """Test fertilizer recommendations."""

    def test_recommend_nitrogen_positive(self) -> None:
        """Test positive nitrogen recommendation."""
        recommended_n = FertilizerRecommendation.recommend_nitrogen(
            yield_goal_bu_acre=150.0,
            soil_nitrate_n_ppm=10.0,
            previous_crop_n_credit_lbs=0.0,
            organic_matter_pct=2.5,
        )

        # Should be positive
        assert recommended_n > 0

    def test_recommend_nitrogen_with_legume_credit(self) -> None:
        """Test nitrogen recommendation with legume credit."""
        with_credit = FertilizerRecommendation.recommend_nitrogen(
            yield_goal_bu_acre=150.0,
            soil_nitrate_n_ppm=10.0,
            previous_crop_n_credit_lbs=50.0,
            organic_matter_pct=2.5,
        )

        without_credit = FertilizerRecommendation.recommend_nitrogen(
            yield_goal_bu_acre=150.0,
            soil_nitrate_n_ppm=10.0,
            previous_crop_n_credit_lbs=0.0,
            organic_matter_pct=2.5,
        )

        # With credit should require less N
        assert with_credit < without_credit

    def test_recommend_phosphorus(self) -> None:
        """Test phosphorus recommendation."""
        recommended_p = FertilizerRecommendation.recommend_phosphorus(
            yield_goal_bu_acre=150.0,
            soil_phosphorus_lbs=15.0,
        )

        # Should be positive
        assert recommended_p > 0

    def test_recommend_phosphorus_high_soil_level(self) -> None:
        """Test P recommendation with high soil level."""
        recommended_p = FertilizerRecommendation.recommend_phosphorus(
            yield_goal_bu_acre=150.0,
            soil_phosphorus_lbs=40.0,  # High level
        )

        # Should be low or zero
        assert recommended_p < 15

    def test_recommend_potassium(self) -> None:
        """Test potassium recommendation."""
        recommended_k = FertilizerRecommendation.recommend_potassium(
            yield_goal_bu_acre=150.0,
            soil_potassium_lbs=100.0,
        )

        # Should be positive
        assert recommended_k > 0


class TestFertilizerBlendCalculator:
    """Test fertilizer blend calculations."""

    def test_calculate_blend(self) -> None:
        """Test fertilizer blend calculation."""
        blend = FertilizerBlendCalculator.calculate_blend(
            target_n_lbs=150.0,
            target_p_lbs=45.0,
            target_k_lbs=40.0,
        )

        # Should have all three components
        assert "Urea (46-0-0)" in blend
        assert "TSP (0-46-0)" in blend
        assert "MOP (0-0-60)" in blend
        assert "Total Application Rate (lbs/acre)" in blend

    def test_blend_no_nitrogen(self) -> None:
        """Test blend with no nitrogen needed."""
        blend = FertilizerBlendCalculator.calculate_blend(
            target_n_lbs=0.0,
            target_p_lbs=30.0,
            target_k_lbs=30.0,
        )

        # Should not have urea
        assert blend.get("Urea (46-0-0)", 0) == 0

    def test_blend_rates_are_positive(self) -> None:
        """Test all blend rates are positive."""
        blend = FertilizerBlendCalculator.calculate_blend(
            target_n_lbs=100.0,
            target_p_lbs=40.0,
            target_k_lbs=35.0,
        )

        for key, value in blend.items():
            if isinstance(value, (int, float)):
                assert value >= 0


class TestVariableRatePrescription:
    """Test variable rate prescription creation."""

    def test_create_zones(self) -> None:
        """Test zone creation from yield and soil data."""
        yield_data = [100, 120, 140, 150, 160, 170, 180]
        soil_data = [10, 15, 20, 25, 30, 35, 40]

        zones = VariableRatePrescription.create_zones(
            yield_history=yield_data,
            soil_test_values=soil_data,
            num_zones=3,
        )

        # Should create 3 zones
        assert len(zones) == 3
        assert all(len(z) == 3 for z in zones)

    def test_generate_vr_map(self) -> None:
        """Test VR map generation."""
        zones = [
            ("Low", 0.2, 0.4),
            ("Medium", 0.4, 0.7),
            ("High", 0.7, 1.0),
        ]

        vr_map = VariableRatePrescription.generate_vr_map(
            zones=zones,
            base_nitrogen_lbs=150.0,
        )

        # Low zone should get less nitrogen
        assert vr_map["Low"] < vr_map["Medium"]
        # High zone should get more nitrogen
        assert vr_map["High"] > vr_map["Medium"]


class TestNutrientBudget:
    """Test nutrient budget calculations."""

    def test_positive_balance(self) -> None:
        """Test positive nitrogen balance."""
        balance = NutrientBudget.calculate_annual_budget(
            nitrogen_applied_lbs=150.0,
            nitrogen_harvested_lbs=100.0,
            nitrogen_leached_lbs=10.0,
            nitrogen_gaseous_loss_lbs=5.0,
        )

        # 150 - (100 + 10 + 5) = 35
        assert abs(balance - 35) < 0.1

    def test_negative_balance(self) -> None:
        """Test negative nitrogen balance."""
        balance = NutrientBudget.calculate_annual_budget(
            nitrogen_applied_lbs=100.0,
            nitrogen_harvested_lbs=100.0,
            nitrogen_leached_lbs=20.0,
            nitrogen_gaseous_loss_lbs=10.0,
        )

        # 100 - (100 + 20 + 10) = -30
        assert balance < 0

    def test_balanced_budget(self) -> None:
        """Test balanced nitrogen budget."""
        balance = NutrientBudget.calculate_annual_budget(
            nitrogen_applied_lbs=150.0,
            nitrogen_harvested_lbs=110.0,
            nitrogen_leached_lbs=20.0,
            nitrogen_gaseous_loss_lbs=20.0,
        )

        # 150 - (110 + 20 + 20) = 0
        assert abs(balance) < 0.1


class TestManureCrediting:
    """Test manure nutrient crediting."""

    def test_cattle_manure_content(self) -> None:
        """Test cattle manure nutrient content."""
        content = ManureCrediting.get_nutrient_content(
            animal_type="cattle",
            manure_tons_acre=10.0,
        )

        # Should have N, P, K
        assert "nitrogen" in content
        assert "phosphorus" in content
        assert "potassium" in content

        # 10 tons Ã— 10 lbs/ton = 100 lbs N
        assert abs(content["nitrogen"] - 100) < 1

    def test_swine_manure_higher_nitrogen(self) -> None:
        """Test swine manure has more N than cattle."""
        cattle = ManureCrediting.get_nutrient_content("cattle", 1.0)
        swine = ManureCrediting.get_nutrient_content("swine", 1.0)

        assert swine["nitrogen"] > cattle["nitrogen"]

    def test_first_year_availability(self) -> None:
        """Test first-year nitrogen availability."""
        total_n = 100.0
        available_n = ManureCrediting.calculate_available_nitrogen(
            manure_nitrogen_total_lbs=total_n,
            first_year_availability=0.3,
        )

        # Should be 30% of total
        assert abs(available_n - 30.0) < 0.1

    def test_available_nitrogen_reasonable_fraction(self) -> None:
        """Test available nitrogen is less than total."""
        available_n = ManureCrediting.calculate_available_nitrogen(
            manure_nitrogen_total_lbs=100.0,
            first_year_availability=0.3,
        )

        # Should be less than 100
        assert available_n < 100.0
