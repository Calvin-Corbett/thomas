"""Core data types for climate science and environmental modeling.

This module defines all fundamental types used throughout the climate
science platform, including station data, observations, and climate models.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class EmissionSource(Enum):
    """Source categories for greenhouse gas emissions."""

    FOSSIL_FUEL_COMBUSTION = "fossil_fuel_combustion"
    AGRICULTURAL = "agricultural"
    INDUSTRIAL_PROCESSES = "industrial_processes"
    LAND_USE_CHANGE = "land_use_change"
    WASTE = "waste"
    ENERGY = "energy"
    TRANSPORT = "transport"
    RESIDENTIAL = "residential"
    COMMERCIAL = "commercial"
    NATURAL = "natural"


class Scenario(Enum):
    """Climate scenario pathways (Representative Concentration Pathways)."""

    RCP_2_6 = "rcp2.6"  # 2.6 W/m² radiative forcing
    RCP_4_5 = "rcp4.5"  # 4.5 W/m² radiative forcing
    RCP_6_0 = "rcp6.0"  # 6.0 W/m² radiative forcing
    RCP_8_5 = "rcp8.5"  # 8.5 W/m² radiative forcing


@dataclass
class Temperature:
    """Temperature measurement with unit handling.

    Attributes:
        celsius: Temperature in degrees Celsius.
        timestamp: Time of measurement.
    """

    celsius: float
    timestamp: datetime

    def to_fahrenheit(self) -> float:
        """Convert temperature to Fahrenheit.

        Returns:
            Temperature in degrees Fahrenheit.
        """
        return (self.celsius * 9 / 5) + 32

    def to_kelvin(self) -> float:
        """Convert temperature to Kelvin.

        Returns:
            Temperature in Kelvin.
        """
        return self.celsius + 273.15


@dataclass
class Precipitation:
    """Precipitation measurement.

    Attributes:
        millimeters: Accumulation in millimeters.
        timestamp: Time of measurement.
        type: Precipitation type (rain, snow, sleet, hail, etc).
    """

    millimeters: float
    timestamp: datetime
    type: str = "rain"

    def to_inches(self) -> float:
        """Convert to inches.

        Returns:
            Precipitation in inches.
        """
        return self.millimeters / 25.4

    @property
    def is_significant(self) -> bool:
        """Check if precipitation exceeds 0.5 mm threshold.

        Returns:
            True if significant, False otherwise.
        """
        return self.millimeters >= 0.5


@dataclass
class WindData:
    """Wind measurement with directional and speed components.

    Attributes:
        speed_ms: Wind speed in meters per second.
        direction_degrees: Wind direction in degrees (0-360).
        gust_speed_ms: Peak gust speed in meters per second.
        timestamp: Time of measurement.
    """

    speed_ms: float
    direction_degrees: float
    gust_speed_ms: float | None = None
    timestamp: datetime | None = None

    def to_knots(self) -> float:
        """Convert wind speed to knots.

        Returns:
            Wind speed in knots.
        """
        return self.speed_ms * 1.94384

    def beaufort_scale(self) -> int:
        """Calculate Beaufort wind scale (0-12).

        Returns:
            Beaufort scale number (0=calm, 12=hurricane).
        """
        if self.speed_ms < 0.5:
            return 0
        elif self.speed_ms < 1.5:
            return 1
        elif self.speed_ms < 3.3:
            return 2
        elif self.speed_ms < 5.4:
            return 3
        elif self.speed_ms < 7.9:
            return 4
        elif self.speed_ms < 10.7:
            return 5
        elif self.speed_ms < 13.8:
            return 6
        elif self.speed_ms < 17.1:
            return 7
        elif self.speed_ms < 20.7:
            return 8
        elif self.speed_ms < 24.4:
            return 9
        elif self.speed_ms < 28.4:
            return 10
        elif self.speed_ms < 32.6:
            return 11
        else:
            return 12


@dataclass
class Pressure:
    """Atmospheric pressure measurement.

    Attributes:
        hectopascals: Pressure in hPa (millibars).
        timestamp: Time of measurement.
    """

    hectopascals: float
    timestamp: datetime

    def to_atmospheres(self) -> float:
        """Convert to atmospheres.

        Returns:
            Pressure in atm.
        """
        return self.hectopascals / 1013.25

    def to_inches_mercury(self) -> float:
        """Convert to inches of mercury.

        Returns:
            Pressure in inHg.
        """
        return self.hectopascals * 0.02953


@dataclass
class Humidity:
    """Relative humidity measurement.

    Attributes:
        percent: Relative humidity as percentage (0-100).
        timestamp: Time of measurement.
    """

    percent: float
    timestamp: datetime

    def is_saturated(self) -> bool:
        """Check if air is saturated (RH >= 95%).

        Returns:
            True if near saturation, False otherwise.
        """
        return self.percent >= 95


@dataclass
class SolarRadiation:
    """Solar radiation measurement.

    Attributes:
        wm2: Solar radiation in watts per square meter.
        timestamp: Time of measurement.
        direct: Direct normal irradiance component.
        diffuse: Diffuse irradiance component.
    """

    wm2: float
    timestamp: datetime
    direct: float | None = None
    diffuse: float | None = None


@dataclass
class CarbonData:
    """Carbon cycle and emission measurements.

    Attributes:
        co2_ppm: CO2 concentration in parts per million.
        ch4_ppb: Methane concentration in parts per billion.
        n2o_ppb: Nitrous oxide concentration in parts per billion.
        timestamp: Time of measurement.
    """

    co2_ppm: float
    ch4_ppb: float
    n2o_ppb: float
    timestamp: datetime


@dataclass
class WeatherObservation:
    """Complete weather observation combining multiple measurements.

    Attributes:
        temperature: Temperature reading.
        pressure: Atmospheric pressure.
        humidity: Relative humidity.
        wind: Wind data.
        precipitation: Precipitation if present.
        solar_radiation: Solar radiation measurement.
        visibility_km: Visibility in kilometers.
        station_id: Identifier for weather station.
        timestamp: Time of observation.
    """

    temperature: Temperature
    pressure: Pressure
    humidity: Humidity
    wind: WindData
    visibility_km: float
    station_id: str
    timestamp: datetime
    precipitation: Precipitation | None = None
    solar_radiation: SolarRadiation | None = None

    @property
    def dew_point_celsius(self) -> float:
        """Calculate dew point using Magnus formula.

        Returns:
            Dew point temperature in Celsius.
        """
        t = self.temperature.celsius
        rh = self.humidity.percent
        a, b, _c = 17.27, 237.7, 110.6
        alpha = ((a * t) / (b + t)) + (lambda x: (a * x) / (b + x))((rh / 100) * ((a * t) / (b + t) - 1))
        return (b * alpha) / (a - alpha)


@dataclass
class ClimateStation:
    """Climate monitoring station with historical data.

    Attributes:
        station_id: Unique identifier.
        name: Station name.
        latitude: Latitude in degrees.
        longitude: Longitude in degrees.
        elevation_m: Elevation in meters.
        region: Geographic region.
        observations: Historical observations.
    """

    station_id: str
    name: str
    latitude: float
    longitude: float
    elevation_m: float
    region: str
    observations: list[WeatherObservation] = field(default_factory=list)

    def add_observation(self, obs: WeatherObservation) -> None:
        """Add weather observation to station history.

        Args:
            obs: Weather observation to add.
        """
        self.observations.append(obs)

    def monthly_mean_temperature(self, year: int, month: int) -> float | None:
        """Calculate monthly mean temperature.

        Args:
            year: Year for calculation.
            month: Month (1-12).

        Returns:
            Mean temperature in Celsius, or None if insufficient data.
        """
        temps = [
            obs.temperature.celsius
            for obs in self.observations
            if obs.timestamp.year == year and obs.timestamp.month == month
        ]
        return sum(temps) / len(temps) if temps else None


@dataclass
class GHGConcentration:
    """Greenhouse gas concentration in atmosphere.

    Attributes:
        co2_ppm: CO2 concentration in ppm.
        ch4_ppb: CH4 concentration in ppb.
        n2o_ppb: N2O concentration in ppb.
        timestamp: Time of measurement.
    """

    co2_ppm: float
    ch4_ppb: float
    n2o_ppb: float
    timestamp: datetime


@dataclass
class SeaLevel:
    """Sea level measurement and anomaly.

    Attributes:
        height_mm: Sea level height in millimeters.
        anomaly_mm: Deviation from reference period.
        timestamp: Time of measurement.
    """

    height_mm: float
    anomaly_mm: float
    timestamp: datetime


@dataclass
class IceCoverage:
    """Ice sheet and sea ice extent data.

    Attributes:
        area_km2: Ice covered area in square kilometers.
        coverage_percent: Percentage coverage.
        type: Type of ice (sheet, sea, glacier).
        timestamp: Time of measurement.
    """

    area_km2: float
    coverage_percent: float
    type: str
    timestamp: datetime


@dataclass
class ClimateIndex:
    """Climate change indicator index.

    Attributes:
        name: Index name (e.g., ENSO, NAO).
        value: Index value.
        anomaly: Anomaly from baseline.
        timestamp: Time of measurement.
    """

    name: str
    value: float
    anomaly: float
    timestamp: datetime


@dataclass
class ClimateModel:
    """Climate model configuration and state.

    Attributes:
        name: Model name.
        scenario: RCP scenario pathway.
        initial_co2_ppm: Initial CO2 concentration.
        equilibrium_sensitivity_K: Climate sensitivity parameter.
        feedback_parameter: Cloud/ice/water vapor feedback.
        time_steps: Number of integration steps.
        ghg_concentrations: Historical/projected concentrations.
        temperature_anomalies: Temperature change from baseline.
    """

    name: str
    scenario: Scenario
    initial_co2_ppm: float
    equilibrium_sensitivity_K: float
    feedback_parameter: float = -1.3
    time_steps: int = 100
    ghg_concentrations: list[GHGConcentration] = field(default_factory=list)
    temperature_anomalies: list[float] = field(default_factory=list)

    def add_ghg_concentration(self, conc: GHGConcentration) -> None:
        """Add GHG concentration to model history.

        Args:
            conc: Concentration measurement.
        """
        self.ghg_concentrations.append(conc)
