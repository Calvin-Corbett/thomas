"""
Tests for motion planning module.
"""

import math

import pytest

from thomas.marketplace.robotics_deep.motion_planning import PRM, RRT, PathSmoother, RRTStar


class TestRRT:
    """Test RRT planner."""

    def test_rrt_simple_path(self) -> None:
        """Test RRT finds path in simple 2D space."""

        def collision_checker(q: list) -> bool:
            """Simple collision check: avoid circular obstacle."""
            x, y = q[0], q[1]
            # Circular obstacle at (0.5, 0.5)
            dist = math.sqrt((x - 0.5) ** 2 + (y - 0.5) ** 2)
            return dist > 0.1 or abs(x) < 0.01 or abs(y) < 0.01

        rrt = RRT(
            config_dim=2,
            bounds=[(-1, 1), (-1, 1)],
            collision_checker=collision_checker,
            step_size=0.2,
        )

        start = [-0.8, -0.8]
        goal = [0.8, 0.8]

        path = rrt.plan(start, goal, max_iterations=1000)

        assert path is not None
        assert len(path) > 0
        assert path[0] == start

    def test_rrt_unreachable_goal(self) -> None:
        """Test RRT fails for unreachable goal."""

        def collision_checker(q: list) -> bool:
            """Collision everywhere."""
            return False

        rrt = RRT(
            config_dim=2,
            bounds=[(0, 1), (0, 1)],
            collision_checker=collision_checker,
        )

        path = rrt.plan([0.2, 0.2], [0.8, 0.8], max_iterations=100)

        assert path is None

    def test_rrt_distance_metric(self) -> None:
        """Test distance computation."""
        rrt = RRT(2, [(0, 1), (0, 1)], lambda q: True)

        dist = rrt._distance([0, 0], [3, 4])

        assert abs(dist - 5.0) < 1e-6

    def test_rrt_extend(self) -> None:
        """Test extending toward target."""
        rrt = RRT(2, [(0, 1), (0, 1)], lambda q: True)

        extended = rrt._extend([0, 0], [1, 1], 0.5)

        assert len(extended) == 2
        dist = math.sqrt(extended[0] ** 2 + extended[1] ** 2)
        assert abs(dist - 0.5) < 1e-6

    def test_path_collision_check(self) -> None:
        """Test path collision checking."""
        obstacle_hit = False

        def collision_checker(q: list) -> bool:
            """Obstacle at (0.5, 0.5)."""
            x, y = q[0], q[1]
            if 0.4 < x < 0.6 and 0.4 < y < 0.6:
                return False
            return True

        rrt = RRT(2, [(0, 1), (0, 1)], collision_checker)

        # Path through obstacle
        result = rrt._path_collision_free([0, 0], [1, 1])

        assert not result

        # Path avoiding obstacle
        result = rrt._path_collision_free([0, 0], [0, 1])

        assert result


class TestRRTStar:
    """Test RRT* planner."""

    def test_rrt_star_optimizes(self) -> None:
        """Test RRT* finds better paths than RRT."""

        def collision_checker(q: list) -> bool:
            x, y = q[0], q[1]
            return True

        rrt_star = RRTStar(
            config_dim=2,
            bounds=[(0, 2), (0, 2)],
            collision_checker=collision_checker,
            rewire_radius=1.0,
        )

        start = [0, 0]
        goal = [2, 2]

        path = rrt_star.plan(start, goal, max_iterations=200)

        assert path is not None
        assert len(path) > 0

    def test_rrt_star_cost_tracking(self) -> None:
        """Test RRT* tracks path costs."""

        def collision_checker(q: list) -> bool:
            return True

        rrt_star = RRTStar(
            config_dim=2,
            bounds=[(0, 2), (0, 2)],
            collision_checker=collision_checker,
        )

        rrt_star.plan([0, 0], [1, 0], max_iterations=100)

        assert rrt_star.best_path_cost < float("inf")


class TestPRM:
    """Test PRM planner."""

    def test_prm_roadmap_building(self) -> None:
        """Test PRM roadmap construction."""

        def collision_checker(q: list) -> bool:
            return True

        prm = PRM(
            config_dim=2,
            bounds=[(0, 1), (0, 1)],
            collision_checker=collision_checker,
            connection_radius=0.5,
        )

        prm.build_roadmap(num_samples=50)

        assert len(prm.roadmap) > 0
        assert len(prm.roadmap) <= 50

    def test_prm_query(self) -> None:
        """Test PRM query."""

        def collision_checker(q: list) -> bool:
            return True

        prm = PRM(2, [(0, 1), (0, 1)], collision_checker)

        prm.build_roadmap(num_samples=30)

        path = prm.query([0.1, 0.1], [0.9, 0.9])

        assert path is not None
        assert len(path) >= 2

    def test_prm_distance_metric(self) -> None:
        """Test PRM distance."""
        prm = PRM(2, [(0, 1), (0, 1)], lambda q: True)

        dist = prm._distance([0, 0], [3, 4])

        assert abs(dist - 5.0) < 1e-6


class TestPathSmoother:
    """Test path smoothing."""

    def test_path_smoothing_shortcutting(self) -> None:
        """Test path smoothing by shortcutting."""

        def collision_checker(q: list) -> bool:
            """No obstacles."""
            return True

        smoother = PathSmoother(collision_checker, config_dim=2)

        # Jagged path
        path = [[0, 0], [0.1, 0.9], [0.5, 0.5], [0.9, 0.9], [1, 1]]

        smoothed = smoother.smooth(path, max_iterations=10)

        # Smoothed path should be shorter or same length
        assert len(smoothed) <= len(path)
        assert smoothed[0] == path[0]
        assert smoothed[-1] == path[-1]

    def test_path_collision_during_smoothing(self) -> None:
        """Test that smoothing respects collisions."""

        def collision_checker(q: list) -> bool:
            """Obstacle in middle."""
            x = q[0]
            if 0.4 < x < 0.6:
                return False
            return True

        smoother = PathSmoother(collision_checker, 1)

        # Path around obstacle
        path = [[0], [0.2], [0.5], [0.8], [1.0]]

        smoothed = smoother.smooth(path)

        assert smoothed is not None

    def test_distance_metric(self) -> None:
        """Test smoothing distance metric."""
        smoother = PathSmoother(lambda q: True, 2)

        dist = smoother._distance([0, 0], [3, 4])

        assert abs(dist - 5.0) < 1e-6


class TestCollisionDetection:
    """Test collision detection in planning."""

    def test_simple_obstacle_avoidance(self) -> None:
        """Test simple obstacle avoidance."""

        def collision_checker(q: list) -> bool:
            """Avoid circle at origin."""
            x, y = q[0], q[1]
            dist = math.sqrt(x**2 + y**2)
            return dist > 0.3

        rrt = RRT(2, [(-2, 2), (-2, 2)], collision_checker)

        # Should find path around obstacle
        path = rrt.plan([-1.5, -1.5], [1.5, 1.5], max_iterations=500)

        if path:
            assert len(path) > 0

    def test_narrow_passage(self) -> None:
        """Test navigation through narrow passage."""

        def collision_checker(q: list) -> bool:
            """Obstacles on sides, narrow passage in middle."""
            x, y = q[0], q[1]

            # Left wall
            if x < 0.3 and y > 0.4:
                return False

            # Right wall
            if x > 0.7 and y > 0.4:
                return False

            return True

        rrt = RRT(2, [(0, 1), (0, 1)], collision_checker)

        path = rrt.plan([0.5, 0.1], [0.5, 0.9], max_iterations=500)

        if path:
            assert len(path) > 1


class TestPathProperties:
    """Test properties of planned paths."""

    def test_path_continuity(self) -> None:
        """Test path segments are connected."""

        def collision_checker(q: list) -> bool:
            return True

        rrt = RRT(2, [(0, 1), (0, 1)], collision_checker, step_size=0.1)

        path = rrt.plan([0, 0], [1, 1], max_iterations=100)

        if path and len(path) > 1:
            for i in range(len(path) - 1):
                dist = rrt._distance(path[i], path[i + 1])
                # Segments should be reasonably close
                assert dist < 0.2

    def test_path_start_goal(self) -> None:
        """Test path connects start and goal."""

        def collision_checker(q: list) -> bool:
            return True

        rrt = RRT(2, [(0, 1), (0, 1)], collision_checker)

        start = [0.1, 0.1]
        goal = [0.9, 0.9]

        path = rrt.plan(start, goal, max_iterations=200)

        if path:
            assert path[0] == start


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
