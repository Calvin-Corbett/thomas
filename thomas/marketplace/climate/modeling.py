"""Climate modeling framework for projections and sensitivity studies.

This module provides energy balance models, radiative-convective models,
climate sensitivity estimation, RCP scenario implementation, feedback
parameterizations, and ensemble statistics.
"""

import math

from thomas.marketplace.climate._exceptions import InvalidParameterError, ModelError


def energy_balance_model_zero_dimensional(
    co2_ppm: float, albedo: float = 0.3, greenhouse_factor: float = 0.61
) -> tuple[float, float]:
    """Calculate planetary equilibrium temperature using 0D energy balance.

    Incoming solar = Outgoing longwave radiation
    S(1-α)/4 = σT^4(1 + f×ln(C/C₀))

    Args:
        co2_ppm: CO2 concentration in ppm.
        albedo: Planetary albedo (0-1, default 0.3).
        greenhouse_factor: Greenhouse gas factor (default 0.61).

    Returns:
        Tuple of (temperature_k, temperature_anomaly_k).

    Raises:
        InvalidParameterError: If parameters are invalid.
    """
    if albedo < 0 or albedo > 1:
        raise InvalidParameterError("Albedo must be 0-1", "albedo", albedo)

    # Solar constant and Stefan-Boltzmann constant
    s0 = 1361.0  # W/m² solar constant
    sigma = 5.670374419e-8  # Stefan-Boltzmann constant

    # Pre-industrial baseline
    co2_pi = 280.0
    c0_ratio = co2_ppm / co2_pi

    # Incoming solar energy
    q_in = s0 * (1 - albedo) / 4.0

    # Radiative forcing factor
    radiative_factor = 1.0 + greenhouse_factor * math.log(c0_ratio)

    # Equilibrium temperature
    temp_k_4 = q_in / (sigma * radiative_factor)
    temp_k = temp_k_4**0.25

    # Temperature anomaly relative to pre-industrial
    temp_pi = (s0 * (1 - albedo) / (4 * sigma)) ** 0.25
    temp_anomaly_k = temp_k - temp_pi

    return temp_k, temp_anomaly_k


def climate_sensitivity_estimation(radiative_forcing_w_m2: float, temperature_change_k: float) -> float:
    """Estimate climate sensitivity (ΔT/ΔF in K/(W/m²)).

    Climate sensitivity λ = ΔT / ΔF
    Equilibrium climate sensitivity (ECS) ≈ 3 K for 2×CO₂ forcing.

    Args:
        radiative_forcing_w_m2: Radiative forcing change in W/m².
        temperature_change_k: Resulting temperature change in Kelvin.

    Returns:
        Climate sensitivity parameter in K/(W/m²).

    Raises:
        InvalidParameterError: If forcing is zero.
    """
    if radiative_forcing_w_m2 == 0:
        raise InvalidParameterError("Forcing cannot be zero", "radiative_forcing_w_m2", radiative_forcing_w_m2)

    return temperature_change_k / radiative_forcing_w_m2


def transient_climate_response(climate_sensitivity_k_w_m2: float, co2_forcing_w_m2: float = 3.7) -> float:
    """Calculate transient climate response to CO2 doubling.

    TCR is temperature change when CO2 doubles at 1%/year (first 70 years).

    Args:
        climate_sensitivity_k_w_m2: Climate sensitivity parameter.
        co2_forcing_w_m2: Forcing for 2×CO2 (typically 3.7 W/m²).

    Returns:
        Transient climate response in Kelvin.
    """
    # TCR is typically ~0.6 × ECS due to thermal inertia
    tcr = climate_sensitivity_k_w_m2 * co2_forcing_w_m2 * 0.6

    return tcr


def rcp_scenario_temperature_projection(
    scenario: str, years: list[int], climate_sensitivity_k: float = 3.0
) -> list[float]:
    """Project global temperature for RCP scenario.

    Args:
        scenario: RCP scenario string ("2.6", "4.5", "6.0", "8.5").
        years: List of years for projection.
        climate_sensitivity_k: Climate sensitivity in Kelvin.

    Returns:
        List of temperature anomalies in Kelvin for each year.

    Raises:
        InvalidParameterError: If scenario is invalid.
    """
    scenarios = {
        "2.6": {"forcing_2100": 2.6, "rate": 0.008},
        "4.5": {"forcing_2100": 4.5, "rate": 0.012},
        "6.0": {"forcing_2100": 6.0, "rate": 0.014},
        "8.5": {"forcing_2100": 8.5, "rate": 0.018},
    }

    if scenario not in scenarios:
        raise InvalidParameterError(f"Invalid RCP scenario: {scenario}", "scenario", scenario)

    params = scenarios[scenario]
    forcing_2100 = params["forcing_2100"]
    base_year = 2020
    end_year = 2100

    temperatures = []

    for year in years:
        if year < base_year:
            # Use historical (simplified)
            temp_anomaly = (year - 1900) * 0.018
        elif year > end_year:
            # Hold at 2100 value
            temp_anomaly = forcing_2100 * climate_sensitivity_k / 3.7
        else:
            # Linear interpolation with acceleration
            progress = (year - base_year) / (end_year - base_year)
            forcing = params["rate"] * (year - 2000)

            # Temperature response (with lag due to thermal inertia)
            temp_anomaly = (forcing * climate_sensitivity_k / 3.7) * (1 - 0.5 * math.exp(-progress))

        temperatures.append(temp_anomaly)

    return temperatures


def water_vapor_feedback(temperature_change_k: float, reference_rh: float = 75.0) -> float:
    """Calculate water vapor feedback effect.

    Water vapor feedback amplifies warming (positive feedback).

    Args:
        temperature_change_k: Temperature change in Kelvin.
        reference_rh: Reference relative humidity (%).

    Returns:
        Feedback parameter in W/m²/K.
    """
    # Water vapor feedback parameter: typically 1.8 ± 0.18 W/m²/K
    # (Dessler et al., 2008)
    base_feedback = 1.8

    # Clausius-Clapeyron scaling: ~7% per K
    clausius_clapeyron = 0.07

    # Feedback scales with temperature change
    feedback = base_feedback * (1 + clausius_clapeyron * temperature_change_k)

    return feedback


def cloud_feedback(temperature_change_k: float, cloud_type: str = "mixed") -> float:
    """Calculate cloud feedback effect.

    Cloud feedback is uncertain; ranges from -0.5 to +1.0 W/m²/K.

    Args:
        temperature_change_k: Temperature change in Kelvin.
        cloud_type: Cloud type ("low", "mid", "high", "mixed").

    Returns:
        Feedback parameter in W/m²/K.
    """
    # Cloud feedback parameters (uncertain)
    feedbacks = {
        "low": 0.29,  # Positive (less low cloud cover in warming)
        "mid": 0.01,  # Neutral
        "high": 0.08,  # Positive (higher clouds in warming)
        "mixed": 0.25,  # Average mixed sign
    }

    base_feedback = feedbacks.get(cloud_type, 0.25)

    # Temperature dependence
    feedback = base_feedback * (1 + 0.05 * temperature_change_k)

    return feedback


def ice_albedo_feedback(temperature_change_k: float, initial_ice_fraction: float = 0.05) -> float:
    """Calculate ice-albedo feedback effect.

    Ice-albedo is a positive feedback (reduces albedo as ice melts).

    Args:
        temperature_change_k: Temperature change in Kelvin.
        initial_ice_fraction: Initial ice/snow covered fraction.

    Returns:
        Feedback parameter in W/m²/K.
    """
    # Ice-albedo feedback: typically -0.15 to -0.25 W/m²/K (negative because
    # less ice reduces albedo, trapping more heat = positive feedback)
    # Sign convention: positive feedback amplifies warming
    base_feedback = 0.20

    # Solar constant
    s0 = 1361.0

    # Feedback scales with ice fraction
    feedback = (base_feedback * s0 / 4.0 / 273.15) * initial_ice_fraction

    return feedback


def total_feedback_parameter(
    temperature_change_k: float,
    include_water_vapor: bool = True,
    include_clouds: bool = True,
    include_ice_albedo: bool = True,
    include_lapse_rate: bool = True,
) -> float:
    """Calculate total climate feedback parameter.

    Negative feedback opposes warming; positive amplifies warming.

    Args:
        temperature_change_k: Temperature change in Kelvin.
        include_water_vapor: Include water vapor feedback.
        include_clouds: Include cloud feedback.
        include_ice_albedo: Include ice-albedo feedback.
        include_lapse_rate: Include lapse rate feedback.

    Returns:
        Total feedback parameter in W/m²/K.
    """
    total_feedback = 0.0

    if include_water_vapor:
        total_feedback += water_vapor_feedback(temperature_change_k)

    if include_clouds:
        total_feedback += cloud_feedback(temperature_change_k)

    if include_ice_albedo:
        total_feedback += ice_albedo_feedback(temperature_change_k)

    if include_lapse_rate:
        # Lapse rate feedback: typically -0.34 W/m²/K (negative)
        total_feedback -= 0.34 * (1 + 0.01 * temperature_change_k)

    return total_feedback


def model_ensemble_mean(model_outputs: list[list[float]]) -> list[float]:
    """Calculate ensemble mean from multiple model runs.

    Args:
        model_outputs: List of model output arrays.

    Returns:
        Ensemble mean values.

    Raises:
        ModelError: If models have different lengths.
    """
    if not model_outputs:
        raise ModelError("Empty model ensemble", "ensemble")

    lengths = [len(output) for output in model_outputs]
    if len(set(lengths)) > 1:
        raise ModelError("All models must have same length outputs", "ensemble")

    n_steps = len(model_outputs[0])
    n_models = len(model_outputs)

    ensemble_mean = []
    for i in range(n_steps):
        mean_val = sum(output[i] for output in model_outputs) / n_models
        ensemble_mean.append(mean_val)

    return ensemble_mean


def model_ensemble_uncertainty(model_outputs: list[list[float]]) -> tuple[list[float], list[float]]:
    """Calculate ensemble uncertainty (percentiles) from multiple models.

    Args:
        model_outputs: List of model output arrays.

    Returns:
        Tuple of (percentile_5, percentile_95) representing 90% confidence interval.

    Raises:
        ModelError: If models have different lengths.
    """
    if not model_outputs:
        raise ModelError("Empty model ensemble", "ensemble")

    lengths = [len(output) for output in model_outputs]
    if len(set(lengths)) > 1:
        raise ModelError("All models must have same length outputs", "ensemble")

    n_steps = len(model_outputs[0])
    p5 = []
    p95 = []

    for i in range(n_steps):
        values = [output[i] for output in model_outputs]
        sorted_vals = sorted(values)

        idx_5 = int(0.05 * len(sorted_vals))
        idx_95 = int(0.95 * len(sorted_vals))

        p5.append(sorted_vals[idx_5])
        p95.append(sorted_vals[idx_95])

    return p5, p95


def heat_diffusion_penetration_depth(period_seconds: float, thermal_diffusivity_m2_s: float = 5e-7) -> float:
    """Calculate depth of temperature signal penetration over time period.

    Used for estimating ocean heat penetration depth and seasonal cycles.

    Args:
        period_seconds: Time period in seconds.
        thermal_diffusivity_m2_s: Thermal diffusivity of medium.

    Returns:
        Penetration depth in meters.
    """
    # Characteristic penetration depth: √(4×κ×t)
    depth = 2 * math.sqrt(thermal_diffusivity_m2_s * period_seconds)

    return depth


def radiative_equilibrium_temperature(
    co2_ppm: float, surface_pressure_hpa: float = 1013.25, surface_emissivity: float = 0.99
) -> float:
    """Calculate radiative equilibrium surface temperature.

    Simple radiative balance assuming clear-sky conditions.

    Args:
        co2_ppm: CO2 concentration in ppm.
        surface_pressure_hpa: Surface pressure in hPa.
        surface_emissivity: Surface emissivity (0-1).

    Returns:
        Equilibrium temperature in Kelvin.
    """
    # Solar constant and albedo
    s0 = 1361.0  # W/m²
    alpha = 0.30  # Planetary albedo

    # Incoming solar
    q_solar = s0 * (1 - alpha) / 4.0

    # Outgoing longwave (Stefan-Boltzmann)
    sigma = 5.67e-8

    # Greenhouse effect parameterization
    co2_factor = 1.0 + 0.61 * math.log(co2_ppm / 280.0)

    # Effective temperature (radiative equilibrium)
    t_eff_4 = q_solar / (sigma * co2_factor)
    t_eff = t_eff_4**0.25

    return t_eff
