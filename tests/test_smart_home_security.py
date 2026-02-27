"""Tests for security system."""

import pytest

from thomas.smart_home._exceptions import SensorError
from thomas.smart_home._types import AlarmState
from thomas.smart_home.security import ArmingSchedule, SecuritySystem


class TestSecuritySystem:
    """Test SecuritySystem functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.system = SecuritySystem()

    def test_create_zone(self):
        """Test creating a sensor zone."""
        zone = self.system.create_zone("front_door", "Front Door", "door_sensor", "door_sensor_1")

        assert zone.zone_id == "front_door"
        assert zone.sensor_type == "door_sensor"
        assert zone.armed is True

    def test_get_zone(self):
        """Test retrieving a zone."""
        self.system.create_zone("zone1", "Zone 1", "motion_sensor", "device1")

        zone = self.system.get_zone("zone1")

        assert zone.zone_id == "zone1"

    def test_get_nonexistent_zone(self):
        """Test getting non-existent zone raises error."""
        with pytest.raises(SensorError):
            self.system.get_zone("nonexistent")

    def test_initial_state_disarmed(self):
        """Test system starts disarmed."""
        assert self.system.get_state() == AlarmState.DISARMED

    def test_arm_home(self):
        """Test arming for home."""
        self.system.arm_home()

        assert self.system.get_state() == AlarmState.ARMED_HOME

    def test_arm_away(self):
        """Test arming for away."""
        self.system.arm_away()

        assert self.system.get_state() == AlarmState.ARMED_AWAY

    def test_arm_night(self):
        """Test arming for night."""
        self.system.arm_night()

        assert self.system.get_state() == AlarmState.ARMED_NIGHT

    def test_disarm(self):
        """Test disarming system."""
        self.system.arm_home()
        self.system.disarm()

        assert self.system.get_state() == AlarmState.DISARMED

    def test_trigger_sensor(self):
        """Test triggering a sensor."""
        self.system.create_zone("zone1", "Zone 1", "door_sensor", "device1")

        self.system.trigger_sensor("zone1")

        zone = self.system.get_zone("zone1")
        assert zone.triggered is True

    def test_entry_delay(self):
        """Test entry delay on sensor trigger."""
        self.system.create_zone("zone1", "Zone 1", "door_sensor", "device1")

        self.system.arm_away()

        # Trigger sensor while armed
        self.system.trigger_sensor("zone1")

        # Should enter pending state
        assert self.system.get_state() == AlarmState.PENDING

    def test_entry_delay_expiration(self):
        """Test entry delay expiration triggers alarm."""
        self.system.set_entry_delay(1)  # 1 second
        self.system.create_zone("zone1", "Zone 1", "door_sensor", "device1")

        self.system.arm_away()
        self.system.trigger_sensor("zone1")

        assert self.system.get_state() == AlarmState.PENDING

        # Simulate delay expiration
        self.system.check_entry_delay()

        # Should be triggered
        assert self.system.get_state() == AlarmState.TRIGGERED

    def test_clear_entry_delay(self):
        """Test clearing entry delay by disarming."""
        self.system.create_zone("zone1", "Zone 1", "door_sensor", "device1")

        self.system.arm_away()
        self.system.trigger_sensor("zone1")

        assert self.system.get_state() == AlarmState.PENDING

        # Disarm clears delay
        self.system.disarm()

        assert self.system.get_state() == AlarmState.DISARMED

    def test_trigger_alarm(self):
        """Test triggering alarm."""
        self.system.trigger_alarm()

        assert self.system.get_state() == AlarmState.TRIGGERED

    def test_panic_mode(self):
        """Test panic mode."""
        self.system.trigger_panic()

        assert self.system.get_state() == AlarmState.TRIGGERED
        assert self.system._panic_active is True

    def test_alarm_callback(self):
        """Test alarm trigger callback."""
        zone_triggered = []

        def alarm_handler(zone_id):
            zone_triggered.append(zone_id)

        self.system.register_alarm_callback(alarm_handler)

        self.system.trigger_alarm("zone1")

        assert "zone1" in zone_triggered

    def test_panic_callback(self):
        """Test panic callback."""
        panic_called = []

        def panic_handler():
            panic_called.append(True)

        self.system.register_panic_callback(panic_handler)

        self.system.trigger_panic()

        assert len(panic_called) > 0

    def test_state_change_callback(self):
        """Test state change callback."""
        states_changed = []

        def state_handler(state):
            states_changed.append(state)

        self.system.register_state_callback(state_handler)

        self.system.arm_home()
        self.system.disarm()

        assert AlarmState.ARMED_HOME in states_changed
        assert AlarmState.DISARMED in states_changed

    def test_set_entry_delay(self):
        """Test setting entry delay."""
        self.system.set_entry_delay(60)

        assert self.system.get_entry_delay() == 60

    def test_set_exit_delay(self):
        """Test setting exit delay."""
        self.system.set_exit_delay(30)

        assert self.system.get_exit_delay() == 30

    def test_detect_tamper(self):
        """Test tamper detection."""
        self.system.create_zone("zone1", "Zone 1", "door_sensor", "device1")

        self.system.detect_tamper("zone1")

        zone = self.system.get_zone("zone1")
        assert zone.tamper_detected is True

    def test_clear_tamper(self):
        """Test clearing tamper detection."""
        self.system.create_zone("zone1", "Zone 1", "door_sensor", "device1")

        self.system.detect_tamper("zone1")
        self.system.clear_tamper("zone1")

        zone = self.system.get_zone("zone1")
        assert zone.tamper_detected is False

    def test_arm_zone(self):
        """Test arming specific zone."""
        self.system.create_zone("zone1", "Zone 1", "motion_sensor", "device1")

        self.system.disarm_zone("zone1")
        assert not self.system.get_zone("zone1").armed

        self.system.arm_zone("zone1")
        assert self.system.get_zone("zone1").armed

    def test_get_armed_zones(self):
        """Test getting armed zones."""
        self.system.create_zone("zone1", "Zone 1", "motion_sensor", "device1")
        self.system.create_zone("zone2", "Zone 2", "motion_sensor", "device2")

        self.system.disarm_zone("zone1")

        armed = self.system.get_armed_zones()

        assert len(armed) == 1
        assert armed[0].zone_id == "zone2"

    def test_get_triggered_zones(self):
        """Test getting triggered zones."""
        self.system.create_zone("zone1", "Zone 1", "motion_sensor", "device1")
        self.system.create_zone("zone2", "Zone 2", "motion_sensor", "device2")

        self.system.trigger_sensor("zone1")

        triggered = self.system.get_triggered_zones()

        assert len(triggered) == 1
        assert triggered[0].zone_id == "zone1"

    def test_get_tampered_zones(self):
        """Test getting tampered zones."""
        self.system.create_zone("zone1", "Zone 1", "motion_sensor", "device1")
        self.system.create_zone("zone2", "Zone 2", "motion_sensor", "device2")

        self.system.detect_tamper("zone1")

        tampered = self.system.get_tampered_zones()

        assert len(tampered) == 1
        assert tampered[0].zone_id == "zone1"

    def test_clear_zone(self):
        """Test clearing triggered zone."""
        self.system.create_zone("zone1", "Zone 1", "motion_sensor", "device1")

        self.system.trigger_sensor("zone1")
        assert self.system.get_zone("zone1").triggered is True

        self.system.clear_zone("zone1")
        assert self.system.get_zone("zone1").triggered is False

    def test_event_log(self):
        """Test event logging."""
        self.system.arm_home()
        self.system.disarm()
        self.system.trigger_panic()

        events = self.system.get_event_log()

        assert len(events) >= 3

    def test_set_auto_arm_schedule(self):
        """Test setting auto-arm schedule."""
        schedule = ArmingSchedule(enabled=True, arm_time="22:00", disarm_time="06:00")

        self.system.set_auto_arm_schedule(schedule)

        retrieved = self.system.get_auto_arm_schedule()

        assert retrieved.arm_time == "22:00"
        assert retrieved.disarm_time == "06:00"

    def test_get_system_status(self):
        """Test system status reporting."""
        self.system.create_zone("zone1", "Zone 1", "motion_sensor", "device1")
        self.system.create_zone("zone2", "Zone 2", "motion_sensor", "device2")

        self.system.arm_away()
        self.system.trigger_sensor("zone1")

        status = self.system.get_system_status()

        assert status["state"] == AlarmState.ARMED_AWAY
        assert status["zones_triggered"] == 1
        assert status["total_zones"] == 2

    def test_entry_delay_remaining(self):
        """Test entry delay remaining calculation."""
        self.system.set_entry_delay(60)
        self.system.create_zone("zone1", "Zone 1", "door_sensor", "device1")

        self.system.arm_away()
        self.system.trigger_sensor("zone1")

        remaining = self.system._get_entry_delay_remaining()

        assert 0 <= remaining <= 60
