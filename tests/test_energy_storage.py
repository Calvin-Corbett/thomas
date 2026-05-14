"""
Tests for energy storage systems.
"""

import pytest

from thomas.marketplace.energy._exceptions import StorageDepletedError
from thomas.marketplace.energy.storage import (
    BatteryUnit,
    FlywheelStorage,
    PumpedHydro,
    ThermalStorage,
    soc_from_voltage,
)


class TestBatteryUnit:
    """Test battery storage."""

    def test_create_battery(self):
        """Test battery creation."""
        battery = BatteryUnit(
            storage_id="batt1",
            capacity_mwh=10.0,
            power_rating_mw=2.0,
            round_trip_efficiency=0.90,
        )

        assert battery.storage_id == "batt1"
        assert battery.capacity_mwh == 10.0
        assert battery.power_rating_mw == 2.0

    def test_battery_charge(self):
        """Test battery charging."""
        battery = BatteryUnit(
            storage_id="batt1",
            capacity_mwh=10.0,
            power_rating_mw=2.0,
            round_trip_efficiency=0.90,
            soc=0.3,
        )

        initial_soc = battery.soc
        charged = battery.charge(power_mw=1.0, duration_hours=1.0)

        assert charged > 0
        assert battery.soc > initial_soc

    def test_battery_discharge(self):
        """Test battery discharging."""
        battery = BatteryUnit(
            storage_id="batt1",
            capacity_mwh=10.0,
            power_rating_mw=2.0,
            round_trip_efficiency=0.90,
            soc=0.8,
        )

        initial_soc = battery.soc
        discharged = battery.discharge(power_mw=1.0, duration_hours=1.0)

        assert discharged > 0
        assert battery.soc < initial_soc

    def test_battery_depleted(self):
        """Test battery discharge when depleted."""
        battery = BatteryUnit(
            storage_id="batt1",
            capacity_mwh=10.0,
            power_rating_mw=2.0,
            soc=0.05,  # Nearly empty
            min_soc=0.1,
        )

        with pytest.raises(StorageDepletedError):
            battery.discharge(power_mw=5.0, duration_hours=1.0)

    def test_battery_self_discharge(self):
        """Test battery self-discharge."""
        battery = BatteryUnit(
            storage_id="batt1",
            capacity_mwh=10.0,
            power_rating_mw=2.0,
            soc=0.8,
            self_discharge_rate=0.001,
        )

        initial_soc = battery.soc
        battery.apply_self_discharge(hours=24.0)

        assert battery.soc < initial_soc

    def test_battery_degradation(self):
        """Test battery degradation over cycles."""
        battery = BatteryUnit(
            storage_id="batt1",
            capacity_mwh=10.0,
            power_rating_mw=2.0,
            soc=0.8,
        )

        initial_capacity = battery.get_effective_capacity()

        # Cycle multiple times
        for _ in range(100):
            battery.discharge(power_mw=1.0, duration_hours=1.0)
            battery.charge(power_mw=1.0, duration_hours=1.0)

        final_capacity = battery.get_effective_capacity()

        # Capacity should degrade
        assert final_capacity < initial_capacity


class TestPumpedHydro:
    """Test pumped hydroelectric storage."""

    def test_create_pumped_hydro(self):
        """Test pumped hydro creation."""
        hydro = PumpedHydro(
            storage_id="hydro1",
            capacity_mwh=100.0,
            power_rating_mw=25.0,
            elevation_difference_m=300.0,
        )

        assert hydro.storage_id == "hydro1"
        assert hydro.capacity_mwh == 100.0

    def test_pumped_hydro_charge(self):
        """Test pumped hydro charging (pumping)."""
        hydro = PumpedHydro(
            storage_id="hydro1",
            capacity_mwh=100.0,
            power_rating_mw=25.0,
            soc=0.4,
        )

        initial_soc = hydro.soc
        charged = hydro.charge(power_mw=10.0, duration_hours=1.0)

        assert charged > 0
        assert hydro.soc > initial_soc

    def test_pumped_hydro_discharge(self):
        """Test pumped hydro discharging (generating)."""
        hydro = PumpedHydro(
            storage_id="hydro1",
            capacity_mwh=100.0,
            power_rating_mw=25.0,
            soc=0.8,
        )

        initial_soc = hydro.soc
        discharged = hydro.discharge(power_mw=15.0, duration_hours=1.0)

        assert discharged > 0
        assert hydro.soc < initial_soc

    def test_pumped_hydro_leakage(self):
        """Test pumped hydro evaporation losses."""
        hydro = PumpedHydro(
            storage_id="hydro1",
            capacity_mwh=100.0,
            power_rating_mw=25.0,
            soc=0.8,
            leakage_rate_per_day=0.001,
        )

        initial_soc = hydro.soc
        hydro.apply_leakage(hours=24.0)

        assert hydro.soc < initial_soc


class TestFlywheelStorage:
    """Test flywheel storage."""

    def test_create_flywheel(self):
        """Test flywheel creation."""
        flywheel = FlywheelStorage(
            storage_id="fly1",
            capacity_mwh=0.1,  # Small capacity
            power_rating_mw=1.0,
            rotor_mass_kg=1000.0,
        )

        assert flywheel.storage_id == "fly1"
        assert flywheel.storage_type == "flywheel"

    def test_flywheel_stored_energy(self):
        """Test flywheel energy calculation."""
        flywheel = FlywheelStorage(
            storage_id="fly1",
            capacity_mwh=0.1,
            power_rating_mw=1.0,
            rotor_mass_kg=1000.0,
            rotor_radius_m=0.5,
        )

        # At max speed
        energy_mwh = flywheel.get_stored_energy_mwh(60000)

        assert energy_mwh > 0

    def test_flywheel_charge_discharge(self):
        """Test flywheel charge/discharge."""
        flywheel = FlywheelStorage(
            storage_id="fly1",
            capacity_mwh=0.1,
            power_rating_mw=1.0,
            soc=0.5,
        )


        # Charge
        charged = flywheel.charge(power_mw=0.5, duration_hours=0.1)
        assert charged > 0

        # Discharge
        discharged = flywheel.discharge(power_mw=0.5, duration_hours=0.1)
        assert discharged > 0

    def test_flywheel_friction_loss(self):
        """Test flywheel friction losses."""
        flywheel = FlywheelStorage(
            storage_id="fly1",
            capacity_mwh=0.1,
            power_rating_mw=1.0,
            soc=0.8,
            friction_loss_rate=0.001,
        )

        initial_soc = flywheel.soc
        flywheel.apply_friction_loss(hours=1.0)

        assert flywheel.soc < initial_soc


class TestThermalStorage:
    """Test thermal energy storage."""

    def test_create_thermal_storage(self):
        """Test thermal storage creation."""
        thermal = ThermalStorage(
            storage_id="thermal1",
            capacity_mwh=100.0,
            power_rating_mw=20.0,
            mass_kg=1e6,
            min_temperature_c=10.0,
            max_temperature_c=90.0,
        )

        assert thermal.storage_id == "thermal1"
        assert thermal.storage_type == "thermal"

    def test_thermal_temperature_conversion(self):
        """Test temperature to SOC conversion."""
        thermal = ThermalStorage(
            storage_id="thermal1",
            capacity_mwh=100.0,
            power_rating_mw=20.0,
            min_temperature_c=10.0,
            max_temperature_c=90.0,
            soc=0.5,
        )

        temp = thermal.get_temperature_from_soc()

        # Should be at midpoint
        assert 40 < temp < 60

    def test_thermal_charge(self):
        """Test thermal storage heating."""
        thermal = ThermalStorage(
            storage_id="thermal1",
            capacity_mwh=100.0,
            power_rating_mw=20.0,
            mass_kg=1e6,
            min_temperature_c=10.0,
            max_temperature_c=90.0,
            soc=0.3,
        )

        initial_soc = thermal.soc
        charged = thermal.charge(power_mw=5.0, duration_hours=1.0)

        assert charged > 0
        assert thermal.soc > initial_soc

    def test_thermal_discharge(self):
        """Test thermal storage cooling."""
        thermal = ThermalStorage(
            storage_id="thermal1",
            capacity_mwh=100.0,
            power_rating_mw=20.0,
            mass_kg=1e6,
            min_temperature_c=10.0,
            max_temperature_c=90.0,
            soc=0.8,
        )

        initial_soc = thermal.soc
        discharged = thermal.discharge(power_mw=5.0, duration_hours=1.0)

        assert discharged > 0
        assert thermal.soc < initial_soc

    def test_thermal_loss(self):
        """Test thermal storage heat loss."""
        thermal = ThermalStorage(
            storage_id="thermal1",
            capacity_mwh=100.0,
            power_rating_mw=20.0,
            soc=0.9,
            insulation_loss_factor=0.01,
        )

        initial_soc = thermal.soc
        thermal.apply_thermal_loss(hours=1.0, ambient_temp=25.0)

        assert thermal.soc < initial_soc


class TestSOCFromVoltage:
    """Test SOC calculation from voltage."""

    def test_soc_from_voltage_min(self):
        """Test SOC at minimum voltage."""
        soc = soc_from_voltage(2.5)

        assert soc == 0.0

    def test_soc_from_voltage_max(self):
        """Test SOC at maximum voltage."""
        soc = soc_from_voltage(4.2)

        assert soc == 1.0

    def test_soc_from_voltage_mid(self):
        """Test SOC at mid-range voltage."""
        soc = soc_from_voltage(3.35)  # Midpoint

        assert 0.4 < soc < 0.6

    def test_soc_from_voltage_out_of_range(self):
        """Test SOC with out-of-range voltage."""
        soc_low = soc_from_voltage(2.0)  # Below minimum
        soc_high = soc_from_voltage(4.5)  # Above maximum

        assert soc_low == 0.0
        assert soc_high == 1.0


class TestStorageIntegration:
    """Integration tests for storage systems."""

    def test_multiple_charge_discharge_cycles(self):
        """Test multiple cycles."""
        battery = BatteryUnit(
            storage_id="batt1",
            capacity_mwh=10.0,
            power_rating_mw=2.0,
            round_trip_efficiency=0.90,
            soc=0.5,
        )

        # Cycle 10 times
        for i in range(10):
            if battery.soc < 0.5:
                battery.charge(power_mw=1.0, duration_hours=1.0)
            else:
                battery.discharge(power_mw=1.0, duration_hours=1.0)

        # Should still be functional
        assert battery.soc > 0.0
        assert battery.soc < 1.0

    def test_mixed_storage_operation(self):
        """Test multiple storage types operating together."""
        battery = BatteryUnit(
            storage_id="batt1",
            capacity_mwh=10.0,
            power_rating_mw=2.0,
            soc=0.5,
        )

        hydro = PumpedHydro(
            storage_id="hydro1",
            capacity_mwh=100.0,
            power_rating_mw=25.0,
            soc=0.6,
        )

        # Discharge both
        batt_out = battery.discharge(power_mw=1.0, duration_hours=1.0)
        hydro_out = hydro.discharge(power_mw=10.0, duration_hours=1.0)

        assert batt_out > 0
        assert hydro_out > 0
