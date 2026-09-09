"""Motion prediction for autonomous vehicles.

Includes constant velocity/acceleration models, lane-following prediction,
interaction-aware prediction, maneuver prediction, and time-to-collision.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from thomas.autonomous_vehicles._types import (
    ManeuverType,
    Obstacle,
    Vector2D,
)


@dataclass
class PredictionTrajectory:
    """Predicted trajectory for an obstacle."""

    obstacle_id: str
    predictions: list[tuple[Vector2D, float]]  # (position, probability)
    maneuver_type: ManeuverType
    time_to_collision: float | None = None
    confidence: float = 0.0


class ConstantVelocityModel:
    """Constant velocity motion model."""

    def __init__(self: ConstantVelocityModel) -> None:
        """Initialize constant velocity model."""
        pass

    def predict(
        self: ConstantVelocityModel,
        obstacle: Obstacle,
        horizon: float,
        num_steps: int = 20,
    ) -> list[Vector2D]:
        """Predict trajectory using constant velocity model.

        Args:
            obstacle: Obstacle to predict
            horizon: Prediction horizon in seconds
            num_steps: Number of prediction steps

        Returns:
            List of predicted positions
        """
        predictions = []
        dt = horizon / num_steps

        for step in range(num_steps):
            t = (step + 1) * dt
            predicted_pos = obstacle.position + obstacle.velocity * t
            predictions.append(predicted_pos)

        return predictions


class ConstantAccelerationModel:
    """Constant acceleration motion model."""

    def __init__(self: ConstantAccelerationModel) -> None:
        """Initialize constant acceleration model."""
        pass

    def predict(
        self: ConstantAccelerationModel,
        obstacle: Obstacle,
        horizon: float,
        num_steps: int = 20,
    ) -> list[Vector2D]:
        """Predict trajectory using constant acceleration model.

        Args:
            obstacle: Obstacle to predict
            horizon: Prediction horizon in seconds
            num_steps: Number of prediction steps

        Returns:
            List of predicted positions
        """
        predictions = []
        dt = horizon / num_steps

        for step in range(num_steps):
            t = (step + 1) * dt
            # p = p0 + v0*t + 0.5*a*t^2
            predicted_pos = obstacle.position + obstacle.velocity * t + obstacle.acceleration * (0.5 * t**2)
            predictions.append(predicted_pos)

        return predictions


class LaneFollowingPredictor:
    """Predict motion for lane-following vehicles."""

    def __init__(
        self: LaneFollowingPredictor,
        max_lateral_acceleration: float = 3.0,
        max_longitudinal_acceleration: float = 3.0,
    ) -> None:
        """Initialize lane following predictor.

        Args:
            max_lateral_acceleration: Maximum lateral acceleration
            max_longitudinal_acceleration: Maximum longitudinal acceleration
        """
        self.max_lateral_acceleration = max_lateral_acceleration
        self.max_longitudinal_acceleration = max_longitudinal_acceleration

    def predict(
        self: LaneFollowingPredictor,
        obstacle: Obstacle,
        lane_centerline: list[Vector2D],
        horizon: float,
        num_steps: int = 20,
    ) -> list[Vector2D]:
        """Predict lane-following trajectory.

        Args:
            obstacle: Obstacle to predict
            lane_centerline: Lane center line points
            horizon: Prediction horizon
            num_steps: Number of prediction steps

        Returns:
            List of predicted positions
        """
        predictions = []
        dt = horizon / num_steps

        # Find nearest point on lane
        min_dist = float("inf")
        nearest_idx = 0
        for i, point in enumerate(lane_centerline):
            dist = obstacle.position.distance_to(point)
            if dist < min_dist:
                min_dist = dist
                nearest_idx = i

        # Follow lane
        current_idx = nearest_idx
        current_pos = obstacle.position
        current_vel = obstacle.velocity

        for step in range(num_steps):
            dt_step = dt
            speed = current_vel.norm()

            # Advance along lane
            if current_idx < len(lane_centerline) - 1:
                target_pos = lane_centerline[current_idx + 1]
                direction = target_pos - current_pos
                direction_norm = direction.norm()

                if direction_norm > 1e-6:
                    direction = direction * (1.0 / direction_norm)
                    new_pos = current_pos + direction * speed * dt_step

                    # Check if we've reached next waypoint
                    if new_pos.distance_to(target_pos) < new_pos.distance_to(current_pos):
                        current_idx = min(current_idx + 1, len(lane_centerline) - 1)

                    current_pos = new_pos
                else:
                    current_pos = current_pos + current_vel * dt_step
            else:
                current_pos = current_pos + current_vel * dt_step

            predictions.append(current_pos)

        return predictions


class InteractionAwarePredictor:
    """Predict motion considering vehicle interactions."""

    def __init__(
        self: InteractionAwarePredictor,
        social_force_strength: float = 1.0,
        reaction_time: float = 0.5,
    ) -> None:
        """Initialize interaction-aware predictor.

        Args:
            social_force_strength: Strength of social force
            reaction_time: Reaction time to perceived threats
        """
        self.social_force_strength = social_force_strength
        self.reaction_time = reaction_time

    def predict(
        self: InteractionAwarePredictor,
        ego_vehicle: Vector2D,
        ego_velocity: Vector2D,
        obstacle: Obstacle,
        horizon: float,
        num_steps: int = 20,
    ) -> list[Vector2D]:
        """Predict trajectory considering ego vehicle.

        Args:
            ego_vehicle: Ego vehicle position
            ego_velocity: Ego vehicle velocity
            obstacle: Obstacle to predict
            horizon: Prediction horizon
            num_steps: Number of prediction steps

        Returns:
            List of predicted positions
        """
        predictions = []
        dt = horizon / num_steps

        current_pos = obstacle.position
        current_vel = obstacle.velocity

        for step in range(num_steps):
            # Social force from ego vehicle
            away_from_ego = current_pos - ego_vehicle
            dist_to_ego = away_from_ego.norm()

            if dist_to_ego > 1e-6:
                # Repulsive force
                force_magnitude = self.social_force_strength / (dist_to_ego + 1.0)
                repulsive_force = away_from_ego * (force_magnitude / (dist_to_ego + 1e-6))

                # Apply force as acceleration
                acceleration = repulsive_force * 0.5
            else:
                acceleration = Vector2D(0.0, 0.0)

            # Update velocity and position
            current_vel = current_vel + acceleration * dt
            current_pos = current_pos + current_vel * dt

            predictions.append(current_pos)

        return predictions


class ManeuverPredictor:
    """Predict maneuvers (lane changes, turns, etc.)."""

    def __init__(self: ManeuverPredictor) -> None:
        """Initialize maneuver predictor."""
        self.lane_change_probability = 0.3
        self.turn_probability = 0.2

    def predict_maneuver(
        self: ManeuverPredictor,
        obstacle: Obstacle,
        predictions: list[Vector2D],
    ) -> ManeuverType:
        """Predict maneuver type.

        Args:
            obstacle: Obstacle
            predictions: List of predicted positions

        Returns:
            Predicted maneuver type
        """
        if len(predictions) < 2:
            return ManeuverType.LANE_FOLLOW

        # Check lateral motion
        lateral_displacement = 0.0
        for i in range(1, len(predictions)):
            dy = predictions[i].y - predictions[i - 1].y
            lateral_displacement += abs(dy)

        if lateral_displacement > 2.0:
            if predictions[-1].y > predictions[0].y:
                return ManeuverType.LANE_CHANGE_LEFT
            else:
                return ManeuverType.LANE_CHANGE_RIGHT

        return ManeuverType.LANE_FOLLOW


class TrajectoryProbabilityEstimator:
    """Estimate probability distribution over trajectories."""

    def __init__(self: TrajectoryProbabilityEstimator) -> None:
        """Initialize trajectory probability estimator."""
        pass

    def compute_probability(
        self: TrajectoryProbabilityEstimator,
        trajectory: list[Vector2D],
        obstacle: Obstacle,
    ) -> float:
        """Compute probability of trajectory.

        Args:
            trajectory: Predicted trajectory
            obstacle: Obstacle

        Returns:
            Probability (0-1)
        """
        if len(trajectory) == 0:
            return 0.0

        # Cost is distance from constant velocity model
        expected_trajectory = []
        for i in range(len(trajectory)):
            t = i * 0.1
            expected_pos = obstacle.position + obstacle.velocity * t
            expected_trajectory.append(expected_pos)

        # Compute squared error
        squared_error = 0.0
        for pred, expected in zip(trajectory, expected_trajectory):
            error = pred.distance_to(expected)
            squared_error += error**2

        # Convert to probability
        probability = np.exp(-squared_error / (2.0 * (1.0**2)))
        return float(probability)


class TimeToCollisionEstimator:
    """Estimate time to collision."""

    def __init__(self: TimeToCollisionEstimator) -> None:
        """Initialize TTC estimator."""
        pass

    def estimate_ttc(
        self: TimeToCollisionEstimator,
        vehicle_position: Vector2D,
        vehicle_velocity: Vector2D,
        obstacle: Obstacle,
        vehicle_width: float = 1.8,
        vehicle_length: float = 4.5,
    ) -> float | None:
        """Estimate time to collision.

        Args:
            vehicle_position: Vehicle position
            vehicle_velocity: Vehicle velocity
            obstacle: Obstacle
            vehicle_width: Vehicle width
            vehicle_length: Vehicle length

        Returns:
            TTC in seconds, or None if no collision
        """
        # Relative position and velocity
        rel_pos = obstacle.position - vehicle_position
        rel_vel = obstacle.velocity - vehicle_velocity

        # Check if vehicles are approaching
        if rel_vel.dot(rel_pos) >= 0:
            return None  # Moving apart

        # Minimum distance required to avoid collision
        min_distance = (vehicle_width + obstacle.width) / 2 + (vehicle_length + obstacle.length) / 2

        # Solve for collision time
        # |rel_pos + rel_vel * t| = min_distance
        a = rel_vel.x**2 + rel_vel.y**2
        b = 2 * (rel_pos.x * rel_vel.x + rel_pos.y * rel_vel.y)
        c = rel_pos.x**2 + rel_pos.y**2 - min_distance**2

        if a < 1e-6:
            return None

        discriminant = b**2 - 4 * a * c
        if discriminant < 0:
            return None

        t1 = (-b - np.sqrt(discriminant)) / (2 * a)
        if t1 >= 0:
            return float(t1)

        t2 = (-b + np.sqrt(discriminant)) / (2 * a)
        if t2 >= 0:
            return float(t2)

        return None


class MotionPredictor:
    """Complete motion prediction system."""

    def __init__(
        self: MotionPredictor,
        prediction_horizon: float = 5.0,
        num_steps: int = 20,
    ) -> None:
        """Initialize motion predictor.

        Args:
            prediction_horizon: Prediction horizon in seconds
            num_steps: Number of prediction steps
        """
        self.prediction_horizon = prediction_horizon
        self.num_steps = num_steps

        self.cv_model = ConstantVelocityModel()
        self.ca_model = ConstantAccelerationModel()
        self.lane_follower = LaneFollowingPredictor()
        self.interaction_predictor = InteractionAwarePredictor()
        self.maneuver_predictor = ManeuverPredictor()
        self.prob_estimator = TrajectoryProbabilityEstimator()
        self.ttc_estimator = TimeToCollisionEstimator()

    def predict(
        self: MotionPredictor,
        ego_vehicle_position: Vector2D,
        ego_vehicle_velocity: Vector2D,
        obstacles: list[Obstacle],
        lane_centerlines: dict[str, list[Vector2D]] | None = None,
    ) -> list[PredictionTrajectory]:
        """Predict motion of all obstacles.

        Args:
            ego_vehicle_position: Ego vehicle position
            ego_vehicle_velocity: Ego vehicle velocity
            obstacles: List of obstacles
            lane_centerlines: Lane centerline points

        Returns:
            List of prediction trajectories
        """
        predictions = []

        for obstacle in obstacles:
            # Generate multiple predictions
            cv_predictions = self.cv_model.predict(obstacle, self.prediction_horizon, self.num_steps)

            ca_predictions = self.ca_model.predict(obstacle, self.prediction_horizon, self.num_steps)

            # Estimate probability
            cv_prob = self.prob_estimator.compute_probability(cv_predictions, obstacle)
            ca_prob = self.prob_estimator.compute_probability(ca_predictions, obstacle)

            # Use weighted average
            if cv_prob + ca_prob > 1e-6:
                cv_weight = cv_prob / (cv_prob + ca_prob)
            else:
                cv_weight = 0.5

            # Predict maneuver
            maneuver = self.maneuver_predictor.predict_maneuver(obstacle, cv_predictions)

            # Estimate TTC
            ttc = self.ttc_estimator.estimate_ttc(ego_vehicle_position, ego_vehicle_velocity, obstacle)

            # Combine predictions
            combined_predictions = [(cv_pred, cv_weight) for cv_pred in cv_predictions]

            predictions.append(
                PredictionTrajectory(
                    obstacle_id=obstacle.obstacle_id,
                    predictions=combined_predictions,
                    maneuver_type=maneuver,
                    time_to_collision=ttc,
                    confidence=max(cv_prob, ca_prob),
                )
            )

        return predictions
