"""Climate control and HVAC management."""

import math
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

from thomas.marketplace.smart_home._exceptions import ClimateError
from thomas.marketplace.smart_home._types import Schedule


@dataclass
class ThermostatMode:
    """Thermostat operating mode."""

    name: str
    """Mode name: heat, cool, auto, off, eco."""
    min_temp: float
    """Minimum setpoint."""
    max_temp: float
    """Maximum setpoint."""
    energy_efficient: bool = False
    """Whether mode is energy-efficient."""


@dataclass
class ZoneState:
    """Climate state of a zone."""

    zone_id: str
    """Zone identifier."""
    current_temp: float = 20.0
    """Current temperature in C."""
    target_temp: float = 21.0
    """Target temperature in C."""
    humidity: float = 50.0
    """Relative humidity %."""
    target_humidity: float | None = None
    """Target humidity % if humidity control enabled."""
    heating_active: bool = False
    """Whether heating is active."""
    cooling_active: bool = False
    """Whether cooling is active."""
    ventilation_level: int = 0
    """Ventilation level 0-100."""


@dataclass
class ThermalModel:
    """Simplified thermal model of house."""

    zone_id: str
    """Zone being modeled."""
    indoor_temp: float = 20.0
    """Current indoor temperature."""
    outdoor_temp: float = 15.0
    """Current outdoor temperature."""
    insulation_factor: float = 0.5
    """How well insulated (0-1)."""
    mass_factor: float = 0.3
    """Thermal mass effect (0-1)."""
    hvac_capacity: float = 5.0
    """HVAC capacity in degrees per minute."""
    solar_gain: float = 0.0
    """Solar heat gain effect."""
    estimated_time_to_target: float = 30.0
    """Minutes to reach target at current rate."""


class ThermostatScheduler:
    """Thermostat scheduling and climate control.

    Manages thermostat schedules with comfort vs economy modes,
    multi-zone HVAC optimization, predictive pre-heating/cooling,
    humidity control, and weather-based adjustments.
    """

    def __init__(self) -> None:
        """Initialize thermostat scheduler."""
        self._zones: dict[str, ZoneState] = {}
        self._schedules: dict[str, Schedule] = {}
        self._modes: dict[str, ThermostatMode] = self._init_modes()
        self._thermal_models: dict[str, ThermalModel] = {}
        self._weather: dict[str, Any] = {}
        self._comfort_settings: dict[str, dict[str, float]] = {}
        self._zone_devices: dict[str, list[str]] = {}

    def _init_modes(self) -> dict[str, ThermostatMode]:
        """Initialize default thermostat modes.

        Returns:
            Dictionary of modes.
        """
        return {
            "heat": ThermostatMode("heat", 15.0, 30.0, energy_efficient=False),
            "cool": ThermostatMode("cool", 15.0, 30.0, energy_efficient=False),
            "auto": ThermostatMode("auto", 15.0, 30.0, energy_efficient=False),
            "off": ThermostatMode("off", 15.0, 30.0, energy_efficient=False),
            "eco": ThermostatMode("eco", 15.0, 30.0, energy_efficient=True),
        }

    def create_zone(self, zone_id: str, devices: list[str]) -> ZoneState:
        """Create a climate control zone.

        Args:
            zone_id: Zone identifier.
            devices: Device IDs in zone.

        Returns:
            Zone state.
        """
        zone = ZoneState(zone_id=zone_id)
        self._zones[zone_id] = zone
        self._zone_devices[zone_id] = devices
        self._thermal_models[zone_id] = ThermalModel(zone_id=zone_id)
        self._comfort_settings[zone_id] = {"comfort_temp": 21.0, "economy_temp": 18.0}
        return zone

    def get_zone(self, zone_id: str) -> ZoneState:
        """Get zone state.

        Args:
            zone_id: Zone identifier.

        Returns:
            Zone state.

        Raises:
            ClimateError: If zone not found.
        """
        if zone_id not in self._zones:
            raise ClimateError(f"Zone {zone_id} not found")
        return self._zones[zone_id]

    def set_target_temperature(self, zone_id: str, temp: float) -> None:
        """Set target temperature for zone.

        Args:
            zone_id: Zone identifier.
            temp: Target temperature in C.

        Raises:
            ClimateError: If zone not found.
        """
        zone = self.get_zone(zone_id)
        zone.target_temp = max(15.0, min(30.0, temp))

    def set_target_humidity(self, zone_id: str, humidity: float) -> None:
        """Set target humidity for zone.

        Args:
            zone_id: Zone identifier.
            humidity: Target humidity percentage.

        Raises:
            ClimateError: If zone not found.
        """
        zone = self.get_zone(zone_id)
        zone.target_humidity = max(20.0, min(80.0, humidity))

    def set_current_temperature(self, zone_id: str, temp: float) -> None:
        """Update current temperature reading.

        Args:
            zone_id: Zone identifier.
            temp: Current temperature in C.

        Raises:
            ClimateError: If zone not found.
        """
        zone = self.get_zone(zone_id)
        zone.current_temp = temp
        model = self._thermal_models[zone_id]
        model.indoor_temp = temp

    def set_current_humidity(self, zone_id: str, humidity: float) -> None:
        """Update current humidity reading.

        Args:
            zone_id: Zone identifier.
            humidity: Current humidity percentage.

        Raises:
            ClimateError: If zone not found.
        """
        zone = self.get_zone(zone_id)
        zone.humidity = max(0.0, min(100.0, humidity))

    def create_schedule(self, zone_id: str, schedule: Schedule) -> None:
        """Create a thermostat schedule.

        Args:
            zone_id: Zone identifier.
            schedule: Schedule to use.

        Raises:
            ClimateError: If zone not found.
        """
        if zone_id not in self._zones:
            raise ClimateError(f"Zone {zone_id} not found")
        self._schedules[zone_id] = schedule

    def get_schedule(self, zone_id: str) -> Schedule | None:
        """Get schedule for zone.

        Args:
            zone_id: Zone identifier.

        Returns:
            Schedule or None.
        """
        return self._schedules.get(zone_id)

    def update_weather(self, outdoor_temp: float, solar_irradiance: float = 0.0) -> None:
        """Update weather conditions.

        Args:
            outdoor_temp: Outdoor temperature in C.
            solar_irradiance: Solar irradiance W/m^2.
        """
        self._weather = {
            "outdoor_temp": outdoor_temp,
            "solar_irradiance": solar_irradiance,
            "timestamp": datetime.now(),
        }

        # Update thermal models
        for zone_id, model in self._thermal_models.items():
            model.outdoor_temp = outdoor_temp
            # Solar gain 0-0.5 C per 100 W/m^2
            model.solar_gain = solar_irradiance * 0.005

    def optimize_multi_zone(self) -> dict[str, dict[str, Any]]:
        """Optimize HVAC across all zones.

        Balances heating/cooling demand across zones.

        Returns:
            Zone ID -> optimization result dict.
        """
        results = {}

        for zone_id, zone in self._zones.items():
            # Calculate demand
            temp_diff = zone.target_temp - zone.current_temp
            demand = abs(temp_diff)

            # Determine HVAC action
            if temp_diff > 0.5:
                zone.heating_active = True
                zone.cooling_active = False
            elif temp_diff < -0.5:
                zone.heating_active = False
                zone.cooling_active = True
            else:
                zone.heating_active = False
                zone.cooling_active = False

            results[zone_id] = {
                "heating": zone.heating_active,
                "cooling": zone.cooling_active,
                "demand": demand,
                "current": zone.current_temp,
                "target": zone.target_temp,
            }

        return results

    def predict_temperature(self, zone_id: str, minutes: int = 30) -> float:
        """Predict temperature using thermal model.

        Args:
            zone_id: Zone identifier.
            minutes: Minutes to predict ahead.

        Returns:
            Predicted temperature in C.

        Raises:
            ClimateError: If zone not found.
        """
        zone = self.get_zone(zone_id)
        model = self._thermal_models[zone_id]

        # Simplified model: exponential approach to target
        current = zone.current_temp
        target = zone.target_temp
        time_constant = 30.0  # minutes to 63% of difference
        progress = 1.0 - math.exp(-minutes / time_constant)

        # Include solar gain and outdoor influence
        outdoor_influence = (model.outdoor_temp - current) * (1.0 - model.insulation_factor)
        net_target = target + model.solar_gain + outdoor_influence

        predicted = current + (net_target - current) * progress
        return predicted

    def estimate_time_to_target(self, zone_id: str) -> float:
        """Estimate time to reach target temperature.

        Args:
            zone_id: Zone identifier.

        Returns:
            Minutes to reach target.

        Raises:
            ClimateError: If zone not found.
        """
        zone = self.get_zone(zone_id)
        model = self._thermal_models[zone_id]

        diff = abs(zone.target_temp - zone.current_temp)
        if diff < 0.1:
            return 0.0

        # Time constant approach: tau = time to reach 63% of difference
        # We want 95% (3 tau), 90% (2.3 tau), or 99% (4.6 tau)
        time_constant = 30.0

        # Calculate time for 90% convergence
        target_progress = 0.9
        time_minutes = -time_constant * math.log(1.0 - target_progress)

        model.estimated_time_to_target = time_minutes
        return time_minutes

    def set_comfort_mode(self, zone_id: str) -> None:
        """Switch to comfort mode.

        Args:
            zone_id: Zone identifier.

        Raises:
            ClimateError: If zone not found.
        """
        zone = self.get_zone(zone_id)
        comfort_temp = self._comfort_settings[zone_id].get("comfort_temp", 21.0)
        zone.target_temp = comfort_temp

    def set_economy_mode(self, zone_id: str) -> None:
        """Switch to economy/eco mode.

        Args:
            zone_id: Zone identifier.

        Raises:
            ClimateError: If zone not found.
        """
        zone = self.get_zone(zone_id)
        economy_temp = self._comfort_settings[zone_id].get("economy_temp", 18.0)
        zone.target_temp = economy_temp

    def set_ventilation(self, zone_id: str, level: int) -> None:
        """Set ventilation level.

        Args:
            zone_id: Zone identifier.
            level: Ventilation level 0-100.

        Raises:
            ClimateError: If zone not found.
        """
        zone = self.get_zone(zone_id)
        zone.ventilation_level = max(0, min(100, level))

    def control_humidity(self, zone_id: str, target: float) -> dict[str, Any]:
        """Control humidity in zone.

        Args:
            zone_id: Zone identifier.
            target: Target humidity percentage.

        Returns:
            Control action dict.

        Raises:
            ClimateError: If zone not found.
        """
        zone = self.get_zone(zone_id)
        zone.target_humidity = max(20.0, min(80.0, target))

        # Determine humidifier/dehumidifier action
        diff = zone.target_humidity - zone.humidity

        action = {
            "humidify": diff > 5.0,
            "dehumidify": diff < -5.0,
            "current": zone.humidity,
            "target": zone.target_humidity,
        }

        return action

    def pre_heat_cool(self, zone_id: str, target_time: time) -> None:
        """Enable pre-heating/cooling before target time.

        Args:
            zone_id: Zone identifier.
            target_time: Time to have zone comfortable by.

        Raises:
            ClimateError: If zone not found.
        """
        zone = self.get_zone(zone_id)

        # Calculate start time based on estimated time to target
        eta = self.estimate_time_to_target(zone_id)

        # Start heating/cooling 10% earlier for safety margin
        start_offset_minutes = eta * 1.1

        # Initiate pre-heating/cooling
        comfort_temp = self._comfort_settings[zone_id].get("comfort_temp", 21.0)

        # Set more aggressive target initially
        zone.target_temp = comfort_temp + 1.0 if zone.current_temp < comfort_temp else comfort_temp - 1.0

    def weather_adjusted_schedule(self, zone_id: str) -> dict[str, Any]:
        """Get weather-adjusted thermostat settings.

        Adjusts comfort temperature based on weather conditions.

        Args:
            zone_id: Zone identifier.

        Returns:
            Adjusted settings dict.

        Raises:
            ClimateError: If zone not found.
        """
        zone = self.get_zone(zone_id)
        comfort_temp = self._comfort_settings[zone_id].get("comfort_temp", 21.0)

        # Adjust based on weather
        outdoor_temp = self._weather.get("outdoor_temp", 15.0)
        solar = self._weather.get("solar_irradiance", 0.0)

        # On hot days, reduce comfort temp
        if outdoor_temp > 25.0:
            adjusted_temp = comfort_temp - 0.5
        # On cold days, increase comfort temp
        elif outdoor_temp < 5.0:
            adjusted_temp = comfort_temp + 0.5
        else:
            adjusted_temp = comfort_temp

        # Solar gain reduces cooling demand
        if solar > 500.0:
            adjusted_temp -= 0.3

        return {
            "base_temp": comfort_temp,
            "adjusted_temp": adjusted_temp,
            "adjustment_reason": f"weather_outdoor_{outdoor_temp}c_solar_{solar}w",
            "zone_id": zone_id,
        }

    def get_system_status(self) -> dict[str, Any]:
        """Get status of climate control system.

        Returns:
            System status dict.
        """
        status = {"zones": {}, "weather": self._weather, "total_heating_demand": 0.0, "total_cooling_demand": 0.0}

        for zone_id, zone in self._zones.items():
            temp_diff = zone.target_temp - zone.current_temp
            status["zones"][zone_id] = {
                "current": zone.current_temp,
                "target": zone.target_temp,
                "humidity": zone.humidity,
                "heating": zone.heating_active,
                "cooling": zone.cooling_active,
                "demand": abs(temp_diff),
            }

            if temp_diff > 0:
                status["total_heating_demand"] += temp_diff
            else:
                status["total_cooling_demand"] += abs(temp_diff)

        return status

    def get_energy_efficiency_score(self, zone_id: str) -> float:
        """Calculate energy efficiency score for zone.

        Args:
            zone_id: Zone identifier.

        Returns:
            Score 0-100 where 100 is most efficient.

        Raises:
            ClimateError: If zone not found.
        """
        zone = self.get_zone(zone_id)

        # Factors: temperature setpoint, mode, target reached
        base_score = 50.0

        # Reward reasonable setpoints (20-22C is efficient)
        if 20.0 <= zone.target_temp <= 22.0:
            base_score += 20.0

        # Reward small delta (less work needed)
        delta = abs(zone.target_temp - zone.current_temp)
        if delta < 0.5:
            base_score += 20.0
        elif delta < 2.0:
            base_score += 10.0

        return min(100.0, max(0.0, base_score))
