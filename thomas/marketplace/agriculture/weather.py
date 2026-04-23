"""Weather module for agricultural weather analysis and risk assessment."""

from datetime import date, timedelta
from statistics import mean, stdev

from thomas.marketplace.agriculture._exceptions import WeatherError
from thomas.marketplace.agriculture._types import Weather


class GDDCalculator:
    """Calculates Growing Degree Days for crop development."""

    def __init__(self, base_temp_f: float = 50.0) -> None:
        """Initialize GDD calculator.

        Args:
            base_temp_f: Base temperature for GDD calculation
        """
        self.base_temp = base_temp_f

    def calculate_daily_gdd(
        self,
        temp_max_f: float,
        temp_min_f: float,
    ) -> float:
        """Calculate GDD for a single day.

        Standard method: GDD = ((Tmax + Tmin) / 2) - Tbase

        Args:
            temp_max_f: Daily maximum temperature
            temp_min_f: Daily minimum temperature

        Returns:
            GDD for the day (minimum 0)
        """
        avg_temp = (temp_max_f + temp_min_f) / 2.0
        gdd = max(0, avg_temp - self.base_temp)
        return gdd

    def accumulate_gdd(self, weather_records: list[Weather]) -> float:
        """Accumulate GDD across multiple days.

        Args:
            weather_records: List of Weather objects in chronological order

        Returns:
            Total accumulated GDD
        """
        total_gdd = 0.0
        for weather in sorted(weather_records, key=lambda w: w.date):
            gdd = self.calculate_daily_gdd(weather.temp_max_f, weather.temp_min_f)
            total_gdd += gdd
        return total_gdd


class FrostProbabilityEstimator:
    """Estimates frost probability from historical data."""

    def __init__(
        self,
        historical_frost_dates: list[date],
    ) -> None:
        """Initialize frost probability estimator.

        Args:
            historical_frost_dates: List of historical frost dates (30+ years ideal)
        """
        self.frost_dates = sorted(historical_frost_dates)

    def calculate_average_frost_date(self) -> date:
        """Calculate average frost date from historical data.

        Returns:
            Date object representing average frost date
        """
        if not self.frost_dates:
            raise WeatherError("No frost data available")

        # Convert to day of year
        day_of_year_values = [d.timetuple().tm_yday for d in self.frost_dates]
        avg_day = int(mean(day_of_year_values))

        # Reconstruct date (assume 2024 non-leap year for consistency)
        try:
            return date(2024, 1, 1) + timedelta(days=avg_day - 1)
        except ValueError:
            return date(2024, 12, 31)

    def estimate_probability(self, target_date: date) -> float:
        """Estimate probability of frost by given date.

        Uses normal distribution fit to historical data.

        Args:
            target_date: Date to estimate frost probability

        Returns:
            Probability of frost (0-1)
        """
        if len(self.frost_dates) < 2:
            return 0.5  # Insufficient data

        day_of_year_values = [d.timetuple().tm_yday for d in self.frost_dates]
        mean_day = mean(day_of_year_values)
        std_dev = stdev(day_of_year_values) if len(day_of_year_values) > 1 else 20

        target_day = target_date.timetuple().tm_yday

        # Simple normal distribution: probability frost occurs by target date
        z_score = (target_day - mean_day) / std_dev if std_dev > 0 else 0
        # Simplified normal CDF approximation
        probability = 0.5 * (1 + (z_score / (1 + abs(z_score) * 0.2)))
        return min(1.0, max(0.0, probability))


class DroughtMonitoring:
    """Monitors drought conditions using PDSI-like calculations."""

    @staticmethod
    def calculate_palmer_index_components(
        precipitation_in: float,
        normal_precipitation_in: float,
        temperature_f: float,
        normal_temperature_f: float,
        soil_moisture_in: float,
    ) -> dict[str, float]:
        """Calculate components for Palmer Drought Severity Index.

        Args:
            precipitation_in: Current precipitation
            normal_precipitation_in: Historical average precipitation
            temperature_f: Current temperature
            normal_temperature_f: Historical average temperature
            soil_moisture_in: Current available soil moisture

        Returns:
            Dictionary with PDSI components
        """
        # Precipitation anomaly
        precip_anomaly = precipitation_in - normal_precipitation_in

        # Temperature anomaly
        temp_anomaly = temperature_f - normal_temperature_f

        # Drought factor combines both
        drought_factor = temp_anomaly * 0.5 - precip_anomaly * 0.3

        return {
            "precipitation_anomaly": precip_anomaly,
            "temperature_anomaly": temp_anomaly,
            "drought_factor": round(drought_factor, 2),
            "soil_moisture_level": soil_moisture_in,
        }

    @staticmethod
    def drought_severity(pdsi_value: float) -> str:
        """Interpret PDSI value as drought severity.

        Args:
            pdsi_value: Palmer Drought Severity Index value

        Returns:
            Drought severity classification
        """
        if pdsi_value > 2:
            return "Very Wet"
        elif pdsi_value > 1:
            return "Wet"
        elif pdsi_value > 0.5:
            return "Slightly Wet"
        elif pdsi_value > -0.5:
            return "Normal"
        elif pdsi_value > -1:
            return "Slightly Dry"
        elif pdsi_value > -2:
            return "Moderate Drought"
        else:
            return "Severe Drought"


class HeatStressCalculator:
    """Calculates heat stress days and effects on crops."""

    @staticmethod
    def identify_heat_stress_day(temp_max_f: float) -> bool:
        """Identify heat stress day for crops.

        Corn heat stress typically occurs above 86°F.

        Args:
            temp_max_f: Daily maximum temperature

        Returns:
            True if heat stress day
        """
        return temp_max_f > 86

    @staticmethod
    def count_heat_stress_days(weather_records: list[Weather]) -> int:
        """Count heat stress days in period.

        Args:
            weather_records: List of Weather objects

        Returns:
            Number of heat stress days
        """
        count = 0
        for weather in weather_records:
            if HeatStressCalculator.identify_heat_stress_day(weather.temp_max_f):
                count += 1
        return count

    @staticmethod
    def calculate_heat_stress_severity(
        max_temp_f: float,
        growing_stage: str,
    ) -> float:
        """Calculate heat stress severity score.

        Heat stress is more damaging during critical flowering/grain fill stages.

        Args:
            max_temp_f: Daily maximum temperature
            growing_stage: Crop growth stage

        Returns:
            Severity score (0-10, where 10 is most severe)
        """
        if max_temp_f < 86:
            return 0.0

        # Base severity
        severity = (max_temp_f - 86) * 0.2

        # Stage multiplier: most critical during grain fill
        stage_multiplier = {
            "Vegetative": 0.5,
            "Flowering": 2.0,
            "Grain Fill": 2.5,
            "Maturity": 0.5,
        }.get(growing_stage, 1.0)

        return min(10.0, severity * stage_multiplier)


class ChillHourAccumulation:
    """Accumulates chill hours for fruit tree dormancy."""

    @staticmethod
    def calculate_chill_hours(
        temp_f: float,
    ) -> float:
        """Calculate chill hours for one day.

        Chill hours: hours between 32°F and 45°F (used for fruit tree dormancy).

        Args:
            temp_f: Temperature in Fahrenheit

        Returns:
            Chill hours (0, 0.5, or 1.0)
        """
        if 32 <= temp_f <= 45:
            return 1.0
        elif (45 < temp_f <= 60) or (0 <= temp_f < 32):
            return 0.5
        else:
            return 0.0

    @staticmethod
    def accumulate_chill_hours(weather_records: list[Weather]) -> float:
        """Accumulate total chill hours.

        Args:
            weather_records: List of Weather objects

        Returns:
            Total accumulated chill hours
        """
        total_chill = 0.0
        for weather in weather_records:
            # Use minimum temperature as approximation
            chill = ChillHourAccumulation.calculate_chill_hours(weather.temp_min_f)
            total_chill += chill
        return total_chill


class PrecipitationProbability:
    """Estimates precipitation probability and severity."""

    @staticmethod
    def estimate_rain_probability(
        historical_rain_days: int,
        total_days_in_period: int,
    ) -> float:
        """Estimate probability of rain on a given day.

        Args:
            historical_rain_days: Days with rain in historical period
            total_days_in_period: Total days in historical period

        Returns:
            Probability (0-1)
        """
        if total_days_in_period <= 0:
            return 0.5
        return historical_rain_days / total_days_in_period

    @staticmethod
    def forecast_precipitation_amount(
        probability: float,
        normal_rainfall_in: float,
    ) -> float:
        """Forecast expected precipitation amount.

        Args:
            probability: Probability of rain (0-1)
            normal_rainfall_in: Normal rainfall for period

        Returns:
            Expected precipitation in inches
        """
        # Expected value calculation
        return probability * normal_rainfall_in


class WindErosionRisk:
    """Assesses wind erosion risk for soil and crop damage."""

    @staticmethod
    def calculate_erosion_risk(
        wind_speed_mph: float,
        soil_texture: str,
        field_length_ft: float,
        vegetative_cover: float = 0.5,
    ) -> float:
        """Calculate wind erosion risk score.

        Wind erosion increases exponentially with wind speed.

        Args:
            wind_speed_mph: Wind speed in mph
            soil_texture: Soil texture classification
            field_length_ft: Unsheltered field length
            vegetative_cover: Fraction of soil covered by vegetation

        Returns:
            Risk score (0-100, higher = more risk)
        """
        # Wind speed factor (risk increases with cube of wind speed)
        wind_factor = (wind_speed_mph / 15.0) ** 3  # Normalize to 15 mph baseline

        # Texture factor (sandy soils more susceptible)
        texture_factors = {
            "Sand": 1.0,
            "Loamy Sand": 0.8,
            "Sandy Loam": 0.6,
            "Loam": 0.4,
            "Silt Loam": 0.3,
            "Clay": 0.2,
        }
        texture_factor = texture_factors.get(soil_texture, 0.5)

        # Field length factor (longer fields = more risk)
        length_factor = min(1.0, field_length_ft / 1000)

        # Vegetation protection (reduces risk)
        vegetation_factor = 1.0 - (vegetative_cover * 0.7)

        risk_score = wind_factor * texture_factor * length_factor * vegetation_factor * 100
        return min(100.0, risk_score)
