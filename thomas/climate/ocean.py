"""Ocean science and marine climate analysis.

This module provides ocean-related climate analysis including sea surface
temperature, ocean heat content, sea level rise projection, ocean acidification,
ENSO index, thermohaline circulation, and tidal prediction.
"""

import math

from thomas.climate._exceptions import ClimateDataError, InvalidParameterError

# Physical constants
SEAWATER_DENSITY: float = 1025.0  # kg/m³
SPECIFIC_HEAT_SEAWATER: float = 3850.0  # J/(kg·K)
THERMAL_EXPANSION_COEFFICIENT: float = 0.0002  # K⁻¹ for seawater


def sea_surface_temperature_anomaly(sst_celsius: float, baseline_sst_celsius: float) -> float:
    """Calculate sea surface temperature anomaly.

    Args:
        sst_celsius: Current sea surface temperature in Celsius.
        baseline_sst_celsius: Baseline period mean SST in Celsius.

    Returns:
        SST anomaly in Celsius.
    """
    return sst_celsius - baseline_sst_celsius


def ocean_heat_content(temperature_profile_c: list[float], depths_m: list[float], area_m2: float) -> float:
    """Calculate ocean heat content for temperature profile.

    Heat content: OHC = ∫ ρ × Cp × T(z) × dz

    Args:
        temperature_profile_c: Temperature at each depth in Celsius.
        depths_m: Corresponding depths in meters.
        area_m2: Ocean surface area in m².

    Returns:
        Ocean heat content in Joules.

    Raises:
        ClimateDataError: If profile lengths don't match.
    """
    if len(temperature_profile_c) != len(depths_m):
        raise ClimateDataError("Temperature and depth profiles must match length")

    if not temperature_profile_c:
        return 0.0

    # Integrate heat content using trapezoidal rule
    ohc = 0.0
    for i in range(len(temperature_profile_c) - 1):
        temp_avg = (temperature_profile_c[i] + temperature_profile_c[i + 1]) / 2
        depth_interval = abs(depths_m[i + 1] - depths_m[i])

        # Heat = density × Cp × temperature × volume
        ohc += SEAWATER_DENSITY * SPECIFIC_HEAT_SEAWATER * temp_avg * depth_interval * area_m2

    return ohc


def sea_level_rise_projection(
    thermal_expansion_rate_mm_year: float, ice_melt_contribution_mm_year: float, years_projection: int
) -> tuple[float, float]:
    """Project sea level rise from thermal expansion and ice melt.

    Args:
        thermal_expansion_rate_mm_year: Thermal expansion rate in mm/year.
        ice_melt_contribution_mm_year: Ice sheet/glacier melt contribution in mm/year.
        years_projection: Years to project forward.

    Returns:
        Tuple of (total_rise_mm, acceleration_factor).
    """
    # Linear projection with acceleration factor for ice melt
    acceleration_factor = 1.0 + (years_projection / 100.0) * 0.15  # 15% per century

    thermal_rise = thermal_expansion_rate_mm_year * years_projection
    melt_rise = ice_melt_contribution_mm_year * years_projection * acceleration_factor

    total_rise = thermal_rise + melt_rise

    return total_rise, acceleration_factor


def ocean_acidification_ph(co2_ppm: float, reference_co2_ppm: float = 280.0, reference_ph: float = 8.21) -> float:
    """Calculate ocean pH change from CO2 concentration using carbonate chemistry.

    Simplified relationship: pH ≈ pH₀ - 0.003 × ΔCO₂

    Args:
        co2_ppm: Current atmospheric CO2 in ppm.
        reference_co2_ppm: Pre-industrial CO2 (baseline).
        reference_ph: Reference ocean pH at baseline CO2.

    Returns:
        Current ocean surface pH.
    """
    co2_change = co2_ppm - reference_co2_ppm

    # Empirical relationship from carbonate chemistry
    ph_change = -0.0030 * co2_change

    current_ph = reference_ph + ph_change

    return current_ph


def saturation_state_aragonite(temperature_c: float, salinity_psu: float = 35.0, depth_m: float = 0.0) -> float:
    """Calculate aragonite saturation state Omega_A.

    Omega < 1 indicates undersaturation (dissolution of aragonite).

    Args:
        temperature_c: Water temperature in Celsius.
        salinity_psu: Salinity in practical salinity units.
        depth_m: Depth in meters.

    Returns:
        Omega_A saturation state.
    """
    # Temperature and salinity dependence (simplified)
    omega_base = 3.5

    temp_factor = 1.0 - 0.015 * temperature_c
    salinity_factor = 1.0 + 0.005 * (salinity_psu - 35.0)
    depth_factor = 1.0 - 0.0004 * depth_m

    omega_a = omega_base * temp_factor * salinity_factor * depth_factor

    return max(0.1, omega_a)


def enso_index_oni(sst_anomalies_nino34: list[float]) -> list[float]:
    """Calculate ENSO index (Oceanic Niño Index) from SST anomalies.

    Nino 3.4 region SST anomaly with 3-month smoothing.

    Args:
        sst_anomalies_nino34: List of monthly SST anomalies in Nino 3.4 region (°C).

    Returns:
        List of smoothed ONI values.

    Raises:
        ClimateDataError: If insufficient data.
    """
    if not sst_anomalies_nino34 or len(sst_anomalies_nino34) < 3:
        raise ClimateDataError("Need at least 3 months of SST anomalies", sst_anomalies_nino34)

    # 3-month running mean
    oni = []
    for i in range(len(sst_anomalies_nino34) - 2):
        mean_anomaly = sum(sst_anomalies_nino34[i : i + 3]) / 3.0
        oni.append(mean_anomaly)

    return oni


def enso_phase_classification(oni_value: float) -> str:
    """Classify ENSO phase from ONI value.

    Args:
        oni_value: Oceanic Niño Index value in °C.

    Returns:
        ENSO phase: "Strong El Nino", "El Nino", "Neutral", "La Nina", "Strong La Nina".
    """
    if oni_value >= 1.5:
        return "Strong El Nino"
    elif oni_value >= 0.5:
        return "El Nino"
    elif oni_value > -0.5:
        return "Neutral"
    elif oni_value >= -1.5:
        return "La Nina"
    else:
        return "Strong La Nina"


def thermohaline_circulation_index(
    north_atlantic_sst_c: float, arctic_freshwater_kg_s: float, deep_water_temperature_c: float
) -> float:
    """Estimate thermohaline circulation (Atlantic Meridional Overturning) strength.

    Args:
        north_atlantic_sst_c: North Atlantic SST in Celsius.
        arctic_freshwater_kg_s: Arctic freshwater input in kg/s.
        deep_water_temperature_c: Deep water temperature in Celsius.

    Returns:
        Relative circulation strength (normalized, 1.0 = modern baseline).
    """
    # Simplified model based on density gradient
    sst_factor = 1.0 - 0.08 * (north_atlantic_sst_c - 10.0)  # Warmer = weaker
    freshwater_factor = 1.0 - (arctic_freshwater_kg_s / 1000000.0) * 0.0001
    temp_gradient = north_atlantic_sst_c - deep_water_temperature_c

    circulation_strength = sst_factor * freshwater_factor * (temp_gradient / 15.0)

    return max(0.1, circulation_strength)


def tidal_constituent_amplitude(harmonic_constant: str = "M2", mean_range_m: float = 1.0) -> float:
    """Get tidal constituent amplitude for major tidal component.

    Constituent periods:
    M2: Principal lunar semidiurnal (12.42 hours)
    S2: Principal solar semidiurnal (12.00 hours)
    K1: Lunar diurnal (23.93 hours)
    O1: Principal lunar diurnal (25.82 hours)

    Args:
        harmonic_constant: Tidal constituent code.
        mean_range_m: Mean tidal range in meters.

    Returns:
        Constituent amplitude in meters.

    Raises:
        InvalidParameterError: If constituent is invalid.
    """
    constituents = {
        "M2": 0.583,  # 58.3% of mean range
        "S2": 0.183,  # 18.3%
        "K1": 0.142,  # 14.2%
        "O1": 0.081,  # 8.1%
    }

    if harmonic_constant not in constituents:
        raise InvalidParameterError("Invalid harmonic constant", "harmonic_constant", harmonic_constant)

    return mean_range_m * constituents[harmonic_constant]


def tidal_prediction(
    time_hours: list[float],
    m2_amplitude_m: float,
    s2_amplitude_m: float,
    k1_amplitude_m: float,
    o1_amplitude_m: float,
    m2_phase_deg: float = 0.0,
) -> list[float]:
    """Predict water level using harmonic tidal analysis.

    Args:
        time_hours: Hours since start (0-24 or longer).
        m2_amplitude_m: M2 constituent amplitude in meters.
        s2_amplitude_m: S2 constituent amplitude in meters.
        k1_amplitude_m: K1 constituent amplitude in meters.
        o1_amplitude_m: O1 constituent amplitude in meters.
        m2_phase_deg: M2 phase lag in degrees.

    Returns:
        List of predicted water levels in meters.
    """
    predictions = []

    # Period of constituents in hours
    m2_period = 12.42
    s2_period = 12.00
    k1_period = 23.93
    o1_period = 25.82

    for t in time_hours:
        # Phase angles in radians
        m2_phase = (2 * math.pi * t / m2_period) + math.radians(m2_phase_deg)
        s2_phase = 2 * math.pi * t / s2_period
        k1_phase = 2 * math.pi * t / k1_period
        o1_phase = 2 * math.pi * t / o1_period

        # Superposition of constituents
        level = (
            m2_amplitude_m * math.cos(m2_phase)
            + s2_amplitude_m * math.cos(s2_phase)
            + k1_amplitude_m * math.cos(k1_phase)
            + o1_amplitude_m * math.cos(o1_phase)
        )

        predictions.append(level)

    return predictions


def marine_heatwave_detection(
    daily_sst_c: list[float], threshold_percentile: float = 90.0, duration_days: int = 5
) -> list[tuple[int, int]]:
    """Detect marine heatwaves using threshold exceedance.

    Marine heatwave: temperatures exceed 90th percentile for ≥5 consecutive days.

    Args:
        daily_sst_c: List of daily SST values in Celsius.
        threshold_percentile: Percentile threshold (default 90).
        duration_days: Minimum consecutive days for event.

    Returns:
        List of (start_day, end_day) tuples for each detected heatwave.

    Raises:
        ClimateDataError: If insufficient data.
    """
    if not daily_sst_c or len(daily_sst_c) < duration_days:
        raise ClimateDataError("Insufficient data for heatwave detection", daily_sst_c)

    # Calculate threshold
    sorted_sst = sorted(daily_sst_c)
    threshold_index = int((threshold_percentile / 100.0) * len(sorted_sst))
    threshold = sorted_sst[min(threshold_index, len(sorted_sst) - 1)]

    # Detect consecutive days above threshold
    heatwaves = []
    in_event = False
    event_start = 0

    for i, sst in enumerate(daily_sst_c):
        if sst >= threshold:
            if not in_event:
                event_start = i
                in_event = True
        else:
            if in_event and (i - event_start) >= duration_days:
                heatwaves.append((event_start, i - 1))
            in_event = False

    # Check if event extends to end of series
    if in_event and (len(daily_sst_c) - event_start) >= duration_days:
        heatwaves.append((event_start, len(daily_sst_c) - 1))

    return heatwaves
