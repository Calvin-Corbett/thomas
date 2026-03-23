"""Climate science and environmental modeling platform.

This module provides comprehensive tools for climate analysis, weather
simulation, and environmental modeling including atmospheric physics,
temperature analysis, precipitation modeling, ocean science, carbon
cycle dynamics, cryosphere analysis, climate modeling, and analytics.
"""

from thomas.marketplace.climate._exceptions import (
    ClimateDataError,
    InvalidParameterError,
    ModelError,
)
from thomas.marketplace.climate._types import (
    CarbonData,
    ClimateIndex,
    ClimateModel,
    ClimateStation,
    EmissionSource,
    GHGConcentration,
    Humidity,
    IceCoverage,
    Precipitation,
    Pressure,
    Scenario,
    SeaLevel,
    SolarRadiation,
    Temperature,
    WeatherObservation,
    WindData,
)

__version__ = "0.1.0"
__all__ = [
    "ClimateStation",
    "WeatherObservation",
    "Temperature",
    "Precipitation",
    "WindData",
    "Pressure",
    "Humidity",
    "SolarRadiation",
    "CarbonData",
    "EmissionSource",
    "ClimateModel",
    "Scenario",
    "GHGConcentration",
    "SeaLevel",
    "IceCoverage",
    "ClimateIndex",
    "ClimateDataError",
    "InvalidParameterError",
    "ModelError",
]
