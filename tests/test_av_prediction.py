"""Tests for prediction module."""

import numpy as np

from thomas.autonomous_vehicles._types import (
    ManeuverType,
    Obstacle,
    ObstacleType,
    Vector2D,
)
from thomas.autonomous_vehicles.prediction import (
    ConstantAccelerationModel,
    ConstantVelocityModel,
    InteractionAwarePredictor,
    LaneFollowingPredictor,
    ManeuverPredictor,
    MotionPredictor,
    TimeToCollisionEstimator,
    TrajectoryProbabilityEstimator,
)


class TestConstantVelocityModel:
    """Test constant velocity model."""

    def test_cv_prediction(self) -> None:
        """Test constant velocity prediction."""
        model = ConstantVelocityModel()

        obstacle = Obstacle(
            obstacle_id="obs_0",
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(5.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            obstacle_type=ObstacleType.VEHICLE,
        )

        predictions = model.predict(obstacle, horizon=2.0, num_steps=10)

        assert len(predictions) == 10
        # Last position should be approximately 10m ahead (5 m/s * 2s)
        assert abs(predictions[-1].x - 10.0) < 0.5


class TestConstantAccelerationModel:
    """Test constant acceleration model."""

    def test_ca_prediction(self) -> None:
        """Test constant acceleration prediction."""
        model = ConstantAccelerationModel()

        obstacle = Obstacle(
            obstacle_id="obs_0",
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(5.0, 0.0),
            acceleration=Vector2D(1.0, 0.0),
            obstacle_type=ObstacleType.VEHICLE,
        )

        predictions = model.predict(obstacle, horizon=2.0, num_steps=10)

        assert len(predictions) == 10
        # Should accelerate
        assert predictions[-1].x > predictions[0].x


class TestLaneFollowingPredictor:
    """Test lane following predictor."""

    def test_lane_following_prediction(self) -> None:
        """Test prediction along lane."""
        predictor = LaneFollowingPredictor()

        # Define lane
        lane = [
            Vector2D(0.0, 0.0),
            Vector2D(5.0, 0.0),
            Vector2D(10.0, 0.0),
            Vector2D(15.0, 0.0),
        ]

        obstacle = Obstacle(
            obstacle_id="obs_0",
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(5.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            obstacle_type=ObstacleType.VEHICLE,
        )

        predictions = predictor.predict(obstacle, lane, horizon=2.0, num_steps=10)

        assert len(predictions) > 0
        assert all(abs(p.y) < 1.0 for p in predictions)  # Stay in lane


class TestInteractionAwarePredictor:
    """Test interaction-aware predictor."""

    def test_repulsive_interaction(self) -> None:
        """Test repulsive force from ego vehicle."""
        predictor = InteractionAwarePredictor(social_force_strength=1.0)

        ego_position = Vector2D(0.0, 0.0)
        ego_velocity = Vector2D(5.0, 0.0)

        obstacle = Obstacle(
            obstacle_id="obs_0",
            position=Vector2D(10.0, 0.0),
            velocity=Vector2D(0.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            obstacle_type=ObstacleType.VEHICLE,
        )

        predictions = predictor.predict(ego_position, ego_velocity, obstacle, horizon=1.0, num_steps=5)

        assert len(predictions) == 5
        # Obstacle should move away from ego
        assert predictions[-1].x > obstacle.position.x


class TestManeuverPredictor:
    """Test maneuver predictor."""

    def test_lane_follow_prediction(self) -> None:
        """Test prediction of lane following."""
        predictor = ManeuverPredictor()

        obstacle = Obstacle(
            obstacle_id="obs_0",
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(5.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            obstacle_type=ObstacleType.VEHICLE,
        )

        predictions = [
            Vector2D(1.0, 0.0),
            Vector2D(2.0, 0.0),
            Vector2D(3.0, 0.05),
        ]

        maneuver = predictor.predict_maneuver(obstacle, predictions)

        assert maneuver == ManeuverType.LANE_FOLLOW

    def test_lane_change_left(self) -> None:
        """Test prediction of left lane change."""
        predictor = ManeuverPredictor()

        obstacle = Obstacle(
            obstacle_id="obs_0",
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(5.0, 1.0),
            acceleration=Vector2D(0.0, 0.0),
            obstacle_type=ObstacleType.VEHICLE,
        )

        predictions = [
            Vector2D(1.0, 0.0),
            Vector2D(2.0, 1.0),
            Vector2D(3.0, 2.5),
        ]

        maneuver = predictor.predict_maneuver(obstacle, predictions)

        assert maneuver == ManeuverType.LANE_CHANGE_LEFT


class TestTrajectoryProbabilityEstimator:
    """Test trajectory probability estimation."""

    def test_probability_computation(self) -> None:
        """Test probability computation."""
        estimator = TrajectoryProbabilityEstimator()

        obstacle = Obstacle(
            obstacle_id="obs_0",
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(5.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            obstacle_type=ObstacleType.VEHICLE,
        )

        # Trajectory following constant velocity
        trajectory = [Vector2D(5.0 * (i + 1) / 10, 0.0) for i in range(10)]

        probability = estimator.compute_probability(trajectory, obstacle)

        assert 0.0 <= probability <= 1.0

    def test_probability_high_for_expected_motion(self) -> None:
        """Test high probability for expected motion."""
        estimator = TrajectoryProbabilityEstimator()

        obstacle = Obstacle(
            obstacle_id="obs_0",
            position=Vector2D(0.0, 0.0),
            velocity=Vector2D(5.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            obstacle_type=ObstacleType.VEHICLE,
        )

        # Trajectory following exactly constant velocity
        trajectory_expected = [Vector2D(5.0 * (i + 1) / 10, 0.0) for i in range(10)]

        # Random trajectory
        trajectory_random = [Vector2D(np.random.randn(), np.random.randn()) for _ in range(10)]

        prob_expected = estimator.compute_probability(trajectory_expected, obstacle)
        prob_random = estimator.compute_probability(trajectory_random, obstacle)

        assert prob_expected > prob_random


class TestTimeToCollisionEstimator:
    """Test TTC estimation."""

    def test_ttc_approaching_vehicles(self) -> None:
        """Test TTC for approaching vehicles."""
        estimator = TimeToCollisionEstimator()

        vehicle_position = Vector2D(0.0, 0.0)
        vehicle_velocity = Vector2D(10.0, 0.0)

        obstacle = Obstacle(
            obstacle_id="obs_0",
            position=Vector2D(20.0, 0.0),
            velocity=Vector2D(0.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            obstacle_type=ObstacleType.VEHICLE,
            width=1.8,
            length=4.5,
        )

        ttc = estimator.estimate_ttc(vehicle_position, vehicle_velocity, obstacle)

        assert ttc is not None
        assert ttc > 0.0

    def test_ttc_separating_vehicles(self) -> None:
        """Test TTC for separating vehicles."""
        estimator = TimeToCollisionEstimator()

        vehicle_position = Vector2D(0.0, 0.0)
        vehicle_velocity = Vector2D(-10.0, 0.0)  # Moving away

        obstacle = Obstacle(
            obstacle_id="obs_0",
            position=Vector2D(20.0, 0.0),
            velocity=Vector2D(0.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            obstacle_type=ObstacleType.VEHICLE,
        )

        ttc = estimator.estimate_ttc(vehicle_position, vehicle_velocity, obstacle)

        assert ttc is None  # No collision

    def test_ttc_lateral_separation(self) -> None:
        """Test TTC with lateral separation."""
        estimator = TimeToCollisionEstimator()

        vehicle_position = Vector2D(0.0, 0.0)
        vehicle_velocity = Vector2D(10.0, 0.0)

        obstacle = Obstacle(
            obstacle_id="obs_0",
            position=Vector2D(20.0, 10.0),  # Laterally separated
            velocity=Vector2D(0.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            obstacle_type=ObstacleType.VEHICLE,
            width=1.8,
            length=4.5,
        )

        ttc = estimator.estimate_ttc(vehicle_position, vehicle_velocity, obstacle)

        assert ttc is None  # Large lateral separation


class TestMotionPredictor:
    """Test complete motion predictor."""

    def test_predict_multiple_obstacles(self) -> None:
        """Test prediction of multiple obstacles."""
        predictor = MotionPredictor(prediction_horizon=5.0, num_steps=20)

        ego_position = Vector2D(0.0, 0.0)
        ego_velocity = Vector2D(10.0, 0.0)

        obstacles = [
            Obstacle(
                obstacle_id="obs_0",
                position=Vector2D(20.0, 0.0),
                velocity=Vector2D(5.0, 0.0),
                acceleration=Vector2D(0.0, 0.0),
                obstacle_type=ObstacleType.VEHICLE,
            ),
            Obstacle(
                obstacle_id="obs_1",
                position=Vector2D(15.0, 2.0),
                velocity=Vector2D(0.0, 0.0),
                acceleration=Vector2D(0.0, 0.0),
                obstacle_type=ObstacleType.VEHICLE,
            ),
        ]

        predictions = predictor.predict(ego_position, ego_velocity, obstacles)

        assert len(predictions) == 2
        assert all(p.obstacle_id in ["obs_0", "obs_1"] for p in predictions)

    def test_ttc_estimation_in_prediction(self) -> None:
        """Test TTC estimation in predictions."""
        predictor = MotionPredictor()

        ego_position = Vector2D(0.0, 0.0)
        ego_velocity = Vector2D(10.0, 0.0)

        obstacle = Obstacle(
            obstacle_id="obs_0",
            position=Vector2D(15.0, 0.0),
            velocity=Vector2D(0.0, 0.0),
            acceleration=Vector2D(0.0, 0.0),
            obstacle_type=ObstacleType.VEHICLE,
            width=1.8,
            length=4.5,
        )

        predictions = predictor.predict(ego_position, ego_velocity, [obstacle])

        assert len(predictions) == 1
        assert predictions[0].time_to_collision is not None
        assert predictions[0].time_to_collision > 0.0
