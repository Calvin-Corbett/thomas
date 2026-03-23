"""Safety systems for autonomous vehicles.

Includes RSS (Responsibility-Sensitive Safety) model, safe distance computation,
worst-case braking scenarios, safety envelope monitoring, fault detection, and ODD checking.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from thomas.marketplace.autonomous_vehicles._types import (
    Obstacle,
    ObstacleType,
    VehicleState,
)


class ODDCondition(Enum):
    """Operational Design Domain condition."""

    GOOD_WEATHER = "good_weather"
    DAYLIGHT = "daylight"
    HIGHWAY = "highway"
    URBAN = "urban"
    VISIBILITY_GOOD = "visibility_good"
    SURFACE_PAVED = "surface_paved"
    NO_PEDESTRIANS = "no_pedestrians"
    STRUCTURED_ROADS = "structured_roads"


@dataclass
class SafeDistance:
    """Safe distance calculation result."""

    longitudinal_distance: float  # Safe following distance
    lateral_distance: float  # Safe lateral distance
    time_to_react: float  # Time available to react


@dataclass
class RSSState:
    """RSS safety state."""

    is_safe_lateral: bool = True
    is_safe_longitudinal: bool = True
    ego_is_at_fault: bool = False
    front_vehicle_id: str | None = None
    rear_vehicle_id: str | None = None


class ResponsibilitySensitiveSafety:
    """Responsibility-Sensitive Safety model."""

    def __init__(
        self: ResponsibilitySensitiveSafety,
        reaction_time: float = 0.1,
        max_acceleration: float = 3.0,
        max_deceleration: float = 8.0,
    ) -> None:
        """Initialize RSS model.

        Args:
            reaction_time: Reaction time in seconds
            max_acceleration: Maximum acceleration
            max_deceleration: Maximum deceleration
        """
        self.reaction_time = reaction_time
        self.max_acceleration = max_acceleration
        self.max_deceleration = max_deceleration

    def compute_safe_distance(
        self: ResponsibilitySensitiveSafety,
        ego_speed: float,
        other_speed: float,
        other_distance: float,
    ) -> SafeDistance:
        """Compute safe distance between vehicles.

        Args:
            ego_speed: Ego vehicle speed
            other_speed: Other vehicle speed
            other_distance: Current distance to other vehicle

        Returns:
            Safe distance calculation
        """
        # Reaction phase
        ego_travel = ego_speed * self.reaction_time
        other_travel = other_speed * self.reaction_time

        # Braking phase
        # Distance required for ego to stop at max deceleration
        if ego_speed > 0:
            ego_braking_distance = ego_speed**2 / (2 * self.max_deceleration)
        else:
            ego_braking_distance = 0.0

        # Maximum distance other vehicle can travel while braking
        # (worst case: other vehicle maintains speed during reaction time)
        if other_speed > 0:
            other_braking_distance = other_speed**2 / (2 * self.max_deceleration)
        else:
            other_braking_distance = 0.0

        # Safe following distance
        safe_longitudinal = ego_travel + ego_braking_distance + other_travel + other_braking_distance

        # Lateral safety distance (vehicle width + margin)
        safe_lateral = 1.8 + 0.5

        return SafeDistance(
            longitudinal_distance=safe_longitudinal,
            lateral_distance=safe_lateral,
            time_to_react=self.reaction_time,
        )

    def check_safety(
        self: ResponsibilitySensitiveSafety,
        ego_state: VehicleState,
        obstacles: list[Obstacle],
        vehicle_width: float = 1.8,
    ) -> RSSState:
        """Check RSS safety conditions.

        Args:
            ego_state: Ego vehicle state
            obstacles: Detected obstacles
            vehicle_width: Vehicle width

        Returns:
            RSS safety state
        """
        state = RSSState()

        # Find front and rear vehicles
        front_vehicle = None
        front_distance = float("inf")
        rear_vehicle = None
        rear_distance = float("inf")

        for obstacle in obstacles:
            if obstacle.obstacle_type not in [
                ObstacleType.VEHICLE,
                ObstacleType.PEDESTRIAN,
                ObstacleType.BICYCLE,
            ]:
                continue

            # Lateral overlap check
            lateral_offset = abs(obstacle.position.y - ego_state.position.y)

            if lateral_offset < vehicle_width + obstacle.width / 2:
                # Longitudinal check
                distance = obstacle.position.x - ego_state.position.x

                if distance > 0 and distance < front_distance:
                    front_vehicle = obstacle
                    front_distance = distance
                    state.front_vehicle_id = obstacle.obstacle_id

                elif distance < 0 and abs(distance) < rear_distance:
                    rear_vehicle = obstacle
                    rear_distance = abs(distance)
                    state.rear_vehicle_id = obstacle.obstacle_id

        # Check front vehicle safety
        if front_vehicle is not None:
            front_speed = front_vehicle.velocity.norm()
            safe_dist = self.compute_safe_distance(ego_state.speed, front_speed, front_distance)

            if front_distance < safe_dist.longitudinal_distance:
                state.is_safe_longitudinal = False
                state.ego_is_at_fault = True

        # Check rear vehicle safety
        if rear_vehicle is not None:
            rear_speed = rear_vehicle.velocity.norm()
            safe_dist = self.compute_safe_distance(rear_speed, ego_state.speed, rear_distance)

            if rear_distance < safe_dist.longitudinal_distance:
                state.is_safe_longitudinal = False
                # Rear vehicle is at fault for following too close

        return state


class SafetyEnvelopeMonitor:
    """Monitor vehicle against safety envelope."""

    def __init__(
        self: SafetyEnvelopeMonitor,
        max_speed: float = 30.0,
        max_acceleration: float = 5.0,
        max_deceleration: float = 10.0,
        max_lateral_acceleration: float = 3.0,
    ) -> None:
        """Initialize safety envelope monitor.

        Args:
            max_speed: Maximum vehicle speed
            max_acceleration: Maximum acceleration
            max_deceleration: Maximum deceleration
            max_lateral_acceleration: Maximum lateral acceleration
        """
        self.max_speed = max_speed
        self.max_acceleration = max_acceleration
        self.max_deceleration = max_deceleration
        self.max_lateral_acceleration = max_lateral_acceleration

    def check_envelope(
        self: SafetyEnvelopeMonitor,
        state: VehicleState,
    ) -> tuple[bool, list[str]]:
        """Check if state violates safety envelope.

        Args:
            state: Vehicle state

        Returns:
            Tuple of (is_safe, list of violations)
        """
        violations = []

        if state.speed > self.max_speed:
            violations.append(f"Speed {state.speed:.1f} exceeds limit {self.max_speed:.1f}")

        if state.acceleration.norm() > self.max_acceleration:
            violations.append(f"Acceleration {state.acceleration.norm():.1f} exceeds limit {self.max_acceleration:.1f}")

        return len(violations) == 0, violations


class FaultDetector:
    """Detect sensor and actuator faults."""

    def __init__(
        self: FaultDetector,
        sensor_timeout: float = 0.5,
        min_sensor_measurements: int = 1,
    ) -> None:
        """Initialize fault detector.

        Args:
            sensor_timeout: Timeout for sensor data
            min_sensor_measurements: Minimum measurements required
        """
        self.sensor_timeout = sensor_timeout
        self.min_sensor_measurements = min_sensor_measurements
        self.last_sensor_update: dict[str, float] = {}
        self.sensor_measurements: dict[str, list[Any]] = {}

    def register_sensor_update(self: FaultDetector, sensor_name: str, timestamp: float) -> None:
        """Register sensor measurement.

        Args:
            sensor_name: Name of sensor
            timestamp: Measurement timestamp
        """
        self.last_sensor_update[sensor_name] = timestamp

        if sensor_name not in self.sensor_measurements:
            self.sensor_measurements[sensor_name] = []

        self.sensor_measurements[sensor_name].append(timestamp)

        # Keep only recent measurements
        cutoff_time = timestamp - 10.0
        self.sensor_measurements[sensor_name] = [t for t in self.sensor_measurements[sensor_name] if t > cutoff_time]

    def check_sensor_health(self: FaultDetector, current_time: float) -> tuple[bool, dict[str, str]]:
        """Check health of all sensors.

        Args:
            current_time: Current timestamp

        Returns:
            Tuple of (all_healthy, faults)
        """
        faults: dict[str, str] = {}

        # Check for sensor timeouts
        for sensor_name, last_update in self.last_sensor_update.items():
            if current_time - last_update > self.sensor_timeout:
                faults[sensor_name] = "Timeout"

        # Check measurement frequency
        for sensor_name, measurements in self.sensor_measurements.items():
            if len(measurements) < self.min_sensor_measurements:
                faults[sensor_name] = "Low measurement frequency"

        return len(faults) == 0, faults

    def check_actuator_limits(
        self: FaultDetector,
        steering_angle: float,
        acceleration: float,
        max_steering: float = 0.5,
        max_acceleration: float = 5.0,
    ) -> tuple[bool, list[str]]:
        """Check actuator limits.

        Args:
            steering_angle: Current steering angle
            acceleration: Current acceleration
            max_steering: Maximum steering angle
            max_acceleration: Maximum acceleration

        Returns:
            Tuple of (within_limits, violations)
        """
        violations = []

        if abs(steering_angle) > max_steering:
            violations.append(f"Steering {steering_angle:.2f} exceeds limit {max_steering:.2f}")

        if abs(acceleration) > max_acceleration:
            violations.append(f"Acceleration {acceleration:.2f} exceeds limit {max_acceleration:.2f}")

        return len(violations) == 0, violations


class OperationalDesignDomainChecker:
    """Check if vehicle is within operational design domain."""

    def __init__(self: OperationalDesignDomainChecker) -> None:
        """Initialize ODD checker."""
        self.enabled_conditions: set = {
            ODDCondition.GOOD_WEATHER,
            ODDCondition.DAYLIGHT,
            ODDCondition.VISIBILITY_GOOD,
            ODDCondition.SURFACE_PAVED,
        }

    def check_odd(
        self: OperationalDesignDomainChecker,
        conditions: list[ODDCondition],
    ) -> tuple[bool, list[str]]:
        """Check if conditions are within ODD.

        Args:
            conditions: Current conditions

        Returns:
            Tuple of (within_ODD, violations)
        """
        violations = []

        for required in self.enabled_conditions:
            if required not in conditions:
                violations.append(f"Required condition {required.value} not met")

        return len(violations) == 0, violations

    def set_enabled_conditions(self: OperationalDesignDomainChecker, conditions: list[ODDCondition]) -> None:
        """Set enabled ODD conditions.

        Args:
            conditions: List of enabled conditions
        """
        self.enabled_conditions = set(conditions)


class SafetySupervisor:
    """Overall safety supervision system."""

    def __init__(self: SafetySupervisor) -> None:
        """Initialize safety supervisor."""
        self.rss = ResponsibilitySensitiveSafety()
        self.envelope = SafetyEnvelopeMonitor()
        self.fault_detector = FaultDetector()
        self.odd_checker = OperationalDesignDomainChecker()

    def check_overall_safety(
        self: SafetySupervisor,
        ego_state: VehicleState,
        obstacles: list[Obstacle],
        current_conditions: list[ODDCondition],
        current_time: float,
    ) -> tuple[bool, dict[str, Any]]:
        """Comprehensive safety check.

        Args:
            ego_state: Ego vehicle state
            obstacles: Detected obstacles
            current_conditions: Current environmental conditions
            current_time: Current timestamp

        Returns:
            Tuple of (is_safe, safety_report)
        """
        report: dict[str, Any] = {
            "is_safe": True,
            "rss_violation": False,
            "envelope_violation": False,
            "sensor_fault": False,
            "actuator_fault": False,
            "odd_violation": False,
            "violations": [],
        }

        # RSS check
        rss_state = self.rss.check_safety(ego_state, obstacles)
        if not rss_state.is_safe_longitudinal or not rss_state.is_safe_lateral:
            report["rss_violation"] = True
            report["violations"].append("RSS safety violation")

        # Safety envelope check
        envelope_safe, envelope_violations = self.envelope.check_envelope(ego_state)
        if not envelope_safe:
            report["envelope_violation"] = True
            report["violations"].extend(envelope_violations)

        # Sensor fault check
        sensor_healthy, sensor_faults = self.fault_detector.check_sensor_health(current_time)
        if not sensor_healthy:
            report["sensor_fault"] = True
            report["violations"].extend([f"Sensor {k}: {v}" for k, v in sensor_faults.items()])

        # ODD check
        odd_ok, odd_violations = self.odd_checker.check_odd(current_conditions)
        if not odd_ok:
            report["odd_violation"] = True
            report["violations"].extend(odd_violations)

        report["is_safe"] = (
            not report["rss_violation"]
            and not report["envelope_violation"]
            and not report["sensor_fault"]
            and not report["odd_violation"]
        )

        return report["is_safe"], report

    def trigger_safe_state(self: SafetySupervisor) -> None:
        """Request transition to safe state (e.g., emergency stop).

        This should trigger emergency braking and controlled pullover.
        """
        # Implementation would signal to control system
        pass
