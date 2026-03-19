import pytest

pytestmark = pytest.mark.xfail(
    reason="Domain skeleton pending implementation (tracking: docs/ops/remediation/DOMAIN_STUB_TRACKING.md)",
    strict=False,
)
"""Tests for weather module."""

from datetime import date

from thomas.agriculture._types import Weather
from thomas.agriculture.weather import (
    ChillHourAccumulation,
    DroughtMonitoring,
    FrostProbabilityEstimator,
    GDDCalculator,
    HeatStressCalculator,
    PrecipitationProbability,
    WindErosionRisk,
)


class TestGDDCalculator:
    """Test GDD calculations."""

    def test_calculate_daily_gdd_positive(self) -> None:
        """Test GDD calculation with positive accumulation."""
        calculator = GDDCalculator(base_temp_f=50.0)

        gdd = calculator.calculate_daily_gdd(temp_max_f=80, temp_min_f=60)

        # (80 + 60) / 2 - 50 = 20 GDD
        assert abs(gdd - 20.0) < 0.01

    def test_calculate_daily_gdd_below_base(self) -> None:
        """Test GDD below base temperature."""
        calculator = GDDCalculator(base_temp_f=50.0)

        gdd = calculator.calculate_daily_gdd(temp_max_f=45, temp_min_f=40)

        # Below base, should be 0
        assert gdd == 0.0

    def test_accumulate_gdd_multiple_days(self) -> None:
        """Test GDD accumulation across days."""
        calculator = GDDCalculator(base_temp_f=50.0)

        weather_records = [
            Weather(
                weather_id="w1",
                location=(40, -93),
                date=date(2024, 5, 1),
                temp_max_f=75,
                temp_min_f=55,
                temp_avg_f=65,
                precipitation_in=0,
                wind_speed_mph=5,
                relative_humidity_pct=50,
                solar_radiation_ly=400,
            ),
            Weather(
                weather_id="w2",
                location=(40, -93),
                date=date(2024, 5, 2),
                temp_max_f=80,
                temp_min_f=60,
                temp_avg_f=70,
                precipitation_in=0,
                wind_speed_mph=5,
                relative_humidity_pct=50,
                solar_radiation_ly=400,
            ),
        ]

        total_gdd = calculator.accumulate_gdd(weather_records)

        # Day 1: (75+55)/2 - 50 = 15 GDD
        # Day 2: (80+60)/2 - 50 = 20 GDD
        # Total: 35 GDD
        assert abs(total_gdd - 35.0) < 0.1


class TestFrostProbabilityEstimator:
    """Test frost probability estimation."""

    def setup_method(self) -> None:
        """Setup frost estimator."""
        # 30 years of frost dates in May, centered around May 10
        frost_dates = [date(year, 5, 10 + (i % 3) - 1) for year in range(1995, 2025) for i in range(1)]
        self.estimator = FrostProbabilityEstimator(frost_dates)

    def test_calculate_average_frost_date(self) -> None:
        """Test average frost date calculation."""
        avg_date = self.estimator.calculate_average_frost_date()

        # Should be around May 10
        assert avg_date.month == 5
        assert 8 <= avg_date.day <= 12

    def test_estimate_probability_before_frost(self) -> None:
        """Test frost probability before average date."""
        # April 15 is before average May 10 frost
        probability = self.estimator.estimate_probability(date(2024, 4, 15))

        # Probability should be low
        assert 0 <= probability < 0.5

    def test_estimate_probability_after_frost(self) -> None:
        """Test frost probability after average date."""
        # May 25 is after average May 10 frost
        probability = self.estimator.estimate_probability(date(2024, 5, 25))

        # Probability should be high
        assert 0.5 < probability <= 1.0


class TestDroughtMonitoring:
    """Test drought monitoring."""

    def test_calculate_palmer_components(self) -> None:
        """Test PDSI component calculation."""
        components = DroughtMonitoring.calculate_palmer_index_components(
            precipitation_in=5.0,
            normal_precipitation_in=4.0,
            temperature_f=85,
            normal_temperature_f=75,
            soil_moisture_in=2.0,
        )

        # Should have all required components
        assert "precipitation_anomaly" in components
        assert "temperature_anomaly" in components
        assert "drought_factor" in components

    def test_drought_severity_wet(self) -> None:
        """Test drought severity for wet conditions."""
        severity = DroughtMonitoring.drought_severity(2.5)
        assert "Very Wet" in severity

    def test_drought_severity_dry(self) -> None:
        """Test drought severity for dry conditions."""
        severity = DroughtMonitoring.drought_severity(-2.5)
        assert "Severe Drought" in severity

    def test_drought_severity_normal(self) -> None:
        """Test drought severity for normal conditions."""
        severity = DroughtMonitoring.drought_severity(0.0)
        assert "Normal" in severity


class TestHeatStressCalculator:
    """Test heat stress calculations."""

    def test_identify_heat_stress_day_above_threshold(self) -> None:
        """Test identification of heat stress day."""
        is_stress = HeatStressCalculator.identify_heat_stress_day(90)
        assert is_stress

    def test_identify_heat_stress_day_below_threshold(self) -> None:
        """Test no heat stress when below threshold."""
        is_stress = HeatStressCalculator.identify_heat_stress_day(80)
        assert not is_stress

    def test_count_heat_stress_days(self) -> None:
        """Test counting heat stress days."""
        weather_records = [
            Weather(
                weather_id=f"w{i}",
                location=(40, -93),
                date=date(2024, 7, i),
                temp_max_f=90 if i % 2 == 0 else 75,
                temp_min_f=70,
                temp_avg_f=80,
                precipitation_in=0,
                wind_speed_mph=5,
                relative_humidity_pct=50,
                solar_radiation_ly=400,
            )
            for i in range(1, 11)
        ]

        stress_days = HeatStressCalculator.count_heat_stress_days(weather_records)

        # Half the days should be heat stress
        assert stress_days == 5

    def test_calculate_heat_stress_severity(self) -> None:
        """Test heat stress severity calculation."""
        severity = HeatStressCalculator.calculate_heat_stress_severity(
            max_temp_f=90,
            growing_stage="Grain Fill",
        )

        # Should be positive
        assert severity > 0

    def test_heat_stress_more_severe_at_critical_stage(self) -> None:
        """Test heat stress is worse at critical stages."""
        veg_severity = HeatStressCalculator.calculate_heat_stress_severity(90, "Vegetative")
        fill_severity = HeatStressCalculator.calculate_heat_stress_severity(90, "Grain Fill")

        # Grain fill is more critical
        assert fill_severity > veg_severity


class TestChillHourAccumulation:
    """Test chill hour calculations."""

    def test_calculate_chill_hours_optimal_range(self) -> None:
        """Test chill hours in optimal range."""
        chill = ChillHourAccumulation.calculate_chill_hours(40)

        # Within 32-45Â°F range
        assert chill == 1.0

    def test_calculate_chill_hours_below_range(self) -> None:
        """Test chill hours below optimal range."""
        chill = ChillHourAccumulation.calculate_chill_hours(20)

        # Below freezing, partial credit
        assert 0 < chill < 1.0

    def test_calculate_chill_hours_above_range(self) -> None:
        """Test chill hours above optimal range."""
        chill = ChillHourAccumulation.calculate_chill_hours(50)

        # Above range, partial credit
        assert 0 < chill < 1.0

    def test_calculate_chill_hours_too_warm(self) -> None:
        """Test no chill hours when too warm."""
        chill = ChillHourAccumulation.calculate_chill_hours(80)

        assert chill == 0.0

    def test_accumulate_chill_hours(self) -> None:
        """Test chill hour accumulation."""
        weather_records = [
            Weather(
                weather_id=f"w{i}",
                location=(40, -93),
                date=date(2024, 1, i),
                temp_max_f=50,
                temp_min_f=35 + i,  # Gradually warming
                temp_avg_f=42,
                precipitation_in=0,
                wind_speed_mph=5,
                relative_humidity_pct=50,
                solar_radiation_ly=200,
            )
            for i in range(1, 11)
        ]

        total_chill = ChillHourAccumulation.accumulate_chill_hours(weather_records)

        # Should have accumulated chill hours
        assert total_chill > 0


class TestPrecipitationProbability:
    """Test precipitation probability."""

    def test_estimate_rain_probability(self) -> None:
        """Test rain probability estimation."""
        probability = PrecipitationProbability.estimate_rain_probability(
            historical_rain_days=15,
            total_days_in_period=30,
        )

        # 15/30 = 50%
        assert abs(probability - 0.5) < 0.01

    def test_forecast_precipitation_amount(self) -> None:
        """Test precipitation forecast."""
        amount = PrecipitationProbability.forecast_precipitation_amount(
            probability=0.75,
            normal_rainfall_in=2.0,
        )

        # 75% of 2 inches = 1.5 inches
        assert abs(amount - 1.5) < 0.01


class TestWindErosionRisk:
    """Test wind erosion risk assessment."""

    def test_calculate_erosion_risk_light_wind(self) -> None:
        """Test erosion risk with light wind."""
        risk = WindErosionRisk.calculate_erosion_risk(
            wind_speed_mph=10,
            soil_texture="Sand",
            field_length_ft=1000,
            vegetative_cover=0.5,
        )

        # Should be low risk with light wind
        assert 0 <= risk < 30

    def test_calculate_erosion_risk_heavy_wind(self) -> None:
        """Test erosion risk with heavy wind."""
        risk = WindErosionRisk.calculate_erosion_risk(
            wind_speed_mph=30,
            soil_texture="Sand",
            field_length_ft=1000,
            vegetative_cover=0.5,
        )

        # Should be high risk with heavy wind
        assert risk > 50

    def test_erosion_risk_sand_vs_clay(self) -> None:
        """Test sand is more erodible than clay."""
        sand_risk = WindErosionRisk.calculate_erosion_risk(
            wind_speed_mph=20,
            soil_texture="Sand",
            field_length_ft=1000,
        )

        clay_risk = WindErosionRisk.calculate_erosion_risk(
            wind_speed_mph=20,
            soil_texture="Clay",
            field_length_ft=1000,
        )

        assert sand_risk > clay_risk

    def test_erosion_risk_vegetation_protection(self) -> None:
        """Test vegetation reduces erosion risk."""
        bare_risk = WindErosionRisk.calculate_erosion_risk(
            wind_speed_mph=20,
            soil_texture="Sand",
            field_length_ft=1000,
            vegetative_cover=0.0,
        )

        covered_risk = WindErosionRisk.calculate_erosion_risk(
            wind_speed_mph=20,
            soil_texture="Sand",
            field_length_ft=1000,
            vegetative_cover=0.8,
        )

        assert covered_risk < bare_risk
