"""
Tests for cooking science module.
"""

from decimal import Decimal

import pytest

from thomas.marketplace.food_tech._types import CookingMethod
from thomas.marketplace.food_tech.cooking import CookingScience


class TestTemperatureConversion:
    """Test temperature conversion utilities."""

    def test_celsius_to_fahrenheit(self) -> None:
        """Test Celsius to Fahrenheit conversion."""
        assert CookingScience.celsius_to_fahrenheit(Decimal("0")) == Decimal("32")
        assert CookingScience.celsius_to_fahrenheit(Decimal("100")) == Decimal("212")
        assert CookingScience.celsius_to_fahrenheit(Decimal("200")) == Decimal("392")

    def test_fahrenheit_to_celsius(self) -> None:
        """Test Fahrenheit to Celsius conversion."""
        assert CookingScience.fahrenheit_to_celsius(Decimal("32")) == Decimal("0")
        assert CookingScience.fahrenheit_to_celsius(Decimal("212")) == Decimal("100")
        # 350F is approximately 176.67C
        result = CookingScience.fahrenheit_to_celsius(Decimal("350"))
        assert Decimal("176") < result < Decimal("177")

    def test_temperature_conversion_roundtrip(self) -> None:
        """Test conversion roundtrip."""
        original = Decimal("25")

        converted = CookingScience.celsius_to_fahrenheit(original)
        back = CookingScience.fahrenheit_to_celsius(converted)

        assert abs(back - original) < Decimal("0.1")


class TestVolumeConversion:
    """Test volume conversion utilities."""

    def test_cup_to_ml(self) -> None:
        """Test cup to milliliter conversion."""
        ml = CookingScience.convert_volume(Decimal("1"), "cup", "ml")
        assert Decimal("235") < ml < Decimal("238")

    def test_ml_to_cup(self) -> None:
        """Test milliliter to cup conversion."""
        cup = CookingScience.convert_volume(Decimal("237"), "ml", "cup")
        assert Decimal("0.99") < cup < Decimal("1.01")

    def test_tbsp_to_ml(self) -> None:
        """Test tablespoon to milliliter conversion."""
        ml = CookingScience.convert_volume(Decimal("1"), "tbsp", "ml")
        assert Decimal("14") < ml < Decimal("15")

    def test_invalid_volume_unit(self) -> None:
        """Test conversion with invalid unit."""
        with pytest.raises(ValueError):
            CookingScience.convert_volume(Decimal("1"), "invalid", "ml")


class TestWeightConversion:
    """Test weight conversion utilities."""

    def test_gram_to_ounce(self) -> None:
        """Test gram to ounce conversion."""
        oz = CookingScience.convert_weight(Decimal("28.35"), "g", "oz")
        assert Decimal("0.99") < oz < Decimal("1.01")

    def test_ounce_to_gram(self) -> None:
        """Test ounce to gram conversion."""
        g = CookingScience.convert_weight(Decimal("1"), "oz", "g")
        assert Decimal("28") < g < Decimal("29")

    def test_pound_to_gram(self) -> None:
        """Test pound to gram conversion."""
        g = CookingScience.convert_weight(Decimal("1"), "lb", "g")
        assert Decimal("453") < g < Decimal("454")

    def test_invalid_weight_unit(self) -> None:
        """Test conversion with invalid unit."""
        with pytest.raises(ValueError):
            CookingScience.convert_weight(Decimal("1"), "invalid", "g")


class TestCookingTimeEstimation:
    """Test cooking time estimation."""

    def test_estimate_cooking_time_baking(self) -> None:
        """Test cooking time estimation for baking."""
        time_min = CookingScience.estimate_cooking_time(Decimal("500"), CookingMethod.BAKING)

        assert time_min > 0
        assert time_min < 60

    def test_estimate_cooking_time_grilling(self) -> None:
        """Test cooking time estimation for grilling."""
        time_min = CookingScience.estimate_cooking_time(Decimal("200"), CookingMethod.GRILLING)

        assert time_min > 0
        assert time_min < 30

    def test_cooking_time_scales_with_weight(self) -> None:
        """Test that cooking time scales with weight."""
        time_light = CookingScience.estimate_cooking_time(Decimal("200"), CookingMethod.ROASTING)
        time_heavy = CookingScience.estimate_cooking_time(Decimal("400"), CookingMethod.ROASTING)

        assert time_heavy > time_light

    def test_cooking_time_with_thickness(self) -> None:
        """Test cooking time with thickness adjustment."""
        time_thin = CookingScience.estimate_cooking_time(Decimal("200"), CookingMethod.GRILLING, Decimal("1"))
        time_thick = CookingScience.estimate_cooking_time(Decimal("200"), CookingMethod.GRILLING, Decimal("3"))

        assert time_thick > time_thin


class TestFoodSafety:
    """Test food safety temperature guidelines."""

    def test_poultry_safe_temperature(self) -> None:
        """Test poultry safe internal temperature."""
        temp, desc = CookingScience.get_safe_internal_temperature("chicken")
        assert temp == Decimal("165")
        assert "Poultry" in desc

    def test_ground_meat_safe_temperature(self) -> None:
        """Test ground meat safe internal temperature."""
        temp, desc = CookingScience.get_safe_internal_temperature("ground beef")
        assert temp == Decimal("160")

    def test_fish_safe_temperature(self) -> None:
        """Test fish safe internal temperature."""
        temp, desc = CookingScience.get_safe_internal_temperature("salmon")
        assert temp == Decimal("145")

    def test_beef_steak_safe_temperature(self) -> None:
        """Test beef steak safe internal temperature."""
        temp, desc = CookingScience.get_safe_internal_temperature("steak")
        assert temp == Decimal("145")


class TestEnergyEfficiency:
    """Test energy efficiency rankings."""

    def test_microwave_most_efficient(self) -> None:
        """Test that microwave is most energy efficient."""
        microwave_rank = CookingScience.get_energy_efficiency_ranking(CookingMethod.MICROWAVING)
        other_rank = CookingScience.get_energy_efficiency_ranking(CookingMethod.BAKING)

        assert microwave_rank < other_rank

    def test_all_methods_ranked(self) -> None:
        """Test that all cooking methods have efficiency rankings."""
        for method in CookingMethod:
            rank = CookingScience.get_energy_efficiency_ranking(method)
            assert 1 <= rank <= 10


class TestAltitudeAdjustment:
    """Test altitude adjustment calculations."""

    def test_baking_altitude_adjustment(self) -> None:
        """Test baking adjustments for altitude."""
        adjustments = CookingScience.adjust_for_altitude(Decimal("350"), Decimal("5000"), is_baking=True)

        assert "temperature_f" in adjustments
        assert "time_increase_percent" in adjustments
        assert "liquid_increase_percent" in adjustments

        # Higher altitude should increase temperature and time
        assert adjustments["temperature_f"] > Decimal("350")
        assert adjustments["time_increase_percent"] > Decimal("0")

    def test_boiling_altitude_adjustment(self) -> None:
        """Test boiling point adjustment for altitude."""
        adjustments = CookingScience.adjust_for_altitude(Decimal("212"), Decimal("5000"), is_baking=False)

        assert "boiling_point_f" in adjustments
        assert adjustments["boiling_point_f"] < Decimal("212")

    def test_sea_level_no_adjustment(self) -> None:
        """Test that sea level has minimal adjustment."""
        adjustments = CookingScience.adjust_for_altitude(Decimal("350"), Decimal("0"), is_baking=True)

        assert adjustments["temperature_f"] == Decimal("350")
        assert adjustments["time_increase_percent"] == Decimal("0")


class TestYeastCalculations:
    """Test yeast and baking calculations."""

    def test_yeast_rise_time_at_standard_temp(self) -> None:
        """Test yeast rise time at standard temperature."""
        rise_time = CookingScience.calculate_yeast_rise_time(Decimal("70"), 60)
        assert rise_time == 60

    def test_yeast_rise_faster_at_warm_temp(self) -> None:
        """Test that yeast rises faster at warmer temperature."""
        cold_rise = CookingScience.calculate_yeast_rise_time(Decimal("60"), 60)
        warm_rise = CookingScience.calculate_yeast_rise_time(Decimal("85"), 60)

        assert warm_rise < cold_rise

    def test_baker_percentage_calculation(self) -> None:
        """Test baker's percentage calculation."""
        flour = Decimal("500")
        percent = Decimal("2")  # 2% salt

        result = CookingScience.scale_baker_percentage(flour, percent)

        assert result == Decimal("10")

    def test_water_absorption_varies_by_flour(self) -> None:
        """Test water absorption differs by flour type."""
        flour = Decimal("500")

        all_purpose = CookingScience.calculate_water_absorption(flour, "all_purpose")
        bread = CookingScience.calculate_water_absorption(flour, "bread")

        assert bread > all_purpose  # Bread flour absorbs more


class TestCookingRecommendations:
    """Test cooking method recommendations."""

    def test_chicken_recommendations(self) -> None:
        """Test cooking method recommendations for chicken."""
        methods = CookingScience.get_cooking_method_recommendations("chicken")

        assert len(methods) > 0
        assert CookingMethod.ROASTING in methods

    def test_fish_recommendations(self) -> None:
        """Test cooking method recommendations for fish."""
        methods = CookingScience.get_cooking_method_recommendations("fish")

        assert len(methods) > 0
        # Fish should include gentle methods
        assert CookingMethod.STEAMING in methods or CookingMethod.POACHING in methods

    def test_recommendations_by_efficiency(self) -> None:
        """Test that recommendations can be sorted by energy efficiency."""
        methods = CookingScience.get_cooking_method_recommendations("chicken", preferred_energy_efficiency=True)

        assert len(methods) > 1
        # First should be more efficient than last
        first_rank = CookingScience.get_energy_efficiency_ranking(methods[0])
        last_rank = CookingScience.get_energy_efficiency_ranking(methods[-1])

        assert first_rank < last_rank
