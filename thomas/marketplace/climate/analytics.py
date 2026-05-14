"""Climate analytics, classification, and data quality tools.

This module provides climate classification systems, climate normals calculation,
trend significance testing, extreme value analysis, climate indicators, data
quality control, and homogeneity testing.
"""

import math

from thomas.marketplace.climate._exceptions import ClimateDataError


def koppen_geiger_classification(
    mean_annual_temp_c: float,
    mean_annual_precip_mm: float,
    coldest_month_temp_c: float,
    warmest_month_temp_c: float,
    driest_month_precip_mm: float,
) -> str:
    """Classify climate using Koppen-Geiger system.

    Returns climate classification code (e.g., "Cfa", "BWh", "Dfb").

    Args:
        mean_annual_temp_c: Mean annual temperature in Celsius.
        mean_annual_precip_mm: Mean annual precipitation in mm.
        coldest_month_temp_c: Coldest month mean temperature in Celsius.
        warmest_month_temp_c: Warmest month mean temperature in Celsius.
        driest_month_precip_mm: Driest month precipitation in mm.

    Returns:
        Koppen-Geiger climate classification string.
    """
    # Group A: Tropical (mean annual temp > 18°C)
    if mean_annual_temp_c >= 18:
        if mean_annual_precip_mm >= 2000:
            return "Af"  # Tropical rainforest
        elif driest_month_precip_mm >= 60:
            return "Am"  # Tropical monsoon
        elif driest_month_precip_mm >= mean_annual_precip_mm / 25:
            return "Aw"  # Tropical wet/dry
        else:
            return "As"  # Tropical dry

    # Group B: Arid
    elif mean_annual_precip_mm < 500:
        if mean_annual_temp_c > 18:
            if mean_annual_precip_mm < 250:
                return "BWh"  # Hot desert
            else:
                return "BSh"  # Hot steppe
        else:
            if mean_annual_precip_mm < 250:
                return "BWk"  # Cold desert
            else:
                return "BSk"  # Cold steppe

    # Group C: Temperate (0 > coldest month > -3°C)
    elif coldest_month_temp_c > -3:
        if mean_annual_precip_mm >= 1500:
            return "Cfb"  # Oceanic
        elif warmest_month_temp_c > 10:
            if driest_month_precip_mm < 30:
                return "Csa"  # Mediterranean hot
            else:
                return "Cfa"  # Humid subtropical
        else:
            return "Cfc"  # Subpolar oceanic

    # Group D: Continental (coldest month < -3°C)
    elif coldest_month_temp_c <= -3:
        if warmest_month_temp_c > 10:
            if driest_month_precip_mm < 30:
                return "Dfa"  # Humid continental hot summer
            else:
                return "Dfb"  # Humid continental warm summer
        else:
            return "Dfc"  # Subpolar

    # Group E: Polar
    else:
        if mean_annual_temp_c > -10:
            return "ET"  # Tundra
        else:
            return "EF"  # Polar ice cap


def climate_normals(observations: list[float], period_years: int = 30) -> tuple[float, float, float]:
    """Calculate 30-year climate normal.

    Climate normals are the arithmetic mean of a climate variable over a
    standard period (typically 30 years).

    Args:
        observations: List of observations (daily, monthly, or annual).
        period_years: Averaging period in years (default 30).

    Returns:
        Tuple of (mean, std_dev, count).

    Raises:
        ClimateDataError: If insufficient data.
    """
    if not observations:
        raise ClimateDataError("Observations list is empty", observations)

    # For monthly data, need period_years * 12 values
    min_required = period_years * 12

    if len(observations) < min_required:
        raise ClimateDataError(f"Need at least {min_required} observations", observations)

    # Use most recent period
    period_data = observations[-min_required:]

    mean = sum(period_data) / len(period_data)
    variance = sum((x - mean) ** 2 for x in period_data) / len(period_data)
    std_dev = math.sqrt(variance)

    return mean, std_dev, len(period_data)


def mann_kendall_trend_test(data: list[float]) -> tuple[float, float, str]:
    """Perform Mann-Kendall test for trend significance.

    Returns Z-statistic and p-value. Positive Z = increasing trend.

    Args:
        data: List of time series values.

    Returns:
        Tuple of (z_statistic, p_value, trend_direction).

    Raises:
        ClimateDataError: If insufficient data.
    """
    if not data or len(data) < 3:
        raise ClimateDataError("Need at least 3 data points", data)

    n = len(data)
    s = 0

    # Calculate Mann-Kendall S statistic
    for i in range(n - 1):
        for j in range(i + 1, n):
            if data[j] > data[i]:
                s += 1
            elif data[j] < data[i]:
                s -= 1

    # Variance calculation
    var_s = n * (n - 1) * (2 * n + 5) / 18

    # Z-score calculation
    if s > 0:
        z = (s - 1) / math.sqrt(var_s)
        trend = "increasing"
    elif s < 0:
        z = (s + 1) / math.sqrt(var_s)
        trend = "decreasing"
    else:
        z = 0.0
        trend = "no_trend"

    # Two-tailed p-value
    from scipy.stats import norm

    p_value = 2 * (1 - norm.cdf(abs(z)))

    return z, p_value, trend


def extreme_value_analysis_gev(extremes: list[float], return_periods: list[int]) -> dict[int, float]:
    """Perform extreme value analysis using GEV distribution.

    Args:
        extremes: List of annual extreme values.
        return_periods: Return periods in years for estimates.

    Returns:
        Dictionary mapping return periods to extreme values.

    Raises:
        ClimateDataError: If insufficient data.
    """
    if not extremes or len(extremes) < 10:
        raise ClimateDataError("Need at least 10 extremes", extremes)

    # Fit parameters
    mean = sum(extremes) / len(extremes)
    variance = sum((x - mean) ** 2 for x in extremes) / len(extremes)
    std_dev = math.sqrt(variance)

    # Gumbel (Type I) approximation
    sqrt_6_pi = math.sqrt(6) / math.pi
    location = mean - sqrt_6_pi * std_dev * 0.5772156649
    scale = sqrt_6_pi * std_dev

    # Calculate return values
    results = {}
    for rp in return_periods:
        reduced_variate = -math.log(-math.log(1 - 1 / rp))
        return_value = location + scale * reduced_variate
        results[rp] = return_value

    return results


def climate_change_indicator_dashboard(
    global_temp_anomaly_k: float,
    sea_level_rise_mm: float,
    ice_loss_gt_year: float,
    co2_ppm: float,
    arctic_sea_ice_extent_million_km2: float,
) -> dict[str, tuple[float, str]]:
    """Create climate change indicator dashboard.

    Args:
        global_temp_anomaly_k: Global temperature anomaly in Kelvin.
        sea_level_rise_mm: Annual sea level rise in mm.
        ice_loss_gt_year: Annual ice sheet loss in Gt/year.
        co2_ppm: CO2 concentration in ppm.
        arctic_sea_ice_extent_million_km2: Arctic sea ice extent.

    Returns:
        Dictionary of indicators with status (green/yellow/red).
    """
    indicators = {}

    # Temperature
    if global_temp_anomaly_k < 0.5:
        temp_status = "green"
    elif global_temp_anomaly_k < 1.0:
        temp_status = "yellow"
    else:
        temp_status = "red"
    indicators["Temperature Anomaly"] = (global_temp_anomaly_k, temp_status)

    # Sea level rise
    if sea_level_rise_mm < 3:
        slr_status = "green"
    elif sea_level_rise_mm < 5:
        slr_status = "yellow"
    else:
        slr_status = "red"
    indicators["Sea Level Rise"] = (sea_level_rise_mm, slr_status)

    # Ice loss
    if ice_loss_gt_year < 300:
        ice_status = "green"
    elif ice_loss_gt_year < 500:
        ice_status = "yellow"
    else:
        ice_status = "red"
    indicators["Ice Loss Rate"] = (ice_loss_gt_year, ice_status)

    # CO2
    if co2_ppm < 350:
        co2_status = "green"
    elif co2_ppm < 420:
        co2_status = "yellow"
    else:
        co2_status = "red"
    indicators["CO2 Concentration"] = (co2_ppm, co2_status)

    # Arctic sea ice
    if arctic_sea_ice_extent_million_km2 > 8.0:
        ice_extent_status = "green"
    elif arctic_sea_ice_extent_million_km2 > 5.0:
        ice_extent_status = "yellow"
    else:
        ice_extent_status = "red"
    indicators["Arctic Sea Ice Extent"] = (arctic_sea_ice_extent_million_km2, ice_extent_status)

    return indicators


def data_quality_range_check(
    observations: list[float],
    variable_name: str = "temperature",
    physical_min: float | None = None,
    physical_max: float | None = None,
) -> tuple[list[bool], int, int]:
    """Check data quality using physical range limits.

    Args:
        observations: List of observations.
        variable_name: Type of variable ("temperature", "precipitation", "pressure").
        physical_min: Physical minimum value.
        physical_max: Physical maximum value.

    Returns:
        Tuple of (valid_flags, num_invalid, num_missing).
    """
    # Default physical ranges
    ranges = {
        "temperature": (-90, 60),
        "precipitation": (0, 1000),
        "pressure": (800, 1100),
        "humidity": (0, 100),
    }

    if physical_min is None or physical_max is None:
        if variable_name in ranges:
            physical_min, physical_max = ranges[variable_name]
        else:
            physical_min, physical_max = float("-inf"), float("inf")

    valid_flags = []
    num_invalid = 0
    num_missing = 0

    for obs in observations:
        if obs is None or (isinstance(obs, float) and math.isnan(obs)):
            valid_flags.append(False)
            num_missing += 1
        elif physical_min <= obs <= physical_max:
            valid_flags.append(True)
        else:
            valid_flags.append(False)
            num_invalid += 1

    return valid_flags, num_invalid, num_missing


def spatial_consistency_check(
    station_values: dict[str, float], station_coords: dict[str, tuple[float, float]], max_gradient: float = 2.0
) -> dict[str, bool]:
    """Check spatial consistency between stations.

    Args:
        station_values: Dictionary of {station_id: value}.
        station_coords: Dictionary of {station_id: (lat, lon)}.
        max_gradient: Maximum allowed gradient per 100 km.

    Returns:
        Dictionary of {station_id: is_consistent}.
    """
    consistency = {sid: True for sid in station_values}

    stations = list(station_values.keys())

    for i in range(len(stations)):
        for j in range(i + 1, len(stations)):
            sid1, sid2 = stations[i], stations[j]

            # Distance between stations (simplified great circle)
            lat1, lon1 = station_coords[sid1]
            lat2, lon2 = station_coords[sid2]

            dlat = lat2 - lat1
            dlon = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))

            distance_km = math.sqrt(dlat**2 + dlon**2) * 111.0  # Approx degrees to km

            # Value difference
            val_diff = abs(station_values[sid1] - station_values[sid2])

            # Check gradient
            expected_max_diff = max_gradient * (distance_km / 100.0)

            if val_diff > expected_max_diff * 2:  # Flag if > 2× expected
                consistency[sid1] = False
                consistency[sid2] = False

    return consistency


def temporal_consistency_check(
    observations: list[float], max_jump: float = 10.0, consecutive_repeat_limit: int = 3
) -> tuple[list[bool], int]:
    """Check temporal consistency of time series.

    Args:
        observations: List of observations in time order.
        max_jump: Maximum allowed value change between consecutive observations.
        consecutive_repeat_limit: Maximum consecutive identical values.

    Returns:
        Tuple of (valid_flags, num_suspicious).
    """
    valid_flags = [True] * len(observations)
    num_suspicious = 0

    # Check for unrealistic jumps
    for i in range(1, len(observations)):
        if observations[i] is not None and observations[i - 1] is not None:
            jump = abs(observations[i] - observations[i - 1])

            if jump > max_jump:
                valid_flags[i] = False
                num_suspicious += 1

    # Check for repeated values
    for i in range(len(observations) - consecutive_repeat_limit + 1):
        window = observations[i : i + consecutive_repeat_limit]

        if all(w == window[0] for w in window) and window[0] is not None:
            for j in range(i, i + consecutive_repeat_limit):
                valid_flags[j] = False
                num_suspicious += 1

    return valid_flags, num_suspicious


def homogeneity_test_pettitt(observations: list[float]) -> tuple[float, float, int]:
    """Test for homogeneity/changepoint using Pettitt test.

    Args:
        observations: List of observations.

    Returns:
        Tuple of (test_statistic, p_value, change_point_index).

    Raises:
        ClimateDataError: If insufficient data.
    """
    if not observations or len(observations) < 10:
        raise ClimateDataError("Need at least 10 observations", observations)

    n = len(observations)
    U = 0

    # Calculate Pettitt statistic
    for i in range(n):
        for j in range(i + 1, n):
            if observations[j] > observations[i]:
                U += 1
            elif observations[j] < observations[i]:
                U -= 1

    # Transformation to U statistic
    U = abs(U)

    # Calculate p-value approximation
    var_u = n * (n - 1) * (2 * n + 5) / 18
    (U - 0.5) / math.sqrt(var_u)

    p_value = 2 * math.exp(-(6 * U**2) / (n**3 + n**2))

    # Find approximate change point
    change_point = 0
    max_abs_u = 0

    for k in range(1, n):
        abs_u_k = abs(
            sum(
                1 if observations[j] > observations[i] else (-1 if observations[j] < observations[i] else 0)
                for i in range(k)
                for j in range(k, n)
            )
        )

        if abs_u_k > max_abs_u:
            max_abs_u = abs_u_k
            change_point = k

    return U, p_value, change_point
