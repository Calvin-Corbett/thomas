"""Tests for safety module."""

from thomas.marketplace.autonomous_vehicles._types import (
    Obstacle,
    ObstacleType,
    Vector2D,
    VehicleState,
)
from thomas.marketplace.autonomous_vehicles.safety import (
    FaultDetector,
    ODDCondition,
    OperationalDesignDomainChecker,
    ResponsibilitySensitiveSafety,
    SafetyEnvelopeMonitor,
    SafetySupervisor,
)


class TestResponsibilitySensitiveSafety:
    """Test RSS model."""

    def test_safe_distance_computation(self) -> None:
        """Test safe distance computation."""
        rss = ResponsibilitySensitiveSafety()

        safe_dist = rss.compute_safe_distance(ego_speed=10.0, other_speed=5.0, other_distance=50.0)

        assert safe_dist.longitudinal_distance > 0.0
        assert safe_dist.lateral_distance > 0.0

    def test_safe_distance_zero_speed(self) -> None:
        """Test safe distance at zero speed."""
        rss = ResponsibilitySensitiveSafety()

        safe_dist = rss.compute_safe_distance(ego_speed=0.0, other_speed=0.0, other_distance=10.0)

        assert safe_dist.longitudinal_distance >= 0.0

    def test_safety_check_no_obstacles(self) -> None:
        """Test safety check with no obstacles."""
        rss = ResponsibilitySensitiveSafety()

        vehicle_state = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(10.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=10.0,
        )

        state = rss.check_safety(vehicle_state, obstacles=[])

        assert state.is_safe_longitudinal
        assert state.is_safe_lateral

    def test_safety_check_with_vehicle(self) -> None:
        """Test safety check with vehicles."""
        rss = ResponsibilitySensitiveSafety()

        vehicle_state = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(10.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=10.0,
        )

        # Vehicle too close
        obstacle = Obstacle(
            obstacle_id="obs_0",
            position=Vector2D(5.0, 0.0),
            velocity=Vector2D(0.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            obstacle_type=ObstacleType.VEHICLE,
        )

        state = rss.check_safety(vehicle_state, obstacles=[obstacle])

        assert not state.is_safe_longitudinal


class TestSafetyEnvelopeMonitor:
    """Test safety envelope monitor."""

    def test_speed_limit_check(self) -> None:
        """Test speed limit check."""
        monitor = SafetyEnvelopeMonitor(max_speed=30.0)

        state = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(25.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=25.0,
        )

        is_safe, violations = monitor.check_envelope(state)

        assert is_safe

    def test_speed_violation(self) -> None:
        """Test speed violation detection."""
        monitor = SafetyEnvelopeMonitor(max_speed=30.0)

        state = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(35.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=35.0,
        )

        is_safe, violations = monitor.check_envelope(state)

        assert not is_safe
        assert len(violations) > 0


class TestFaultDetector:
    """Test fault detector."""

    def test_register_sensor_update(self) -> None:
        """Test sensor update registration."""
        detector = FaultDetector()

        detector.register_sensor_update("lidar", timestamp=1.0)

        assert "lidar" in detector.last_sensor_update

    def test_sensor_timeout_detection(self) -> None:
        """Test sensor timeout detection."""
        detector = FaultDetector(sensor_timeout=0.5)

        detector.register_sensor_update("lidar", timestamp=0.0)

        healthy, faults = detector.check_sensor_health(current_time=1.0)

        assert not healthy
        assert "lidar" in faults

    def test_sensor_healthy(self) -> None:
        """Test healthy sensor."""
        detector = FaultDetector(sensor_timeout=1.0)

        detector.register_sensor_update("lidar", timestamp=0.0)

        healthy, faults = detector.check_sensor_health(current_time=0.5)

        assert healthy

    def test_actuator_limit_check(self) -> None:
        """Test actuator limit checking."""
        detector = FaultDetector()

        # Normal actuator command
        within_limits, violations = detector.check_actuator_limits(steering_angle=0.2, acceleration=1.0)

        assert within_limits

    def test_actuator_violation(self) -> None:
        """Test actuator limit violation."""
        detector = FaultDetector()

        # Excessive steering
        within_limits, violations = detector.check_actuator_limits(
            steering_angle=1.0, acceleration=1.0, max_steering=0.5
        )

        assert not within_limits
        assert len(violations) > 0


class TestOperationalDesignDomainChecker:
    """Test ODD checker."""

    def test_odd_within_domain(self) -> None:
        """Test check when within ODD."""
        checker = OperationalDesignDomainChecker()

        conditions = [
            ODDCondition.GOOD_WEATHER,
            ODDCondition.DAYLIGHT,
            ODDCondition.VISIBILITY_GOOD,
            ODDCondition.SURFACE_PAVED,
        ]

        within, violations = checker.check_odd(conditions)

        assert within

    def test_odd_outside_domain(self) -> None:
        """Test check when outside ODD."""
        checker = OperationalDesignDomainChecker()

        conditions = [
            ODDCondition.DAYLIGHT,
        ]

        within, violations = checker.check_odd(conditions)

        assert not within
        assert len(violations) > 0

    def test_set_enabled_conditions(self) -> None:
        """Test setting enabled conditions."""
        checker = OperationalDesignDomainChecker()

        new_conditions = [ODDCondition.DAYLIGHT, ODDCondition.HIGHWAY]
        checker.set_enabled_conditions(new_conditions)

        assert ODDCondition.DAYLIGHT in checker.enabled_conditions
        assert ODDCondition.HIGHWAY in checker.enabled_conditions


class TestSafetySupervisor:
    """Test safety supervisor."""

    def test_overall_safety_check_safe(self) -> None:
        """Test overall safety when safe."""
        supervisor = SafetySupervisor()

        vehicle_state = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(10.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=10.0,
        )

        conditions = [
            ODDCondition.GOOD_WEATHER,
            ODDCondition.DAYLIGHT,
            ODDCondition.VISIBILITY_GOOD,
            ODDCondition.SURFACE_PAVED,
        ]

        is_safe, report = supervisor.check_overall_safety(
            vehicle_state,
            obstacles=[],
            current_conditions=conditions,
            current_time=0.0,
        )

        assert is_safe
        assert report["is_safe"]

    def test_overall_safety_check_rss_violation(self) -> None:
        """Test safety check with RSS violation."""
        supervisor = SafetySupervisor()

        vehicle_state = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(20.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=20.0,
        )

        # Close obstacle
        obstacle = Obstacle(
            obstacle_id="obs_0",
            position=Vector2D(5.0, 0.0),
            velocity=Vector2D(0.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            obstacle_type=ObstacleType.VEHICLE,
        )

        conditions = [
            ODDCondition.GOOD_WEATHER,
            ODDCondition.DAYLIGHT,
            ODDCondition.VISIBILITY_GOOD,
        ]

        is_safe, report = supervisor.check_overall_safety(
            vehicle_state,
            obstacles=[obstacle],
            current_conditions=conditions,
            current_time=0.0,
        )

        assert not is_safe
        assert report["rss_violation"]

    def test_overall_safety_check_odd_violation(self) -> None:
        """Test safety check with ODD violation."""
        supervisor = SafetySupervisor()

        vehicle_state = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(10.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=10.0,
        )

        # Missing required ODD condition
        conditions = [ODDCondition.DAYLIGHT]

        is_safe, report = supervisor.check_overall_safety(
            vehicle_state,
            obstacles=[],
            current_conditions=conditions,
            current_time=0.0,
        )

        assert not is_safe
        assert report["odd_violation"]

    def test_safety_report_content(self) -> None:
        """Test safety report structure."""
        supervisor = SafetySupervisor()

        vehicle_state = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(10.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=10.0,
        )

        is_safe, report = supervisor.check_overall_safety(
            vehicle_state, obstacles=[], current_conditions=[], current_time=0.0
        )

        assert "is_safe" in report
        assert "rss_violation" in report
        assert "envelope_violation" in report
        assert "sensor_fault" in report
        assert "odd_violation" in report
        assert "violations" in report
