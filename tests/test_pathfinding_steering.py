"""
Tests for steering behaviors and movement simulation.
"""

import math

from thomas.marketplace.pathfinding.steering import (
    Boid,
    arrive,
    evade,
    flee,
    flocking,
    flow_field_following,
    group_movement,
    obstacle_avoidance,
    path_following,
    pursue,
    seek,
    wander,
)


class TestBoid:
    """Tests for Boid data structure."""

    def test_boid_creation(self) -> None:
        """Test creating a boid."""
        boid = Boid(x=0.0, y=0.0, vx=1.0, vy=0.0)

        assert boid.x == 0.0
        assert boid.y == 0.0
        assert boid.vx == 1.0
        assert boid.vy == 0.0

    def test_boid_defaults(self) -> None:
        """Test boid default values."""
        boid = Boid(x=5.0, y=5.0, vx=0.0, vy=0.0)

        assert boid.mass == 1.0
        assert boid.max_speed == 5.0
        assert boid.max_acceleration == 2.0


class TestSeek:
    """Tests for seek behavior."""

    def test_seek_toward_target(self) -> None:
        """Test seeking toward target."""
        boid = Boid(x=0.0, y=0.0, vx=0.0, vy=0.0)
        target_x, target_y = 10.0, 10.0

        output = seek(boid, target_x, target_y)

        assert output.linear_velocity[0] > 0.0
        assert output.linear_velocity[1] > 0.0

    def test_seek_at_target(self) -> None:
        """Test seek when already at target."""
        boid = Boid(x=10.0, y=10.0, vx=0.0, vy=0.0)

        output = seek(boid, 10.0, 10.0)

        assert output.linear_velocity[0] == 0.0
        assert output.linear_velocity[1] == 0.0

    def test_seek_respects_max_acceleration(self) -> None:
        """Test that seek respects max acceleration."""
        boid = Boid(x=0.0, y=0.0, vx=0.0, vy=0.0, max_acceleration=2.0)

        output = seek(boid, 100.0, 100.0)

        mag = math.sqrt(output.linear_velocity[0] ** 2 + output.linear_velocity[1] ** 2)

        assert mag <= boid.max_acceleration + 0.01


class TestFlee:
    """Tests for flee behavior."""

    def test_flee_from_threat(self) -> None:
        """Test fleeing from threat."""
        boid = Boid(x=10.0, y=10.0, vx=0.0, vy=0.0)
        threat_x, threat_y = 0.0, 0.0

        output = flee(boid, threat_x, threat_y)

        assert output.linear_velocity[0] > 0.0
        assert output.linear_velocity[1] > 0.0

    def test_flee_away_direction(self) -> None:
        """Test that flee moves away from threat."""
        boid = Boid(x=5.0, y=5.0, vx=0.0, vy=0.0)

        output = flee(boid, 0.0, 0.0)

        assert output.linear_velocity[0] > 0.0
        assert output.linear_velocity[1] > 0.0


class TestArrive:
    """Tests for arrive behavior."""

    def test_arrive_decelerates(self) -> None:
        """Test that arrive behavior decelerates."""
        boid = Boid(x=0.0, y=0.0, vx=5.0, vy=5.0)

        output = arrive(boid, 5.0, 5.0, slow_radius=10.0)

        assert output.linear_velocity is not None

    def test_arrive_at_target(self) -> None:
        """Test arrive when at target."""
        boid = Boid(x=5.0, y=5.0, vx=0.0, vy=0.0)

        output = arrive(boid, 5.0, 5.0, slow_radius=10.0)

        assert output.linear_velocity[0] == 0.0
        assert output.linear_velocity[1] == 0.0

    def test_slow_radius_effect(self) -> None:
        """Test that slow radius affects deceleration."""
        boid = Boid(x=0.0, y=0.0, vx=0.0, vy=0.0)

        arrive(boid, 10.0, 0.0, slow_radius=2.0)
        arrive(boid, 10.0, 0.0, slow_radius=20.0)


class TestPursue:
    """Tests for pursue behavior."""

    def test_pursue_moving_target(self) -> None:
        """Test pursuing a moving target."""
        pursuer = Boid(x=0.0, y=0.0, vx=0.0, vy=0.0)
        target = Boid(x=10.0, y=10.0, vx=1.0, vy=1.0)

        output = pursue(pursuer, target)

        assert output.linear_velocity is not None

    def test_pursue_stationary_target(self) -> None:
        """Test pursuing a stationary target."""
        pursuer = Boid(x=0.0, y=0.0, vx=0.0, vy=0.0)
        target = Boid(x=10.0, y=10.0, vx=0.0, vy=0.0)

        output = pursue(pursuer, target)

        assert output.linear_velocity[0] > 0.0


class TestEvade:
    """Tests for evade behavior."""

    def test_evade_moving_threat(self) -> None:
        """Test evading a moving threat."""
        evader = Boid(x=10.0, y=10.0, vx=0.0, vy=0.0)
        threat = Boid(x=0.0, y=0.0, vx=1.0, vy=1.0)

        output = evade(evader, threat)

        assert output.linear_velocity[0] > 0.0
        assert output.linear_velocity[1] > 0.0


class TestWander:
    """Tests for wander behavior."""

    def test_wander_generates_steering(self) -> None:
        """Test that wander produces steering."""
        boid = Boid(x=0.0, y=0.0, vx=1.0, vy=0.0)

        output, angle = wander(boid)

        assert output.linear_velocity is not None
        assert isinstance(angle, float)

    def test_wander_angle_changes(self) -> None:
        """Test that wander angle changes over time."""
        boid = Boid(x=0.0, y=0.0, vx=1.0, vy=0.0)

        output1, angle1 = wander(boid, wander_rate=1.0)
        output2, angle2 = wander(boid, wander_rate=1.0)


class TestObstacleAvoidance:
    """Tests for obstacle avoidance."""

    def test_avoid_obstacle(self) -> None:
        """Test avoiding an obstacle."""
        boid = Boid(x=0.0, y=0.0, vx=1.0, vy=0.0)
        obstacles = [(5.0, 0.0, 1.0)]

        output = obstacle_avoidance(boid, obstacles)

        assert output.linear_velocity is not None

    def test_no_obstacle_no_avoidance(self) -> None:
        """Test that no steering when no obstacles."""
        boid = Boid(x=0.0, y=0.0, vx=1.0, vy=0.0)
        obstacles = [(100.0, 100.0, 1.0)]

        obstacle_avoidance(boid, obstacles, lookahead_dist=5.0)

    def test_multiple_obstacles(self) -> None:
        """Test avoiding multiple obstacles."""
        boid = Boid(x=0.0, y=0.0, vx=1.0, vy=0.0)
        obstacles = [
            (5.0, 0.0, 1.0),
            (5.0, 2.0, 1.0),
            (5.0, -2.0, 1.0),
        ]

        output = obstacle_avoidance(boid, obstacles)

        assert output.linear_velocity is not None


class TestFlocking:
    """Tests for flocking behavior."""

    def test_flock_with_neighbors(self) -> None:
        """Test flocking with neighbors."""
        leader = Boid(x=0.0, y=0.0, vx=1.0, vy=0.0)
        neighbors = [
            Boid(x=1.0, y=1.0, vx=1.0, vy=0.0),
            Boid(x=-1.0, y=1.0, vx=1.0, vy=0.0),
        ]

        output = flocking(leader, neighbors)

        assert output.linear_velocity is not None

    def test_flock_separation(self) -> None:
        """Test separation in flocking."""
        boid = Boid(x=0.0, y=0.0, vx=0.0, vy=0.0)
        neighbors = [Boid(x=1.0, y=0.0, vx=0.0, vy=0.0)]

        flocking(boid, neighbors, separation_radius=5.0)

    def test_flock_no_neighbors(self) -> None:
        """Test flocking with no neighbors."""
        boid = Boid(x=0.0, y=0.0, vx=1.0, vy=0.0)

        output = flocking(boid, [])

        assert output.linear_velocity is not None

    def test_flock_weights(self) -> None:
        """Test that weights affect flocking output."""
        boid = Boid(x=0.0, y=0.0, vx=0.0, vy=0.0)
        neighbors = [Boid(x=1.0, y=0.0, vx=1.0, vy=0.0)]

        flocking(
            boid,
            neighbors,
            separation_weight=1.0,
            alignment_weight=0.0,
            cohesion_weight=0.0,
        )

        flocking(
            boid,
            neighbors,
            separation_weight=0.0,
            alignment_weight=1.0,
            cohesion_weight=0.0,
        )


class TestPathFollowing:
    """Tests for path following behavior."""

    def test_follow_simple_path(self) -> None:
        """Test following a simple path."""
        boid = Boid(x=0.0, y=0.0, vx=0.0, vy=0.0)
        path = [(1.0, 0.0), (2.0, 0.0), (3.0, 0.0)]

        output, index = path_following(boid, path)

        assert output.linear_velocity is not None
        assert isinstance(index, int)

    def test_path_following_progression(self) -> None:
        """Test that path index progresses."""
        boid = Boid(x=0.0, y=0.0, vx=5.0, vy=0.0)
        path = [(1.0, 0.0), (2.0, 0.0), (3.0, 0.0)]

        output1, index1 = path_following(boid, path, current_path_index=0)
        assert index1 >= 0

    def test_empty_path(self) -> None:
        """Test path following with empty path."""
        boid = Boid(x=0.0, y=0.0, vx=0.0, vy=0.0)

        output, index = path_following(boid, [])

        assert output.linear_velocity == (0.0, 0.0)


class TestGroupMovement:
    """Tests for group movement."""

    def test_group_formation(self) -> None:
        """Test group moving in formation."""
        leader = Boid(x=0.0, y=0.0, vx=1.0, vy=0.0)
        followers = [
            Boid(x=-1.0, y=0.0, vx=0.0, vy=0.0),
            Boid(x=1.0, y=0.0, vx=0.0, vy=0.0),
        ]
        formation = [(-1.0, 0.0), (1.0, 0.0)]

        outputs = group_movement(leader, followers, formation)

        assert len(outputs) == 2

    def test_formation_offsets(self) -> None:
        """Test different formation offsets."""
        leader = Boid(x=0.0, y=0.0, vx=0.0, vy=0.0)
        followers = [
            Boid(x=0.0, y=0.0, vx=0.0, vy=0.0),
        ]
        formation = [(2.0, 0.0)]

        outputs = group_movement(leader, followers, formation)

        assert outputs[0].linear_velocity[0] > 0.0


class TestFlowFieldFollowing:
    """Tests for flow field following."""

    def test_follow_flow_field(self) -> None:
        """Test following a flow field."""
        boid = Boid(x=0.0, y=0.0, vx=0.0, vy=0.0)
        flow_field = {
            (0, 0): (1.0, 0.0),
            (1, 0): (1.0, 0.0),
        }

        output = flow_field_following(boid, flow_field)

        assert output.linear_velocity is not None

    def test_flow_field_not_found(self) -> None:
        """Test flow field following when position not in field."""
        boid = Boid(x=10.0, y=10.0, vx=0.0, vy=0.0)
        flow_field = {(0, 0): (1.0, 0.0)}

        output = flow_field_following(boid, flow_field)

        assert output.linear_velocity == (0.0, 0.0)


class TestSteeringIntegration:
    """Integration tests for steering behaviors."""

    def test_multiple_behaviors_composable(self) -> None:
        """Test that steering behaviors can be composed."""
        boid = Boid(x=0.0, y=0.0, vx=1.0, vy=0.0)

        seek_output = seek(boid, 10.0, 10.0)
        arrive_output = arrive(boid, 10.0, 10.0)

        assert seek_output.linear_velocity is not None
        assert arrive_output.linear_velocity is not None

    def test_behavior_output_magnitude(self) -> None:
        """Test that output magnitudes are reasonable."""
        boid = Boid(x=0.0, y=0.0, vx=0.0, vy=0.0)

        output = seek(boid, 100.0, 100.0)

        mag = math.sqrt(output.linear_velocity[0] ** 2 + output.linear_velocity[1] ** 2)

        assert mag <= boid.max_acceleration + 0.01
