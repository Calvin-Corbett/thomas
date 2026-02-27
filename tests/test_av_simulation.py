"""Tests for simulation module."""

from thomas.autonomous_vehicles._types import (
    ControlCommand,
    Vector2D,
    VehicleState,
)
from thomas.autonomous_vehicles.simulation import (
    CollisionDetector,
    DynamicBicycleModel,
    IntelligentDriverModel,
    KinematicBicycleModel,
    TireModel,
    TrafficSimulator,
    VehicleParams,
    VehicleSimulator,
)


class TestVehicleParams:
    """Test vehicle parameters."""

    def test_default_params(self) -> None:
        """Test default parameters."""
        params = VehicleParams()

        assert params.mass > 0
        assert params.wheelbase > 0
        assert params.track_width > 0


class TestTireModel:
    """Test tire model."""

    def test_lateral_force_computation(self) -> None:
        """Test lateral force computation."""
        tire = TireModel()

        force = tire.lateral_force(slip_angle=0.1, normal_force=5000.0)

        assert force > 0.0

    def test_zero_slip_angle(self) -> None:
        """Test zero slip angle."""
        tire = TireModel()

        force = tire.lateral_force(slip_angle=0.0, normal_force=5000.0)

        assert abs(force) < 100.0


class TestKinematicBicycleModel:
    """Test kinematic bicycle model."""

    def test_straight_motion(self) -> None:
        """Test straight line motion."""
        model = KinematicBicycleModel(VehicleParams())

        state = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(5.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=5.0,
        )

        control = ControlCommand(timestamp=0.0, acceleration=0.0, steering_angle=0.0)

        new_state = model.step(state, control, dt=0.1)

        # Should move forward in x direction
        assert new_state.position.x > state.position.x
        assert abs(new_state.position.y) < 0.01

    def test_acceleration(self) -> None:
        """Test acceleration."""
        model = KinematicBicycleModel(VehicleParams())

        state = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(5.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=5.0,
        )

        control = ControlCommand(timestamp=0.0, acceleration=1.0, steering_angle=0.0)

        new_state = model.step(state, control, dt=0.1)

        assert new_state.speed > state.speed

    def test_steering(self) -> None:
        """Test steering."""
        model = KinematicBicycleModel(VehicleParams())

        state = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(5.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=5.0,
        )

        control = ControlCommand(timestamp=0.0, acceleration=0.0, steering_angle=0.1)

        new_state = model.step(state, control, dt=0.1)

        # Should turn
        assert new_state.heading > state.heading


class TestDynamicBicycleModel:
    """Test dynamic bicycle model."""

    def test_dynamic_model_motion(self) -> None:
        """Test dynamic model produces motion."""
        model = DynamicBicycleModel(VehicleParams())

        state = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(5.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=5.0,
        )

        control = ControlCommand(timestamp=0.0, acceleration=1.0, steering_angle=0.05)

        new_state = model.step(state, control, dt=0.1)

        assert new_state.position.x > state.position.x
        assert new_state.speed > state.speed


class TestIntelligentDriverModel:
    """Test Intelligent Driver Model."""

    def test_idm_free_flow(self) -> None:
        """Test IDM in free flow."""
        idm = IntelligentDriverModel(desired_speed=25.0)

        # No lead vehicle
        acceleration = idm.compute_acceleration(speed=20.0, lead_speed=25.0, gap=100.0)

        assert acceleration > 0.0

    def test_idm_car_following(self) -> None:
        """Test IDM in car following."""
        idm = IntelligentDriverModel(desired_speed=25.0, safe_time_headway=1.5)

        # Lead vehicle at desired spacing
        desired_gap = 25.0 * 1.5
        acceleration = idm.compute_acceleration(speed=25.0, lead_speed=25.0, gap=desired_gap)

        # Should accelerate minimally
        assert abs(acceleration) < 0.5

    def test_idm_emergency_braking(self) -> None:
        """Test IDM emergency braking."""
        idm = IntelligentDriverModel(desired_speed=25.0)

        # Close gap with faster lead vehicle approaching
        acceleration = idm.compute_acceleration(speed=20.0, lead_speed=30.0, gap=5.0)

        assert acceleration < -2.0


class TestCollisionDetector:
    """Test collision detector."""

    def test_collision_detection(self) -> None:
        """Test collision detection."""
        detector = CollisionDetector()

        state1 = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(0.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=0.0,
        )

        state2 = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.5, 0.0),
            velocity=Vector2D(0.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=0.0,
        )

        collision = detector.check_collision(state1, width1=1.8, length1=4.5, state2=state2, width2=1.8, length2=4.5)

        assert collision

    def test_no_collision(self) -> None:
        """Test no collision."""
        detector = CollisionDetector()

        state1 = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(0.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=0.0,
        )

        state2 = VehicleState(
            timestamp=0.0,
            position=Vector2D(100.0, 0.0),
            velocity=Vector2D(0.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=0.0,
        )

        collision = detector.check_collision(state1, width1=1.8, length1=4.5, state2=state2, width2=1.8, length2=4.5)

        assert not collision


class TestVehicleSimulator:
    """Test vehicle simulator."""

    def test_kinematic_simulation(self) -> None:
        """Test kinematic simulation."""
        simulator = VehicleSimulator(use_dynamic_model=False)

        initial_state = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(5.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=5.0,
        )

        controls = [ControlCommand(timestamp=i * 0.1, acceleration=0.0, steering_angle=0.0) for i in range(10)]

        trajectory = simulator.simulate(initial_state, controls, dt=0.1)

        assert len(trajectory) == 11  # Initial + 10 steps
        assert trajectory[-1].position.x > trajectory[0].position.x

    def test_dynamic_simulation(self) -> None:
        """Test dynamic simulation."""
        simulator = VehicleSimulator(use_dynamic_model=True)

        initial_state = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(5.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=5.0,
        )

        controls = [ControlCommand(timestamp=i * 0.1, acceleration=1.0, steering_angle=0.05) for i in range(10)]

        trajectory = simulator.simulate(initial_state, controls, dt=0.1)

        assert len(trajectory) == 11
        assert trajectory[-1].speed > initial_state.speed


class TestTrafficSimulator:
    """Test traffic simulator."""

    def test_add_vehicle(self) -> None:
        """Test adding vehicle to simulation."""
        sim = TrafficSimulator()

        state = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(10.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=10.0,
        )

        sim.add_vehicle("vehicle_0", state)

        assert "vehicle_0" in sim.vehicles

    def test_traffic_simulation_step(self) -> None:
        """Test traffic simulation step."""
        sim = TrafficSimulator()

        state0 = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(10.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=10.0,
        )

        state1 = VehicleState(
            timestamp=0.0,
            position=Vector2D(50.0, 0.0),
            velocity=Vector2D(8.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=8.0,
        )

        sim.add_vehicle("vehicle_0", state0)
        sim.add_vehicle("vehicle_1", state1)

        updated = sim.step(dt=0.1)

        assert len(updated) == 2
        assert updated["vehicle_0"].position.x > state0.position.x

    def test_collision_detection(self) -> None:
        """Test collision detection in traffic."""
        sim = TrafficSimulator()

        state0 = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(10.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=10.0,
        )

        state1 = VehicleState(
            timestamp=0.0,
            position=Vector2D(0.5, 0.0),
            velocity=Vector2D(0.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            heading=0.0,
            heading_rate=0.0,
            steering_angle=0.0,
            speed=0.0,
        )

        sim.add_vehicle("vehicle_0", state0)
        sim.add_vehicle("vehicle_1", state1)

        collisions = sim.check_collisions()

        assert len(collisions) > 0
