"""Carbon cycle and emission analysis for climate science.

This module provides carbon budget calculations, emission factor computation,
carbon footprint estimation, Keeling curve fitting, radiative forcing
calculation, and emission reduction scenario modeling.
"""

import math

from scipy import stats

from thomas.climate._exceptions import ClimateDataError, InvalidParameterError

# Emission factors (kg CO2 per unit)
EMISSION_FACTORS: dict[str, float] = {
    "coal": 2.4,  # kg CO2 per kg coal
    "oil": 3.15,  # kg CO2 per liter
    "natural_gas": 1.9,  # kg CO2 per m³
    "electricity_coal": 1.0,  # kg CO2 per kWh
    "electricity_natural_gas": 0.45,  # kg CO2 per kWh
    "electricity_renewable": 0.05,  # kg CO2 per kWh
}

# Global warming potentials (100-year)
GWP_VALUES: dict[str, float] = {
    "CO2": 1.0,
    "CH4": 28.0,
    "N2O": 265.0,
    "SF6": 23500.0,
}


def carbon_budget(
    atmospheric_co2_increase_ppm: float, emissions_gt_year: float, absorption_fraction: float = 0.45
) -> dict[str, float]:
    """Calculate global carbon budget: sources and sinks.

    Args:
        atmospheric_co2_increase_ppm: Annual CO2 increase in atmosphere in ppm.
        emissions_gt_year: Total emissions in Gt CO2/year.
        absorption_fraction: Fraction absorbed by oceans/land (0.45 default).

    Returns:
        Dictionary with budgets for atmosphere, ocean, land sinks.
    """
    # Convert ppm increase to Gt (1 ppm CO2 ~ 2.12 Gt)
    atm_increase_gt = atmospheric_co2_increase_ppm * 2.12

    ocean_sink = emissions_gt_year * absorption_fraction * 0.5  # ~50% to ocean
    land_sink = emissions_gt_year * absorption_fraction * 0.5  # ~50% to land

    return {
        "total_emissions": emissions_gt_year,
        "atmospheric_increase": atm_increase_gt,
        "ocean_sink": ocean_sink,
        "land_sink": land_sink,
        "accounting_residual": emissions_gt_year - atm_increase_gt - ocean_sink - land_sink,
    }


def emission_factor_calculation(fuel_type: str, quantity: float) -> float:
    """Calculate CO2 emissions from fuel combustion.

    Args:
        fuel_type: Type of fuel ("coal", "oil", "natural_gas", etc).
        quantity: Quantity of fuel (kg, liters, or m³).

    Returns:
        CO2 emissions in kg.

    Raises:
        InvalidParameterError: If fuel type is unknown.
    """
    if fuel_type not in EMISSION_FACTORS:
        raise InvalidParameterError(f"Unknown fuel type: {fuel_type}", "fuel_type", fuel_type)

    factor = EMISSION_FACTORS[fuel_type]
    return quantity * factor


def carbon_footprint_personal(
    annual_electricity_kwh: float,
    annual_natural_gas_m3: float,
    annual_vehicle_km: float,
    vehicle_efficiency_km_per_liter: float = 8.0,
    annual_flights_km: float = 0.0,
) -> float:
    """Calculate annual carbon footprint for individual.

    Args:
        annual_electricity_kwh: Annual electricity consumption in kWh.
        annual_natural_gas_m3: Annual natural gas in m³.
        annual_vehicle_km: Annual vehicle distance in km.
        vehicle_efficiency_km_per_liter: Vehicle fuel efficiency.
        annual_flights_km: Annual flight distance in km.

    Returns:
        Total annual carbon footprint in kg CO2 equivalent.
    """
    # Electricity (assuming average grid)
    electricity_emissions = annual_electricity_kwh * 0.45  # kg CO2/kWh

    # Natural gas
    gas_emissions = emission_factor_calculation("natural_gas", annual_natural_gas_m3)

    # Vehicles
    vehicle_liters = annual_vehicle_km / vehicle_efficiency_km_per_liter
    vehicle_emissions = emission_factor_calculation("oil", vehicle_liters)

    # Flights (0.25 kg CO2 per km)
    flight_emissions = annual_flights_km * 0.25

    total = electricity_emissions + gas_emissions + vehicle_emissions + flight_emissions

    return total


def carbon_footprint_organizational(
    employees: int,
    annual_emissions_scope1_gt: float,
    annual_emissions_scope2_gt: float,
    annual_emissions_scope3_gt: float = 0.0,
) -> dict[str, float]:
    """Calculate organizational carbon footprint.

    Scopes:
    1: Direct emissions from owned assets
    2: Indirect emissions from purchased energy
    3: Indirect emissions from value chain

    Args:
        employees: Number of employees.
        annual_emissions_scope1_gt: Scope 1 emissions in Gt CO2e.
        annual_emissions_scope2_gt: Scope 2 emissions in Gt CO2e.
        annual_emissions_scope3_gt: Scope 3 emissions in Gt CO2e.

    Returns:
        Dictionary with total and per-employee footprint.
    """
    total_emissions = annual_emissions_scope1_gt + annual_emissions_scope2_gt + annual_emissions_scope3_gt

    per_employee = (total_emissions * 1e9) / employees if employees > 0 else 0

    return {
        "scope_1": annual_emissions_scope1_gt,
        "scope_2": annual_emissions_scope2_gt,
        "scope_3": annual_emissions_scope3_gt,
        "total": total_emissions,
        "per_employee_kg": per_employee,
    }


def keeling_curve_fitting(years: list[float], co2_ppm: list[float]) -> tuple[float, float, list[float]]:
    """Fit Keeling curve model to CO2 measurements (trend + seasonal).

    Args:
        years: List of measurement years.
        co2_ppm: List of CO2 concentrations in ppm.

    Returns:
        Tuple of (linear_trend_ppm_year, seasonal_amplitude_ppm, fitted_values).

    Raises:
        ClimateDataError: If insufficient data.
    """
    if not years or len(years) < 10:
        raise ClimateDataError("Need at least 10 years of data", years)

    # Linear regression for trend
    slope, intercept, _, _, _ = stats.linregress(years, co2_ppm)

    # Remove trend to analyze seasonality
    trend = [slope * year + intercept for year in years]
    detrended = [co2 - t for co2, t in zip(co2_ppm, trend)]

    # Estimate seasonal amplitude (amplitude of residuals)
    seasonal_amplitude = max(detrended) - min(detrended)

    # Reconstruct fitted curve
    fitted = [t + detrended[i] for i, t in enumerate(trend)]

    return slope, seasonal_amplitude, fitted


def radiative_forcing_co2(co2_ppm: float, co2_baseline_ppm: float = 280.0) -> float:
    """Calculate radiative forcing from CO2 using IPCC formula.

    ΔF = 5.35 × ln(C/C₀) W/m²

    Args:
        co2_ppm: Current CO2 concentration in ppm.
        co2_baseline_ppm: Baseline CO2 concentration (pre-industrial).

    Returns:
        Radiative forcing in W/m².

    Raises:
        InvalidParameterError: If concentrations are invalid.
    """
    if co2_ppm <= 0 or co2_baseline_ppm <= 0:
        raise InvalidParameterError("CO2 concentrations must be positive")

    ratio = co2_ppm / co2_baseline_ppm
    if ratio <= 0:
        raise InvalidParameterError("Invalid CO2 ratio", "ratio", ratio)

    return 5.35 * math.log(ratio)


def radiative_forcing_ghg(
    co2_ppm: float = 415.0,
    ch4_ppb: float = 1900.0,
    n2o_ppb: float = 335.0,
    co2_baseline_ppm: float = 280.0,
    ch4_baseline_ppb: float = 722.0,
    n2o_baseline_ppb: float = 270.0,
) -> dict[str, float]:
    """Calculate total radiative forcing from multiple GHGs.

    Args:
        co2_ppm: CO2 concentration in ppm.
        ch4_ppb: Methane concentration in ppb.
        n2o_ppb: Nitrous oxide concentration in ppb.
        co2_baseline_ppm: Baseline CO2.
        ch4_baseline_ppb: Baseline CH4.
        n2o_baseline_ppb: Baseline N2O.

    Returns:
        Dictionary with forcing contributions in W/m².
    """
    # CO2 forcing
    f_co2 = radiative_forcing_co2(co2_ppm, co2_baseline_ppm)

    # CH4 forcing (0.036 W/m² per ppb above baseline)
    f_ch4 = 0.036 * (ch4_ppb - ch4_baseline_ppb)

    # N2O forcing (0.12 W/m² per ppb above baseline)
    f_n2o = 0.12 * (n2o_ppb - n2o_baseline_ppb)

    # Total
    total = f_co2 + f_ch4 + f_n2o

    return {
        "co2": f_co2,
        "ch4": f_ch4,
        "n2o": f_n2o,
        "total": total,
    }


def carbon_offset_verification(
    offset_amount_tonnes: float, baseline_emissions_tonnes: float, verification_standard: str = "gold"
) -> dict[str, float]:
    """Verify carbon offset quantities with adjustment factors.

    Verification standards have different credibility factors.

    Args:
        offset_amount_tonnes: Carbon offset claimed in tonnes CO2e.
        baseline_emissions_tonnes: Baseline emission level in tonnes.
        verification_standard: Verification standard ("gold", "vcs", "default").

    Returns:
        Dictionary with verified offset and reduction percentage.

    Raises:
        InvalidParameterError: If standard is invalid.
    """
    standards = {"gold": 0.95, "vcs": 0.90, "default": 0.80}

    if verification_standard not in standards:
        raise InvalidParameterError(
            f"Unknown standard: {verification_standard}", "verification_standard", verification_standard
        )

    factor = standards[verification_standard]
    verified_offset = offset_amount_tonnes * factor
    reduction_percent = (verified_offset / baseline_emissions_tonnes) * 100 if baseline_emissions_tonnes > 0 else 0

    return {
        "claimed_offset": offset_amount_tonnes,
        "verified_offset": verified_offset,
        "credibility_factor": factor,
        "reduction_percent": reduction_percent,
    }


def emission_reduction_scenario(
    baseline_emissions_gt: float,
    target_year: int,
    reduction_rate_percent_per_year: float,
    acceleration_factor: float = 1.0,
) -> list[tuple[int, float]]:
    """Model emission reduction pathway to target.

    Args:
        baseline_emissions_gt: Baseline emissions in Gt CO2e.
        target_year: Target year for reductions.
        reduction_rate_percent_per_year: Annual reduction rate (%).
        acceleration_factor: Acceleration of reduction over time (1.0 = linear).

    Returns:
        List of (year, emissions_gt) tuples.
    """
    start_year = 2020
    years_span = target_year - start_year

    pathway = []

    for year in range(start_year, target_year + 1):
        years_elapsed = year - start_year

        # Accelerating reduction with polynomial factor
        if years_span > 0:
            progress = years_elapsed / years_span
            acceleration = 1.0 + (acceleration_factor - 1.0) * (progress**2)
        else:
            acceleration = 1.0

        reduction_fraction = (reduction_rate_percent_per_year / 100.0) * years_elapsed * acceleration
        emissions = baseline_emissions_gt * max(0, 1.0 - reduction_fraction)

        pathway.append((year, emissions))

    return pathway


def rcp_scenario_co2_projection(scenario: str, years: list[int]) -> list[float]:
    """Project CO2 concentrations for RCP scenarios.

    RCP 2.6, 4.5, 6.0, 8.5 represent different pathways.

    Args:
        scenario: RCP scenario ("2.6", "4.5", "6.0", "8.5").
        years: List of years for projection.

    Returns:
        List of CO2 concentrations in ppm for each year.

    Raises:
        InvalidParameterError: If scenario is invalid.
    """
    valid_scenarios = {"2.6": 420, "4.5": 540, "6.0": 670, "8.5": 936}

    if scenario not in valid_scenarios:
        raise InvalidParameterError(f"Invalid RCP scenario: {scenario}", "scenario", scenario)

    end_year = 2100
    end_co2 = valid_scenarios[scenario]
    start_year = 2020
    start_co2 = 410.0

    projections = []

    for year in years:
        if year < start_year:
            # Use observational data (simplified)
            co2 = start_co2
        elif year > end_year:
            # Beyond 2100, hold constant
            co2 = end_co2
        else:
            # Linear interpolation with acceleration
            progress = (year - start_year) / (end_year - start_year)
            acceleration = math.exp(0.02 * progress)  # Accelerating increase

            co2 = start_co2 + (end_co2 - start_co2) * progress * acceleration

        projections.append(co2)

    return projections
