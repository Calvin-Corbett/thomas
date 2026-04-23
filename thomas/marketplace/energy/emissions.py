"""
Emissions tracking and carbon accounting.

Provides CO2/NOx/SO2 emission factors, lifecycle assessment, carbon intensity
calculation, marginal emission rates, EPA eGRID compatible reporting, and
scope 1/2/3 classification.
"""

from dataclasses import dataclass, field
from datetime import datetime

from thomas.marketplace.energy._types import EmissionFactor, EnergySource, PowerPlant


@dataclass
class CarbonFootprint:
    """Carbon footprint for power generation."""

    co2_kg: float = 0.0
    nox_kg: float = 0.0
    so2_kg: float = 0.0
    pm25_kg: float = 0.0  # Particulate matter
    ch4_kg: float = 0.0  # Methane
    lifecycle_co2_kg: float = 0.0  # Includes construction, decommissioning


# Default emission factors (kg per MWh) based on EPA eGRID and IPCC
DEFAULT_EMISSION_FACTORS = {
    EnergySource.COAL: EmissionFactor(
        fuel_type=EnergySource.COAL,
        co2_kg_per_mwh=950.0,
        nox_kg_per_mwh=4.0,
        so2_kg_per_mwh=6.0,
    ),
    EnergySource.NATURAL_GAS: EmissionFactor(
        fuel_type=EnergySource.NATURAL_GAS,
        co2_kg_per_mwh=450.0,
        nox_kg_per_mwh=1.5,
        so2_kg_per_mwh=0.02,
    ),
    EnergySource.NUCLEAR: EmissionFactor(
        fuel_type=EnergySource.NUCLEAR,
        co2_kg_per_mwh=12.0,  # Lifecycle
        nox_kg_per_mwh=0.0,
        so2_kg_per_mwh=0.0,
    ),
    EnergySource.HYDRO: EmissionFactor(
        fuel_type=EnergySource.HYDRO,
        co2_kg_per_mwh=24.0,  # Lifecycle (dam construction)
        nox_kg_per_mwh=0.0,
        so2_kg_per_mwh=0.0,
    ),
    EnergySource.SOLAR: EmissionFactor(
        fuel_type=EnergySource.SOLAR,
        co2_kg_per_mwh=48.0,  # Lifecycle (panel manufacturing)
        nox_kg_per_mwh=0.0,
        so2_kg_per_mwh=0.0,
    ),
    EnergySource.WIND: EmissionFactor(
        fuel_type=EnergySource.WIND,
        co2_kg_per_mwh=11.0,  # Lifecycle (turbine manufacturing)
        nox_kg_per_mwh=0.0,
        so2_kg_per_mwh=0.0,
    ),
    EnergySource.BIOMASS: EmissionFactor(
        fuel_type=EnergySource.BIOMASS,
        co2_kg_per_mwh=0.0,  # Carbon neutral (renewable carbon)
        nox_kg_per_mwh=2.5,
        so2_kg_per_mwh=1.5,
    ),
    EnergySource.GEOTHERMAL: EmissionFactor(
        fuel_type=EnergySource.GEOTHERMAL,
        co2_kg_per_mwh=45.0,
        nox_kg_per_mwh=0.0,
        so2_kg_per_mwh=0.0,
    ),
}


@dataclass
class EmissionsCalculator:
    """Calculate emissions from power generation."""

    emission_factors: dict[EnergySource, EmissionFactor] = field(
        default_factory=lambda: DEFAULT_EMISSION_FACTORS.copy()
    )

    def calculate_emissions(
        self,
        plant: PowerPlant,
        energy_generated_mwh: float,
    ) -> CarbonFootprint:
        """
        Calculate emissions from power generation.

        Args:
            plant: Power plant
            energy_generated_mwh: Energy generated in MWh

        Returns:
            Carbon footprint
        """
        if plant.fuel_type not in self.emission_factors:
            return CarbonFootprint()

        factor = self.emission_factors[plant.fuel_type]

        # Operational emissions
        co2_kg = energy_generated_mwh * factor.co2_kg_per_mwh
        nox_kg = energy_generated_mwh * factor.nox_kg_per_mwh
        so2_kg = energy_generated_mwh * factor.so2_kg_per_mwh

        # Lifecycle emissions
        lifecycle_co2_kg = self._calculate_lifecycle_emissions(plant, energy_generated_mwh)

        # Additional emissions
        pm25_kg = self._calculate_particulate_matter(plant, energy_generated_mwh)
        ch4_kg = self._calculate_methane(plant, energy_generated_mwh)

        return CarbonFootprint(
            co2_kg=co2_kg,
            nox_kg=nox_kg,
            so2_kg=so2_kg,
            pm25_kg=pm25_kg,
            ch4_kg=ch4_kg,
            lifecycle_co2_kg=lifecycle_co2_kg,
        )

    def _calculate_lifecycle_emissions(
        self,
        plant: PowerPlant,
        energy_generated_mwh: float,
    ) -> float:
        """Calculate lifecycle emissions including construction and decommissioning."""
        # Simplified lifecycle model (kg CO2)
        lifecycle_factors = {
            EnergySource.SOLAR: 48.0,
            EnergySource.WIND: 11.0,
            EnergySource.NUCLEAR: 12.0,
            EnergySource.HYDRO: 24.0,
            EnergySource.COAL: 950.0,
            EnergySource.NATURAL_GAS: 450.0,
            EnergySource.BIOMASS: 0.0,
            EnergySource.GEOTHERMAL: 45.0,
        }

        factor = lifecycle_factors.get(plant.fuel_type, 0.0)
        return energy_generated_mwh * factor

    def _calculate_particulate_matter(
        self,
        plant: PowerPlant,
        energy_generated_mwh: float,
    ) -> float:
        """Calculate PM2.5 emissions."""
        pm_factors = {
            EnergySource.COAL: 0.025,
            EnergySource.NATURAL_GAS: 0.003,
            EnergySource.BIOMASS: 0.15,
            EnergySource.GEOTHERMAL: 0.001,
        }

        factor = pm_factors.get(plant.fuel_type, 0.0)
        return energy_generated_mwh * factor

    def _calculate_methane(
        self,
        plant: PowerPlant,
        energy_generated_mwh: float,
    ) -> float:
        """Calculate methane emissions."""
        ch4_factors = {
            EnergySource.NATURAL_GAS: 0.005,
            EnergySource.COAL: 0.002,
            EnergySource.BIOMASS: 0.001,
        }

        factor = ch4_factors.get(plant.fuel_type, 0.0)
        return energy_generated_mwh * factor * 28.0  # GWP of CH4

    def register_emission_factor(self, factor: EmissionFactor) -> None:
        """Register custom emission factor."""
        self.emission_factors[factor.fuel_type] = factor


@dataclass
class CarbonIntensity:
    """Grid carbon intensity tracking and analysis."""

    hourly_intensities: list[float] = field(default_factory=list)  # kg CO2/MWh
    timestamps: list[datetime] = field(default_factory=list)

    def calculate_grid_intensity(
        self,
        generation_mix: dict[EnergySource, float],  # source -> MW
        emission_factors: dict[EnergySource, float],  # source -> kg CO2/MWh
    ) -> float:
        """
        Calculate grid carbon intensity.

        Args:
            generation_mix: Generation by source in MW
            emission_factors: Emission factors by source

        Returns:
            Grid carbon intensity in kg CO2/MWh
        """
        total_generation = sum(generation_mix.values())

        if total_generation <= 0:
            return 0.0

        weighted_intensity = 0.0

        for source, generation_mw in generation_mix.items():
            if source in emission_factors:
                factor = emission_factors[source]
                weighted_intensity += (generation_mw / total_generation) * factor

        return weighted_intensity

    def calculate_marginal_intensity(
        self,
        marginal_fuel: EnergySource,
        emission_factors: dict[EnergySource, float],
    ) -> float:
        """
        Calculate marginal emission rate (intensity of next unit).

        Args:
            marginal_fuel: Fuel type of marginal generator
            emission_factors: Emission factors by fuel

        Returns:
            Marginal carbon intensity in kg CO2/MWh
        """
        return emission_factors.get(marginal_fuel, 0.0)

    def add_hourly_data(self, intensity_kg_co2_per_mwh: float, timestamp: datetime) -> None:
        """Add hourly carbon intensity data."""
        self.hourly_intensities.append(intensity_kg_co2_per_mwh)
        self.timestamps.append(timestamp)

    def get_average_intensity(self, window_hours: int = 24) -> float:
        """Get average carbon intensity over recent hours."""
        if not self.hourly_intensities:
            return 0.0

        recent_data = self.hourly_intensities[-window_hours:]
        return sum(recent_data) / len(recent_data)

    def get_peak_intensity_hour(self) -> int | None:
        """Get hour with highest carbon intensity."""
        if not self.hourly_intensities:
            return None

        return self.hourly_intensities.index(max(self.hourly_intensities))


@dataclass
class EmissionScope:
    """Emission scope classification (GHG Protocol)."""

    scope_1: float = 0.0  # Direct emissions (kg CO2e)
    scope_2: float = 0.0  # Indirect electricity (kg CO2e)
    scope_3: float = 0.0  # Other indirect (kg CO2e)


def classify_emissions(
    plant_type: EnergySource,
    generation_mwh: float,
    emission_factors: dict[EnergySource, float],
) -> EmissionScope:
    """
    Classify emissions by GHG Protocol scope.

    Args:
        plant_type: Type of power plant
        generation_mwh: Energy generated
        emission_factors: Emission factors by fuel

    Returns:
        Emission scope breakdown
    """
    factor = emission_factors.get(plant_type, 0.0)
    emissions_kg = generation_mwh * factor

    if plant_type in [EnergySource.SOLAR, EnergySource.WIND, EnergySource.HYDRO]:
        # Renewable: only Scope 3 (lifecycle)
        return EmissionScope(scope_3=emissions_kg)

    elif plant_type in [EnergySource.NUCLEAR, EnergySource.GEOTHERMAL]:
        # Low-carbon: mostly Scope 3
        return EmissionScope(scope_3=emissions_kg)

    else:
        # Fossil fuels: Scope 1 (combustion)
        return EmissionScope(scope_1=emissions_kg)


@dataclass
class EmissionReportingData:
    """EPA eGRID compatible emissions data."""

    egrid_fuel_code: str
    emissions_mtco2_per_mwh: float
    nox_kg_per_mwh: float
    so2_kg_per_mwh: float
    pm25_kg_per_mwh: float
    annual_generation_mwh: float
    emissions_mtco2_annual: float


def generate_egrid_report(
    plants: list[PowerPlant],
    emission_factors: dict[EnergySource, EmissionFactor],
    annual_generation: dict[str, float],
) -> list[EmissionReportingData]:
    """
    Generate EPA eGRID compatible emissions report.

    Args:
        plants: Power plants
        emission_factors: Emission factors by fuel
        annual_generation: Annual generation by plant_id

    Returns:
        List of EGRID reporting records
    """
    reports = []

    for plant in plants:
        if plant.fuel_type not in emission_factors:
            continue

        factor = emission_factors[plant.fuel_type]
        plant_generation = annual_generation.get(plant.plant_id, 0.0)

        annual_emissions_mt = plant_generation * factor.co2_kg_per_mwh / 1000

        # EGRID fuel code mapping
        fuel_codes = {
            EnergySource.COAL: "COAL",
            EnergySource.NATURAL_GAS: "NG",
            EnergySource.NUCLEAR: "NUC",
            EnergySource.HYDRO: "WAT",
            EnergySource.SOLAR: "SUN",
            EnergySource.WIND: "WND",
            EnergySource.BIOMASS: "BIO",
            EnergySource.GEOTHERMAL: "GEO",
        }

        reports.append(
            EmissionReportingData(
                egrid_fuel_code=fuel_codes.get(plant.fuel_type, "OTH"),
                emissions_mtco2_per_mwh=factor.co2_kg_per_mwh / 1000,
                nox_kg_per_mwh=factor.nox_kg_per_mwh,
                so2_kg_per_mwh=factor.so2_kg_per_mwh,
                pm25_kg_per_mwh=0.01,  # Placeholder
                annual_generation_mwh=plant_generation,
                emissions_mtco2_annual=annual_emissions_mt,
            )
        )

    return reports
