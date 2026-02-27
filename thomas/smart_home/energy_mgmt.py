"""Energy management and monitoring."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from thomas.smart_home._exceptions import EnergyError


@dataclass
class PowerReading:
    """A power consumption reading."""

    device_id: str
    """Device ID."""
    power_watts: float
    """Power consumption in watts."""
    timestamp: datetime = field(default_factory=datetime.now)
    """When reading was taken."""


@dataclass
class TariffPeriod:
    """A time-of-use tariff period."""

    name: str
    """Period name (e.g., 'peak', 'off-peak')."""
    start_hour: int
    """Start hour 0-23."""
    end_hour: int
    """End hour 0-23."""
    cost_per_kwh: float
    """Cost per kWh in currency units."""
    priority: int = 0
    """Priority for overlapping periods."""


@dataclass
class DeviceEnergyProfile:
    """Energy profile for a device."""

    device_id: str
    """Device ID."""
    device_name: str
    """Device name."""
    typical_power: float
    """Typical power consumption in watts."""
    standby_power: float = 0.1
    """Standby power in watts."""
    cost_per_day: float = 0.0
    """Estimated daily cost."""
    cost_per_month: float = 0.0
    """Estimated monthly cost."""


class EnergyManager:
    """Energy management with monitoring and optimization.

    Provides real-time power monitoring per device, daily/weekly/monthly
    usage aggregation, cost calculation with time-of-use tariffs,
    solar integration, battery storage optimization, and peak demand reduction.
    """

    def __init__(self) -> None:
        """Initialize energy manager."""
        self._devices: dict[str, DeviceEnergyProfile] = {}
        self._readings: list[PowerReading] = []
        self._tariffs: dict[str, TariffPeriod] = self._init_tariffs()
        self._current_readings: dict[str, float] = {}
        self._solar_generation: float = 0.0
        self._battery_charge: float = 100.0
        self._battery_capacity: float = 10.0
        self._schedule_history: list[dict[str, Any]] = []

    def _init_tariffs(self) -> dict[str, TariffPeriod]:
        """Initialize default tariff periods.

        Returns:
            Dictionary of tariff periods.
        """
        return {
            "night": TariffPeriod("night", 22, 7, 0.08, priority=0),
            "peak": TariffPeriod("peak", 17, 21, 0.25, priority=2),
            "off_peak": TariffPeriod("off_peak", 7, 17, 0.15, priority=1),
        }

    def register_device(self, device_id: str, name: str, typical_power: float) -> DeviceEnergyProfile:
        """Register a device for energy monitoring.

        Args:
            device_id: Device identifier.
            name: Device name.
            typical_power: Typical power in watts.

        Returns:
            Device energy profile.
        """
        profile = DeviceEnergyProfile(device_id=device_id, device_name=name, typical_power=typical_power)
        self._devices[device_id] = profile
        return profile

    def record_power(self, device_id: str, power_watts: float) -> None:
        """Record power consumption for a device.

        Args:
            device_id: Device identifier.
            power_watts: Power in watts.

        Raises:
            EnergyError: If device not registered.
        """
        if device_id not in self._devices:
            raise EnergyError(f"Device {device_id} not registered")

        reading = PowerReading(device_id=device_id, power_watts=power_watts)
        self._readings.append(reading)
        self._current_readings[device_id] = power_watts

    def get_current_power(self, device_id: str) -> float:
        """Get current power consumption.

        Args:
            device_id: Device identifier.

        Returns:
            Power in watts.

        Raises:
            EnergyError: If device not found.
        """
        if device_id not in self._devices:
            raise EnergyError(f"Device {device_id} not registered")
        return self._current_readings.get(device_id, 0.0)

    def get_total_power(self) -> float:
        """Get total current power consumption.

        Returns:
            Total power in watts.
        """
        return sum(self._current_readings.values())

    def get_total_power_minus_solar(self) -> float:
        """Get net power consumption minus solar generation.

        Returns:
            Net power in watts (negative means exporting).
        """
        return self.get_total_power() - self._solar_generation

    def get_daily_energy(self, device_id: str | None = None) -> dict[str, float]:
        """Get daily energy consumption.

        Args:
            device_id: Optional device to filter by.

        Returns:
            Device ID -> kWh dict.
        """
        now = datetime.now()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

        daily: dict[str, float] = {}
        for reading in self._readings:
            if reading.timestamp >= start_of_day:
                if device_id is None or reading.device_id == device_id:
                    # Approximate: treat as 5-minute interval (0.083 hours)
                    energy = reading.power_watts * (5.0 / 60.0) / 1000.0
                    daily[reading.device_id] = daily.get(reading.device_id, 0) + energy

        return daily

    def get_monthly_energy(self, device_id: str | None = None) -> dict[str, float]:
        """Get monthly energy consumption.

        Args:
            device_id: Optional device to filter by.

        Returns:
            Device ID -> kWh dict.
        """
        now = datetime.now()
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        monthly: dict[str, float] = {}
        for reading in self._readings:
            if reading.timestamp >= start_of_month:
                if device_id is None or reading.device_id == device_id:
                    # Approximate: treat as 5-minute interval
                    energy = reading.power_watts * (5.0 / 60.0) / 1000.0
                    monthly[reading.device_id] = monthly.get(reading.device_id, 0) + energy

        return monthly

    def get_weekly_energy(self, device_id: str | None = None) -> dict[str, float]:
        """Get weekly energy consumption.

        Args:
            device_id: Optional device to filter by.

        Returns:
            Device ID -> kWh dict.
        """
        now = datetime.now()
        start_of_week = now - timedelta(days=now.weekday())
        start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)

        weekly: dict[str, float] = {}
        for reading in self._readings:
            if reading.timestamp >= start_of_week:
                if device_id is None or reading.device_id == device_id:
                    energy = reading.power_watts * (5.0 / 60.0) / 1000.0
                    weekly[reading.device_id] = weekly.get(reading.device_id, 0) + energy

        return weekly

    def calculate_cost(self, energy_kwh: float, hour: int | None = None) -> float:
        """Calculate cost using time-of-use tariff.

        Args:
            energy_kwh: Energy in kWh.
            hour: Hour of day or None for current.

        Returns:
            Cost in currency units.
        """
        if hour is None:
            hour = datetime.now().hour

        # Find applicable tariff for hour
        applicable_tariff = None
        best_priority = -1

        for tariff in self._tariffs.values():
            # Handle tariffs that wrap around midnight
            if tariff.start_hour <= tariff.end_hour:
                in_period = tariff.start_hour <= hour < tariff.end_hour
            else:
                in_period = hour >= tariff.start_hour or hour < tariff.end_hour

            if in_period and tariff.priority > best_priority:
                applicable_tariff = tariff
                best_priority = tariff.priority

        rate = applicable_tariff.cost_per_kwh if applicable_tariff else 0.15
        return energy_kwh * rate

    def get_daily_cost(self) -> float:
        """Get estimated daily cost.

        Returns:
            Cost in currency units.
        """
        daily = self.get_daily_energy()
        total_kwh = sum(daily.values())
        return self.calculate_cost(total_kwh)

    def get_monthly_cost(self) -> float:
        """Get estimated monthly cost.

        Returns:
            Cost in currency units.
        """
        monthly = self.get_monthly_energy()
        total_kwh = sum(monthly.values())
        return self.calculate_cost(total_kwh)

    def set_solar_generation(self, power_watts: float) -> None:
        """Set current solar generation.

        Args:
            power_watts: Solar power in watts.
        """
        self._solar_generation = max(0.0, power_watts)

    def get_solar_generation(self) -> float:
        """Get current solar generation.

        Returns:
            Power in watts.
        """
        return self._solar_generation

    def set_battery_charge(self, percent: float) -> None:
        """Set battery charge level.

        Args:
            percent: Charge level 0-100.
        """
        self._battery_charge = max(0.0, min(100.0, percent))

    def get_battery_charge(self) -> float:
        """Get battery charge level.

        Returns:
            Charge level 0-100.
        """
        return self._battery_charge

    def get_battery_capacity_kwh(self) -> float:
        """Get battery capacity.

        Returns:
            Capacity in kWh.
        """
        return self._battery_capacity

    def optimize_battery(self) -> dict[str, Any]:
        """Optimize battery charge/discharge.

        Returns:
            Optimization action dict.
        """
        net_power = self.get_total_power_minus_solar()
        action = {"action": "none", "power_watts": 0.0, "reason": ""}

        if net_power > 2000.0 and self._battery_charge > 20.0:
            # High demand, discharge battery
            action = {"action": "discharge", "power_watts": min(net_power, 3000.0), "reason": "high_demand"}
        elif net_power < -1000.0 and self._battery_charge < 100.0:
            # Excess solar, charge battery
            action = {"action": "charge", "power_watts": min(abs(net_power), 3000.0), "reason": "excess_solar"}

        return action

    def schedule_appliance(self, device_id: str, start_hour: int, duration_minutes: int) -> dict[str, Any]:
        """Schedule appliance to run during off-peak hours.

        Args:
            device_id: Device to schedule.
            start_hour: Preferred start hour.
            duration_minutes: Duration in minutes.

        Returns:
            Scheduling decision dict.

        Raises:
            EnergyError: If device not registered.
        """
        if device_id not in self._devices:
            raise EnergyError(f"Device {device_id} not registered")

        # Find cheapest hour in next 24 hours
        best_hour = 0
        best_cost = float("inf")

        for hour in range(24):
            profile = self._devices[device_id]
            energy_kwh = (profile.typical_power * duration_minutes) / 60000.0
            cost = self.calculate_cost(energy_kwh, hour)

            if cost < best_cost:
                best_cost = cost
                best_hour = hour

        schedule = {
            "device_id": device_id,
            "scheduled_hour": best_hour,
            "duration_minutes": duration_minutes,
            "estimated_cost": best_cost,
            "timestamp": datetime.now(),
        }

        self._schedule_history.append(schedule)
        return schedule

    def reduce_peak_demand(self) -> list[str]:
        """Suggest devices to turn off to reduce peak demand.

        Returns:
            List of device IDs to reduce.
        """
        candidates = []
        threshold = self.get_total_power() * 0.2  # Top 20% power consumers

        # Sort devices by power consumption
        devices_by_power = sorted(self._current_readings.items(), key=lambda x: x[1], reverse=True)

        cumulative = 0.0
        for device_id, power in devices_by_power:
            cumulative += power
            candidates.append(device_id)
            if cumulative >= threshold:
                break

        return candidates

    def get_peak_hours(self) -> list[int]:
        """Get peak hours from tariff.

        Returns:
            List of peak hours 0-23.
        """
        peak_hours = []
        for tariff in self._tariffs.values():
            if "peak" in tariff.name.lower():
                if tariff.start_hour <= tariff.end_hour:
                    peak_hours.extend(range(tariff.start_hour, tariff.end_hour))
                else:
                    peak_hours.extend(range(tariff.start_hour, 24))
                    peak_hours.extend(range(0, tariff.end_hour))

        return sorted(set(peak_hours))

    def get_off_peak_hours(self) -> list[int]:
        """Get off-peak hours from tariff.

        Returns:
            List of off-peak hours 0-23.
        """
        peak = self.get_peak_hours()
        return [h for h in range(24) if h not in peak]

    def get_device_profile(self, device_id: str) -> DeviceEnergyProfile:
        """Get device energy profile.

        Args:
            device_id: Device identifier.

        Returns:
            Device profile.

        Raises:
            EnergyError: If device not found.
        """
        if device_id not in self._devices:
            raise EnergyError(f"Device {device_id} not registered")
        return self._devices[device_id]

    def get_energy_report(self) -> dict[str, Any]:
        """Get comprehensive energy report.

        Returns:
            Report dict.
        """
        daily = self.get_daily_energy()
        weekly = self.get_weekly_energy()
        monthly = self.get_monthly_energy()

        return {
            "current_power_watts": self.get_total_power(),
            "solar_generation_watts": self._solar_generation,
            "net_power_watts": self.get_total_power_minus_solar(),
            "battery_charge_percent": self._battery_charge,
            "daily_energy_kwh": sum(daily.values()),
            "weekly_energy_kwh": sum(weekly.values()),
            "monthly_energy_kwh": sum(monthly.values()),
            "daily_cost": self.get_daily_cost(),
            "monthly_cost": self.get_monthly_cost(),
            "peak_hours": self.get_peak_hours(),
            "off_peak_hours": self.get_off_peak_hours(),
            "timestamp": datetime.now(),
        }

    def add_tariff(self, tariff_id: str, tariff: TariffPeriod) -> None:
        """Add or update a tariff period.

        Args:
            tariff_id: Tariff identifier.
            tariff: Tariff period.
        """
        self._tariffs[tariff_id] = tariff
