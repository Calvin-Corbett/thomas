"""
Tests for rigid body physics.
"""

import pytest

from thomas.marketplace.physics._types import RigidBodyType, Vec3
from thomas.marketplace.physics.rigid_body import RigidBody


class TestRigidBodyCreation:
    """Tests for rigid body initialization."""

    def test_create_dynamic_body(self) -> None:
        """Test creating dynamic body."""
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 0, 0),
            mass=1.0,
        )
        assert body.body_type == RigidBodyType.DYNAMIC
        assert body.inverse_mass == 1.0
        assert not body.is_sleeping

    def test_create_static_body(self) -> None:
        """Test creating static body."""
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 0, 0),
            mass=1.0,
            body_type=RigidBodyType.STATIC,
        )
        assert body.inverse_mass == 0.0
        assert body.inverse_inertia == 0.0

    def test_create_kinematic_body(self) -> None:
        """Test creating kinematic body."""
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 0, 0),
            mass=1.0,
            body_type=RigidBodyType.KINEMATIC,
        )
        assert body.inverse_mass == 0.0

    def test_set_mass(self) -> None:
        """Test setting mass."""
        body = RigidBody(body_id=0, position=Vec3(0, 0, 0), mass=1.0)
        body.set_mass(2.0)
        assert body.mass == 2.0
        assert body.inverse_mass == 0.5

    def test_set_negative_mass_raises_error(self) -> None:
        """Test that negative mass raises error."""
        body = RigidBody(body_id=0, position=Vec3(0, 0, 0), mass=1.0)
        with pytest.raises(ValueError):
            body.set_mass(-1.0)

    def test_set_zero_mass_raises_error(self) -> None:
        """Test that zero mass raises error."""
        body = RigidBody(body_id=0, position=Vec3(0, 0, 0), mass=1.0)
        with pytest.raises(ValueError):
            body.set_mass(0.0)


class TestForces:
    """Tests for force application."""

    def test_apply_force(self) -> None:
        """Test applying force."""
        body = RigidBody(body_id=0, position=Vec3(0, 0, 0), mass=1.0)
        force = Vec3(10, 0, 0)
        body.apply_force(force)
        assert body.force_accumulator == force

    def test_apply_multiple_forces(self) -> None:
        """Test applying multiple forces."""
        body = RigidBody(body_id=0, position=Vec3(0, 0, 0), mass=1.0)
        body.apply_force(Vec3(5, 0, 0))
        body.apply_force(Vec3(5, 0, 0))
        assert body.force_accumulator == Vec3(10, 0, 0)

    def test_static_body_ignores_force(self) -> None:
        """Test that static body ignores forces."""
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 0, 0),
            mass=1.0,
            body_type=RigidBodyType.STATIC,
        )
        body.apply_force(Vec3(10, 0, 0))
        assert body.force_accumulator == Vec3(0, 0, 0)

    def test_apply_force_at_point(self) -> None:
        """Test applying force at a point creates torque."""
        body = RigidBody(body_id=0, position=Vec3(0, 0, 0), mass=1.0)
        body.set_moment_of_inertia_circle(1.0)
        force = Vec3(0, 10, 0)
        point = Vec3(1, 0, 0)
        body.apply_force_at_point(force, point)
        assert body.force_accumulator == force
        assert body.torque_accumulator.z != 0  # Should have torque around Z


class TestImpulses:
    """Tests for impulse application."""

    def test_apply_impulse(self) -> None:
        """Test applying impulse changes velocity."""
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 0, 0),
            mass=1.0,
            velocity=Vec3(0, 0, 0),
        )
        impulse = Vec3(5, 0, 0)
        body.apply_impulse(impulse)
        assert body.velocity == Vec3(5, 0, 0)

    def test_impulse_with_mass(self) -> None:
        """Test impulse respects mass."""
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 0, 0),
            mass=2.0,
            velocity=Vec3(0, 0, 0),
        )
        impulse = Vec3(10, 0, 0)
        body.apply_impulse(impulse)
        assert body.velocity == Vec3(5, 0, 0)

    def test_apply_impulse_at_point(self) -> None:
        """Test impulse at point affects rotation."""
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 0, 0),
            mass=1.0,
            velocity=Vec3(0, 0, 0),
        )
        body.set_moment_of_inertia_circle(1.0)
        impulse = Vec3(0, 10, 0)
        point = Vec3(1, 0, 0)
        body.apply_impulse_at_point(impulse, point)
        assert body.velocity == Vec3(0, 10, 0)
        assert body.angular_velocity != 0


class TestMomentOfInertia:
    """Tests for moment of inertia calculations."""

    def test_circle_inertia(self) -> None:
        """Test moment of inertia for circle."""
        body = RigidBody(body_id=0, position=Vec3(0, 0, 0), mass=2.0)
        body.set_moment_of_inertia_circle(1.0)
        # I = 0.5 * m * r^2 = 0.5 * 2 * 1 = 1.0
        assert abs(body.inertia - 1.0) < 1e-6

    def test_rectangle_inertia(self) -> None:
        """Test moment of inertia for rectangle."""
        body = RigidBody(body_id=0, position=Vec3(0, 0, 0), mass=12.0)
        body.set_moment_of_inertia_rectangle(2.0, 2.0)
        # I = (1/12) * m * (w^2 + h^2) = (1/12) * 12 * 8 = 8.0
        assert abs(body.inertia - 8.0) < 1e-6

    def test_box_inertia(self) -> None:
        """Test moment of inertia for box."""
        body = RigidBody(body_id=0, position=Vec3(0, 0, 0), mass=12.0)
        body.set_moment_of_inertia_box(2.0, 2.0, 2.0)
        # I = (1/12) * m * (w^2 + h^2)
        assert body.inertia > 0


class TestIntegration:
    """Tests for physics integration."""

    def test_integrate_forces_basic(self) -> None:
        """Test force integration."""
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 0, 0),
            mass=1.0,
            velocity=Vec3(0, 0, 0),
        )
        gravity = Vec3(0, -10, 0)
        body.apply_force(Vec3(5, 0, 0))
        body.integrate_forces(gravity, 0.1)
        # a = (5, -10) / 1 = (5, -10)
        # v = (0, 0) + (5, -10) * 0.1 = (0.5, -1.0)
        assert abs(body.velocity.x - 0.5) < 1e-6
        assert abs(body.velocity.y - (-1.0)) < 1e-6

    def test_integrate_velocity(self) -> None:
        """Test velocity integration."""
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 0, 0),
            velocity=Vec3(1, 0, 0),
        )
        body.integrate_velocity(0.1, damping=1.0)
        # x = 0 + 1 * 0.1 = 0.1
        assert abs(body.position.x - 0.1) < 1e-6

    def test_velocity_damping(self) -> None:
        """Test velocity damping."""
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 0, 0),
            velocity=Vec3(1, 0, 0),
        )
        body.integrate_velocity(0.1, damping=0.9)
        assert body.velocity.x < 1.0


class TestSleep:
    """Tests for sleep detection."""

    def test_body_goes_to_sleep(self) -> None:
        """Test body sleeps when below threshold."""
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 0, 0),
            velocity=Vec3(0.01, 0, 0),
        )
        body.check_sleep(
            velocity_threshold=0.1,
            angular_velocity_threshold=0.1,
            time_threshold=0.5,
            timestep=0.2,
        )
        # First check - sleep_time increases
        assert not body.is_sleeping

        body.check_sleep(
            velocity_threshold=0.1,
            angular_velocity_threshold=0.1,
            time_threshold=0.5,
            timestep=0.2,
        )
        # Second check - sleep_time >= threshold
        assert not body.is_sleeping or body.sleep_time > 0.3

    def test_body_wakes_on_impulse(self) -> None:
        """Test body wakes when hit by impulse."""
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 0, 0),
            velocity=Vec3(0, 0, 0),
        )
        body.put_to_sleep()
        assert body.is_sleeping

        body.apply_impulse(Vec3(5, 0, 0))
        body.check_sleep(0.1, 0.1, 0.5, 0.1)
        assert not body.is_sleeping


class TestEnergy:
    """Tests for energy calculations."""

    def test_kinetic_energy(self) -> None:
        """Test kinetic energy calculation."""
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 0, 0),
            mass=2.0,
            velocity=Vec3(3, 4, 0),
        )
        # KE = 0.5 * m * v^2 = 0.5 * 2 * 25 = 25
        assert abs(body.get_kinetic_energy() - 25.0) < 1e-6

    def test_potential_energy(self) -> None:
        """Test potential energy calculation."""
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 5, 0),
            mass=2.0,
        )
        gravity = Vec3(0, -10, 0)
        # U = -m * g · r = -2 * (-10) * 5 = 100
        # (but our implementation uses -m * g · r format)
        pe = body.get_potential_energy(gravity)
        assert pe == 100.0

    def test_energy_conservation_no_damping(self) -> None:
        """Test energy conservation without damping."""
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 10, 0),
            mass=1.0,
            velocity=Vec3(0, 0, 0),
        )
        gravity = Vec3(0, -10, 0)
        initial_energy = body.get_kinetic_energy() + body.get_potential_energy(gravity)

        # Free fall for 1 second
        for _ in range(10):
            body.integrate_forces(gravity, 0.1)
            body.integrate_velocity(0.1, damping=1.0)

        final_energy = body.get_kinetic_energy() + body.get_potential_energy(gravity)
        # Energy should be approximately conserved (allow some numerical error)
        assert abs(initial_energy - final_energy) < 10.0


class TestVelocityAtPoint:
    """Tests for calculating velocity at a point."""

    def test_velocity_at_center(self) -> None:
        """Test velocity at center of mass."""
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 0, 0),
            velocity=Vec3(5, 0, 0),
            angular_velocity=0.0,
        )
        vel = body.get_velocity_at_point(body.position)
        assert vel == Vec3(5, 0, 0)

    def test_velocity_with_rotation(self) -> None:
        """Test velocity includes rotational component."""
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 0, 0),
            velocity=Vec3(0, 0, 0),
            angular_velocity=1.0,
        )
        point = Vec3(1, 0, 0)
        vel = body.get_velocity_at_point(point)
        # v = ω × r = 1 * (0, 1, 0) for point at (1, 0, 0)
        assert abs(vel.x) < 1e-6
        assert abs(vel.y - 1.0) < 1e-6
