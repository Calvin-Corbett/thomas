"""Tests for control module."""

from thomas.autonomous_vehicles._types import (
    ControlCommand,
    Obstacle,
    ObstacleType,
    Vector2D,
    VehicleState,
    Waypoint,
)
from thomas.autonomous_vehicles.control import (
    AdaptiveCruiseControl,
    EmergencyBraking,
    LongitudinalController,
    PIDController,
    StanleyController,
    VehicleController,
)


class TestPIDController:
    """Test PID controller."""

    def test_pid_proportional(self) -> None:
        """Test proportional control."""
        pid = PIDController(kp=1.0, ki=0.0, kd=0.0)

        error = 10.0
        output = pid.update(error, dt=0.1)

        assert output > 0.0
        assert abs(output - 10.0) < 0.1

    def test_pid_integral(self) -> None:
        """Test integral action."""
        pid = PIDController(kp=0.0, ki=1.0, kd=0.0)

        for _ in range(10):
            output = pid.update(1.0, dt=0.1)

        assert pid.integral_error > 0.0

    def test_pid_derivative(self) -> None:
        """Test derivative action."""
        pid = PIDController(kp=0.0, ki=0.0, kd=1.0)

        pid.update(0.0, dt=0.1)
        output = pid.update(10.0, dt=0.1)

        assert output != 0.0

    def test_pid_reset(self) -> None:
        """Test controller reset."""
        pid = PIDController(kp=1.0, ki=0.5, kd=0.5)

        pid.update(5.0, dt=0.1)
        pid.reset()

        assert pid.integral_error == 0.0
        assert pid.last_error == 0.0


class TestStanleyController:
    """Test Stanley controller."""

    def test_stanley_on_path(self) -> None:
        """Test Stanley controller when on path."""
        controller = StanleyController(wheelbase=2.7)

        vehicle_state = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(5.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=5.0,
        )

        path = [
            Waypoint(position=Vector2D(0.0, 0.0), heading=0.0),
            Waypoint(position=Vector2D(10.0, 0.0), heading=0.0),
        ]

        steering = controller.compute_steering(vehicle_state, path)

        assert abs(steering) <= 0.5

    def test_stanley_lateral_error_correction(self) -> None:
        """Test Stanley correction for lateral error."""
        controller = StanleyController(wheelbase=2.7, gain=1.0)

        # Vehicle offset from path
        vehicle_state = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.0, 1.0),  # 1m off path
            velocity=Vector2D(5.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=5.0,
        )

        path = [
            Waypoint(position=Vector2D(0.0, 0.0), heading=0.0),
            Waypoint(position=Vector2D(10.0, 0.0), heading=0.0),
        ]

        steering = controller.compute_steering(vehicle_state, path)

        # Should steer to correct lateral error
        assert steering < 0.0  # Steer right toward path


class TestLongitudinalController:
    """Test longitudinal controller."""

    def test_speed_control(self) -> None:
        """Test speed control."""
        controller = LongitudinalController(kp=1.0, ki=0.0, kd=0.0)

        current_speed = 5.0
        target_speed = 10.0

        acceleration = controller.compute_acceleration(current_speed, target_speed, dt=0.1)

        assert acceleration > 0.0

    def test_deceleration(self) -> None:
        """Test deceleration."""
        controller = LongitudinalController(kp=1.0, ki=0.0, kd=0.0)

        current_speed = 10.0
        target_speed = 5.0

        acceleration = controller.compute_acceleration(current_speed, target_speed, dt=0.1)

        assert acceleration < 0.0


class TestAdaptiveCruiseControl:
    """Test adaptive cruise control."""

    def test_acc_no_lead_vehicle(self) -> None:
        """Test ACC when no lead vehicle."""
        acc = AdaptiveCruiseControl(desired_speed=25.0)

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

        acceleration = acc.compute_acceleration(vehicle_state, lead_obstacle=None)

        assert acceleration > 0.0

    def test_acc_with_lead_vehicle(self) -> None:
        """Test ACC with lead vehicle."""
        acc = AdaptiveCruiseControl(desired_gap=20.0, desired_speed=25.0)

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

        lead = Obstacle(
            obstacle_id="lead",
            position=Vector2D(25.0, 0.0),
            velocity=Vector2D(15.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            obstacle_type=ObstacleType.VEHICLE,
        )

        acceleration = acc.compute_acceleration(vehicle_state, lead_obstacle=lead)

        assert acceleration < 0.0  # Should decelerate


class TestEmergencyBraking:
    """Test emergency braking."""

    def test_emergency_brake_trigger(self) -> None:
        """Test emergency brake triggering."""
        brake = EmergencyBraking()

        assert not brake.braking

        brake.trigger_brake(timestamp=0.0)

        assert brake.braking

    def test_emergency_brake_deceleration(self) -> None:
        """Test emergency brake deceleration."""
        brake = EmergencyBraking(max_deceleration=10.0)

        vehicle_state = VehicleState(
            timestamp=0.2,
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(20.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=20.0,
        )

        brake.trigger_brake(timestamp=0.0)

        deceleration = brake.compute_deceleration(vehicle_state)

        assert deceleration < 0.0
        assert deceleration >= -10.0


class TestVehicleController:
    """Test complete vehicle controller."""

    def test_compute_control_command(self) -> None:
        """Test control command computation."""
        controller = VehicleController()

        vehicle_state = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(5.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=5.0,
        )

        path = [
            Waypoint(position=Vector2D(0.0, 0.0), heading=0.0),
            Waypoint(position=Vector2D(10.0, 0.0), heading=0.0),
        ]

        command = controller.compute_control(
            vehicle_state,
            path,
            target_speed=10.0,
            obstacles=[],
            emergency_stop=False,
        )

        assert isinstance(command, ControlCommand)
        assert command.is_valid()

    def test_steering_rate_limiting(self) -> None:
        """Test steering rate limiting."""
        controller = VehicleController(max_steering_angle=0.5)

        vehicle_state1 = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(5.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=5.0,
        )

        path = [
            Waypoint(position=Vector2D(0.0, 0.0), heading=0.0),
            Waypoint(position=Vector2D(10.0, 0.0), heading=0.0),
        ]

        command1 = controller.compute_control(vehicle_state1, path, target_speed=5.0, obstacles=[])

        # Abrupt state change
        vehicle_state2 = VehicleState(
            timestamp=0.01,
            position=Vector2D(0.0, 2.0),  # Large lateral error
            velocity=Vector2D(5.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=command1.steering_angle,
            speed=5.0,
        )

        command2 = controller.compute_control(vehicle_state2, path, target_speed=5.0, obstacles=[])

        # Steering should be rate-limited
        steering_change = abs(command2.steering_angle - command1.steering_angle)
        max_allowed_change = controller.steering_rate_limiter * 0.01

        assert steering_change <= max_allowed_change + 1e-6

    def test_emergency_stop(self) -> None:
        """Test emergency stop."""
        controller = VehicleController()

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

        path = [
            Waypoint(position=Vector2D(0.0, 0.0), heading=0.0),
            Waypoint(position=Vector2D(10.0, 0.0), heading=0.0),
        ]

        command = controller.compute_control(vehicle_state, path, target_speed=10.0, obstacles=[], emergency_stop=True)

        # Emergency stop should trigger heavy deceleration
        assert command.acceleration < -5.0


class TestControlCommandValidation:
    """Test control command validation."""

    def test_valid_command(self) -> None:
        """Test valid control command."""
        command = ControlCommand(timestamp=0.0, acceleration=1.0, steering_angle=0.1)

        assert command.is_valid()

    def test_invalid_acceleration(self) -> None:
        """Test invalid acceleration."""
        command = ControlCommand(timestamp=0.0, acceleration=15.0, steering_angle=0.1)

        assert not command.is_valid()

    def test_invalid_steering(self) -> None:
        """Test invalid steering angle."""
        command = ControlCommand(timestamp=0.0, acceleration=1.0, steering_angle=1.5)

        assert not command.is_valid()
