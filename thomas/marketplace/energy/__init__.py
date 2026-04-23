"""
Energy systems simulation and management module for Thomas.

This module provides comprehensive energy modeling, simulation, and optimization
capabilities including renewable energy integration, grid operations, storage
management, market dynamics, and smart grid features.
"""

from thomas.marketplace.energy._exceptions import (
    FrequencyDeviationError,
    GenerationShortfallError,
    GridOverloadError,
    NoFeasibleSolutionError,
    StorageDepletedError,
    VoltageViolationError,
)
from thomas.marketplace.energy._types import (
    BusState,
    BusType,
    BusVoltage,
    DemandResponse,
    EmissionFactor,
    EnergyProfile,
    EnergySource,
    Grid,
    Load,
    PowerPlant,
    StorageUnit,
    TariffSchedule,
    WeatherCondition,
)
from thomas.marketplace.energy.emissions import CarbonIntensity, EmissionsCalculator
from thomas.marketplace.energy.forecasting import LoadForecaster, SolarForecaster, WindForecaster
from thomas.marketplace.energy.grid import FrequencyRegulator, GridController, PowerFlowSolver
from thomas.marketplace.energy.market import EnergyMarket, MeritOrderDispatch, PricingEngine
from thomas.marketplace.energy.optimization import EconomicDispatch, MicrogridOptimizer, UnitCommitment
from thomas.marketplace.energy.smart_grid import DemandResponseController, V2GManager, VirtualPowerPlant
from thomas.marketplace.energy.solar import SolarPlant, calculate_irradiance, optimize_panel_angle
from thomas.marketplace.energy.storage import BatteryUnit, PumpedHydro, ThermalStorage
from thomas.marketplace.energy.wind import WakeLossModel, WindPlant, calculate_wind_power

__all__ = [
    # Types
    "EnergySource",
    "PowerPlant",
    "Grid",
    "Load",
    "EnergyProfile",
    "WeatherCondition",
    "StorageUnit",
    "TariffSchedule",
    "EmissionFactor",
    "DemandResponse",
    "BusType",
    "BusVoltage",
    "BusState",
    # Exceptions
    "GridOverloadError",
    "StorageDepletedError",
    "GenerationShortfallError",
    "FrequencyDeviationError",
    "VoltageViolationError",
    "NoFeasibleSolutionError",
    # Solar
    "SolarPlant",
    "calculate_irradiance",
    "optimize_panel_angle",
    # Wind
    "WindPlant",
    "calculate_wind_power",
    "WakeLossModel",
    # Grid
    "PowerFlowSolver",
    "GridController",
    "FrequencyRegulator",
    # Storage
    "BatteryUnit",
    "PumpedHydro",
    "ThermalStorage",
    # Market
    "EnergyMarket",
    "MeritOrderDispatch",
    "PricingEngine",
    # Optimization
    "UnitCommitment",
    "EconomicDispatch",
    "MicrogridOptimizer",
    # Emissions
    "EmissionsCalculator",
    "CarbonIntensity",
    # Forecasting
    "LoadForecaster",
    "SolarForecaster",
    "WindForecaster",
    # Smart Grid
    "VirtualPowerPlant",
    "DemandResponseController",
    "V2GManager",
]
