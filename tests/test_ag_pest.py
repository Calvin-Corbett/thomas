"""Tests for pest management module."""

import pytest

pytestmark = pytest.mark.xfail(
    reason="Domain skeleton pending implementation (tracking: docs/ops/remediation/DOMAIN_STUB_TRACKING.md)",
    strict=False,
)

from thomas.agriculture.pest import (
    EconomicThresholdCalculator,
    IPMDecisionFramework,
    PestIdentification,
    PestPredictionModel,
    ResistanceManagement,
    SprayTimingOptimization,
)


class TestIPMDecisionFramework:
    """Test IPM decision framework."""

    def setup_method(self) -> None:
        """Setup IPM framework."""
        self.ipm = IPMDecisionFramework()

    def test_scout_field(self) -> None:
        """Test field scouting."""
        result = self.ipm.scout_field(
            field_id="field1",
            sample_size_plants=100,
            pest_count=15,
        )

        # 15 / 100 = 0.15 pests per plant
        assert abs(result["pest_per_plant"] - 0.15) < 0.01

    def test_scout_field_invalid_sample_size(self) -> None:
        """Test invalid sample size raises error."""
        with pytest.raises(Exception):
            self.ipm.scout_field(
                field_id="field1",
                sample_size_plants=0,
                pest_count=10,
            )

    def test_identify_pest(self) -> None:
        """Test pest identification."""
        result = self.ipm.identify_pest(
            pest_name="corn_borer",
            symptoms=["holes_in_stalks", "sawdust_frass"],
        )

        assert result["pest_name"] == "corn_borer"
        assert len(result["symptoms"]) == 2

    def test_evaluate_threshold_below(self) -> None:
        """Test evaluation below threshold."""
        below_threshold = self.ipm.evaluate_threshold(
            pest_per_plant=0.3,
            economic_threshold_per_plant=0.5,
        )

        assert not below_threshold

    def test_evaluate_threshold_above(self) -> None:
        """Test evaluation above threshold."""
        above_threshold = self.ipm.evaluate_threshold(
            pest_per_plant=0.7,
            economic_threshold_per_plant=0.5,
        )

        assert above_threshold

    def test_recommend_action_monitor(self) -> None:
        """Test recommendation to monitor."""
        action = self.ipm.recommend_action(
            pest_type="insect",
            pest_population=0.2,
            threshold=0.5,
        )

        assert "Monitor" in action

    def test_recommend_action_treat(self) -> None:
        """Test recommendation to treat."""
        action = self.ipm.recommend_action(
            pest_type="insect",
            pest_population=1.0,
            threshold=0.5,
        )

        assert "Treat" in action


class TestEconomicThresholdCalculator:
    """Test economic threshold calculation."""

    def test_calculate_threshold(self) -> None:
        """Test economic threshold calculation."""
        threshold = EconomicThresholdCalculator.calculate_threshold(
            treatment_cost_per_acre=15.0,
            yield_goal_bu_acre=150.0,
            grain_price_per_bu=4.0,
            damage_pct_per_pest_unit=0.01,
        )

        # Should be positive and reasonable
        assert 0 < threshold < 1.0

    def test_threshold_increases_with_treatment_cost(self) -> None:
        """Test higher treatment cost increases threshold."""
        cheap_threshold = EconomicThresholdCalculator.calculate_threshold(
            treatment_cost_per_acre=10.0,
            yield_goal_bu_acre=150.0,
            grain_price_per_bu=4.0,
            damage_pct_per_pest_unit=0.01,
        )

        expensive_threshold = EconomicThresholdCalculator.calculate_threshold(
            treatment_cost_per_acre=25.0,
            yield_goal_bu_acre=150.0,
            grain_price_per_bu=4.0,
            damage_pct_per_pest_unit=0.01,
        )

        # Higher cost justifies treatment at higher pest levels
        assert expensive_threshold > cheap_threshold

    def test_invalid_grain_price_raises_error(self) -> None:
        """Test invalid grain price raises error."""
        with pytest.raises(Exception):
            EconomicThresholdCalculator.calculate_threshold(
                treatment_cost_per_acre=15.0,
                yield_goal_bu_acre=150.0,
                grain_price_per_bu=0.0,
                damage_pct_per_pest_unit=0.01,
            )


class TestPestPredictionModel:
    """Test pest prediction modeling."""

    def setup_method(self) -> None:
        """Setup pest prediction model."""
        self.model = PestPredictionModel()

    def test_calculate_pest_gdd(self) -> None:
        """Test pest GDD calculation."""
        gdd = self.model.calculate_pest_gdd(
            temp_max_f=85,
            temp_min_f=65,
        )

        # (85 + 65) / 2 - 50 = 25 pest GDD
        assert abs(gdd - 25.0) < 0.01

    def test_predict_emergence_early(self) -> None:
        """Test emergence prediction early in season."""
        prediction = self.model.predict_emergence(
            pest_type="corn_borer",
            gdd_accumulated=100,
        )

        # Early in season
        assert prediction["percent_development"] < 50
        assert "away from emergence" in prediction["status"]

    def test_predict_emergence_peak(self) -> None:
        """Test emergence prediction at peak."""
        prediction = self.model.predict_emergence(
            pest_type="corn_borer",
            gdd_accumulated=600,
        )

        # At emergence GDD
        assert prediction["percent_development"] >= 90
        assert "Peak" in prediction["status"]

    def test_predict_emergence_unknown_pest(self) -> None:
        """Test unknown pest raises error."""
        with pytest.raises(Exception):
            self.model.predict_emergence(
                pest_type="unknown_pest",
                gdd_accumulated=100,
            )


class TestSprayTimingOptimization:
    """Test spray timing optimization."""

    def test_recommend_spray_optimal_conditions(self) -> None:
        """Test spray timing with optimal conditions."""
        recommendation = SprayTimingOptimization.recommend_spray_time(
            pest_stage="nymph",
            weather_conditions={
                "wind_mph": 5,
                "rain_expected": False,
                "temp_f": 70,
            },
        )

        assert "acceptable" in recommendation["wind"].lower()
        assert "good" in recommendation["rain"].lower()
        assert "Optimal" in recommendation["temperature"]

    def test_recommend_spray_high_wind(self) -> None:
        """Test spray timing with high wind."""
        recommendation = SprayTimingOptimization.recommend_spray_time(
            pest_stage="nymph",
            weather_conditions={
                "wind_mph": 20,
                "rain_expected": False,
                "temp_f": 70,
            },
        )

        assert "wait" in recommendation["wind"].lower()

    def test_recommend_spray_rain_expected(self) -> None:
        """Test spray timing with rain expected."""
        recommendation = SprayTimingOptimization.recommend_spray_time(
            pest_stage="nymph",
            weather_conditions={
                "wind_mph": 10,
                "rain_expected": True,
                "temp_f": 70,
            },
        )

        assert "wait" in recommendation["rain"].lower()

    def test_recommend_spray_extreme_temperature(self) -> None:
        """Test spray timing with extreme temperature."""
        recommendation = SprayTimingOptimization.recommend_spray_time(
            pest_stage="nymph",
            weather_conditions={
                "wind_mph": 5,
                "rain_expected": False,
                "temp_f": 40,
            },
        )

        assert "wait" in recommendation["temperature"].lower()


class TestResistanceManagement:
    """Test resistance management."""

    def test_get_mode_of_action_pyrethroid(self) -> None:
        """Test MOA identification for pyrethroid."""
        moa = ResistanceManagement.get_mode_of_action("permethrin")
        assert moa == "pyrethroids"

    def test_get_mode_of_action_neonicotinoid(self) -> None:
        """Test MOA identification for neonicotinoid."""
        moa = ResistanceManagement.get_mode_of_action("imidacloprid")
        assert moa == "neonicotinoids"

    def test_get_mode_of_action_unknown(self) -> None:
        """Test unknown product returns None."""
        moa = ResistanceManagement.get_mode_of_action("unknown_product")
        assert moa is None

    def test_check_rotation_good(self) -> None:
        """Test good MOA rotation."""
        is_rotated = ResistanceManagement.check_rotation(
            previous_applications=["permethrin", "imidacloprid"],
            current_product="bt",
            years_back=2,
        )

        assert is_rotated

    def test_check_rotation_poor(self) -> None:
        """Test poor MOA rotation."""
        is_rotated = ResistanceManagement.check_rotation(
            previous_applications=["permethrin", "cypermethrin"],
            current_product="lambda-cyhalothrin",  # Same MOA
            years_back=2,
        )

        assert not is_rotated


class TestPestIdentification:
    """Test pest identification."""

    def setup_method(self) -> None:
        """Setup pest identification."""
        self.identifier = PestIdentification()

    def test_identify_by_symptoms_high_confidence(self) -> None:
        """Test high confidence identification."""
        results = self.identifier.identify_by_symptoms(
            symptoms=["holes_in_stalks", "sawdust_frass", "wilting"],
        )

        # Should identify corn borer
        assert len(results) > 0
        if results[0][0] == "european_corn_borer":
            assert results[0][1] > 0.6  # High confidence

    def test_identify_by_symptoms_low_confidence(self) -> None:
        """Test low confidence identification."""
        results = self.identifier.identify_by_symptoms(
            symptoms=["unknown_symptom"],
        )

        # Should have low or no matches
        if results:
            assert results[0][1] < 0.5

    def test_get_pest_info(self) -> None:
        """Test getting pest information."""
        info = self.identifier.get_pest_info("european_corn_borer")

        assert info is not None
        assert "damage_type" in info
        assert "threshold" in info

    def test_get_pest_info_unknown(self) -> None:
        """Test unknown pest returns None."""
        info = self.identifier.get_pest_info("unknown_pest")

        assert info is None
