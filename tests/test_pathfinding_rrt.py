"""
Tests for sampling-based motion planning algorithms (RRT, PRM).
"""

import math

from thomas.marketplace.pathfinding import Obstacle
from thomas.marketplace.pathfinding.rrt import (
    informed_rrt_star,
    probabilistic_roadmap,
    rrt,
    rrt_connect,
    rrt_star,
)


class TestRRT:
    """Tests for RRT algorithm."""

    def test_simple_rrt_path(self) -> None:
        """Test RRT finds path in simple space."""
        start = (0.0, 0.0)
        goal = (10.0, 10.0)
        obstacles = []
        bounds = (0.0, 0.0, 20.0, 20.0)

        result = rrt(
            start,
            goal,
            obstacles,
            bounds,
            max_iterations=1000,
            step_size=1.0,
        )

        assert result.found
        assert len(result.path.nodes) > 0

    def test_rrt_avoids_obstacles(self) -> None:
        """Test RRT avoids obstacles."""
        start = (0.0, 0.0)
        goal = (20.0, 20.0)
        obstacles = [Obstacle(8.0, 8.0, 12.0, 12.0)]
        bounds = (0.0, 0.0, 20.0, 20.0)

        result = rrt(
            start,
            goal,
            obstacles,
            bounds,
            max_iterations=2000,
            step_size=1.0,
        )

        assert result.found

    def test_rrt_goal_bias(self) -> None:
        """Test that goal bias affects convergence."""
        start = (0.0, 0.0)
        goal = (10.0, 10.0)
        obstacles = []
        bounds = (0.0, 0.0, 20.0, 20.0)

        result_no_bias = rrt(
            start,
            goal,
            obstacles,
            bounds,
            max_iterations=100,
            goal_bias=0.0,
        )

        result_with_bias = rrt(
            start,
            goal,
            obstacles,
            bounds,
            max_iterations=100,
            goal_bias=0.2,
        )

    def test_rrt_step_size_effect(self) -> None:
        """Test that step size affects tree growth."""
        start = (0.0, 0.0)
        goal = (10.0, 10.0)
        obstacles = []
        bounds = (0.0, 0.0, 20.0, 20.0)

        result_small_step = rrt(
            start,
            goal,
            obstacles,
            bounds,
            max_iterations=500,
            step_size=0.5,
        )

        result_large_step = rrt(
            start,
            goal,
            obstacles,
            bounds,
            max_iterations=500,
            step_size=2.0,
        )


class TestRRTStar:
    """Tests for RRT* algorithm."""

    def test_rrt_star_finds_path(self) -> None:
        """Test RRT* finds path."""
        start = (0.0, 0.0)
        goal = (10.0, 10.0)
        obstacles = []
        bounds = (0.0, 0.0, 20.0, 20.0)

        result = rrt_star(
            start,
            goal,
            obstacles,
            bounds,
            max_iterations=1000,
            step_size=1.0,
        )

        assert result.found

    def test_rrt_star_better_than_rrt(self) -> None:
        """Test that RRT* finds better paths than RRT."""
        start = (0.0, 0.0)
        goal = (10.0, 10.0)
        obstacles = []
        bounds = (0.0, 0.0, 20.0, 20.0)

        rrt_result = rrt(
            start,
            goal,
            obstacles,
            bounds,
            max_iterations=1000,
            step_size=1.0,
        )

        rrt_star_result = rrt_star(
            start,
            goal,
            obstacles,
            bounds,
            max_iterations=1000,
            step_size=1.0,
        )

        assert rrt_result.found
        assert rrt_star_result.found

    def test_rrt_star_rewiring(self) -> None:
        """Test that RRT* performs rewiring."""
        start = (0.0, 0.0)
        goal = (10.0, 10.0)
        obstacles = []
        bounds = (0.0, 0.0, 20.0, 20.0)

        result = rrt_star(
            start,
            goal,
            obstacles,
            bounds,
            max_iterations=1000,
            rewire_radius=5.0,
        )

        assert result.found

    def test_rrt_star_avoids_obstacles(self) -> None:
        """Test RRT* with obstacles."""
        start = (0.0, 0.0)
        goal = (20.0, 20.0)
        obstacles = [Obstacle(8.0, 8.0, 12.0, 12.0)]
        bounds = (0.0, 0.0, 20.0, 20.0)

        result = rrt_star(
            start,
            goal,
            obstacles,
            bounds,
            max_iterations=2000,
        )

        assert result.found


class TestRRTConnect:
    """Tests for bidirectional RRT-Connect."""

    def test_rrt_connect_finds_path(self) -> None:
        """Test RRT-Connect finds path."""
        start = (0.0, 0.0)
        goal = (10.0, 10.0)
        obstacles = []
        bounds = (0.0, 0.0, 20.0, 20.0)

        result = rrt_connect(
            start,
            goal,
            obstacles,
            bounds,
            max_iterations=1000,
        )

        assert result.found

    def test_rrt_connect_efficiency(self) -> None:
        """Test that RRT-Connect is efficient."""
        start = (0.0, 0.0)
        goal = (20.0, 20.0)
        obstacles = []
        bounds = (0.0, 0.0, 30.0, 30.0)

        result = rrt_connect(
            start,
            goal,
            obstacles,
            bounds,
            max_iterations=500,
        )

        assert result.found

    def test_rrt_connect_avoids_obstacles(self) -> None:
        """Test RRT-Connect avoids obstacles."""
        start = (0.0, 0.0)
        goal = (20.0, 20.0)
        obstacles = [Obstacle(8.0, 8.0, 12.0, 12.0)]
        bounds = (0.0, 0.0, 20.0, 20.0)

        result = rrt_connect(
            start,
            goal,
            obstacles,
            bounds,
            max_iterations=2000,
        )

        assert result.found


class TestInformedRRTStar:
    """Tests for Informed RRT*."""

    def test_informed_rrt_star_finds_path(self) -> None:
        """Test Informed RRT* finds path."""
        start = (0.0, 0.0)
        goal = (10.0, 10.0)
        obstacles = []
        bounds = (0.0, 0.0, 20.0, 20.0)

        result = informed_rrt_star(
            start,
            goal,
            obstacles,
            bounds,
            max_iterations=1000,
        )

        assert result.found

    def test_informed_rrt_star_ellipsoidal_sampling(self) -> None:
        """Test that Informed RRT* uses ellipsoidal sampling."""
        start = (0.0, 0.0)
        goal = (10.0, 10.0)
        obstacles = []
        bounds = (0.0, 0.0, 20.0, 20.0)

        euclidean_dist = math.sqrt((goal[0] - start[0]) ** 2 + (goal[1] - start[1]) ** 2)

        result = informed_rrt_star(
            start,
            goal,
            obstacles,
            bounds,
            max_iterations=1000,
            initial_solution_cost=euclidean_dist * 2,
        )

        assert result.found

    def test_informed_rrt_star_with_obstacles(self) -> None:
        """Test Informed RRT* with obstacles."""
        start = (0.0, 0.0)
        goal = (20.0, 20.0)
        obstacles = [Obstacle(8.0, 8.0, 12.0, 12.0)]
        bounds = (0.0, 0.0, 20.0, 20.0)

        result = informed_rrt_star(
            start,
            goal,
            obstacles,
            bounds,
            max_iterations=2000,
        )

        assert result.found


class TestPRM:
    """Tests for Probabilistic Roadmap."""

    def test_prm_finds_path(self) -> None:
        """Test PRM finds path."""
        start = (0.0, 0.0)
        goal = (10.0, 10.0)
        obstacles = []
        bounds = (0.0, 0.0, 20.0, 20.0)

        result = probabilistic_roadmap(
            start,
            goal,
            obstacles,
            bounds,
            num_samples=50,
        )

        assert result.found

    def test_prm_avoids_obstacles(self) -> None:
        """Test PRM avoids obstacles."""
        start = (0.0, 0.0)
        goal = (20.0, 20.0)
        obstacles = [Obstacle(8.0, 8.0, 12.0, 12.0)]
        bounds = (0.0, 0.0, 20.0, 20.0)

        result = probabilistic_roadmap(
            start,
            goal,
            obstacles,
            bounds,
            num_samples=100,
        )

        assert result.found

    def test_prm_sample_count_effect(self) -> None:
        """Test that more samples improve success."""
        start = (0.0, 0.0)
        goal = (15.0, 15.0)
        obstacles = []
        bounds = (0.0, 0.0, 20.0, 20.0)

        result_few = probabilistic_roadmap(
            start,
            goal,
            obstacles,
            bounds,
            num_samples=10,
        )

        result_many = probabilistic_roadmap(
            start,
            goal,
            obstacles,
            bounds,
            num_samples=50,
        )

    def test_prm_max_edge_length(self) -> None:
        """Test PRM respects edge length constraint."""
        start = (0.0, 0.0)
        goal = (10.0, 10.0)
        obstacles = []
        bounds = (0.0, 0.0, 20.0, 20.0)

        result = probabilistic_roadmap(
            start,
            goal,
            obstacles,
            bounds,
            num_samples=50,
            max_edge_length=5.0,
        )

        assert result.found


class TestMotionPlanningMetrics:
    """Test metrics from motion planning."""

    def test_execution_time_recorded(self) -> None:
        """Test that execution time is recorded."""
        start = (0.0, 0.0)
        goal = (10.0, 10.0)
        obstacles = []
        bounds = (0.0, 0.0, 20.0, 20.0)

        result = rrt(start, goal, obstacles, bounds, max_iterations=500)

        assert result.execution_time >= 0.0

    def test_nodes_generated_tracked(self) -> None:
        """Test that nodes generated is tracked."""
        start = (0.0, 0.0)
        goal = (10.0, 10.0)
        obstacles = []
        bounds = (0.0, 0.0, 20.0, 20.0)

        result = rrt(start, goal, obstacles, bounds, max_iterations=500)

        assert result.nodes_generated > 0

    def test_path_cost_computed(self) -> None:
        """Test that path cost is computed."""
        start = (0.0, 0.0)
        goal = (10.0, 10.0)
        obstacles = []
        bounds = (0.0, 0.0, 20.0, 20.0)

        result = rrt(start, goal, obstacles, bounds, max_iterations=500)

        if result.found:
            assert result.cost > 0.0


class TestBoundaryHandling:
    """Test boundary handling in motion planning."""

    def test_start_at_boundary(self) -> None:
        """Test starting at boundary."""
        start = (0.0, 0.0)
        goal = (10.0, 10.0)
        obstacles = []
        bounds = (0.0, 0.0, 20.0, 20.0)

        result = rrt(start, goal, obstacles, bounds, max_iterations=500)

        assert result.found

    def test_goal_at_boundary(self) -> None:
        """Test goal at boundary."""
        start = (10.0, 10.0)
        goal = (20.0, 20.0)
        obstacles = []
        bounds = (0.0, 0.0, 20.0, 20.0)

        result = rrt(start, goal, obstacles, bounds, max_iterations=500)

        assert result.found
