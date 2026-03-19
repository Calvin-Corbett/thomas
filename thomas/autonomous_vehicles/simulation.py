"""Vehicle simulation and scenario runner for autonomous vehicles.

Includes kinematic and dynamic bicycle model, tire model, traffic simulation,
scenario runner, and collision detection.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from thomas.autonomous_vehicles._types import (
    ControlCommand,
    Vector2D,
    VehicleState,
)


@dataclass
class VehicleParams:
    """Vehicle parameters for simulation."""

    mass: float = 1500.0  # kg
    wheelbase: float = 2.7  # m
    track_width: float = 1.6  # m
    length: float = 4.5  # m
    width: float = 1.8  # m
    cf: float = 80000.0  # Front cornering stiffness
    cr: float = 80000.0  # Rear cornering stiffness
    ixx: float = 2000.0  # Yaw moment of inertia
    max_steering_angle: float = 0.5  # radians


class TireModel:
    """Simplified Pacejka tire model."""

    def __init__(self: TireModel) -> None:
        """Initialize tire model."""
        self.b = 10.0  # Stiffness factor
        self.c = 1.3  # Shape factor
        self.d = 1.0  # Peak factor

    def lateral_force(self: TireModel, slip_angle: float, normal_force: float) -> float:
        """Compute lateral tire force using Pacejka model.

        Args:
            slip_angle: Tire slip angle in radians
            normal_force: Normal force on tire

        Returns:
            Lateral force in Newtons
        """
        # Simplified Pacejka: Fy = D * sin(C * arctan(B * slip_angle))
        alpha = np.degrees(slip_angle)
        mu_y = self.d * np.sin(self.c * np.arctan(self.b * alpha))
        return mu_y * normal_force


class KinematicBicycleModel:
    """Kinematic bicycle model (no tire dynamics)."""

    def __init__(self: KinematicBicycleModel, params: VehicleParams) -> None:
        """Initialize kinematic bicycle model.

        Args:
            params: Vehicle parameters
        """
        self.params = params

    def step(
        self: KinematicBicycleModel,
        state: VehicleState,
        control: ControlCommand,
        dt: float,
    ) -> VehicleState:
        """Integrate state using kinematic bicycle model.

        Args:
            state: Current vehicle state
            control: Control command
            dt: Time step

        Returns:
            Updated state
        """
        x = state.position.x
        y = state.position.y
        theta = state.heading
        v = state.speed

        # Acceleration
        v_new = max(0.0, v + control.acceleration * dt)

        # Steering
        delta = control.steering_angle
        delta = np.clip(delta, -self.params.max_steering_angle, self.params.max_steering_angle)

        # Bicycle model equations
        if v_new > 0.1:
            beta = np.arctan2(np.tan(delta) * self.params.wheelbase / 2, self.params.wheelbase)
            x_new = x + v_new * np.cos(theta + beta) * dt
            y_new = y + v_new * np.sin(theta + beta) * dt
            theta_new = theta + v_new * np.sin(beta) / (self.params.wheelbase / 2) * dt
        else:
            x_new = x
            y_new = y
            theta_new = theta

        # Normalize heading
        theta_new = self._normalize_angle(theta_new)

        return VehicleState(
            timestamp=state.timestamp + dt,
            position=Vector2D(x_new, y_new),
            velocity=Vector2D(v_new * np.cos(theta_new), v_new * np.sin(theta_new)),
            acceleration=Vector2D(control.acceleration * np.cos(theta_new), control.acceleration * np.sin(theta_new)),
            heading=theta_new,
            heading_rate=v_new * np.sin(beta) / (self.params.wheelbase / 2) if v_new > 0.1 else 0.0,
            steering_angle=delta,
            speed=v_new,
        )

    @staticmethod
    def _normalize_angle(angle: float) -> float:
        """Normalize angle to [-pi, pi]."""
        while angle > np.pi:
            angle -= 2 * np.pi
        while angle < -np.pi:
            angle += 2 * np.pi
        return angle


class DynamicBicycleModel:
    """Dynamic bicycle model with tire forces."""

    def __init__(self: DynamicBicycleModel, params: VehicleParams) -> None:
        """Initialize dynamic bicycle model.

        Args:
            params: Vehicle parameters
        """
        self.params = params
        self.tire_model = TireModel()

    def step(
        self: DynamicBicycleModel,
        state: VehicleState,
        control: ControlCommand,
        dt: float,
    ) -> VehicleState:
        """Integrate state using dynamic bicycle model.

        Args:
            state: Current vehicle state
            control: Control command
            dt: Time step

        Returns:
            Updated state
        """
        x = state.position.x
        y = state.position.y
        theta = state.heading
        vx = state.velocity.x
        vy = state.velocity.y
        omega = state.heading_rate

        # Control inputs
        a = control.acceleration
        delta = np.clip(
            control.steering_angle,
            -self.params.max_steering_angle,
            self.params.max_steering_angle,
        )

        # Normal forces
        m = self.params.mass
        g = 9.81
        nz_f = m * g / 2
        nz_r = m * g / 2

        # Slip angles
        v = math.sqrt(vx**2 + vy**2)
        if v > 0.1:
            alpha_f = np.arctan2(vy + omega * self.params.wheelbase / 2, vx) - delta
            alpha_r = np.arctan2(vy - omega * self.params.wheelbase / 2, vx)
        else:
            alpha_f = 0.0
            alpha_r = 0.0

        # Tire forces
        fy_f = self.tire_model.lateral_force(alpha_f, nz_f)
        fy_r = self.tire_model.lateral_force(alpha_r, nz_r)
        fx = a * m

        # Vehicle dynamics
        ax = (fx - np.sin(delta) * fy_f) / m
        ay = (np.cos(delta) * fy_f + fy_r) / m
        a_omega = (
            fy_f * self.params.wheelbase / 2 * np.cos(delta) - fy_r * self.params.wheelbase / 2
        ) / self.params.ixx

        # Update state
        vx_new = vx + ax * dt
        vy_new = vy + ay * dt
        omega_new = omega + a_omega * dt

        v_new = math.sqrt(vx_new**2 + vy_new**2)
        theta_new = theta + omega * dt

        x_new = x + vx_new * np.cos(theta_new) * dt - vy_new * np.sin(theta_new) * dt
        y_new = y + vx_new * np.sin(theta_new) * dt + vy_new * np.cos(theta_new) * dt

        # Normalize heading
        theta_new = self._normalize_angle(theta_new)

        return VehicleState(
            timestamp=state.timestamp + dt,
            position=Vector2D(x_new, y_new),
            velocity=Vector2D(vx_new, vy_new),
            acceleration=Vector2D(ax, ay),
            heading=theta_new,
            heading_rate=omega_new,
            steering_angle=delta,
            speed=v_new,
        )

    @staticmethod
    def _normalize_angle(angle: float) -> float:
        """Normalize angle to [-pi, pi]."""
        while angle > np.pi:
            angle -= 2 * np.pi
        while angle < -np.pi:
            angle += 2 * np.pi
        return angle


class IntelligentDriverModel:
    """Intelligent Driver Model for traffic simulation."""

    def __init__(
        self: IntelligentDriverModel,
        desired_speed: float = 25.0,
        safe_time_headway: float = 1.5,
        max_acceleration: float = 2.0,
        max_deceleration: float = 3.0,
        jam_distance: float = 2.0,
    ) -> None:
        """Initialize IDM.

        Args:
            desired_speed: Desired speed
            safe_time_headway: Safe time headway
            max_acceleration: Maximum acceleration
            max_deceleration: Maximum deceleration
            jam_distance: Jam distance
        """
        self.desired_speed = desired_speed
        self.safe_time_headway = safe_time_headway
        self.max_acceleration = max_acceleration
        self.max_deceleration = max_deceleration
        self.jam_distance = jam_distance

    def compute_acceleration(
        self: IntelligentDriverModel,
        speed: float,
        lead_speed: float,
        gap: float,
    ) -> float:
        """Compute acceleration using IDM.

        Args:
            speed: Current speed
            lead_speed: Lead vehicle speed
            gap: Gap to lead vehicle

        Returns:
            Acceleration
        """
        # Desired headway gap; only apply closing-speed term when ego is faster.
        closing_term = max(
            0.0,
            speed * (speed - lead_speed) / (2 * np.sqrt(self.max_acceleration * self.max_deceleration)),
        )
        desired_gap = self.safe_time_headway * speed + closing_term

        # Free-road acceleration toward desired speed.
        accel_free = self.max_acceleration * (1 - (speed / max(self.desired_speed, 1e-6)) ** 4)

        # Car-following interaction term when too close.
        gap_error_ratio = (desired_gap - max(gap, 0.1)) / max(gap, 0.1)
        accel_interaction = -self.max_deceleration * max(0.0, gap_error_ratio)

        a = accel_free + accel_interaction

        return float(a)


class CollisionDetector:
    """Collision detection between vehicles."""

    def __init__(self: CollisionDetector) -> None:
        """Initialize collision detector."""
        pass

    def check_collision(
        self: CollisionDetector,
        state1: VehicleState,
        width1: float,
        length1: float,
        state2: VehicleState,
        width2: float,
        length2: float,
    ) -> bool:
        """Check collision between two vehicles.

        Args:
            state1: First vehicle state
            width1: First vehicle width
            length1: First vehicle length
            state2: Second vehicle state
            width2: Second vehicle width
            length2: Second vehicle length

        Returns:
            True if collision detected
        """
        # Simple bounding box collision check
        dx = state1.position.x - state2.position.x
        dy = state1.position.y - state2.position.y

        dist = math.sqrt(dx**2 + dy**2)
        min_distance = (length1 + length2) / 2 + (width1 + width2) / 2

        return dist < min_distance


class VehicleSimulator:
    """Vehicle dynamics simulator."""

    def __init__(
        self: VehicleSimulator,
        params: VehicleParams | None = None,
        use_dynamic_model: bool = False,
    ) -> None:
        """Initialize vehicle simulator.

        Args:
            params: Vehicle parameters
            use_dynamic_model: Use dynamic model instead of kinematic
        """
        self.params = params or VehicleParams()

        if use_dynamic_model:
            self.model = DynamicBicycleModel(self.params)
        else:
            self.model = KinematicBicycleModel(self.params)

    def simulate(
        self: VehicleSimulator,
        initial_state: VehicleState,
        control_sequence: list[ControlCommand],
        dt: float = 0.1,
    ) -> list[VehicleState]:
        """Simulate vehicle trajectory.

        Args:
            initial_state: Initial vehicle state
            control_sequence: Sequence of control commands
            dt: Simulation time step

        Returns:
            List of simulated states
        """
        states = [initial_state]
        current_state = initial_state

        for control in control_sequence:
            next_state = self.model.step(current_state, control, dt)
            states.append(next_state)
            current_state = next_state

        return states


class TrafficSimulator:
    """Simulate traffic with multiple vehicles."""

    def __init__(self: TrafficSimulator) -> None:
        """Initialize traffic simulator."""
        self.vehicles: dict[str, VehicleSimulator] = {}
        self.vehicle_states: dict[str, VehicleState] = {}
        self.idm_controllers: dict[str, IntelligentDriverModel] = {}
        self.collision_detector = CollisionDetector()

    def add_vehicle(
        self: TrafficSimulator,
        vehicle_id: str,
        state: VehicleState,
        params: VehicleParams | None = None,
    ) -> None:
        """Add vehicle to simulation.

        Args:
            vehicle_id: Vehicle ID
            state: Initial state
            params: Vehicle parameters
        """
        self.vehicles[vehicle_id] = VehicleSimulator(params=params)
        self.vehicle_states[vehicle_id] = state
        self.idm_controllers[vehicle_id] = IntelligentDriverModel()

    def step(self: TrafficSimulator, dt: float = 0.1) -> dict[str, VehicleState]:
        """Advance traffic simulation by one time step.

        Args:
            dt: Time step

        Returns:
            Updated vehicle states
        """
        vehicle_ids = list(self.vehicles.keys())

        # Compute accelerations using IDM
        for vehicle_id in vehicle_ids:
            current_state = self.vehicle_states[vehicle_id]
            speed = current_state.speed

            # Find lead vehicle
            lead_speed = 25.0
            gap = 100.0

            for other_id in vehicle_ids:
                if other_id != vehicle_id:
                    other_state = self.vehicle_states[other_id]
                    if (
                        other_state.position.x > current_state.position.x
                        and abs(other_state.position.y - current_state.position.y) < 2.0
                    ):
                        dist_to_lead = other_state.position.x - current_state.position.x
                        if dist_to_lead < gap:
                            gap = dist_to_lead
                            lead_speed = other_state.speed

            # Compute acceleration
            acceleration = self.idm_controllers[vehicle_id].compute_acceleration(speed, lead_speed, gap)

            # Create control command
            control = ControlCommand(
                timestamp=current_state.timestamp,
                acceleration=float(acceleration),
                steering_angle=0.0,
            )

            # Update state
            new_state = self.vehicles[vehicle_id].model.step(current_state, control, dt)

            self.vehicle_states[vehicle_id] = new_state

        return self.vehicle_states

    def check_collisions(self: TrafficSimulator) -> list[tuple[str, str]]:
        """Check for collisions.

        Returns:
            List of collision pairs (vehicle_id_1, vehicle_id_2)
        """
        collisions = []
        vehicle_ids = list(self.vehicles.keys())

        for i, vid1 in enumerate(vehicle_ids):
            for vid2 in vehicle_ids[i + 1 :]:
                state1 = self.vehicle_states[vid1]
                state2 = self.vehicle_states[vid2]
                params1 = self.vehicles[vid1].params
                params2 = self.vehicles[vid2].params

                if self.collision_detector.check_collision(
                    state1,
                    params1.width,
                    params1.length,
                    state2,
                    params2.width,
                    params2.length,
                ):
                    collisions.append((vid1, vid2))

        return collisions
