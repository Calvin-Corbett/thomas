"""
Core type definitions for energy systems module.

Defines all dataclasses and enums used throughout the energy module including
power plants, grid infrastructure, loads, weather data, and market structures.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class EnergySource(str, Enum):
    """Energy source types."""

    SOLAR = "solar"
    WIND = "wind"
    HYDRO = "hydro"
    NUCLEAR = "nuclear"
    NATURAL_GAS = "natural_gas"
    COAL = "coal"
    BIOMASS = "biomass"
    GEOTHERMAL = "geothermal"
    BATTERY = "battery"
    PUMPED_HYDRO = "pumped_hydro"


class BusType(str, Enum):
    """Power system bus types."""

    SLACK = "slack"  # Reference/swing bus
    PV = "pv"  # Voltage-controlled (generator)
    PQ = "pq"  # Load bus


class TariffType(str, Enum):
    """Electricity tariff types."""

    FLAT = "flat"
    TIME_OF_USE = "time_of_use"
    CRITICAL_PEAK = "critical_peak"
    REAL_TIME = "real_time"
    CAPACITY = "capacity"


@dataclass
class BusVoltage:
    """Voltage state at a bus."""

    magnitude: float  # in per-unit (1.0 = nominal)
    angle: float  # in radians

    def __post_init__(self) -> None:
        if self.magnitude <= 0.0:
            raise ValueError(f"Voltage magnitude must be positive, got {self.magnitude}")


@dataclass
class BusState:
    """Complete state of a bus in the grid."""

    bus_id: int
    bus_type: BusType
    voltage: BusVoltage
    real_power: float  # MW
    reactive_power: float  # MVAr
    base_voltage: float  # kV


@dataclass
class WeatherCondition:
    """Weather conditions affecting renewable generation."""

    timestamp: datetime
    temperature: float  # Celsius
    wind_speed: float  # m/s
    wind_direction: float  # degrees (0-360)
    solar_irradiance: float  # W/m^2
    cloud_cover: float  # 0.0-1.0
    humidity: float  # 0.0-1.0
    precipitation: float  # mm
    air_density: float = 1.225  # kg/m^3 at sea level

    def calculate_air_mass(self, latitude: float, solar_altitude: float) -> float:
        """Calculate atmospheric air mass for solar radiation."""
        if solar_altitude <= 0:
            return 100.0
        sin_altitude = math.sin(math.radians(solar_altitude))
        # Kasten and Czeplak formula
        air_mass = 1.0 / (sin_altitude + 0.50572 * (96.07995 - solar_altitude) ** (-1.6364))
        return max(1.0, air_mass)

    def update_air_density(self, elevation: float) -> None:
        """Update air density based on elevation (meters above sea level)."""
        # Barometric formula approximation
        self.air_density = 1.225 * math.exp(-elevation / 8435.0)


@dataclass
class EnergyProfile:
    """Time-series energy data."""

    timestamps: list[datetime]
    values: list[float]  # MW or MWh depending on context

    def __post_init__(self) -> None:
        if len(self.timestamps) != len(self.values):
            raise ValueError("Timestamps and values must have same length")

    def get_value_at(self, timestamp: datetime) -> float | None:
        """Get energy value at specific timestamp with linear interpolation."""
        if not self.timestamps:
            return None

        if timestamp <= self.timestamps[0]:
            return self.values[0]
        if timestamp >= self.timestamps[-1]:
            return self.values[-1]

        for i in range(len(self.timestamps) - 1):
            t1, t2 = self.timestamps[i], self.timestamps[i + 1]
            if t1 <= timestamp <= t2:
                v1, v2 = self.values[i], self.values[i + 1]
                # Linear interpolation
                fraction = (timestamp - t1) / (t2 - t1)
                return v1 + fraction * (v2 - v1)

        return self.values[-1]

    def rolling_average(self, window_hours: int) -> "EnergyProfile":
        """Calculate rolling average over specified window."""
        if window_hours < 1:
            raise ValueError("Window must be at least 1 hour")

        new_values = []
        for i in range(len(self.values)):
            start_idx = max(0, i - window_hours + 1)
            window_vals = self.values[start_idx : i + 1]
            new_values.append(sum(window_vals) / len(window_vals))

        return EnergyProfile(self.timestamps.copy(), new_values)


@dataclass
class EmissionFactor:
    """Emission factors for different fuel types."""

    fuel_type: EnergySource
    co2_kg_per_mwh: float  # kg CO2 per MWh
    nox_kg_per_mwh: float  # kg NOx per MWh
    so2_kg_per_mwh: float  # kg SO2 per MWh

    def __post_init__(self) -> None:
        if any(v < 0 for v in [self.co2_kg_per_mwh, self.nox_kg_per_mwh, self.so2_kg_per_mwh]):
            raise ValueError("Emission factors cannot be negative")


@dataclass
class TariffSchedule:
    """Electricity tariff schedule."""

    tariff_type: TariffType
    base_rate: float  # $/MWh
    peak_rate: float | None = None  # $/MWh for peak hours
    off_peak_rate: float | None = None  # $/MWh for off-peak
    peak_hours: list[int] | None = None  # 0-23 for hours
    critical_peak_threshold: float = 2.0  # multiplier for critical peak

    def get_rate(self, hour: int, demand_level: str = "normal") -> float:
        """Get tariff rate for given hour and demand level."""
        if self.tariff_type == TariffType.FLAT:
            return self.base_rate

        if self.tariff_type == TariffType.CRITICAL_PEAK and demand_level == "critical":
            return self.base_rate * self.critical_peak_threshold

        if self.tariff_type == TariffType.TIME_OF_USE:
            if self.peak_hours and hour in self.peak_hours:
                return self.peak_rate or self.base_rate
            return self.off_peak_rate or self.base_rate

        return self.base_rate


@dataclass
class Load:
    """Electrical load/demand."""

    load_id: str
    active_power: float  # MW
    reactive_power: float = 0.0  # MVAr
    power_factor: float = 0.95
    is_controllable: bool = False
    emergency_shed_capability: float = 0.0  # Fraction that can be shed

    def __post_init__(self) -> None:
        if not 0.0 <= self.power_factor <= 1.0:
            raise ValueError(f"Power factor {self.power_factor} outside [0, 1]")
        if not 0.0 <= self.emergency_shed_capability <= 1.0:
            raise ValueError(f"Emergency shed capability {self.emergency_shed_capability} invalid")


@dataclass
class StorageUnit:
    """Energy storage unit specifications."""

    storage_id: str = ""
    storage_type: str = "battery"  # "battery", "pumped_hydro", "thermal", "flywheel"
    capacity_mwh: float = 10.0  # Energy capacity
    power_rating_mw: float = 1.0  # Charging/discharging power rating
    round_trip_efficiency: float = 0.9  # 0.0-1.0
    min_soc: float = 0.1  # Minimum state of charge
    max_soc: float = 0.9  # Maximum state of charge
    soc: float = 0.5  # Current state of charge (0-1)

    # Battery-specific
    degradation_rate: float = 0.0  # Capacity loss per cycle
    cycle_lifetime: int = 5000  # Total cycles to 80% capacity

    # Thermal-specific
    ambient_temperature: float = 25.0  # Celsius
    thermal_loss_rate: float = 0.001  # Per hour

    def __post_init__(self) -> None:
        if not 0.0 <= self.round_trip_efficiency <= 1.0:
            raise ValueError("Efficiency must be in [0, 1]")
        if not self.capacity_mwh > 0.0:
            raise ValueError("Capacity must be positive")


@dataclass
class PowerPlant:
    """Power generation plant."""

    plant_id: str = ""
    fuel_type: EnergySource = EnergySource.NATURAL_GAS
    capacity_mw: float = 100.0
    min_power_mw: float = 0.0
    ramp_rate_mw_per_min: float = 1.0
    efficiency: float = 0.35  # Heat rate dependent
    startup_time_hours: float = 1.0
    shutdown_time_hours: float = 0.5
    startup_cost_usd: float = 500.0
    fuel_cost_per_mwh: float = 30.0
    variable_om_per_mwh: float = 5.0
    fixed_om_per_hour: float = 50.0

    # State tracking
    current_output_mw: float = 0.0
    is_online: bool = False
    time_online_hours: float = 0.0
    last_startup_time: datetime | None = None
    total_energy_generated_mwh: float = 0.0

    # For renewables
    capacity_factor: float = 0.0  # 0.0-1.0

    def __post_init__(self) -> None:
        if not self.capacity_mw > 0.0:
            raise ValueError("Capacity must be positive")
        if not 0.0 <= self.min_power_mw < self.capacity_mw:
            raise ValueError("Min power must be less than capacity")
        if not 0.0 < self.efficiency <= 1.0:
            raise ValueError("Efficiency must be in (0, 1]")

    def get_available_power(self) -> float:
        """Get available power output considering minimum and maximum."""
        if not self.is_online and self.current_output_mw <= 0.0:
            return 0.0
        if self.is_online:
            return max(self.min_power_mw, min(self.capacity_mw, self.current_output_mw))
        return min(self.capacity_mw, max(0.0, self.current_output_mw))

    def get_operating_cost_per_mwh(self) -> float:
        """Get total operating cost per MWh."""
        return (self.fuel_cost_per_mwh / self.efficiency) + self.variable_om_per_mwh


@dataclass
class Grid:
    """Electrical power grid."""

    grid_id: str
    buses: dict[int, BusState] = field(default_factory=dict)
    plants: dict[str, PowerPlant] = field(default_factory=dict)
    loads: dict[str, Load] = field(default_factory=dict)
    storage_units: dict[str, StorageUnit] = field(default_factory=dict)
    transmission_lines: list[tuple[int, int, float, float]] = field(default_factory=list)  # (from_bus, to_bus, R, X)
    frequency_hz: float = 60.0
    base_mva: float = 100.0

    def total_generation_mw(self) -> float:
        """Total current generation capacity."""
        return sum(p.get_available_power() for p in self.plants.values())

    def total_load_mw(self) -> float:
        """Total current load."""
        return sum(l.active_power for l in self.loads.values())

    def total_reserve_mw(self) -> float:
        """Total spinning reserve."""
        return self.total_generation_mw() - self.total_load_mw()


@dataclass
class DemandResponse:
    """Demand response program."""

    program_id: str
    max_shed_mw: float  # Maximum power that can be shed
    shed_price_per_mwh: float  # Payment for shedding
    response_time_minutes: int  # Time to activate
    duration_hours: int  # How long it lasts
    frequency_per_year: int  # Expected activations per year
    customer_participation_rate: float  # 0.0-1.0

    def effective_shed_capacity(self) -> float:
        """Effective load shedding capacity considering participation."""
        return self.max_shed_mw * self.customer_participation_rate
