"""
Steering behaviors for character animation and movement.

This module implements classic steering behaviors including seek, flee, arrive,
pursuit, evasion, flocking, and obstacle avoidance.
"""

import math
from dataclasses import dataclass


@dataclass
class SteeringOutput:
    """Result of a steering behavior calculation."""

    linear_velocity: tuple[float, float]
    angular_velocity: float = 0.0


@dataclass
class Boid:
    """A character with position, velocity, and orientation."""

    x: float
    y: float
    vx: float
    vy: float
    mass: float = 1.0
    max_speed: float = 5.0
    max_acceleration: float = 2.0
    rotation: float = 0.0


def seek(
    character: Boid,
    target_x: float,
    target_y: float,
) -> SteeringOutput:
    """
    Seek steering behavior: accelerate toward target.

    Args:
        character: The character seeking.
        target_x: Target X coordinate.
        target_y: Target Y coordinate.

    Returns:
        SteeringOutput with desired steering.
    """
    dx = target_x - character.x
    dy = target_y - character.y
    dist = math.sqrt(dx * dx + dy * dy)

    if dist < 0.01:
        return SteeringOutput((0.0, 0.0))

    desired_speed = character.max_speed
    desired_vx = (dx / dist) * desired_speed
    desired_vy = (dy / dist) * desired_speed

    steering_x = desired_vx - character.vx
    steering_y = desired_vy - character.vy

    mag = math.sqrt(steering_x * steering_x + steering_y * steering_y)
    if mag > character.max_acceleration:
        steering_x = (steering_x / mag) * character.max_acceleration
        steering_y = (steering_y / mag) * character.max_acceleration

    return SteeringOutput((steering_x, steering_y))


def flee(
    character: Boid,
    threat_x: float,
    threat_y: float,
) -> SteeringOutput:
    """
    Flee steering behavior: accelerate away from threat.

    Args:
        character: The character fleeing.
        threat_x: Threat X coordinate.
        threat_y: Threat Y coordinate.

    Returns:
        SteeringOutput with desired steering.
    """
    dx = character.x - threat_x
    dy = character.y - threat_y
    dist = math.sqrt(dx * dx + dy * dy)

    if dist < 0.01:
        return SteeringOutput((character.max_speed, 0.0))

    desired_speed = character.max_speed
    desired_vx = (dx / dist) * desired_speed
    desired_vy = (dy / dist) * desired_speed

    steering_x = desired_vx - character.vx
    steering_y = desired_vy - character.vy

    mag = math.sqrt(steering_x * steering_x + steering_y * steering_y)
    if mag > character.max_acceleration:
        steering_x = (steering_x / mag) * character.max_acceleration
        steering_y = (steering_y / mag) * character.max_acceleration

    return SteeringOutput((steering_x, steering_y))


def arrive(
    character: Boid,
    target_x: float,
    target_y: float,
    slow_radius: float = 10.0,
) -> SteeringOutput:
    """
    Arrive steering behavior: decelerate approaching target.

    Args:
        character: The character arriving.
        target_x: Target X coordinate.
        target_y: Target Y coordinate.
        slow_radius: Distance at which to start decelerating.

    Returns:
        SteeringOutput with desired steering.
    """
    dx = target_x - character.x
    dy = target_y - character.y
    dist = math.sqrt(dx * dx + dy * dy)

    if dist < 0.01:
        return SteeringOutput((0.0, 0.0))

    if dist < slow_radius:
        desired_speed = character.max_speed * (dist / slow_radius)
    else:
        desired_speed = character.max_speed

    desired_vx = (dx / dist) * desired_speed
    desired_vy = (dy / dist) * desired_speed

    steering_x = desired_vx - character.vx
    steering_y = desired_vy - character.vy

    mag = math.sqrt(steering_x * steering_x + steering_y * steering_y)
    if mag > character.max_acceleration:
        steering_x = (steering_x / mag) * character.max_acceleration
        steering_y = (steering_y / mag) * character.max_acceleration

    return SteeringOutput((steering_x, steering_y))


def pursue(
    character: Boid,
    target: Boid,
    look_ahead_time: float = 1.0,
) -> SteeringOutput:
    """
    Pursue steering behavior: seek predicted target position.

    Args:
        character: The character pursuing.
        target: The target being pursued.
        look_ahead_time: Time to predict ahead.

    Returns:
        SteeringOutput with desired steering.
    """
    dx = target.x - character.x
    dy = target.y - character.y
    math.sqrt(dx * dx + dy * dy)

    predicted_x = target.x + target.vx * look_ahead_time
    predicted_y = target.y + target.vy * look_ahead_time

    return seek(character, predicted_x, predicted_y)


def evade(
    character: Boid,
    threat: Boid,
    look_ahead_time: float = 1.0,
) -> SteeringOutput:
    """
    Evade steering behavior: flee from predicted threat position.

    Args:
        character: The character evading.
        threat: The threat being evaded.
        look_ahead_time: Time to predict ahead.

    Returns:
        SteeringOutput with desired steering.
    """
    dx = threat.x - character.x
    dy = threat.y - character.y
    math.sqrt(dx * dx + dy * dy)

    predicted_x = threat.x + threat.vx * look_ahead_time
    predicted_y = threat.y + threat.vy * look_ahead_time

    return flee(character, predicted_x, predicted_y)


def wander(
    character: Boid,
    wander_distance: float = 10.0,
    wander_radius: float = 5.0,
    wander_rate: float = 0.1,
    wander_angle: float = 0.0,
) -> tuple[SteeringOutput, float]:
    """
    Wander steering behavior: random wandering.

    Args:
        character: The character wandering.
        wander_distance: Distance to wander circle.
        wander_radius: Radius of wander circle.
        wander_rate: Rate of angle change.
        wander_angle: Current wander angle (for consistency).

    Returns:
        Tuple of (SteeringOutput, updated_wander_angle).
    """
    import random

    wander_angle += (random.random() - 0.5) * wander_rate

    wander_x = wander_distance * math.cos(character.rotation)
    wander_y = wander_distance * math.sin(character.rotation)

    target_x = character.x + wander_x + wander_radius * math.cos(wander_angle)
    target_y = character.y + wander_y + wander_radius * math.sin(wander_angle)

    output = seek(character, target_x, target_y)
    return (output, wander_angle)


def obstacle_avoidance(
    character: Boid,
    obstacles: list[tuple[float, float, float]],
    lookahead_dist: float = 10.0,
) -> SteeringOutput:
    """
    Obstacle avoidance steering behavior using ray casting.

    Args:
        character: The character avoiding obstacles.
        obstacles: List of (x, y, radius) obstacles.
        lookahead_dist: Distance to look ahead.

    Returns:
        SteeringOutput with avoidance steering.
    """
    speed = math.sqrt(character.vx * character.vx + character.vy * character.vy)
    if speed < 0.01:
        return SteeringOutput((0.0, 0.0))

    look_ahead_x = character.x + (character.vx / speed) * lookahead_dist
    look_ahead_y = character.y + (character.vy / speed) * lookahead_dist

    min_dist = float("inf")
    closest_obstacle = None
    closest_point = (look_ahead_x, look_ahead_y)

    for obs_x, obs_y, obs_radius in obstacles:
        dist_to_center = math.sqrt((look_ahead_x - obs_x) ** 2 + (look_ahead_y - obs_y) ** 2)
        if dist_to_center < min_dist:
            min_dist = dist_to_center
            closest_obstacle = (obs_x, obs_y, obs_radius)
            dx = look_ahead_x - obs_x
            dy = look_ahead_y - obs_y
            dist_to_center_actual = math.sqrt(dx * dx + dy * dy)
            if dist_to_center_actual > 0:
                normal_x = dx / dist_to_center_actual
                normal_y = dy / dist_to_center_actual
                closest_point = (
                    obs_x + normal_x * (obs_radius + 1.0),
                    obs_y + normal_y * (obs_radius + 1.0),
                )

    if closest_obstacle and min_dist < closest_obstacle[2] + 5.0:
        return seek(character, closest_point[0], closest_point[1])

    return SteeringOutput((0.0, 0.0))


def flocking(
    character: Boid,
    neighbors: list[Boid],
    separation_radius: float = 5.0,
    alignment_radius: float = 15.0,
    cohesion_radius: float = 20.0,
    separation_weight: float = 1.0,
    alignment_weight: float = 1.0,
    cohesion_weight: float = 1.0,
) -> SteeringOutput:
    """
    Flocking behavior: separation, alignment, and cohesion.

    Args:
        character: The character flocking.
        neighbors: List of neighboring boids.
        separation_radius: Radius for separation behavior.
        alignment_radius: Radius for alignment behavior.
        cohesion_radius: Radius for cohesion behavior.
        separation_weight: Weight of separation component.
        alignment_weight: Weight of alignment component.
        cohesion_weight: Weight of cohesion component.

    Returns:
        SteeringOutput with flocking behavior.
    """
    separation = SteeringOutput((0.0, 0.0))
    alignment = SteeringOutput((0.0, 0.0))
    cohesion = SteeringOutput((0.0, 0.0))

    sep_count = 0
    align_count = 0
    cohe_count = 0

    align_vx = 0.0
    align_vy = 0.0
    cohe_x = 0.0
    cohe_y = 0.0

    for neighbor in neighbors:
        dx = neighbor.x - character.x
        dy = neighbor.y - character.y
        dist = math.sqrt(dx * dx + dy * dy)

        if dist < 0.01 or dist > cohesion_radius:
            continue

        if dist < separation_radius:
            sep_dx = -dx / (dist + 0.01)
            sep_dy = -dy / (dist + 0.01)
            separation.linear_velocity = (
                separation.linear_velocity[0] + sep_dx,
                separation.linear_velocity[1] + sep_dy,
            )
            sep_count += 1

        if dist < alignment_radius:
            align_vx += neighbor.vx
            align_vy += neighbor.vy
            align_count += 1

        if dist < cohesion_radius:
            cohe_x += neighbor.x
            cohe_y += neighbor.y
            cohe_count += 1

    if sep_count > 0:
        mag = math.sqrt(separation.linear_velocity[0] ** 2 + separation.linear_velocity[1] ** 2)
        if mag > character.max_acceleration:
            separation.linear_velocity = (
                separation.linear_velocity[0] / mag * character.max_acceleration,
                separation.linear_velocity[1] / mag * character.max_acceleration,
            )

    if align_count > 0:
        alignment = seek(
            character,
            character.x + align_vx / align_count,
            character.y + align_vy / align_count,
        )

    if cohe_count > 0:
        cohesion = seek(
            character,
            cohe_x / cohe_count,
            cohe_y / cohe_count,
        )

    combined_x = (
        separation.linear_velocity[0] * separation_weight
        + alignment.linear_velocity[0] * alignment_weight
        + cohesion.linear_velocity[0] * cohesion_weight
    )
    combined_y = (
        separation.linear_velocity[1] * separation_weight
        + alignment.linear_velocity[1] * alignment_weight
        + cohesion.linear_velocity[1] * cohesion_weight
    )

    mag = math.sqrt(combined_x * combined_x + combined_y * combined_y)
    if mag > character.max_acceleration:
        combined_x = (combined_x / mag) * character.max_acceleration
        combined_y = (combined_y / mag) * character.max_acceleration

    return SteeringOutput((combined_x, combined_y))


def path_following(
    character: Boid,
    path: list[tuple[float, float]],
    lookahead_distance: float = 5.0,
    path_radius: float = 2.0,
    current_path_index: int = 0,
) -> tuple[SteeringOutput, int]:
    """
    Path following steering behavior.

    Args:
        character: The character following path.
        path: List of waypoints.
        lookahead_distance: Distance along path to look ahead.
        path_radius: Radius of path corridor.
        current_path_index: Current waypoint index.

    Returns:
        Tuple of (SteeringOutput, updated_path_index).
    """
    if not path or current_path_index >= len(path):
        return (SteeringOutput((0.0, 0.0)), current_path_index)

    current_target = path[current_path_index]

    dx = current_target[0] - character.x
    dy = current_target[1] - character.y
    dist = math.sqrt(dx * dx + dy * dy)

    if dist < path_radius and current_path_index < len(path) - 1:
        current_path_index += 1
        current_target = path[current_path_index]

    output = seek(character, current_target[0], current_target[1])

    return (output, current_path_index)


def group_movement(
    leader: Boid,
    followers: list[Boid],
    formation_offsets: list[tuple[float, float]],
) -> list[SteeringOutput]:
    """
    Generate steering for group moving together.

    Args:
        leader: The group leader.
        followers: List of follower boids.
        formation_offsets: Formation positions relative to leader.

    Returns:
        List of SteeringOutput for each follower.
    """
    outputs = []

    for i, follower in enumerate(followers):
        if i < len(formation_offsets):
            offset_x, offset_y = formation_offsets[i]
            target_x = leader.x + offset_x
            target_y = leader.y + offset_y
        else:
            target_x = leader.x
            target_y = leader.y

        output = arrive(follower, target_x, target_y, slow_radius=5.0)
        outputs.append(output)

    return outputs


def flow_field_following(
    character: Boid,
    flow_field: dict[tuple[int, int], tuple[float, float]],
    cell_size: float = 1.0,
) -> SteeringOutput:
    """
    Follow a pre-computed flow field.

    Args:
        character: The character following field.
        flow_field: Precalculated flow field.
        cell_size: Size of cells in flow field.

    Returns:
        SteeringOutput following field.
    """
    grid_x = int(character.x / cell_size)
    grid_y = int(character.y / cell_size)

    if (grid_x, grid_y) not in flow_field:
        return SteeringOutput((0.0, 0.0))

    flow_vx, flow_vy = flow_field[(grid_x, grid_y)]

    desired_vx = flow_vx * character.max_speed
    desired_vy = flow_vy * character.max_speed

    steering_x = desired_vx - character.vx
    steering_y = desired_vy - character.vy

    mag = math.sqrt(steering_x * steering_x + steering_y * steering_y)
    if mag > character.max_acceleration:
        steering_x = (steering_x / mag) * character.max_acceleration
        steering_y = (steering_y / mag) * character.max_acceleration

    return SteeringOutput((steering_x, steering_y))
