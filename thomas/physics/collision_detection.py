"""
Collision detection: sphere-sphere, AABB, ray casting, SAT, and GJK.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from thomas.physics._types import AABB, Plane, Ray, Sphere, Vec2, Vec3


@dataclass
class CollisionManifold:
    """Contact information from collision."""

    contact_point: Vec3
    contact_normal: Vec3  # From A to B
    penetration_depth: float
    relative_velocity: Vec3 | None = None


def collide_sphere_sphere(s1: Sphere, s2: Sphere) -> CollisionManifold | None:
    """Detect collision between two spheres.

    Args:
        s1: First sphere
        s2: Second sphere

    Returns:
        CollisionManifold if collision, None otherwise
    """
    distance_vec = s2.center - s1.center
    distance = distance_vec.magnitude()
    sum_radius = s1.radius + s2.radius

    if distance > sum_radius + 1e-9:
        return None

    # Collision detected
    if distance < 1e-9:
        # Spheres are at same center, use arbitrary normal
        contact_normal = Vec3(1, 0, 0)
        contact_point = s1.center
    else:
        contact_normal = distance_vec.normalize()
        contact_point = s1.center + contact_normal * s1.radius

    penetration_depth = sum_radius - distance

    return CollisionManifold(
        contact_point=contact_point,
        contact_normal=contact_normal,
        penetration_depth=penetration_depth,
    )


def collide_aabb_aabb(a: AABB, b: AABB) -> bool:
    """Check if two AABBs overlap.

    Args:
        a: First AABB
        b: Second AABB

    Returns:
        True if AABBs overlap
    """
    return (
        a.min.x <= b.max.x
        and a.max.x >= b.min.x
        and a.min.y <= b.max.y
        and a.max.y >= b.min.y
        and a.min.z <= b.max.z
        and a.max.z >= b.min.z
    )


def collide_sphere_plane(s: Sphere, p: Plane) -> CollisionManifold | None:
    """Detect collision between sphere and plane.

    Args:
        s: Sphere
        p: Plane

    Returns:
        CollisionManifold if collision, None otherwise
    """
    distance = p.distance_to_point(s.center)

    if abs(distance) > s.radius:
        return None

    # Collision detected
    contact_point = p.closest_point_on_plane(s.center)
    contact_normal = p.normal if distance >= 0 else -p.normal
    penetration_depth = s.radius - abs(distance)

    return CollisionManifold(
        contact_point=contact_point,
        contact_normal=contact_normal,
        penetration_depth=penetration_depth,
    )


def collide_aabb_sphere(a: AABB, s: Sphere) -> CollisionManifold | None:
    """Detect collision between AABB and sphere.

    Args:
        a: AABB
        s: Sphere

    Returns:
        CollisionManifold if collision, None otherwise
    """
    # Find closest point on AABB to sphere center
    closest = Vec3(
        max(a.min.x, min(s.center.x, a.max.x)),
        max(a.min.y, min(s.center.y, a.max.y)),
        max(a.min.z, min(s.center.z, a.max.z)),
    )

    distance = s.center.distance_to(closest)

    if distance > s.radius:
        return None

    # Collision detected
    if distance < 1e-9:
        contact_normal = Vec3(1, 0, 0)
    else:
        contact_normal = (s.center - closest).normalize()

    contact_point = closest
    penetration_depth = s.radius - distance

    return CollisionManifold(
        contact_point=contact_point,
        contact_normal=contact_normal,
        penetration_depth=penetration_depth,
    )


def ray_sphere_intersection(r: Ray, s: Sphere) -> float | None:
    """Check ray-sphere intersection.

    Args:
        r: Ray
        s: Sphere

    Returns:
        Parameter t (distance along ray) if intersection, None otherwise
    """
    # Solve |r.origin + t*r.direction - s.center|^2 = r.radius^2
    oc = r.origin - s.center
    a = r.direction.dot(r.direction)
    b = 2.0 * oc.dot(r.direction)
    c = oc.dot(oc) - s.radius * s.radius

    discriminant = b * b - 4 * a * c
    if discriminant < 0:
        return None

    t = (-b - math.sqrt(discriminant)) / (2 * a)
    if t < 0:
        t = (-b + math.sqrt(discriminant)) / (2 * a)

    return t if t >= 0 else None


def ray_aabb_intersection(r: Ray, a: AABB) -> float | None:
    """Check ray-AABB intersection (slab method).

    Args:
        r: Ray
        a: AABB

    Returns:
        Parameter t (distance along ray) if intersection, None otherwise
    """
    t_min = 0.0
    t_max = float("inf")

    for axis in range(3):
        origin_val = r.origin[axis]
        dir_val = r.direction[axis]
        min_val = a.min[axis]
        max_val = a.max[axis]

        if abs(dir_val) < 1e-9:
            if origin_val < min_val or origin_val > max_val:
                return None
        else:
            t1 = (min_val - origin_val) / dir_val
            t2 = (max_val - origin_val) / dir_val

            if t1 > t2:
                t1, t2 = t2, t1

            t_min = max(t_min, t1)
            t_max = min(t_max, t2)

            if t_min > t_max:
                return None

    return t_min if t_min >= 0 else (t_max if t_max >= 0 else None)


def ray_plane_intersection(r: Ray, p: Plane) -> float | None:
    """Check ray-plane intersection.

    Args:
        r: Ray
        p: Plane

    Returns:
        Parameter t (distance along ray) if intersection, None otherwise
    """
    denom = p.normal.dot(r.direction)

    if abs(denom) < 1e-9:
        return None  # Ray parallel to plane

    t = -(p.normal.dot(r.origin) + p.d) / denom
    return t if t >= 0 else None


def sat_collision_2d(vertices_a: list[Vec2], vertices_b: list[Vec2]) -> bool:
    """Separating Axis Theorem for 2D convex polygon collision.

    Args:
        vertices_a: Vertices of first polygon (in order)
        vertices_b: Vertices of second polygon (in order)

    Returns:
        True if polygons collide
    """
    if len(vertices_a) < 3 or len(vertices_b) < 3:
        return False

    def project_polygon(axis: Vec2, vertices: list[Vec2]) -> tuple[float, float]:
        """Project polygon onto axis."""
        projections = [v.dot(axis) for v in vertices]
        return min(projections), max(projections)

    def check_overlap(proj_a: tuple[float, float], proj_b: tuple[float, float]) -> bool:
        """Check if projections overlap."""
        return proj_a[1] >= proj_b[0] and proj_b[1] >= proj_a[0]

    # Get all axes to test (edges of both polygons)
    axes: list[Vec2] = []

    for i in range(len(vertices_a)):
        edge = vertices_a[(i + 1) % len(vertices_a)] - vertices_a[i]
        axis = edge.perpendicular().normalize()
        axes.append(axis)

    for i in range(len(vertices_b)):
        edge = vertices_b[(i + 1) % len(vertices_b)] - vertices_b[i]
        axis = edge.perpendicular().normalize()
        axes.append(axis)

    # Test all axes
    for axis in axes:
        proj_a = project_polygon(axis, vertices_a)
        proj_b = project_polygon(axis, vertices_b)

        if not check_overlap(proj_a, proj_b):
            return False  # Separating axis found

    return True  # No separating axis, collision


def gjk_collision(vertices_a: list[Vec3], vertices_b: list[Vec3]) -> bool:
    """Gilbert-Johnson-Keerthi (GJK) algorithm for collision detection.

    Args:
        vertices_a: Vertices of first convex shape
        vertices_b: Vertices of second convex shape

    Returns:
        True if shapes collide
    """
    if not vertices_a or not vertices_b:
        return False

    def support_function(verts: list[Vec3], direction: Vec3) -> Vec3:
        """Get furthest vertex in direction."""
        max_dot = float("-inf")
        result = verts[0]
        for v in verts:
            dot = v.dot(direction)
            if dot > max_dot:
                max_dot = dot
                result = v
        return result

    def support(direction: Vec3) -> Vec3:
        """Support function for Minkowski difference."""
        return support_function(vertices_a, direction) - support_function(vertices_b, -direction)

    # Initial direction
    direction = vertices_b[0] - vertices_a[0]
    if direction.magnitude_squared() < 1e-9:
        return True

    simplex: list[Vec3] = [support(direction)]
    direction = -direction
    max_iterations = 100

    for _ in range(max_iterations):
        support_point = support(direction)

        if support_point.dot(direction) < 0:
            return False

        simplex.append(support_point)

        # Try to reduce simplex
        if len(simplex) == 2:
            # Line segment
            a, b = simplex[1], simplex[0]
            ab = b - a
            ao = -a
            direction = (ab.cross(ao).cross(ab)).normalize()
        elif len(simplex) == 3:
            # Triangle
            a, b, c = simplex[2], simplex[1], simplex[0]
            ab = b - a
            ac = c - a
            ao = -a

            abc_normal = ab.cross(ac)
            ab_perp = abc_normal.cross(ab)
            ac_perp = ac.cross(abc_normal)

            if ab_perp.dot(ao) > 0:
                simplex = [a, b]
                direction = ab_perp.normalize()
            elif ac_perp.dot(ao) > 0:
                simplex = [a, c]
                direction = ac_perp.normalize()
            else:
                return True
        else:
            # Tetrahedron
            return True

    return False


def generate_collision_manifold(
    pos_a: Vec3,
    pos_b: Vec3,
    vertices_a: list[Vec3] | None = None,
    vertices_b: list[Vec3] | None = None,
    sphere_a: Sphere | None = None,
    sphere_b: Sphere | None = None,
) -> CollisionManifold | None:
    """Generate detailed collision manifold.

    Args:
        pos_a: Position of first object
        pos_b: Position of second object
        vertices_a: Vertices of first object
        vertices_b: Vertices of second object
        sphere_a: First object as sphere (optional)
        sphere_b: Second object as sphere (optional)

    Returns:
        CollisionManifold with contact details
    """
    # Sphere-sphere case
    if sphere_a and sphere_b:
        return collide_sphere_sphere(sphere_a, sphere_b)

    # Sphere-plane case
    if sphere_a and vertices_b:
        # Simple plane approximation: normal from first triangle
        if len(vertices_b) >= 3:
            edge1 = vertices_b[1] - vertices_b[0]
            edge2 = vertices_b[2] - vertices_b[0]
            normal = edge1.cross(edge2).normalize()
            plane = Plane(normal, -normal.dot(vertices_b[0]))
            return collide_sphere_plane(sphere_a, plane)

    return None
