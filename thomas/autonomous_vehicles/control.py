"""Vehicle control system for autonomous vehicles.

Includes Stanley lateral controller, PID longitudinal controller,
MPC, adaptive cruise control, emergency braking, and torque vectoring.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from thomas.autonomous_vehicles._exceptions import ActuatorLimitException
from thomas.autonomous_vehicles._types import (
    ControlCommand,
    Obstacle,
    Vector2D,
    VehicleState,
    Waypoint,
)


@dataclass
class PIDController:
    """PID controller for longitudinal control."""

    kp: float = 1.0
    ki: float = 0.1
    kd: float = 0.5
    integral_error: float = 0.0
    last_error: float = 0.0
    max_output: float = 10.0

    def update(self: PIDController, error: float, dt: float) -> float:
        """Update PID controller.

        Args:
            error: Current error
            dt: Time step

        Returns:
            Control output
        """
        self.integral_error += error * dt
        self.integral_error = np.clip(self.integral_error, -1.0, 1.0)

        derivative_error = (error - self.last_error) / (dt + 1e-6)
        self.last_error = error

        output = self.kp * error + self.ki * self.integral_error + self.kd * derivative_error
        return np.clip(output, -self.max_output, self.max_output)

    def reset(self: PIDController) -> None:
        """Reset controller state."""
        self.integral_error = 0.0
        self.last_error = 0.0


class StanleyController:
    """Stanley lateral controller for path tracking."""

    def __init__(
        self: StanleyController,
        wheelbase: float = 2.7,
        gain: float = 1.0,
        max_steering_angle: float = 0.5,
    ) -> None:
        """Initialize Stanley controller.

        Args:
            wheelbase: Vehicle wheelbase
            gain: Controller gain
            max_steering_angle: Maximum steering angle
        """
        self.wheelbase = wheelbase
        self.gain = gain
        self.max_steering_angle = max_steering_angle

    def compute_steering(
        self: StanleyController,
        vehicle_state: VehicleState,
        path_points: list[Waypoint],
    ) -> float:
        """Compute steering command using Stanley method.

        Args:
            vehicle_state: Current vehicle state
            path_points: Reference path points

        Returns:
            Steering angle in radians
        """
        if len(path_points) < 2:
            return 0.0

        # Find nearest point on path
        min_dist = float("inf")
        nearest_idx = 0
        lateral_error = 0.0

        for i in range(len(path_points) - 1):
            p1 = path_points[i]
            p2 = path_points[i + 1]

            # Project vehicle onto path segment
            v = p2.position - p1.position
            w = vehicle_state.position - p1.position

            c1 = w.dot(v)
            if c1 <= 0:
                dist = w.norm()
                proj_point = p1.position
            else:
                c2 = v.dot(v)
                if c1 >= c2:
                    dist = (vehicle_state.position - p2.position).norm()
                    proj_point = p2.position
                else:
                    b = c1 / c2
                    proj_point = p1.position + v * b
                    dist = (vehicle_state.position - proj_point).norm()

            if dist < min_dist:
                min_dist = dist
                nearest_idx = i
                lateral_error = dist

        # Determine sign of lateral error
        ref_point = path_points[nearest_idx].position
        heading_vector = Vector2D(np.cos(vehicle_state.heading), np.sin(vehicle_state.heading))

        error_vector = ref_point - vehicle_state.position
        cross = heading_vector.x * error_vector.y - heading_vector.y * error_vector.x
        if cross < 0:
            lateral_error = -lateral_error

        # Reference heading
        if nearest_idx < len(path_points) - 1:
            ref_heading = path_points[nearest_idx].heading
        else:
            ref_heading = path_points[-1].heading

        # Heading error
        heading_error = ref_heading - vehicle_state.heading
        heading_error = self._normalize_angle(heading_error)

        # Stanley control law
        speed = vehicle_state.speed + 1e-6
        cross_track_term = np.arctan2(self.gain * lateral_error, speed)

        steering = heading_error + cross_track_term

        return np.clip(steering, -self.max_steering_angle, self.max_steering_angle)

    @staticmethod
    def _normalize_angle(angle: float) -> float:
        """Normalize angle to [-pi, pi]."""
        while angle > np.pi:
            angle -= 2 * np.pi
        while angle < -np.pi:
            angle += 2 * np.pi
        return angle


class LongitudinalController:
    """PID-based longitudinal controller."""

    def __init__(
        self: LongitudinalController,
        kp: float = 1.0,
        ki: float = 0.1,
        kd: float = 0.5,
    ) -> None:
        """Initialize longitudinal controller.

        Args:
            kp: Proportional gain
            ki: Integral gain
            kd: Derivative gain
        """
        self.pid = PIDController(kp=kp, ki=ki, kd=kd)

    def compute_acceleration(
        self: LongitudinalController,
        current_speed: float,
        target_speed: float,
        dt: float,
    ) -> float:
        """Compute longitudinal acceleration command.

        Args:
            current_speed: Current vehicle speed
            target_speed: Target speed
            dt: Time step

        Returns:
            Acceleration in m/s^2
        """
        speed_error = target_speed - current_speed
        return self.pid.update(speed_error, dt)

    def reset(self: LongitudinalController) -> None:
        """Reset controller."""
        self.pid.reset()


class ModelPredictiveControl:
    """Model Predictive Control for trajectory tracking."""

    def __init__(
        self: ModelPredictiveControl,
        wheelbase: float = 2.7,
        prediction_horizon: int = 10,
        dt: float = 0.1,
    ) -> None:
        """Initialize MPC controller.

        Args:
            wheelbase: Vehicle wheelbase
            prediction_horizon: Prediction horizon steps
            dt: Time step
        """
        self.wheelbase = wheelbase
        self.prediction_horizon = prediction_horizon
        self.dt = dt

    def compute_control(
        self: ModelPredictiveControl,
        vehicle_state: VehicleState,
        reference_trajectory: list[Waypoint],
    ) -> tuple[float, float]:
        """Compute control inputs using MPC.

        Args:
            vehicle_state: Current vehicle state
            reference_trajectory: Reference trajectory

        Returns:
            Tuple of (acceleration, steering_angle)
        """
        # Linearized bicycle model at current state
        x = vehicle_state.position.x
        y = vehicle_state.position.y
        theta = vehicle_state.heading
        v = vehicle_state.speed

        # Simple linear MPC: compute desired lateral and longitudinal errors
        if len(reference_trajectory) < 2:
            return 0.0, 0.0

        # Get reference point ahead
        lookahead_time = min(2.0, self.prediction_horizon * self.dt)
        ref_idx = min(int(lookahead_time / self.dt), len(reference_trajectory) - 1)
        ref_point = reference_trajectory[ref_idx]

        # Lateral error
        dx = ref_point.position.x - x
        dy = ref_point.position.y - y
        lateral_error = -dx * np.sin(theta) + dy * np.cos(theta)

        # Heading error
        heading_error = ref_point.heading - theta

        # Simple proportional control
        steering = 0.5 * heading_error + 0.1 * lateral_error
        steering = np.clip(steering, -0.5, 0.5)

        # Longitudinal control
        speed_error = ref_point.speed_limit - v
        acceleration = 0.5 * speed_error

        return acceleration, steering


class AdaptiveCruiseControl:
    """Adaptive cruise control system."""

    def __init__(
        self: AdaptiveCruiseControl,
        desired_gap: float = 20.0,
        desired_speed: float = 25.0,
        max_acceleration: float = 2.0,
        max_deceleration: float = 5.0,
    ) -> None:
        """Initialize adaptive cruise control.

        Args:
            desired_gap: Desired gap to front vehicle
            desired_speed: Desired cruise speed
            max_acceleration: Maximum acceleration
            max_deceleration: Maximum deceleration
        """
        self.desired_gap = desired_gap
        self.desired_speed = desired_speed
        self.max_acceleration = max_acceleration
        self.max_deceleration = max_deceleration
        self.pid = PIDController(kp=0.5, ki=0.1, kd=0.3)

    def compute_acceleration(
        self: AdaptiveCruiseControl,
        vehicle_state: VehicleState,
        lead_obstacle: Obstacle | None,
    ) -> float:
        """Compute ACC acceleration.

        Args:
            vehicle_state: Current vehicle state
            lead_obstacle: Lead vehicle/obstacle

        Returns:
            Acceleration command
        """
        if lead_obstacle is None:
            # No lead vehicle, accelerate to desired speed
            speed_error = self.desired_speed - vehicle_state.speed
            return np.clip(
                self.pid.update(speed_error, 0.1),
                -self.max_deceleration,
                self.max_acceleration,
            )

        # Lead vehicle present
        range_to_lead = lead_obstacle.distance_to(vehicle_state.position)

        # Desired spacing
        desired_spacing = self.desired_gap + 0.5 * vehicle_state.speed

        # Gap error
        gap_error = range_to_lead - desired_spacing

        # Time derivative of gap (closing velocity)
        relative_velocity = lead_obstacle.velocity.norm() - vehicle_state.speed

        # Combined control law
        acceleration = 0.5 * gap_error + 0.2 * relative_velocity

        return np.clip(
            acceleration,
            -self.max_deceleration,
            self.max_acceleration,
        )


class EmergencyBraking:
    """Emergency braking system."""

    def __init__(
        self: EmergencyBraking,
        reaction_time: float = 0.1,
        max_deceleration: float = 10.0,
    ) -> None:
        """Initialize emergency braking.

        Args:
            reaction_time: Reaction time delay
            max_deceleration: Maximum deceleration
        """
        self.reaction_time = reaction_time
        self.max_deceleration = max_deceleration
        self.braking = False
        self.brake_start_time = 0.0

    def trigger_brake(self: EmergencyBraking, timestamp: float) -> None:
        """Trigger emergency brake.

        Args:
            timestamp: Current timestamp
        """
        self.braking = True
        self.brake_start_time = timestamp

    def compute_deceleration(self: EmergencyBraking, vehicle_state: VehicleState) -> float:
        """Compute emergency braking deceleration.

        Args:
            vehicle_state: Current vehicle state

        Returns:
            Deceleration command
        """
        if not self.braking:
            return 0.0

        elapsed = vehicle_state.timestamp - self.brake_start_time

        if elapsed < self.reaction_time:
            return 0.0

        return -self.max_deceleration

    def reset(self: EmergencyBraking) -> None:
        """Reset emergency brake."""
        self.braking = False


class VehicleController:
    """Complete vehicle control system."""

    def __init__(
        self: VehicleController,
        wheelbase: float = 2.7,
        max_steering_angle: float = 0.5,
    ) -> None:
        """Initialize vehicle controller.

        Args:
            wheelbase: Vehicle wheelbase
            max_steering_angle: Maximum steering angle
        """
        self.wheelbase = wheelbase
        self.max_steering_angle = max_steering_angle

        self.stanley_controller = StanleyController(wheelbase=wheelbase)
        self.longitudinal_controller = LongitudinalController()
        self.mpc = ModelPredictiveControl(wheelbase=wheelbase)
        self.acc = AdaptiveCruiseControl()
        self.emergency_brake = EmergencyBraking()

        self.steering_rate_limiter = 0.5  # rad/s
        self.last_steering_angle = 0.0
        self.last_timestamp = 0.0

    def compute_control(
        self: VehicleController,
        vehicle_state: VehicleState,
        reference_trajectory: list[Waypoint],
        target_speed: float,
        obstacles: list[Obstacle] | None = None,
        emergency_stop: bool = False,
    ) -> ControlCommand:
        """Compute control command.

        Args:
            vehicle_state: Current vehicle state
            reference_trajectory: Reference trajectory
            target_speed: Target speed
            obstacles: Detected obstacles
            emergency_stop: Trigger emergency stop

        Returns:
            Control command

        Raises:
            ActuatorLimitException: If limits exceeded
        """
        if emergency_stop:
            self.emergency_brake.trigger_brake(vehicle_state.timestamp)

        # Lateral control
        steering_raw = self.stanley_controller.compute_steering(vehicle_state, reference_trajectory)

        # Rate limit steering
        dt = vehicle_state.timestamp - self.last_timestamp
        if dt > 0.0:
            max_change = self.steering_rate_limiter * dt
            steering = np.clip(
                steering_raw,
                self.last_steering_angle - max_change,
                self.last_steering_angle + max_change,
            )
        else:
            steering = steering_raw

        steering = np.clip(steering, -self.max_steering_angle, self.max_steering_angle)
        self.last_steering_angle = steering

        # Longitudinal control
        if emergency_stop:
            acceleration = -self.emergency_brake.max_deceleration
        else:
            # Check for lead vehicle
            lead_obstacle = None
            if obstacles:
                for obs in obstacles:
                    if obs.position.x > vehicle_state.position.x:
                        if lead_obstacle is None or obs.position.x < lead_obstacle.position.x:
                            lead_obstacle = obs

            acceleration = self.acc.compute_acceleration(vehicle_state, lead_obstacle)

        # Validate command
        if abs(steering) > self.max_steering_angle:
            raise ActuatorLimitException(f"Steering angle {steering} exceeds limit")

        self.last_timestamp = vehicle_state.timestamp

        return ControlCommand(
            timestamp=vehicle_state.timestamp,
            acceleration=float(acceleration),
            steering_angle=float(steering),
            gear="D" if acceleration >= 0 else "R",
        )
