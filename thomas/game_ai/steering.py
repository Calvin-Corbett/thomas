"""
Steering behaviors for physics-based entity movement.

Implements individual and group behaviors: seek, flee, arrive, pursue, evade,
wander, obstacle avoidance, and flocking (separation, alignment, cohesion).
"""

import math
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass

from thomas.game_ai._types import GameEntity, Vec2


@dataclass
class SteeringOutput:
    """Result of a steering behavior calculation."""

    force: Vec2
    is_active: bool = True


class SteeringBehavior(ABC):
    """Base class for all steering behaviors."""

    @abstractmethod
    def calculate(self, entity: GameEntity) -> SteeringOutput:
        """Calculate steering force.

        Args:
            entity: Entity to calculate steering for

        Returns:
            SteeringOutput with force and active status
        """
        pass


class Seek(SteeringBehavior):
    """Steering behavior that seeks a target position.

    Creates acceleration toward target.
    """

    def __init__(self, target: Vec2, max_force: float = 10.0) -> None:
        """Initialize seek behavior.

        Args:
            target: Target position to seek
            max_force: Maximum steering force magnitude
        """
        self.target = target
        self.max_force = max_force

    def calculate(self, entity: GameEntity) -> SteeringOutput:
        """Calculate seek force toward target."""
        direction = self.target - entity.position
        distance = direction.magnitude()

        if distance < 0.01:
            return SteeringOutput(Vec2(0, 0), False)

        speed = max(entity.velocity.magnitude(), 5.0)  # Use minimum speed of 5.0
        desired_velocity = direction.normalize() * speed
        steering = desired_velocity - entity.velocity
        steering = steering.clamp_magnitude(self.max_force)

        return SteeringOutput(steering, True)


class Flee(SteeringBehavior):
    """Steering behavior that flees from a target position.

    Creates acceleration away from target.
    """

    def __init__(self, target: Vec2, max_force: float = 10.0, panic_distance: float = 50.0) -> None:
        """Initialize flee behavior.

        Args:
            target: Position to flee from
            max_force: Maximum steering force
            panic_distance: Distance at which fleeing starts
        """
        self.target = target
        self.max_force = max_force
        self.panic_distance = panic_distance

    def calculate(self, entity: GameEntity) -> SteeringOutput:
        """Calculate flee force away from target."""
        direction = entity.position - self.target
        distance = direction.magnitude()

        if distance > self.panic_distance:
            return SteeringOutput(Vec2(0, 0), False)

        if distance < 0.01:
            direction = Vec2(random.uniform(-1, 1), random.uniform(-1, 1))

        desired_velocity = direction.normalize() * entity.velocity.magnitude()
        steering = desired_velocity - entity.velocity
        steering = steering.clamp_magnitude(self.max_force)

        return SteeringOutput(steering, True)


class Arrive(SteeringBehavior):
    """Steering behavior that seeks target and slows down on approach.

    Decelerates as it approaches target for smooth arrival.
    """

    def __init__(
        self, target: Vec2, max_force: float = 10.0, arrival_distance: float = 5.0, deceleration: float = 1.0
    ) -> None:
        """Initialize arrive behavior.

        Args:
            target: Target position
            max_force: Maximum steering force
            arrival_distance: Distance at which to start slowing
            deceleration: Deceleration rate
        """
        self.target = target
        self.max_force = max_force
        self.arrival_distance = arrival_distance
        self.deceleration = deceleration

    def calculate(self, entity: GameEntity) -> SteeringOutput:
        """Calculate arrive force with deceleration."""
        direction = self.target - entity.position
        distance = direction.magnitude()

        if distance < 0.01:
            return SteeringOutput(Vec2(0, 0), False)

        # Scale velocity based on distance
        speed = entity.velocity.magnitude()
        if distance < self.arrival_distance:
            speed = speed * (distance / self.arrival_distance) / self.deceleration
        else:
            speed = entity.velocity.magnitude()

        desired_velocity = direction.normalize() * speed
        steering = desired_velocity - entity.velocity
        steering = steering.clamp_magnitude(self.max_force)

        return SteeringOutput(steering, True)


class Pursue(SteeringBehavior):
    """Steering behavior that pursues a moving target.

    Predicts target's future position and steers toward it.
    """

    def __init__(self, target_entity: GameEntity, max_force: float = 10.0, prediction_time: float = 0.5) -> None:
        """Initialize pursue behavior.

        Args:
            target_entity: Entity to pursue
            max_force: Maximum steering force
            prediction_time: How far ahead to predict target
        """
        self.target_entity = target_entity
        self.max_force = max_force
        self.prediction_time = prediction_time

    def calculate(self, entity: GameEntity) -> SteeringOutput:
        """Calculate pursue force toward predicted position."""
        # Predict target's future position
        predicted_position = self.target_entity.position + self.target_entity.velocity * self.prediction_time

        # Seek toward predicted position
        direction = predicted_position - entity.position
        distance = direction.magnitude()

        if distance < 0.01:
            return SteeringOutput(Vec2(0, 0), False)

        speed = max(entity.velocity.magnitude(), 5.0)  # Use minimum speed of 5.0
        desired_velocity = direction.normalize() * speed
        steering = desired_velocity - entity.velocity
        steering = steering.clamp_magnitude(self.max_force)

        return SteeringOutput(steering, True)


class Evade(SteeringBehavior):
    """Steering behavior that evades a moving threat.

    Predicts threat's future position and steers away.
    """

    def __init__(
        self,
        threat_entity: GameEntity,
        max_force: float = 10.0,
        prediction_time: float = 0.5,
        panic_distance: float = 50.0,
    ) -> None:
        """Initialize evade behavior.

        Args:
            threat_entity: Entity to evade from
            max_force: Maximum steering force
            prediction_time: How far ahead to predict threat
            panic_distance: Distance at which evasion starts
        """
        self.threat_entity = threat_entity
        self.max_force = max_force
        self.prediction_time = prediction_time
        self.panic_distance = panic_distance

    def calculate(self, entity: GameEntity) -> SteeringOutput:
        """Calculate evade force away from predicted threat position."""
        distance = entity.position.distance_to(self.threat_entity.position)

        if distance > self.panic_distance:
            return SteeringOutput(Vec2(0, 0), False)

        # Predict threat's future position
        predicted_position = self.threat_entity.position + self.threat_entity.velocity * self.prediction_time

        # Flee from predicted position
        direction = entity.position - predicted_position
        distance = direction.magnitude()

        if distance < 0.01:
            direction = Vec2(random.uniform(-1, 1), random.uniform(-1, 1))

        desired_velocity = direction.normalize() * entity.velocity.magnitude()
        steering = desired_velocity - entity.velocity
        steering = steering.clamp_magnitude(self.max_force)

        return SteeringOutput(steering, True)


class Wander(SteeringBehavior):
    """Steering behavior that creates random-ish movement.

    Moves around a circular target that rotates randomly.
    """

    def __init__(
        self,
        max_force: float = 10.0,
        wander_distance: float = 20.0,
        wander_radius: float = 5.0,
        wander_jitter: float = 2.0,
    ) -> None:
        """Initialize wander behavior.

        Args:
            max_force: Maximum steering force
            wander_distance: Distance to wander circle
            wander_radius: Radius of wander circle
            wander_jitter: Random angle change per frame
        """
        self.max_force = max_force
        self.wander_distance = wander_distance
        self.wander_radius = wander_radius
        self.wander_jitter = wander_jitter
        self._wander_angle = 0.0

    def calculate(self, entity: GameEntity) -> SteeringOutput:
        """Calculate wander force."""
        # Update wander angle randomly
        self._wander_angle += random.uniform(-self.wander_jitter, self.wander_jitter)

        # Calculate wander circle center ahead of entity
        entity_heading = entity.velocity.normalize() if entity.velocity.magnitude() > 0 else Vec2(1, 0)
        circle_center = entity.position + entity_heading * self.wander_distance

        # Calculate point on wander circle
        wander_point = Vec2(
            circle_center.x + self.wander_radius * math.cos(self._wander_angle),
            circle_center.y + self.wander_radius * math.sin(self._wander_angle),
        )

        # Seek toward wander point
        direction = wander_point - entity.position
        desired_velocity = direction.normalize() * entity.velocity.magnitude()
        steering = desired_velocity - entity.velocity
        steering = steering.clamp_magnitude(self.max_force)

        return SteeringOutput(steering, True)


class ObstacleAvoidance(SteeringBehavior):
    """Steering behavior that avoids static obstacles.

    Uses ray casting to detect approaching obstacles.
    """

    def __init__(self, obstacles: list[Vec2], max_force: float = 10.0, detection_range: float = 20.0) -> None:
        """Initialize obstacle avoidance.

        Args:
            obstacles: List of obstacle positions
            max_force: Maximum steering force
            detection_range: How far ahead to detect obstacles
        """
        self.obstacles = obstacles
        self.max_force = max_force
        self.detection_range = detection_range

    def calculate(self, entity: GameEntity) -> SteeringOutput:
        """Calculate avoidance force."""
        if not self.obstacles or entity.velocity.magnitude() < 0.01:
            return SteeringOutput(Vec2(0, 0), False)

        heading = entity.velocity.normalize()
        detection_ray_end = entity.position + heading * self.detection_range

        # Find closest obstacle in path
        closest_distance = float("inf")
        closest_obstacle = None

        for obstacle in self.obstacles:
            distance = entity.position.distance_to(obstacle)

            if distance < closest_distance and distance < self.detection_range:
                closest_distance = distance
                closest_obstacle = obstacle

        if closest_obstacle is None:
            return SteeringOutput(Vec2(0, 0), False)

        # Steer away from obstacle
        direction = entity.position - closest_obstacle
        if direction.magnitude() < 0.01:
            direction = Vec2(random.uniform(-1, 1), random.uniform(-1, 1))

        steering = direction.normalize() * self.max_force
        return SteeringOutput(steering, True)


class Separation(SteeringBehavior):
    """Flocking behavior: maintain distance from neighbors."""

    def __init__(self, neighbors: list[GameEntity], max_force: float = 10.0, separation_distance: float = 10.0) -> None:
        """Initialize separation behavior.

        Args:
            neighbors: List of neighbor entities
            max_force: Maximum steering force
            separation_distance: Minimum comfortable distance
        """
        self.neighbors = neighbors
        self.max_force = max_force
        self.separation_distance = separation_distance

    def calculate(self, entity: GameEntity) -> SteeringOutput:
        """Calculate separation force."""
        steering = Vec2(0, 0)
        count = 0

        for neighbor in self.neighbors:
            if neighbor.id == entity.id:
                continue

            distance = entity.position.distance_to(neighbor.position)

            if distance < self.separation_distance and distance > 0.01:
                # Move away from neighbor
                direction = entity.position - neighbor.position
                direction = direction.normalize() / distance  # Weight by proximity
                steering = steering + direction
                count += 1

        if count > 0:
            steering = steering / count
            steering = steering.clamp_magnitude(self.max_force)

        return SteeringOutput(steering, count > 0)


class Alignment(SteeringBehavior):
    """Flocking behavior: match neighbors' heading."""

    def __init__(self, neighbors: list[GameEntity], max_force: float = 10.0, alignment_distance: float = 20.0) -> None:
        """Initialize alignment behavior.

        Args:
            neighbors: List of neighbor entities
            max_force: Maximum steering force
            alignment_distance: Distance to consider neighbors
        """
        self.neighbors = neighbors
        self.max_force = max_force
        self.alignment_distance = alignment_distance

    def calculate(self, entity: GameEntity) -> SteeringOutput:
        """Calculate alignment force."""
        avg_heading = Vec2(0, 0)
        count = 0

        for neighbor in self.neighbors:
            if neighbor.id == entity.id:
                continue

            distance = entity.position.distance_to(neighbor.position)

            if distance < self.alignment_distance and distance > 0.01:
                if neighbor.velocity.magnitude() > 0.01:
                    avg_heading = avg_heading + neighbor.velocity.normalize()
                    count += 1

        if count > 0:
            avg_heading = avg_heading / count
            steering = avg_heading - entity.velocity.normalize()
            steering = steering.clamp_magnitude(self.max_force)
            return SteeringOutput(steering, True)

        return SteeringOutput(Vec2(0, 0), False)


class Cohesion(SteeringBehavior):
    """Flocking behavior: move toward neighbors' center."""

    def __init__(self, neighbors: list[GameEntity], max_force: float = 10.0, cohesion_distance: float = 20.0) -> None:
        """Initialize cohesion behavior.

        Args:
            neighbors: List of neighbor entities
            max_force: Maximum steering force
            cohesion_distance: Distance to consider neighbors
        """
        self.neighbors = neighbors
        self.max_force = max_force
        self.cohesion_distance = cohesion_distance

    def calculate(self, entity: GameEntity) -> SteeringOutput:
        """Calculate cohesion force."""
        center = Vec2(0, 0)
        count = 0

        for neighbor in self.neighbors:
            if neighbor.id == entity.id:
                continue

            distance = entity.position.distance_to(neighbor.position)

            if distance < self.cohesion_distance and distance > 0.01:
                center = center + neighbor.position
                count += 1

        if count > 0:
            center = center / count
            direction = center - entity.position
            speed = max(entity.velocity.magnitude(), 5.0)  # Use minimum speed of 5.0
            desired_velocity = direction.normalize() * speed
            steering = desired_velocity - entity.velocity
            steering = steering.clamp_magnitude(self.max_force)
            return SteeringOutput(steering, True)

        return SteeringOutput(Vec2(0, 0), False)


class SteeringManager:
    """Manages multiple steering behaviors with weighted blending."""

    def __init__(self) -> None:
        """Initialize steering manager."""
        self.behaviors: list[tuple[SteeringBehavior, float]] = []

    def add_behavior(self, behavior: SteeringBehavior, weight: float = 1.0) -> None:
        """Add a steering behavior with weight.

        Args:
            behavior: SteeringBehavior to add
            weight: Weight for this behavior
        """
        self.behaviors.append((behavior, weight))

    def calculate(self, entity: GameEntity) -> Vec2:
        """Calculate blended steering force.

        Args:
            entity: Entity to calculate steering for

        Returns:
            Combined steering force
        """
        total_force = Vec2(0, 0)
        total_weight = 0.0

        for behavior, weight in self.behaviors:
            output = behavior.calculate(entity)

            if output.is_active:
                total_force = total_force + output.force * weight
                total_weight += weight

        if total_weight > 0:
            return total_force / total_weight

        return Vec2(0, 0)

    def update_entity(self, entity: GameEntity, delta_time: float, max_speed: float = 10.0) -> None:
        """Update entity velocity based on steering forces.

        Args:
            entity: Entity to update
            delta_time: Time since last update
            max_speed: Maximum velocity magnitude
        """
        steering = self.calculate(entity)
        entity.velocity = entity.velocity + steering * delta_time
        entity.velocity = entity.velocity.clamp_magnitude(max_speed)
        entity.position = entity.position + entity.velocity * delta_time
