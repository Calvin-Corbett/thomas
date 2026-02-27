"""
Energy storage modeling and management.

Provides battery models with degradation curves, charge/discharge cycles,
pumped hydro, flywheel kinetic energy, thermal storage, and state-of-charge
tracking.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime

from thomas.energy._exceptions import StorageDepletedError
from thomas.energy._types import StorageUnit


@dataclass
class BatteryDegradation:
    """Battery degradation tracking."""

    cycles_completed: int = 0
    dod_index: int = 0  # Depth of discharge category
    calendar_degradation_factor: float = 1.0
    cycle_degradation_factor: float = 1.0
    dod_index_weighted: float = 1.0

    def update_after_cycle(self, dod: float) -> None:
        """Update degradation after a charge/discharge cycle."""
        self.cycles_completed += 1

        # Determine DOD category (deeper discharge = faster degradation)
        if dod < 0.3:
            self.dod_index = 0
            dod_penalty = 0.0001  # Minimal impact for shallow discharge
        elif dod < 0.6:
            self.dod_index = 1
            dod_penalty = 0.0002
        else:
            self.dod_index = 2
            dod_penalty = 0.0003  # Deep discharge faster degradation

        # Update cycle degradation (quadratic with cycles)
        cycle_factor = 1.0 - (self.cycles_completed / 5000.0) ** 1.5
        self.cycle_degradation_factor = max(0.8, cycle_factor)

        # Update DOD-weighted degradation
        dod_factor = 1.0 - dod_penalty * self.cycles_completed
        self.dod_index_weighted = max(0.7, dod_factor)

    def get_effective_capacity_factor(self) -> float:
        """Get effective capacity accounting for degradation."""
        return self.cycle_degradation_factor * max(0.8, self.dod_index_weighted)


@dataclass
class BatteryUnit(StorageUnit):
    """Lithium-ion battery storage with degradation modeling."""

    storage_type: str = "battery"
    # Chemistry and thermal
    nominal_voltage: float = 400.0  # Volts
    charge_loss_factor: float = 0.02  # 2% loss during charging
    discharge_loss_factor: float = 0.01  # 1% loss during discharging
    self_discharge_rate: float = 0.0005  # Per hour

    degradation: BatteryDegradation = field(default_factory=BatteryDegradation)
    last_charge_timestamp: datetime | None = None
    last_discharge_timestamp: datetime | None = None

    def get_effective_capacity(self) -> float:
        """Get usable capacity accounting for degradation."""
        nominal = self.capacity_mwh
        return nominal * self.degradation.get_effective_capacity_factor()

    def charge(
        self,
        power_mw: float,
        duration_hours: float,
        ambient_temp: float = 25.0,
    ) -> float:
        """
        Charge battery.

        Args:
            power_mw: Charging power in MW
            duration_hours: Charging duration in hours
            ambient_temp: Ambient temperature in Celsius

        Returns:
            Actual energy charged in MWh
        """
        # Limit by power rating and SOC limits
        max_power = min(power_mw, self.power_rating_mw)
        usable_capacity = self.get_effective_capacity()

        # Space available to charge
        space_mwh = usable_capacity * (self.max_soc - self.soc)
        max_energy = max_power * duration_hours

        energy_to_charge = min(space_mwh, max_energy)

        # Apply charging losses
        energy_from_grid = energy_to_charge / (1.0 - self.charge_loss_factor)

        # Temperature effects (charging slower in cold)
        if ambient_temp < 10:
            temp_penalty = 1.0 - (10 - ambient_temp) * 0.02
            energy_to_charge *= temp_penalty

        # Update SOC
        self.soc = min(self.max_soc, self.soc + energy_to_charge / usable_capacity)
        self.last_charge_timestamp = datetime.now()

        return energy_to_charge

    def discharge(
        self,
        power_mw: float,
        duration_hours: float,
        ambient_temp: float = 25.0,
    ) -> float:
        """
        Discharge battery.

        Args:
            power_mw: Discharging power in MW
            duration_hours: Discharging duration in hours
            ambient_temp: Ambient temperature in Celsius

        Returns:
            Actual energy discharged in MWh

        Raises:
            StorageDepletedError: If insufficient energy available
        """
        # Limit by power rating and SOC limits
        max_power = min(power_mw, self.power_rating_mw)
        usable_capacity = self.get_effective_capacity()

        # Available energy to discharge
        available_energy = usable_capacity * (self.soc - self.min_soc)
        energy_needed = max_power * duration_hours

        if energy_needed > available_energy:
            # Can discharge remaining available
            energy_to_discharge = available_energy
        else:
            energy_to_discharge = energy_needed

        # Apply discharge losses
        actual_discharge = energy_to_discharge * (1.0 - self.discharge_loss_factor)

        # Temperature effects
        if ambient_temp < 0 or ambient_temp > 45:
            temp_penalty = 1.0 - abs(ambient_temp - 25) * 0.005
            actual_discharge *= temp_penalty

        # Check if available
        if actual_discharge < energy_needed * 0.5:  # Can't provide 50% of request
            raise StorageDepletedError(
                storage_id=self.storage_id,
                requested_mw=power_mw,
                available_mw=actual_discharge / duration_hours if duration_hours > 0 else 0,
                soc=self.soc,
            )

        # Update SOC
        self.soc = max(self.min_soc, self.soc - energy_to_discharge / usable_capacity)
        self.last_discharge_timestamp = datetime.now()

        # Track degradation (simplified)
        dod = energy_to_discharge / usable_capacity
        self.degradation.update_after_cycle(dod)

        return actual_discharge

    def apply_self_discharge(self, hours: float) -> None:
        """Apply self-discharge over time."""
        energy_lost = self.soc * self.capacity_mwh * self.self_discharge_rate * hours
        self.soc = max(self.min_soc, self.soc - energy_lost / self.capacity_mwh)


@dataclass
class PumpedHydro(StorageUnit):
    """Pumped hydroelectric storage."""

    storage_type: str = "pumped_hydro"
    upper_reservoir_area_km2: float = 1.0
    lower_reservoir_area_km2: float = 1.0
    elevation_difference_m: float = 300.0
    turbine_efficiency: float = 0.90
    pump_efficiency: float = 0.88
    leakage_rate_per_day: float = 0.001

    def charge(
        self,
        power_mw: float,
        duration_hours: float,
        ambient_temp: float = 25.0,
    ) -> float:
        """
        Pump water to upper reservoir (charge).

        Args:
            power_mw: Pumping power in MW
            duration_hours: Pumping duration in hours
            ambient_temp: Ambient temperature (unused for hydro)

        Returns:
            Actual energy stored in MWh
        """
        # Limit by power and capacity
        max_power = min(power_mw, self.power_rating_mw)
        usable_capacity = self.capacity_mwh * (self.max_soc - self.min_soc)
        space = usable_capacity * (self.max_soc - self.soc)

        energy_input = max_power * duration_hours
        space_available = min(space, energy_input)

        # Account for pump efficiency
        energy_stored = space_available * self.pump_efficiency

        self.soc = min(self.max_soc, self.soc + energy_stored / usable_capacity)
        return energy_stored

    def discharge(
        self,
        power_mw: float,
        duration_hours: float,
        ambient_temp: float = 25.0,
    ) -> float:
        """
        Release water to generate power (discharge).

        Args:
            power_mw: Discharge power in MW
            duration_hours: Discharge duration in hours
            ambient_temp: Ambient temperature (unused for hydro)

        Returns:
            Actual energy discharged in MWh
        """
        # Limit by power and capacity
        max_power = min(power_mw, self.power_rating_mw)
        usable_capacity = self.capacity_mwh * (self.max_soc - self.min_soc)
        available = usable_capacity * (self.soc - self.min_soc)

        energy_needed = max_power * duration_hours
        energy_available = min(available, energy_needed)

        # Account for turbine efficiency
        energy_output = energy_available * self.turbine_efficiency

        self.soc = max(self.min_soc, self.soc - energy_available / usable_capacity)
        return energy_output

    def apply_leakage(self, hours: float) -> None:
        """Apply evaporation/seepage losses."""
        energy_lost = self.soc * self.capacity_mwh * self.leakage_rate_per_day / 24 * hours
        self.soc = max(self.min_soc, self.soc - energy_lost / self.capacity_mwh)


@dataclass
class FlywheelStorage(StorageUnit):
    """Flywheel kinetic energy storage."""

    storage_type: str = "flywheel"
    rotor_mass_kg: float = 1000.0  # kg
    rotor_radius_m: float = 0.5
    max_speed_rpm: int = 60000
    friction_loss_rate: float = 0.001  # Per hour

    def get_stored_energy_mwh(self, rpm: float) -> float:
        """Calculate stored kinetic energy from rotational speed."""
        # E = 0.5 * I * ω^2
        # I = m * r^2 (for disk)
        moment_inertia = 0.5 * self.rotor_mass_kg * (self.rotor_radius_m**2)

        omega = rpm * 2 * math.pi / 60  # Convert to rad/s

        energy_j = 0.5 * moment_inertia * (omega**2)
        energy_mwh = energy_j / 3.6e12  # Convert to MWh

        return energy_mwh

    def get_rpm_from_energy(self, energy_mwh: float) -> float:
        """Calculate rotational speed from stored energy."""
        energy_j = energy_mwh * 3.6e12

        moment_inertia = 0.5 * self.rotor_mass_kg * (self.rotor_radius_m**2)

        if moment_inertia <= 0:
            return 0.0

        omega_sq = 2 * energy_j / moment_inertia
        if omega_sq < 0:
            return 0.0

        omega = math.sqrt(omega_sq)
        rpm = omega * 60 / (2 * math.pi)

        return min(self.max_speed_rpm, rpm)

    def charge(
        self,
        power_mw: float,
        duration_hours: float,
        ambient_temp: float = 25.0,
    ) -> float:
        """
        Charge flywheel by accelerating rotor.

        Args:
            power_mw: Charging power in MW
            duration_hours: Charging duration in hours
            ambient_temp: Ambient temperature (unused)

        Returns:
            Actual energy stored in MWh
        """
        max_capacity = self.get_stored_energy_mwh(self.max_speed_rpm)
        current_capacity = self.soc * max_capacity
        space_available = max_capacity * (self.max_soc - self.soc)

        energy_input = power_mw * duration_hours
        energy_to_store = min(space_available, energy_input)

        # Account for motor/converter efficiency
        actual_stored = energy_to_store * 0.95

        self.soc = min(self.max_soc, self.soc + actual_stored / max_capacity)
        return actual_stored

    def discharge(
        self,
        power_mw: float,
        duration_hours: float,
        ambient_temp: float = 25.0,
    ) -> float:
        """
        Discharge flywheel by decelerating rotor.

        Args:
            power_mw: Discharge power in MW
            duration_hours: Discharge duration in hours
            ambient_temp: Ambient temperature (unused)

        Returns:
            Actual energy discharged in MWh
        """
        max_capacity = self.get_stored_energy_mwh(self.max_speed_rpm)
        available = self.soc * max_capacity * (self.max_soc - self.min_soc)

        energy_needed = power_mw * duration_hours
        energy_available = min(available, energy_needed)

        # Account for generator/converter efficiency
        actual_output = energy_available * 0.95

        self.soc = max(self.min_soc, self.soc - energy_needed / max_capacity)
        return actual_output

    def apply_friction_loss(self, hours: float) -> None:
        """Apply friction losses."""
        max_capacity = self.get_stored_energy_mwh(self.max_speed_rpm)
        energy_lost = self.soc * max_capacity * self.friction_loss_rate * hours
        self.soc = max(self.min_soc, self.soc - energy_lost / max_capacity)


@dataclass
class ThermalStorage(StorageUnit):
    """Thermal energy storage (sensible heat)."""

    storage_type: str = "thermal"
    medium_type: str = "water"  # "water", "molten_salt", "phase_change"
    mass_kg: float = 1e6  # kg of storage medium
    specific_heat_kj_kg_k: float = 4.18  # kJ/kg·K for water
    max_temperature_c: float = 100.0
    min_temperature_c: float = 10.0
    insulation_loss_factor: float = 0.01  # Per hour

    def get_temperature_from_soc(self) -> float:
        """Calculate temperature from state of charge."""
        return self.min_temperature_c + self.soc * (self.max_temperature_c - self.min_temperature_c)

    def set_temperature(self, temperature_c: float) -> None:
        """Set temperature and update SOC."""
        temp_range = self.max_temperature_c - self.min_temperature_c
        if temp_range > 0:
            self.soc = (temperature_c - self.min_temperature_c) / temp_range

    def charge(
        self,
        power_mw: float,
        duration_hours: float,
        ambient_temp: float = 25.0,
    ) -> float:
        """
        Heat thermal storage (charge).

        Args:
            power_mw: Heating power in MW
            duration_hours: Duration in hours
            ambient_temp: Ambient temperature in Celsius

        Returns:
            Actual thermal energy stored in MWh
        """
        # Energy input
        energy_input = power_mw * duration_hours

        # Current temperature
        current_temp = self.get_temperature_from_soc()

        # Calculate temperature rise
        # Q = m * c * ΔT
        # Energy in kJ = power(MW) * 3600 * 1000 = kJ for duration_hours
        energy_kj = power_mw * 3600 * 1000 * duration_hours

        if self.mass_kg > 0:
            temp_rise = energy_kj / (self.mass_kg * self.specific_heat_kj_kg_k)
        else:
            temp_rise = 0.0

        new_temp = min(self.max_temperature_c, current_temp + temp_rise)
        self.set_temperature(new_temp)

        return energy_input

    def discharge(
        self,
        power_mw: float,
        duration_hours: float,
        ambient_temp: float = 25.0,
    ) -> float:
        """
        Use thermal storage (discharge).

        Args:
            power_mw: Power draw in MW
            duration_hours: Duration in hours
            ambient_temp: Ambient temperature in Celsius

        Returns:
            Actual thermal energy delivered in MWh
        """
        energy_output = power_mw * duration_hours

        # Current temperature
        current_temp = self.get_temperature_from_soc()

        # Temperature drop
        energy_kj = power_mw * 3600 * 1000 * duration_hours

        if self.mass_kg > 0:
            temp_drop = energy_kj / (self.mass_kg * self.specific_heat_kj_kg_k)
        else:
            temp_drop = 0.0

        new_temp = max(self.min_temperature_c, current_temp - temp_drop)
        self.set_temperature(new_temp)

        return energy_output

    def apply_thermal_loss(self, hours: float, ambient_temp: float) -> None:
        """Apply heat loss to surroundings."""
        current_temp = self.get_temperature_from_soc()
        temp_diff = current_temp - ambient_temp

        # Heat loss rate proportional to temperature difference
        loss_fraction = self.insulation_loss_factor * (temp_diff / 50) * hours
        current_temp -= temp_diff * loss_fraction

        self.set_temperature(max(self.min_temperature_c, current_temp))


def soc_from_voltage(
    voltage: float,
    v_min: float = 2.5,
    v_max: float = 4.2,
) -> float:
    """
    Estimate state of charge from cell voltage.

    Args:
        voltage: Current cell voltage
        v_min: Minimum voltage (0% SOC)
        v_max: Maximum voltage (100% SOC)

    Returns:
        Estimated SOC (0.0-1.0)
    """
    if voltage <= v_min:
        return 0.0
    if voltage >= v_max:
        return 1.0

    return (voltage - v_min) / (v_max - v_min)
