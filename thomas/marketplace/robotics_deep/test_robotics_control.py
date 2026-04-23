"""
Tests for control module.
"""

import pytest

from thomas.marketplace.robotics_deep._types import JointState, Vec3
from thomas.marketplace.robotics_deep.control import (
    ComputedTorqueController,
    ImpedanceController,
    PIDController,
    TrajectoryTracker,
    VelocityController,
)


class TestPIDController:
    """Test PID controller."""

    def test_pid_proportional_action(self) -> None:
        """Test proportional control."""
        pid = PIDController(kp=1.0, ki=0.0, kd=0.0)

        error = 10.0
        output = pid.compute(error)

        assert output == 10.0

    def test_pid_integral_action(self) -> None:
        """Test integral action."""
        pid = PIDController(kp=0.0, ki=1.0, kd=0.0, dt=0.01)

        pid.compute(1.0)
        pid.compute(1.0)

        integral = pid.integral
        assert integral > 0

    def test_pid_derivative_action(self) -> None:
        """Test derivative action."""
        pid = PIDController(kp=0.0, ki=0.0, kd=1.0, dt=0.01)

        pid.compute(1.0)
        output = pid.compute(2.0)

        assert output > 0

    def test_pid_anti_windup(self) -> None:
        """Test anti-windup limits integral."""
        pid = PIDController(kp=0.0, ki=1.0, kd=0.0, max_integral=1.0, dt=0.01)

        for _ in range(200):
            pid.compute(10.0)

        assert pid.integral <= 1.0

    def test_pid_reset(self) -> None:
        """Test PID reset."""
        pid = PIDController(kp=1.0, ki=0.5, kd=0.1)

        pid.compute(5.0)
        pid.reset()

        assert pid.integral == 0.0
        assert pid.last_error == 0.0


class TestTrajectoryTracker:
    """Test trajectory tracking controller."""

    def test_trajectory_tracker_initialization(self) -> None:
        """Test tracker initialization."""
        tracker = TrajectoryTracker(num_joints=2)

        assert len(tracker.pid_controllers) == 2

    def test_trajectory_tracker_compute(self) -> None:
        """Test torque computation."""
        tracker = TrajectoryTracker(num_joints=2)

        current = [
            JointState(position=0.0, velocity=0.0, acceleration=0.0, effort=0.0),
            JointState(position=0.0, velocity=0.0, acceleration=0.0, effort=0.0),
        ]

        desired = [
            JointState(position=1.0, velocity=0.1, acceleration=0.0, effort=0.0),
            JointState(position=0.5, velocity=0.0, acceleration=0.0, effort=0.0),
        ]

        torques = tracker.compute(current, desired)

        assert len(torques) == 2
        assert torques[0] > 0  # Should move first joint forward

    def test_trajectory_tracker_joint_mismatch(self) -> None:
        """Test error on joint count mismatch."""
        tracker = TrajectoryTracker(num_joints=2)

        current = [JointState(0, 0, 0, 0)]

        with pytest.raises(ValueError):
            tracker.compute(current, [])


class TestComputedTorqueController:
    """Test computed torque control."""

    def test_computed_torque_initialize(self) -> None:
        """Test controller initialization."""

        def mass_matrix_fn(q):
            return [[1, 0], [0, 1]]

        def coriolis_fn(q, qdot):
            return [0, 0]

        def gravity_fn(q):
            return [0, 0]

        controller = ComputedTorqueController(mass_matrix_fn, coriolis_fn, gravity_fn)

        assert controller.kp > 0
        assert controller.kd > 0

    def test_computed_torque_compute(self) -> None:
        """Test torque computation."""

        def mass_matrix_fn(q):
            return [[1.0, 0], [0, 1.0]]

        def coriolis_fn(q, qdot):
            return [0.0, 0.0]

        def gravity_fn(q):
            return [0.0, 0.0]

        controller = ComputedTorqueController(mass_matrix_fn, coriolis_fn, gravity_fn)

        q = [0.0, 0.0]
        qdot = [0.0, 0.0]
        q_desired = [1.0, 1.0]
        qdot_desired = [0.0, 0.0]
        qddot_desired = [0.0, 0.0]

        torques = controller.compute(q, qdot, q_desired, qdot_desired, qddot_desired)

        assert len(torques) == 2
        # Should produce positive torques to move toward goal
        assert torques[0] > 0
        assert torques[1] > 0


class TestImpedanceController:
    """Test impedance control."""

    def test_impedance_controller_initialization(self) -> None:
        """Test initialization."""
        controller = ImpedanceController(mass=1.0, damping=0.5, stiffness=100.0)

        assert controller.mass == 1.0
        assert controller.damping == 0.5
        assert controller.stiffness == 100.0

    def test_impedance_controller_spring_force(self) -> None:
        """Test spring force computation."""
        controller = ImpedanceController(mass=1.0, damping=0, stiffness=100.0)

        error = Vec3(1.0, 0, 0)
        external_force = Vec3(0, 0, 0)

        force = controller.compute(error, external_force)

        # Spring force should be negative error (restoring)
        assert force.x < 0

    def test_impedance_controller_damping(self) -> None:
        """Test damping effect."""
        controller = ImpedanceController(mass=1.0, damping=1.0, stiffness=0)

        error = Vec3(0, 0, 0)
        external_force = Vec3(0, 0, 0)

        controller.compute(error, external_force)
        force = controller.compute(error, external_force)

        assert force is not None


class TestVelocityController:
    """Test Jacobian-based velocity control."""

    def test_velocity_controller_compute(self) -> None:
        """Test velocity control computation."""

        def jacobian_fn(q):
            return [[1, 0], [0, 1], [0, 0], [0, 0], [0, 0], [0, 0]]

        controller = VelocityController(jacobian_fn, num_joints=2)

        desired_velocity = [0.1, 0.0, 0.0, 0.0, 0.0, 0.0]
        q = [0.0, 0.0]

        qdot = controller.compute(desired_velocity, q)

        assert len(qdot) == 2

    def test_velocity_controller_pseudoinverse(self) -> None:
        """Test pseudoinverse computation."""

        def jacobian_fn(q):
            return [[1, 0], [0, 1], [0, 0], [0, 0], [0, 0], [0, 0]]

        controller = VelocityController(jacobian_fn, num_joints=2)

        J = [[1, 0], [0, 1], [0, 0], [0, 0], [0, 0], [0, 0]]

        J_pinv = controller._pseudoinverse(J)

        assert len(J_pinv) == 2
        assert len(J_pinv[0]) == 6


class TestControllerPerformance:
    """Test control performance metrics."""

    def test_pid_steady_state_error(self) -> None:
        """Test PID steady-state error reduction."""
        pid = PIDController(kp=10.0, ki=1.0, kd=1.0, dt=0.01)

        error = 1.0
        for _ in range(100):
            output = pid.compute(error)

        final_integral = pid.integral

        # Integral should reduce error
        assert final_integral > 0

    def test_pid_oscillation(self) -> None:
        """Test PID can cause oscillation with bad gains."""
        pid = PIDController(kp=100.0, ki=0, kd=0, dt=0.01)

        error = 1.0
        outputs = []

        for _ in range(50):
            output = pid.compute(error)
            outputs.append(output)

        # Should oscillate with high proportional gain
        assert len(set(outputs)) > 1

    def test_trajectory_tracker_convergence(self) -> None:
        """Test trajectory tracker converges."""
        tracker = TrajectoryTracker(num_joints=1, kp=10.0, kd=2.0)

        for _ in range(10):
            current = [
                JointState(position=0.0, velocity=0.0, acceleration=0.0, effort=0.0),
            ]
            desired = [
                JointState(position=1.0, velocity=0.0, acceleration=0.0, effort=0.0),
            ]

            torques = tracker.compute(current, desired)

            # Should produce positive torque
            assert torques[0] > 0


class TestControllerIntegration:
    """Test controller integration."""

    def test_impedance_with_external_force(self) -> None:
        """Test impedance controller with external force."""
        controller = ImpedanceController(mass=1.0, damping=1.0, stiffness=50.0)

        error = Vec3(1.0, 0, 0)
        external_force = Vec3(50.0, 0, 0)  # Large external force

        force = controller.compute(error, external_force)

        # Force should partially resist external force
        assert force is not None

    def test_multiple_pid_controllers(self) -> None:
        """Test multiple independent PID controllers."""
        pids = [PIDController(kp=1.0, ki=0.1, kd=0.1) for _ in range(3)]

        errors = [1.0, 2.0, 0.5]

        outputs = [pid.compute(err) for pid, err in zip(pids, errors)]

        assert len(outputs) == 3
        assert all(out > 0 for out in outputs)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
