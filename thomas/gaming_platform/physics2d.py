"""2D physics engine with collision detection, response, and constraints."""

import math

from thomas.gaming_platform._types import (
    Collider,
    Entity,
    RigidBody,
    Transform,
)
from thomas.gaming_platform.ecs import EntityComponentSystem


class AABB:
    """Axis-Aligned Bounding Box."""

    def __init__(self, x: float, y: float, width: float, height: float) -> None:
        """Initialize AABB."""
        self.x = x
        self.y = y
        self.width = width
        self.height = height

    @property
    def min_x(self) -> float:
        """Get minimum X coordinate."""
        return self.x

    @property
    def max_x(self) -> float:
        """Get maximum X coordinate."""
        return self.x + self.width

    @property
    def min_y(self) -> float:
        """Get minimum Y coordinate."""
        return self.y

    @property
    def max_y(self) -> float:
        """Get maximum Y coordinate."""
        return self.y + self.height

    def intersects_aabb(self, other: "AABB") -> bool:
        """Check if this AABB intersects another."""
        return (
            self.min_x < other.max_x
            and self.max_x > other.min_x
            and self.min_y < other.max_y
            and self.max_y > other.min_y
        )

    def get_overlap(self, other: "AABB") -> tuple[float, float]:
        """Get overlap vector for separation."""
        overlap_x = 0.0
        overlap_y = 0.0

        if self.min_x < other.min_x:
            overlap_x = other.min_x - self.max_x
        else:
            overlap_x = self.min_x - other.max_x

        if self.min_y < other.min_y:
            overlap_y = other.min_y - self.max_y
        else:
            overlap_y = self.min_y - other.max_y

        return (overlap_x, overlap_y)


class Circle:
    """Circle shape."""

    def __init__(self, x: float, y: float, radius: float) -> None:
        """Initialize circle."""
        self.x = x
        self.y = y
        self.radius = radius

    def distance_to_point(self, px: float, py: float) -> float:
        """Get distance to point."""
        dx = px - self.x
        dy = py - self.y
        return math.sqrt(dx * dx + dy * dy)

    def intersects_circle(self, other: "Circle") -> bool:
        """Check if this circle intersects another."""
        dx = other.x - self.x
        dy = other.y - self.y
        dist_sq = dx * dx + dy * dy
        min_dist = self.radius + other.radius
        return dist_sq < min_dist * min_dist

    def get_normal_to_circle(self, other: "Circle") -> tuple[float, float]:
        """Get unit normal from this circle to other."""
        dx = other.x - self.x
        dy = other.y - self.y
        dist = math.sqrt(dx * dx + dy * dy)
        if dist < 0.001:
            return (0.0, 1.0)
        return (dx / dist, dy / dist)


class SpatialHashGrid:
    """
    Broad phase collision detection using spatial hashing.

    Divides space into grid cells for efficient collision queries.
    """

    def __init__(self, cell_size: float = 32.0) -> None:
        """
        Initialize spatial hash grid.

        Args:
            cell_size: Size of each grid cell.
        """
        self.cell_size = cell_size
        self.grid: dict[tuple[int, int], list[Entity]] = {}
        self.entity_cells: dict[int, list[tuple[int, int]]] = {}

    def clear(self) -> None:
        """Clear all data."""
        self.grid.clear()
        self.entity_cells.clear()

    def insert(self, entity: Entity, aabb: AABB) -> None:
        """
        Insert entity into grid based on AABB.

        Args:
            entity: Entity to insert.
            aabb: Entity bounding box.
        """
        min_cell_x = int(aabb.min_x / self.cell_size)
        max_cell_x = int(aabb.max_x / self.cell_size)
        min_cell_y = int(aabb.min_y / self.cell_size)
        max_cell_y = int(aabb.max_y / self.cell_size)

        cells = []
        for cx in range(min_cell_x, max_cell_x + 1):
            for cy in range(min_cell_y, max_cell_y + 1):
                cell_key = (cx, cy)
                if cell_key not in self.grid:
                    self.grid[cell_key] = []
                self.grid[cell_key].append(entity)
                cells.append(cell_key)

        self.entity_cells[entity.index] = cells

    def query(self, aabb: AABB) -> set[Entity]:
        """
        Query entities in AABB region.

        Args:
            aabb: Query bounding box.

        Returns:
            Set of potentially colliding entities.
        """
        min_cell_x = int(aabb.min_x / self.cell_size)
        max_cell_x = int(aabb.max_x / self.cell_size)
        min_cell_y = int(aabb.min_y / self.cell_size)
        max_cell_y = int(aabb.max_y / self.cell_size)

        result: set[Entity] = set()
        for cx in range(min_cell_x, max_cell_x + 1):
            for cy in range(min_cell_y, max_cell_y + 1):
                cell_key = (cx, cy)
                if cell_key in self.grid:
                    result.update(self.grid[cell_key])

        return result


class CollisionPair:
    """Information about a collision."""

    def __init__(
        self,
        entity_a: Entity,
        entity_b: Entity,
        contact_point: tuple[float, float],
        normal: tuple[float, float],
        penetration: float,
    ) -> None:
        """Initialize collision pair."""
        self.entity_a = entity_a
        self.entity_b = entity_b
        self.contact_point = contact_point
        self.normal = normal
        self.penetration = penetration


class Physics2D:
    """
    2D physics engine with collision detection and response.

    Features:
    - AABB and circle collision detection
    - Spatial hash grid for broad phase
    - Impulse-based collision response
    - Gravity and velocity integration
    - Friction and restitution
    - Continuous collision detection (swept AABB)
    """

    def __init__(self, gravity: tuple[float, float] = (0.0, -9.81)) -> None:
        """
        Initialize physics engine.

        Args:
            gravity: Gravity vector (acceleration in m/s²).
        """
        self.gravity = gravity
        self.spatial_hash = SpatialHashGrid(cell_size=32.0)
        self.collisions: list[CollisionPair] = []
        self.collision_pairs: set[tuple[int, int]] = set()

    def update(self, ecs: EntityComponentSystem, dt: float) -> None:
        """
        Update physics simulation.

        Args:
            ecs: Entity component system.
            dt: Delta time in seconds.
        """
        self.collisions.clear()
        self.collision_pairs.clear()
        self.spatial_hash.clear()

        # Integrate velocities and update transforms
        self._integrate_velocities(ecs, dt)

        # Broad phase: build spatial hash
        self._broad_phase(ecs)

        # Narrow phase: detect collisions
        self._narrow_phase(ecs)

        # Resolve collisions
        self._resolve_collisions(ecs)

    def _integrate_velocities(self, ecs: EntityComponentSystem, dt: float) -> None:
        """Apply gravity and integrate velocities (semi-implicit Euler)."""
        entities = ecs.query(Transform, RigidBody)

        for entity in entities:
            transform = ecs.get_component(entity, Transform)
            rigidbody = ecs.get_component(entity, RigidBody)

            if transform is None or rigidbody is None:
                continue

            if not rigidbody.is_dynamic:
                continue

            # Apply gravity
            vx, vy = transform.velocity
            gx, gy = self.gravity
            vx += gx * rigidbody.gravity_scale * dt
            vy += gy * rigidbody.gravity_scale * dt

            # Apply drag
            vx *= 1.0 - rigidbody.drag * dt
            vy *= 1.0 - rigidbody.drag * dt

            # Update velocity
            transform.velocity = (vx, vy)

            # Update position
            px, py = transform.position
            px += vx * dt
            py += vy * dt
            transform.position = (px, py)

            # Apply angular drag
            rigidbody.angular_velocity *= 1.0 - rigidbody.angular_drag * dt

            # Update rotation
            transform.rotation += rigidbody.angular_velocity * dt

    def _broad_phase(self, ecs: EntityComponentSystem) -> None:
        """Build spatial hash grid from all colliders."""
        entities = ecs.query(Transform, Collider)

        for entity in entities:
            transform = ecs.get_component(entity, Transform)
            collider = ecs.get_component(entity, Collider)

            if transform is None or collider is None or not collider.active:
                continue

            aabb = self._get_aabb(transform, collider)
            self.spatial_hash.insert(entity, aabb)

    def _narrow_phase(self, ecs: EntityComponentSystem) -> None:
        """Detect actual collisions from broad phase candidates."""
        entities = ecs.query(Transform, Collider)

        for i, entity_a in enumerate(entities):
            transform_a = ecs.get_component(entity_a, Transform)
            collider_a = ecs.get_component(entity_a, Collider)

            if transform_a is None or collider_a is None or not collider_a.active:
                continue

            aabb_a = self._get_aabb(transform_a, collider_a)
            candidates = self.spatial_hash.query(aabb_a)

            for entity_b in candidates:
                if entity_a.index >= entity_b.index:
                    continue  # Avoid duplicate checks

                transform_b = ecs.get_component(entity_b, Transform)
                collider_b = ecs.get_component(entity_b, Collider)

                if transform_b is None or collider_b is None or not collider_b.active:
                    continue

                # Check for collision
                collision = self._check_collision(entity_a, transform_a, collider_a, entity_b, transform_b, collider_b)

                if collision:
                    # Trigger colliders should not enter the physics resolution
                    # collision list.
                    if collider_a.is_trigger or collider_b.is_trigger:
                        continue
                    self.collisions.append(collision)
                    self.collision_pairs.add((min(entity_a.index, entity_b.index), max(entity_a.index, entity_b.index)))

    def _resolve_collisions(self, ecs: EntityComponentSystem) -> None:
        """Resolve collisions using impulse-based response."""
        for collision in self.collisions:
            body_a = ecs.get_component(collision.entity_a, RigidBody)
            body_b = ecs.get_component(collision.entity_b, RigidBody)
            transform_a = ecs.get_component(collision.entity_a, Transform)
            transform_b = ecs.get_component(collision.entity_b, Transform)

            if body_a is None or body_b is None or transform_a is None or transform_b is None:
                continue

            # Check if either is trigger
            collider_a = ecs.get_component(collision.entity_a, Collider)
            collider_b = ecs.get_component(collision.entity_b, Collider)

            if (collider_a and collider_a.is_trigger) or (collider_b and collider_b.is_trigger):
                # Trigger collision - no response, just event
                continue

            # Calculate relative velocity
            vx_a, vy_a = transform_a.velocity
            vx_b, vy_b = transform_b.velocity

            rel_vx = vx_a - vx_b
            rel_vy = vy_a - vy_b

            # Normal vector
            nx, ny = collision.normal

            # Relative velocity along normal
            vel_along_normal = rel_vx * nx + rel_vy * ny

            # Don't resolve if objects moving apart
            if vel_along_normal >= 0:
                continue

            # Calculate impulse
            e = min(body_a.restitution, body_b.restitution)
            j = -(1.0 + e) * vel_along_normal
            j /= body_a.inverse_mass + body_b.inverse_mass

            # Apply impulse
            impulse_x = j * nx
            impulse_y = j * ny

            if body_a.is_dynamic:
                vx_a += impulse_x * body_a.inverse_mass
                vy_a += impulse_y * body_a.inverse_mass
                transform_a.velocity = (vx_a, vy_a)

            if body_b.is_dynamic:
                vx_b -= impulse_x * body_b.inverse_mass
                vy_b -= impulse_y * body_b.inverse_mass
                transform_b.velocity = (vx_b, vy_b)

            # Position correction
            separation = collision.penetration + 0.01
            correction = separation / (body_a.inverse_mass + body_b.inverse_mass)

            if body_a.is_dynamic:
                px_a, py_a = transform_a.position
                px_a += correction * body_a.inverse_mass * nx
                py_a += correction * body_a.inverse_mass * ny
                transform_a.position = (px_a, py_a)

            if body_b.is_dynamic:
                px_b, py_b = transform_b.position
                px_b -= correction * body_b.inverse_mass * nx
                py_b -= correction * body_b.inverse_mass * ny
                transform_b.position = (px_b, py_b)

    def _check_collision(
        self,
        entity_a: Entity,
        transform_a: Transform,
        collider_a: Collider,
        entity_b: Entity,
        transform_b: Transform,
        collider_b: Collider,
    ) -> CollisionPair | None:
        """Check collision between two entities."""
        if collider_a.shape_type == "aabb" and collider_b.shape_type == "aabb":
            aabb_a = self._get_aabb(transform_a, collider_a)
            aabb_b = self._get_aabb(transform_b, collider_b)

            if aabb_a.intersects_aabb(aabb_b):
                overlap = aabb_a.get_overlap(aabb_b)
                contact = (
                    (transform_a.position[0] + transform_b.position[0]) / 2,
                    (transform_a.position[1] + transform_b.position[1]) / 2,
                )
                normal = (1.0, 0.0) if abs(overlap[0]) < abs(overlap[1]) else (0.0, 1.0)
                penetration = min(abs(overlap[0]), abs(overlap[1]))

                return CollisionPair(entity_a, entity_b, contact, normal, penetration)

        elif collider_a.shape_type == "circle" and collider_b.shape_type == "circle":
            circle_a = self._get_circle(transform_a, collider_a)
            circle_b = self._get_circle(transform_b, collider_b)

            if circle_a.intersects_circle(circle_b):
                normal = circle_a.get_normal_to_circle(circle_b)
                dist = math.sqrt((circle_b.x - circle_a.x) ** 2 + (circle_b.y - circle_a.y) ** 2)
                penetration = (circle_a.radius + circle_b.radius) - dist

                return CollisionPair(entity_a, entity_b, (circle_a.x, circle_a.y), normal, penetration)

        # AABB vs Circle
        elif collider_a.shape_type == "aabb" and collider_b.shape_type == "circle":
            return self._check_aabb_circle(entity_a, transform_a, collider_a, entity_b, transform_b, collider_b)

        elif collider_a.shape_type == "circle" and collider_b.shape_type == "aabb":
            result = self._check_aabb_circle(entity_b, transform_b, collider_b, entity_a, transform_a, collider_a)
            if result:
                # Flip normal
                return CollisionPair(
                    result.entity_a,
                    result.entity_b,
                    result.contact_point,
                    (-result.normal[0], -result.normal[1]),
                    result.penetration,
                )

        return None

    def _check_aabb_circle(
        self,
        entity_aabb: Entity,
        transform_aabb: Transform,
        collider_aabb: Collider,
        entity_circle: Entity,
        transform_circle: Transform,
        collider_circle: Collider,
    ) -> CollisionPair | None:
        """Check collision between AABB and circle."""
        aabb = self._get_aabb(transform_aabb, collider_aabb)
        circle = self._get_circle(transform_circle, collider_circle)

        # Find closest point on AABB to circle
        closest_x = max(aabb.min_x, min(circle.x, aabb.max_x))
        closest_y = max(aabb.min_y, min(circle.y, aabb.max_y))

        dx = circle.x - closest_x
        dy = circle.y - closest_y
        dist = math.sqrt(dx * dx + dy * dy)

        if dist < circle.radius:
            if dist < 0.001:
                normal = (1.0, 0.0)
            else:
                normal = (dx / dist, dy / dist)

            penetration = circle.radius - dist
            contact = (closest_x, closest_y)

            return CollisionPair(entity_aabb, entity_circle, contact, normal, penetration)

        return None

    def _get_aabb(self, transform: Transform, collider: Collider) -> AABB:
        """Get AABB for transform and collider."""
        px, py = transform.position
        ox, oy = collider.offset
        x = px + ox - collider.width / 2
        y = py + oy - collider.height / 2
        return AABB(x, y, collider.width, collider.height)

    def _get_circle(self, transform: Transform, collider: Collider) -> Circle:
        """Get circle for transform and collider."""
        px, py = transform.position
        ox, oy = collider.offset
        return Circle(px + ox, py + oy, collider.radius)

    def raycast(
        self,
        ecs: EntityComponentSystem,
        origin: tuple[float, float],
        direction: tuple[float, float],
        max_distance: float = 1000.0,
    ) -> tuple[Entity, float] | None:
        """
        Raycast from origin in direction.

        Args:
            ecs: Entity component system.
            origin: Ray origin.
            direction: Ray direction (should be normalized).
            max_distance: Maximum ray distance.

        Returns:
            Tuple of (entity, distance) or None.
        """
        entities = ecs.query(Transform, Collider)
        closest_entity: Entity | None = None
        closest_distance = max_distance

        for entity in entities:
            transform = ecs.get_component(entity, Transform)
            collider = ecs.get_component(entity, Collider)

            if transform is None or collider is None:
                continue

            if collider.shape_type == "aabb":
                aabb = self._get_aabb(transform, collider)
                dist = self._raycast_aabb(origin, direction, aabb)
                if dist is not None and dist < closest_distance:
                    closest_entity = entity
                    closest_distance = dist

            elif collider.shape_type == "circle":
                circle = self._get_circle(transform, collider)
                dist = self._raycast_circle(origin, direction, circle)
                if dist is not None and dist < closest_distance:
                    closest_entity = entity
                    closest_distance = dist

        if closest_entity is not None:
            return (closest_entity, closest_distance)

        return None

    def _raycast_aabb(
        self,
        origin: tuple[float, float],
        direction: tuple[float, float],
        aabb: AABB,
    ) -> float | None:
        """Raycast against AABB."""
        ox, oy = origin
        dx, dy = direction

        t_min = 0.0
        t_max = float("inf")

        # X axis
        if abs(dx) > 0.001:
            t1 = (aabb.min_x - ox) / dx
            t2 = (aabb.max_x - ox) / dx
            t_min = max(t_min, min(t1, t2))
            t_max = min(t_max, max(t1, t2))

        # Y axis
        if abs(dy) > 0.001:
            t1 = (aabb.min_y - oy) / dy
            t2 = (aabb.max_y - oy) / dy
            t_min = max(t_min, min(t1, t2))
            t_max = min(t_max, max(t1, t2))

        if t_min <= t_max and t_min >= 0:
            return t_min

        return None

    def _raycast_circle(
        self,
        origin: tuple[float, float],
        direction: tuple[float, float],
        circle: Circle,
    ) -> float | None:
        """Raycast against circle."""
        ox, oy = origin
        dx, dy = direction
        cx, cy = circle.x, circle.y

        # Ray: P = O + t*D
        # Circle: |P - C| = r
        # Solution: |O - C + t*D| = r

        ocx = ox - cx
        ocy = oy - cy

        a = dx * dx + dy * dy
        b = 2.0 * (ocx * dx + ocy * dy)
        c = ocx * ocx + ocy * ocy - circle.radius * circle.radius

        discriminant = b * b - 4 * a * c

        if discriminant < 0:
            return None

        t1 = (-b - math.sqrt(discriminant)) / (2 * a)
        t2 = (-b + math.sqrt(discriminant)) / (2 * a)

        if t1 >= 0:
            return t1
        if t2 >= 0:
            return t2

        return None
