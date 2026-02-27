"""
Wind energy modeling and simulation.

Provides Weibull distribution wind speed modeling, power curve interpolation,
wake effects (Jensen model), turbine layout optimization, and capacity factor
calculation.
"""

import math
from dataclasses import dataclass

from thomas.energy._types import EnergySource, PowerPlant


@dataclass
class WindTurbine:
    """Individual wind turbine specifications."""

    turbine_id: str
    capacity_mw: float
    rotor_diameter_m: float
    hub_height_m: float
    power_curve: list[tuple[float, float]]  # (wind_speed_ms, power_mw)
    cut_in_speed_ms: float = 3.0
    rated_speed_ms: float = 12.0
    cut_out_speed_ms: float = 25.0
    efficiency: float = 0.45  # Betz limit is 0.593


@dataclass
class WakeLossModel:
    """Wake loss calculation model parameters."""

    model_type: str = "jensen"  # "jensen", "larsen", "none"
    downwind_loss_factor: float = 0.05  # 5% loss per turbine downwind
    wake_decay_constant: float = 0.05  # Decay coefficient


@dataclass
class WindPlant(PowerPlant):
    """Wind farm generation plant."""

    latitude: float = 0.0
    longitude: float = 0.0
    elevation: float = 0.0
    turbine_count: int = 10
    turbine_capacity_mw: float = 3.0
    rotor_diameter_m: float = 100.0
    hub_height_m: float = 90.0
    spacing_rotor_diameters: float = 4.0  # Typical spacing
    wind_resource_class: str = "3"  # IEC wind classes 1-7
    surface_roughness_m: float = 0.1  # Forest ~0.5, grassland ~0.1

    def __post_init__(self) -> None:
        self.fuel_type = EnergySource.WIND
        self.capacity_mw = self.turbine_count * self.turbine_capacity_mw


def weibull_distribution(
    wind_speed: float,
    scale_parameter: float = 10.0,
    shape_parameter: float = 2.0,
) -> float:
    """
    Weibull probability density function for wind speed.

    Args:
        wind_speed: Wind speed in m/s
        scale_parameter: Weibull scale parameter (m/s)
        shape_parameter: Weibull shape parameter (dimensionless)

    Returns:
        Probability density
    """
    if wind_speed < 0 or scale_parameter <= 0 or shape_parameter <= 0:
        return 0.0

    k = shape_parameter
    c = scale_parameter

    exponent = -((wind_speed / c) ** k)
    pdf = (k / c) * ((wind_speed / c) ** (k - 1)) * math.exp(exponent)

    return pdf


def weibull_cdf(
    wind_speed: float,
    scale_parameter: float = 10.0,
    shape_parameter: float = 2.0,
) -> float:
    """
    Weibull cumulative distribution function.

    Args:
        wind_speed: Wind speed in m/s
        scale_parameter: Weibull scale parameter
        shape_parameter: Weibull shape parameter

    Returns:
        Cumulative probability (0.0-1.0)
    """
    if wind_speed < 0:
        return 0.0

    k = shape_parameter
    c = scale_parameter

    cdf = 1.0 - math.exp(-((wind_speed / c) ** k))
    return min(1.0, cdf)


def wind_shear_profile(
    wind_speed_ref: float,
    height_ref: float,
    height_target: float,
    surface_roughness: float = 0.1,
) -> float:
    """
    Calculate wind speed at target height using logarithmic wind profile.

    Args:
        wind_speed_ref: Wind speed at reference height (m/s)
        height_ref: Reference height (m)
        height_target: Target height (m)
        surface_roughness: Surface roughness length (m)

    Returns:
        Wind speed at target height (m/s)
    """
    if height_ref <= surface_roughness or height_target <= surface_roughness:
        return wind_speed_ref

    # Logarithmic wind profile
    ratio = math.log(height_target / surface_roughness) / math.log(height_ref / surface_roughness)
    return wind_speed_ref * ratio


def interpolate_power_curve(
    wind_speed: float,
    power_curve: list[tuple[float, float]],
    cut_in: float = 3.0,
    cut_out: float = 25.0,
) -> float:
    """
    Interpolate power output from wind speed using power curve.

    Args:
        wind_speed: Wind speed in m/s
        power_curve: List of (wind_speed, power_mw) tuples
        cut_in: Cut-in wind speed (m/s)
        cut_out: Cut-out wind speed (m/s)

    Returns:
        Power output in MW
    """
    if wind_speed < cut_in or wind_speed > cut_out or not power_curve:
        return 0.0

    # Sort curve by wind speed
    sorted_curve = sorted(power_curve, key=lambda x: x[0])

    # Find bracketing points
    for i in range(len(sorted_curve) - 1):
        ws1, p1 = sorted_curve[i]
        ws2, p2 = sorted_curve[i + 1]

        if ws1 <= wind_speed <= ws2:
            # Linear interpolation
            if ws2 - ws1 == 0:
                return p1
            fraction = (wind_speed - ws1) / (ws2 - ws1)
            power = p1 + fraction * (p2 - p1)
            return max(0.0, power)

    # Beyond curve
    if wind_speed >= sorted_curve[-1][0]:
        return sorted_curve[-1][1]

    return 0.0


def jensen_wake_loss(
    distance_m: float,
    rotor_diameter_m: float,
    wake_decay: float = 0.05,
) -> float:
    """
    Calculate downwind wind speed deficit using Jensen model.

    Args:
        distance_m: Distance downwind (m)
        rotor_diameter_m: Upwind turbine rotor diameter (m)
        wake_decay: Wake decay constant

    Returns:
        Wind speed deficit fraction (0.0-1.0)
    """
    if distance_m <= 0:
        return 0.0

    # Wake radius grows with distance
    wake_radius = rotor_diameter_m / 2 + wake_decay * distance_m

    # Deficit decreases with distance
    deficit = (rotor_diameter_m / (2 * wake_radius)) ** 2

    return min(1.0, deficit)


def apply_wake_losses(
    turbine_positions: list[tuple[float, float]],
    wind_direction_deg: float,
    wind_speed: float,
    rotor_diameter: float,
    wake_model: WakeLossModel = None,
) -> list[float]:
    """
    Calculate wind speed at each turbine considering wake effects.

    Args:
        turbine_positions: List of (x_m, y_m) coordinates
        wind_direction_deg: Wind direction in degrees (0-360)
        wind_speed: Inflow wind speed in m/s
        rotor_diameter: Rotor diameter in m
        wake_model: Wake loss model parameters

    Returns:
        List of wind speeds at each turbine position
    """
    if not wake_model:
        wake_model = WakeLossModel()

    if wake_model.model_type == "none":
        return [wind_speed] * len(turbine_positions)

    n = len(turbine_positions)
    wind_speeds = [wind_speed] * n

    if wake_model.model_type == "jensen":
        # Convert wind direction to radians
        wind_dir_rad = math.radians(wind_direction_deg)

        for i in range(n):
            x_i, y_i = turbine_positions[i]
            deficit_sq = 0.0

            # Sum deficits from upwind turbines
            for j in range(n):
                if i == j:
                    continue

                x_j, y_j = turbine_positions[j]
                dx = x_i - x_j
                dy = y_i - y_j

                # Check if j is upwind of i
                distance_along_wind = dx * math.cos(wind_dir_rad) + dy * math.sin(wind_dir_rad)

                if distance_along_wind > 0:  # Downwind
                    # Perpendicular distance
                    perp_distance = abs(dx * math.sin(wind_dir_rad) - dy * math.cos(wind_dir_rad))

                    # Calculate deficit using Jensen model
                    deficit = jensen_wake_loss(distance_along_wind, rotor_diameter, wake_model.wake_decay_constant)

                    # Gaussian distribution of deficit across wake
                    wake_radius = rotor_diameter / 2 + wake_model.wake_decay_constant * distance_along_wind
                    if wake_radius > 0:
                        gaussian = math.exp(-(perp_distance**2) / (2 * (wake_radius / 2) ** 2))
                        deficit_sq += (deficit * gaussian) ** 2

            # Combined deficit (square root of sum of squares)
            total_deficit = math.sqrt(deficit_sq)
            wind_speeds[i] = wind_speed * (1.0 - total_deficit)

    return wind_speeds


def calculate_wind_power(
    wind_speed: float,
    rotor_diameter: float,
    air_density: float = 1.225,
    cp_efficiency: float = 0.45,
) -> float:
    """
    Calculate theoretical wind power from Betz law.

    Args:
        wind_speed: Wind speed in m/s
        rotor_diameter: Rotor diameter in m
        air_density: Air density in kg/m^3
        cp_efficiency: Power coefficient (max Betz limit 0.593)

    Returns:
        Power in watts
    """
    if wind_speed <= 0:
        return 0.0

    # Validate Betz limit
    betz_limit = 0.593
    actual_cp = min(cp_efficiency, betz_limit)

    # Rotor area
    rotor_area = math.pi * (rotor_diameter / 2) ** 2

    # Wind power: P = 0.5 * ρ * A * v^3 * Cp
    power_w = 0.5 * air_density * rotor_area * (wind_speed**3) * actual_cp

    return power_w


def optimize_turbine_layout(
    wind_farm_area_m2: float,
    wind_direction_dominant: float,
    turbine_diameter: float,
    nominal_spacing: float = 4.0,
    wind_direction_variability: float = 30.0,
) -> list[tuple[float, float]]:
    """
    Optimize turbine positions for maximum energy (greedy algorithm).

    Args:
        wind_farm_area_m2: Farm area in m^2
        wind_direction_dominant: Dominant wind direction in degrees
        turbine_diameter: Turbine rotor diameter in m
        nominal_spacing: Spacing in rotor diameters
        wind_direction_variability: Range of wind directions in degrees

    Returns:
        List of optimized turbine positions (x, y)
    """
    # Estimate farm dimensions
    farm_dimension = math.sqrt(wind_farm_area_m2)

    # Spacing in meters
    spacing_m = turbine_diameter * nominal_spacing

    # Grid-based layout perpendicular to dominant wind
    positions = []
    wind_dir_rad = math.radians(wind_direction_dominant)

    # Wind direction axes
    along_wind_cos = math.cos(wind_dir_rad)
    along_wind_sin = math.sin(wind_dir_rad)
    cross_wind_cos = -math.sin(wind_dir_rad)
    cross_wind_sin = math.cos(wind_dir_rad)

    # Generate grid
    cross_count = int(farm_dimension / spacing_m)
    along_count = int(farm_dimension / spacing_m)

    for i in range(along_count):
        for j in range(cross_count):
            # Grid coordinates
            along = i * spacing_m
            cross = j * spacing_m

            # Convert to (x, y)
            x = along * along_wind_cos - cross * cross_wind_sin
            y = along * along_wind_sin + cross * cross_wind_cos

            if 0 <= x < farm_dimension and 0 <= y < farm_dimension:
                positions.append((x, y))

    return positions


def calculate_capacity_factor(
    turbine: WindTurbine,
    mean_wind_speed: float,
    wind_shear_exponent: float = 0.2,
    hours_per_year: int = 8760,
) -> float:
    """
    Calculate capacity factor from wind resource.

    Args:
        turbine: Wind turbine specifications
        mean_wind_speed: Mean annual wind speed at reference height (m/s)
        wind_shear_exponent: Wind shear power law exponent
        hours_per_year: Hours in analysis period

    Returns:
        Capacity factor (0.0-1.0)
    """
    if turbine.capacity_mw <= 0 or hours_per_year <= 0:
        return 0.0

    # Estimate energy production using Rayleigh distribution
    total_energy = 0.0

    # Sample wind speeds
    for hour in range(hours_per_year):
        # Simplified model: assume Rayleigh distribution
        # with mean wind speed
        k_shape = 2.0  # Rayleigh parameter
        c_scale = mean_wind_speed * math.sqrt(math.pi / 2)

        # Sample at various wind speeds
        ws_samples = [v * 0.1 for v in range(1, 300)]
        total_probability = 0.0
        energy_weighted = 0.0

        for ws in ws_samples:
            prob = weibull_distribution(ws, c_scale, k_shape)
            power = interpolate_power_curve(ws, turbine.power_curve)
            energy_weighted += prob * power * 0.1
            total_probability += prob * 0.1

        total_energy += energy_weighted / max(1.0, total_probability)

    # Average power over year
    avg_power = total_energy / hours_per_year

    # Capacity factor
    capacity_factor = avg_power / turbine.capacity_mw if turbine.capacity_mw > 0 else 0.0

    return min(1.0, max(0.0, capacity_factor))


def calculate_annual_energy(
    plant: WindPlant,
    hourly_wind_speeds: list[float],
    power_curves: list[list[tuple[float, float]]] | None = None,
) -> float:
    """
    Calculate annual wind energy production in MWh.

    Args:
        plant: Wind plant
        hourly_wind_speeds: Hourly wind speeds at hub height (m/s)
        power_curves: Optional power curves for each turbine

    Returns:
        Annual energy in MWh
    """
    if not hourly_wind_speeds:
        return 0.0

    # Default power curve (approximate cubic relationship)
    if power_curves is None:

        def default_power_curve(ws: float) -> float:
            if ws < plant.turbine_capacity_mw or ws > 25:
                return 0.0
            power_w = calculate_wind_power(ws, plant.rotor_diameter_m, plant.surface_roughness_m)
            return min(plant.turbine_capacity_mw * 1_000_000, power_w)

    total_energy_wh = 0.0

    for wind_speed in hourly_wind_speeds:
        if power_curves:
            # Use provided power curves
            total_power = 0.0
            for curve in power_curves:
                total_power += interpolate_power_curve(wind_speed, curve)
        else:
            # Use default cubic model
            power_w = default_power_curve(wind_speed)
            total_power = (power_w / 1_000_000) * plant.turbine_count

        total_energy_wh += total_power * 1_000  # Convert MWh to Wh

    annual_mwh = total_energy_wh / 1_000_000
    plant.capacity_factor = annual_mwh / (plant.capacity_mw * len(hourly_wind_speeds))

    return annual_mwh
