"""Tests for planning module."""

from thomas.autonomous_vehicles._types import (
    Obstacle,
    ObstacleType,
    PlannerConfig,
    Vector2D,
    VehicleState,
)
from thomas.autonomous_vehicles.planning import (
    GlobalPlanner,
    LaneChangePlanner,
    LatticeTrajectoryGenerator,
    MotionPlanner,
    Trajectory,
    TrajectoryOptimizer,
    TrajectoryPoint,
)


class TestTrajectoryPoint:
    """Test trajectory point."""

    def test_trajectory_point_to_waypoint(self) -> None:
        """Test conversion to waypoint."""
        point = TrajectoryPoint(x=1.0, y=2.0, theta=0.5, v=5.0, a=0.0, t=0.0)
        waypoint = point.to_waypoint()

        assert waypoint.position.x == 1.0
        assert waypoint.position.y == 2.0
        assert waypoint.heading == 0.5
        assert waypoint.speed_limit == 5.0


class TestTrajectory:
    """Test trajectory."""

    def test_trajectory_length(self) -> None:
        """Test trajectory length computation."""
        points = [
            TrajectoryPoint(x=0.0, y=0.0, theta=0.0, v=1.0, a=0.0, t=0.0),
            TrajectoryPoint(x=1.0, y=0.0, theta=0.0, v=1.0, a=0.0, t=1.0),
            TrajectoryPoint(x=2.0, y=0.0, theta=0.0, v=1.0, a=0.0, t=2.0),
        ]

        trajectory = Trajectory(points=points)
        length = trajectory.length()

        assert length > 0.0
        assert abs(length - 2.0) < 0.1

    def test_trajectory_duration(self) -> None:
        """Test trajectory duration."""
        points = [
            TrajectoryPoint(x=0.0, y=0.0, theta=0.0, v=1.0, a=0.0, t=0.0),
            TrajectoryPoint(x=1.0, y=0.0, theta=0.0, v=1.0, a=0.0, t=1.0),
        ]

        trajectory = Trajectory(points=points)
        duration = trajectory.duration()

        assert duration == 1.0

    def test_trajectory_jerk(self) -> None:
        """Test jerk computation."""
        points = [
            TrajectoryPoint(x=0.0, y=0.0, theta=0.0, v=1.0, a=0.0, t=0.0),
            TrajectoryPoint(x=1.0, y=0.0, theta=0.0, v=1.0, a=1.0, t=0.1),
            TrajectoryPoint(x=2.0, y=0.0, theta=0.0, v=1.0, a=2.0, t=0.2),
        ]

        trajectory = Trajectory(points=points)
        jerk = trajectory.compute_jerk()

        assert jerk >= 0.0


class TestGlobalPlanner:
    """Test global path planner."""

    def test_add_road_segment(self) -> None:
        """Test adding road segments."""
        planner = GlobalPlanner()

        planner.add_road_segment(
            "int_0",
            "int_1",
            Vector2D(0.0, 0.0),
            Vector2D(10.0, 0.0),
        )

        assert "int_0" in planner.road_graph
        assert "int_1" in planner.waypoints_map

    def test_simple_path_planning(self) -> None:
        """Test path planning on simple graph."""
        planner = GlobalPlanner()

        # Create simple road network
        planner.add_road_segment("int_0", "int_1", Vector2D(0.0, 0.0), Vector2D(10.0, 0.0))
        planner.add_road_segment("int_1", "int_2", Vector2D(10.0, 0.0), Vector2D(20.0, 0.0))

        path = planner.plan("int_0", "int_2")

        assert path is not None
        assert len(path.waypoints) == 3

    def test_no_path_exists(self) -> None:
        """Test when no path exists."""
        planner = GlobalPlanner()

        planner.add_road_segment("int_0", "int_1", Vector2D(0.0, 0.0), Vector2D(10.0, 0.0))
        planner.add_road_segment("int_2", "int_3", Vector2D(20.0, 0.0), Vector2D(30.0, 0.0))

        path = planner.plan("int_0", "int_3")

        assert path is None


class TestLatticeTrajectoryGenerator:
    """Test lattice trajectory generator."""

    def test_generate_trajectories(self) -> None:
        """Test trajectory generation."""
        config = PlannerConfig(planning_frequency=10.0)
        generator = LatticeTrajectoryGenerator(config)

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

        trajectories = generator.generate_trajectories(vehicle_state, target_speed=10.0, planning_horizon=5.0)

        assert len(trajectories) > 0
        assert all(len(t.points) > 0 for t in trajectories)

    def test_trajectory_diversity(self) -> None:
        """Test that generated trajectories are diverse."""
        config = PlannerConfig(planning_frequency=10.0)
        generator = LatticeTrajectoryGenerator(config)

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

        trajectories = generator.generate_trajectories(vehicle_state, target_speed=10.0, planning_horizon=2.0)

        # Check that lateral positions vary
        final_lateral_positions = [t.points[-1].y for t in trajectories]
        assert len(set(final_lateral_positions)) > 1


class TestTrajectoryOptimizer:
    """Test trajectory optimizer."""

    def test_optimize_trajectory(self) -> None:
        """Test trajectory optimization."""
        optimizer = TrajectoryOptimizer()

        points = [
            TrajectoryPoint(x=0.0, y=0.0, theta=0.0, v=5.0, a=0.0, t=0.0),
            TrajectoryPoint(x=1.0, y=0.0, theta=0.0, v=5.0, a=0.0, t=0.2),
            TrajectoryPoint(x=2.0, y=0.0, theta=0.0, v=5.0, a=0.0, t=0.4),
        ]

        trajectory = Trajectory(points=points)
        optimized = optimizer.optimize(trajectory, obstacles=[])

        assert optimized.cost >= 0.0

    def test_collision_penalty(self) -> None:
        """Test collision detection penalty."""
        optimizer = TrajectoryOptimizer()

        points = [
            TrajectoryPoint(x=0.0, y=0.0, theta=0.0, v=5.0, a=0.0, t=0.0),
            TrajectoryPoint(x=5.0, y=0.0, theta=0.0, v=5.0, a=0.0, t=1.0),
        ]

        trajectory = Trajectory(points=points)

        # Add obstacle at trajectory position
        obstacle = Obstacle(
            obstacle_id="obs_0",
            position=Vector2D(5.0, 0.0),
            velocity=Vector2D(0.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            obstacle_type=ObstacleType.VEHICLE,
            width=1.8,
            length=4.5,
        )

        optimized_with_collision = optimizer.optimize(trajectory, obstacles=[obstacle])
        optimized_without = optimizer.optimize(trajectory, obstacles=[])

        assert optimized_with_collision.cost > optimized_without.cost


class TestLaneChangePlanner:
    """Test lane change planner."""

    def test_plan_safe_lane_change(self) -> None:
        """Test planning safe lane change."""
        planner = LaneChangePlanner()
        config = PlannerConfig()

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

        # No obstacles, should allow lane change
        trajectory = planner.plan_lane_change(vehicle_state, target_lane_offset=2.0, obstacles=[], config=config)

        assert trajectory is not None
        assert len(trajectory.points) > 0

    def test_unsafe_lane_change(self) -> None:
        """Test rejection of unsafe lane change."""
        planner = LaneChangePlanner()
        config = PlannerConfig()

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

        # Add obstacle in target lane
        obstacle = Obstacle(
            obstacle_id="obs_0",
            position=Vector2D(5.0, 1.2),
            velocity=Vector2D(0.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            obstacle_type=ObstacleType.VEHICLE,
        )

        trajectory = planner.plan_lane_change(
            vehicle_state, target_lane_offset=2.0, obstacles=[obstacle], config=config
        )

        assert trajectory is None


class TestMotionPlanner:
    """Test complete motion planner."""

    def test_plan_motion(self) -> None:
        """Test motion planning."""
        config = PlannerConfig()
        planner = MotionPlanner(config)

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

        trajectory = planner.plan(
            vehicle_state,
            goal_position=Vector2D(100.0, 0.0),
            obstacles=[],
        )

        assert trajectory is not None
        assert len(trajectory.points) > 0

    def test_plan_with_obstacles(self) -> None:
        """Test planning with obstacles."""
        config = PlannerConfig()
        planner = MotionPlanner(config)

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

        obstacle = Obstacle(
            obstacle_id="obs_0",
            position=Vector2D(10.0, 0.0),
            velocity=Vector2D(0.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            obstacle_type=ObstacleType.VEHICLE,
        )

        trajectory = planner.plan(
            vehicle_state,
            goal_position=Vector2D(100.0, 0.0),
            obstacles=[obstacle],
        )

        assert trajectory is not None
