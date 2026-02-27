"""Security system management and alarm control."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from thomas.smart_home._exceptions import AlarmError, SensorError
from thomas.smart_home._types import AlarmState


@dataclass
class SensorZone:
    """A security sensor zone."""

    zone_id: str
    """Zone identifier."""
    name: str
    """Zone name."""
    sensor_type: str
    """Type: door_sensor, window_sensor, motion_sensor, glass_break."""
    device_id: str
    """Associated device ID."""
    triggered: bool = False
    """Whether sensor is triggered."""
    tamper_detected: bool = False
    """Whether tamper is detected."""
    last_trigger: datetime | None = None
    """When last triggered."""
    armed: bool = True
    """Whether zone is armed."""


@dataclass
class AlarmEvent:
    """An alarm event."""

    event_id: str
    """Unique event ID."""
    event_type: str
    """Type: triggered, armed, disarmed, tamper."""
    alarm_state: AlarmState
    """State of alarm."""
    zone_id: str | None = None
    """Zone involved."""
    device_id: str | None = None
    """Device involved."""
    timestamp: datetime = field(default_factory=datetime.now)
    """When event occurred."""
    description: str | None = None
    """Event description."""


@dataclass
class ArmingSchedule:
    """Schedule for auto-arming."""

    enabled: bool = True
    """Whether auto-arm is enabled."""
    arm_time: str | None = None
    """Time to arm in HH:MM format."""
    disarm_time: str | None = None
    """Time to disarm in HH:MM format."""
    days: list[int] = field(default_factory=lambda: list(range(7)))
    """Days of week (0=Mon, 6=Sun)."""


class SecuritySystem:
    """Security system with alarm states and sensor management.

    Provides multiple alarm states, sensor zones, entry/exit delays,
    panic modes, event logging with tamper detection, and auto-arm schedules.
    """

    def __init__(self) -> None:
        """Initialize security system."""
        self._state: AlarmState = AlarmState.DISARMED
        self._zones: dict[str, SensorZone] = {}
        self._events: list[AlarmEvent] = []
        self._entry_delay_seconds: int = 30
        self._exit_delay_seconds: int = 30
        self._entry_delay_active: bool = False
        self._entry_delay_start: datetime | None = None
        self._panic_active: bool = False
        self._panic_callbacks: list[Callable] = []
        self._alarm_callbacks: list[Callable] = []
        self._state_callbacks: list[Callable] = []
        self._schedule: ArmingSchedule = ArmingSchedule()

    def create_zone(self, zone_id: str, name: str, sensor_type: str, device_id: str) -> SensorZone:
        """Create a sensor zone.

        Args:
            zone_id: Zone identifier.
            name: Zone name.
            sensor_type: Type of sensor.
            device_id: Associated device ID.

        Returns:
            Created zone.
        """
        zone = SensorZone(zone_id=zone_id, name=name, sensor_type=sensor_type, device_id=device_id)
        self._zones[zone_id] = zone
        return zone

    def get_zone(self, zone_id: str) -> SensorZone:
        """Get a zone.

        Args:
            zone_id: Zone identifier.

        Returns:
            Zone object.

        Raises:
            SensorError: If zone not found.
        """
        if zone_id not in self._zones:
            raise SensorError(f"Zone {zone_id} not found")
        return self._zones[zone_id]

    def set_state(self, new_state: AlarmState, user_id: str | None = None) -> None:
        """Set alarm state.

        Args:
            new_state: New alarm state.
            user_id: User who made change.

        Raises:
            AlarmError: If state change invalid.
        """
        old_state = self._state

        # Validate state transitions
        if new_state == AlarmState.TRIGGERED:
            # Can be triggered from any non-triggered state
            if self._state == AlarmState.TRIGGERED:
                return
        elif new_state == AlarmState.PENDING:
            # Entry delay state
            if self._state not in (AlarmState.ARMED_AWAY, AlarmState.ARMED_HOME, AlarmState.ARMED_NIGHT):
                raise AlarmError("Cannot enter pending from disarmed")
        elif new_state == AlarmState.DISARMED:
            # Can disarm from any state
            pass
        elif new_state in (AlarmState.ARMED_AWAY, AlarmState.ARMED_HOME, AlarmState.ARMED_NIGHT):
            # Can arm from disarmed
            if self._state != AlarmState.DISARMED:
                raise AlarmError(f"Cannot arm from {self._state}")

        self._state = new_state
        self._log_event(
            event_type="armed" if new_state != AlarmState.DISARMED else "disarmed",
            alarm_state=new_state,
            description=f"Changed from {old_state} to {new_state}",
        )

        # Call state callbacks
        for callback in self._state_callbacks:
            try:
                callback(new_state)
            except Exception:  # REVIEWED: broad catch
                pass

    def get_state(self) -> AlarmState:
        """Get current alarm state.

        Returns:
            Current state.
        """
        return self._state

    def arm_home(self, user_id: str | None = None) -> None:
        """Arm system for home (armed with perimeter protection).

        Args:
            user_id: Optional user ID.

        Raises:
            AlarmError: If cannot arm.
        """
        self.set_state(AlarmState.ARMED_HOME, user_id)

    def arm_away(self, user_id: str | None = None) -> None:
        """Arm system for away (full protection).

        Args:
            user_id: Optional user ID.

        Raises:
            AlarmError: If cannot arm.
        """
        self.set_state(AlarmState.ARMED_AWAY, user_id)

    def arm_night(self, user_id: str | None = None) -> None:
        """Arm system for night (reduced interior sensors).

        Args:
            user_id: Optional user ID.

        Raises:
            AlarmError: If cannot arm.
        """
        self.set_state(AlarmState.ARMED_NIGHT, user_id)

    def disarm(self, user_id: str | None = None) -> None:
        """Disarm the system.

        Args:
            user_id: Optional user ID.

        Raises:
            AlarmError: If cannot disarm.
        """
        self.set_state(AlarmState.DISARMED, user_id)

    def trigger_sensor(self, zone_id: str) -> None:
        """Trigger a sensor.

        Args:
            zone_id: Zone ID that triggered.

        Raises:
            SensorError: If zone not found.
        """
        zone = self.get_zone(zone_id)
        zone.triggered = True
        zone.last_trigger = datetime.now()

        # Check if alarm should trigger
        if self._state in (AlarmState.ARMED_AWAY, AlarmState.ARMED_HOME, AlarmState.ARMED_NIGHT):
            # Handle entry delay if system just armed
            if self._state != AlarmState.PENDING:
                self._enter_entry_delay()
            else:
                self.trigger_alarm(zone_id)

    def _enter_entry_delay(self) -> None:
        """Enter entry delay state."""
        self._state = AlarmState.PENDING
        self._entry_delay_active = True
        self._entry_delay_start = datetime.now()

    def clear_entry_delay(self) -> None:
        """Clear entry delay (user disarmed during delay)."""
        self._entry_delay_active = False
        self._entry_delay_start = None

    def check_entry_delay(self) -> bool:
        """Check if entry delay has expired.

        Returns:
            True if expired.
        """
        if not self._entry_delay_active or not self._entry_delay_start:
            return False

        elapsed = datetime.now() - self._entry_delay_start
        if elapsed.total_seconds() >= self._entry_delay_seconds:
            self._entry_delay_active = False
            self.trigger_alarm()
            return True

        return False

    def trigger_alarm(self, zone_id: str | None = None) -> None:
        """Trigger the alarm.

        Args:
            zone_id: Optional zone that triggered alarm.
        """
        self._state = AlarmState.TRIGGERED
        self._entry_delay_active = False

        self._log_event(
            event_type="triggered",
            alarm_state=AlarmState.TRIGGERED,
            zone_id=zone_id,
            description=f"Alarm triggered by zone {zone_id}",
        )

        # Call alarm callbacks
        for callback in self._alarm_callbacks:
            try:
                callback(zone_id)
            except Exception:  # REVIEWED: broad catch
                pass

    def trigger_panic(self, user_id: str | None = None) -> None:
        """Trigger panic mode.

        Args:
            user_id: Optional user ID.
        """
        self._panic_active = True
        self._state = AlarmState.TRIGGERED

        self._log_event(event_type="triggered", alarm_state=AlarmState.TRIGGERED, description="Panic triggered")

        # Call panic callbacks
        for callback in self._panic_callbacks:
            try:
                callback()
            except Exception:  # REVIEWED: broad catch
                pass

    def register_alarm_callback(self, callback: Callable) -> None:
        """Register a callback for alarm triggered.

        Args:
            callback: Callable(zone_id) when alarm triggered.
        """
        self._alarm_callbacks.append(callback)

    def register_panic_callback(self, callback: Callable) -> None:
        """Register a callback for panic.

        Args:
            callback: Callable() when panic triggered.
        """
        self._panic_callbacks.append(callback)

    def register_state_callback(self, callback: Callable) -> None:
        """Register a callback for state changes.

        Args:
            callback: Callable(state) when state changes.
        """
        self._state_callbacks.append(callback)

    def set_entry_delay(self, seconds: int) -> None:
        """Set entry delay time.

        Args:
            seconds: Delay in seconds.
        """
        self._entry_delay_seconds = max(0, seconds)

    def set_exit_delay(self, seconds: int) -> None:
        """Set exit delay time.

        Args:
            seconds: Delay in seconds.
        """
        self._exit_delay_seconds = max(0, seconds)

    def get_entry_delay(self) -> int:
        """Get entry delay.

        Returns:
            Delay in seconds.
        """
        return self._entry_delay_seconds

    def get_exit_delay(self) -> int:
        """Get exit delay.

        Returns:
            Delay in seconds.
        """
        return self._exit_delay_seconds

    def detect_tamper(self, zone_id: str) -> None:
        """Detect tamper on zone.

        Args:
            zone_id: Zone ID.

        Raises:
            SensorError: If zone not found.
        """
        zone = self.get_zone(zone_id)
        zone.tamper_detected = True

        self._log_event(
            event_type="tamper", alarm_state=self._state, zone_id=zone_id, description=f"Tamper detected on {zone.name}"
        )

    def clear_tamper(self, zone_id: str) -> None:
        """Clear tamper for zone.

        Args:
            zone_id: Zone ID.

        Raises:
            SensorError: If zone not found.
        """
        zone = self.get_zone(zone_id)
        zone.tamper_detected = False

    def arm_zone(self, zone_id: str) -> None:
        """Arm a specific zone.

        Args:
            zone_id: Zone ID.

        Raises:
            SensorError: If zone not found.
        """
        zone = self.get_zone(zone_id)
        zone.armed = True

    def disarm_zone(self, zone_id: str) -> None:
        """Disarm a specific zone.

        Args:
            zone_id: Zone ID.

        Raises:
            SensorError: If zone not found.
        """
        zone = self.get_zone(zone_id)
        zone.armed = False

    def get_armed_zones(self) -> list[SensorZone]:
        """Get all armed zones.

        Returns:
            List of armed zones.
        """
        return [z for z in self._zones.values() if z.armed]

    def get_triggered_zones(self) -> list[SensorZone]:
        """Get all triggered zones.

        Returns:
            List of triggered zones.
        """
        return [z for z in self._zones.values() if z.triggered]

    def get_tampered_zones(self) -> list[SensorZone]:
        """Get all tampered zones.

        Returns:
            List of tampered zones.
        """
        return [z for z in self._zones.values() if z.tamper_detected]

    def clear_zone(self, zone_id: str) -> None:
        """Clear triggered state for zone.

        Args:
            zone_id: Zone ID.

        Raises:
            SensorError: If zone not found.
        """
        zone = self.get_zone(zone_id)
        zone.triggered = False

    def get_event_log(self, limit: int = 100) -> list[AlarmEvent]:
        """Get event log.

        Args:
            limit: Maximum events to return.

        Returns:
            List of events.
        """
        return self._events[-limit:]

    def _log_event(
        self,
        event_type: str,
        alarm_state: AlarmState,
        zone_id: str | None = None,
        device_id: str | None = None,
        description: str | None = None,
    ) -> None:
        """Log a security event.

        Args:
            event_type: Type of event.
            alarm_state: Current alarm state.
            zone_id: Optional zone ID.
            device_id: Optional device ID.
            description: Optional description.
        """
        event = AlarmEvent(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            alarm_state=alarm_state,
            zone_id=zone_id,
            device_id=device_id,
            description=description,
        )
        self._events.append(event)

    def set_auto_arm_schedule(self, schedule: ArmingSchedule) -> None:
        """Set auto-arm schedule.

        Args:
            schedule: Arming schedule.
        """
        self._schedule = schedule

    def get_auto_arm_schedule(self) -> ArmingSchedule:
        """Get auto-arm schedule.

        Returns:
            Schedule.
        """
        return self._schedule

    def get_system_status(self) -> dict[str, Any]:
        """Get full system status.

        Returns:
            Status dict.
        """
        return {
            "state": self._state,
            "zones_armed": len(self.get_armed_zones()),
            "zones_triggered": len(self.get_triggered_zones()),
            "zones_tampered": len(self.get_tampered_zones()),
            "panic_active": self._panic_active,
            "entry_delay_active": self._entry_delay_active,
            "entry_delay_remaining": self._get_entry_delay_remaining(),
            "total_zones": len(self._zones),
        }

    def _get_entry_delay_remaining(self) -> int:
        """Get remaining entry delay in seconds.

        Returns:
            Seconds remaining.
        """
        if not self._entry_delay_active or not self._entry_delay_start:
            return 0

        elapsed = (datetime.now() - self._entry_delay_start).total_seconds()
        remaining = max(0, self._entry_delay_seconds - int(elapsed))
        return remaining
