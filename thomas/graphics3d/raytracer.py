"""
Ray tracing: intersection tests, BVH, recursive ray tracing, soft shadows.

Provides:
- Ray intersection with primitives (sphere, triangle, AABB)
- Bounding Volume Hierarchy (BVH) with SAH
- Recursive ray tracing (reflection, refraction)
- Fresnel effect
- Anti-aliasing via supersampling
- Soft shadows via area light sampling
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from thomas.graphics3d import math3d
from thomas.graphics3d._types import (
    AABB,
    Color,
    Light,
    LightType,
    Material,
    Mesh,
    Ray,
    Vec3,
)


@dataclass
class HitResult:
    """Ray-object intersection result."""

    hit: bool = False
    distance: float = float("inf")
    position: Vec3 = None
    normal: Vec3 = None
    material: Material = None
    texcoord: tuple[float, float] = (0.0, 0.0)


def ray_intersect_sphere(ray: Ray, center: Vec3, radius: float) -> tuple[bool, float]:
    """Test ray-sphere intersection.

    Args:
        ray: Ray to test
        center: Sphere center
        radius: Sphere radius

    Returns:
        Tuple of (intersects: bool, distance: float)
    """
    return math3d.ray_intersect_sphere(ray.origin, ray.direction, center, radius)


def ray_intersect_triangle(
    ray: Ray, v0: Vec3, v1: Vec3, v2: Vec3, cull_backface: bool = True
) -> tuple[bool, float, float, float]:
    """Test ray-triangle intersection (Möller-Trumbore).

    Args:
        ray: Ray to test
        v0, v1, v2: Triangle vertices

    Args:
        ray: Ray to test
        v0, v1, v2: Triangle vertices
        cull_backface: If True, skip intersections where the ray approaches the
            triangle from its back side based on winding.

    Returns:
        Tuple of (intersects: bool, t: float, u: float, v: float)
    """
    if cull_backface:
        face_normal = (v1 - v0).cross(v2 - v0)
        if face_normal.dot(ray.direction) <= 1e-9:
            return False, 0.0, 0.0, 0.0

    return math3d.ray_intersect_triangle(ray.origin, ray.direction, v0, v1, v2)


def ray_intersect_aabb(ray: Ray, aabb: AABB) -> tuple[bool, float]:
    """Test ray-AABB intersection (slab method).

    Args:
        ray: Ray to test
        aabb: Axis-aligned bounding box

    Returns:
        Tuple of (intersects: bool, distance: float)
    """
    return math3d.ray_intersect_aabb(ray.origin, ray.direction, aabb)


def fresnel_schlick(cos_theta: float, f0: float) -> float:
    """Compute Fresnel factor via Schlick approximation.

    Args:
        cos_theta: Cosine of angle between view and normal
        f0: Base reflectivity

    Returns:
        Fresnel factor [0, 1]
    """
    return f0 + (1 - f0) * ((1 - cos_theta) ** 5)


def refract_direction(incident: Vec3, normal: Vec3, ior: float) -> Vec3 | None:
    """Compute refraction direction via Snell's law.

    Args:
        incident: Incident direction (normalized)
        normal: Surface normal (normalized)
        ior: Index of refraction ratio (n2/n1)

    Returns:
        Refraction direction or None if total internal reflection
    """
    cos_i = -incident.dot(normal)
    sin_sq_t = ior * ior * (1 - cos_i * cos_i)

    if sin_sq_t > 1:
        # Total internal reflection
        return None

    cos_t = math.sqrt(1 - sin_sq_t)
    return incident * ior + normal * (ior * cos_i - cos_t)


@dataclass
class BVHNode:
    """BVH tree node."""

    bounds: AABB
    triangles: list[tuple[int, int, int]] = None  # (v0, v1, v2) indices
    left: BVHNode = None
    right: BVHNode = None
    is_leaf: bool = False


class BVH:
    """Bounding Volume Hierarchy for ray tracing."""

    def __init__(self, mesh: Mesh) -> None:
        """Build BVH from mesh.

        Args:
            mesh: Input mesh
        """
        self.mesh = mesh
        self.root = None

        # Extract triangles
        triangles: list[tuple[int, int, int]] = []
        for i in range(0, len(mesh.indices), 3):
            triangles.append((mesh.indices[i], mesh.indices[i + 1], mesh.indices[i + 2]))

        # Build BVH
        self.root = self._build_bvh(triangles, 0)

    def _build_bvh(self, triangles: list[tuple[int, int, int]], depth: int) -> BVHNode:
        """Recursively build BVH node.

        Uses Surface Area Heuristic (SAH) for split selection.

        Args:
            triangles: List of triangle indices
            depth: Current tree depth

        Returns:
            BVH node
        """
        if not triangles:
            return None

        # Compute bounds
        bounds = self._compute_bounds(triangles)

        # Leaf node
        if len(triangles) <= 4 or depth > 20:
            node = BVHNode(bounds=bounds, triangles=triangles, is_leaf=True)
            return node

        # Find best split using SAH
        best_axis = 0
        best_cost = float("inf")
        best_split_idx = 0

        for axis in range(3):
            # Sort triangles along axis
            sorted_triangles = sorted(triangles, key=lambda t: self._get_triangle_center(t, axis))

            for split_idx in range(1, len(sorted_triangles)):
                left = sorted_triangles[:split_idx]
                right = sorted_triangles[split_idx:]

                if not left or not right:
                    continue

                left_bounds = self._compute_bounds(left)
                right_bounds = self._compute_bounds(right)

                cost = len(left) * left_bounds.extent().length() + len(right) * right_bounds.extent().length()

                if cost < best_cost:
                    best_cost = cost
                    best_axis = axis
                    best_split_idx = split_idx

        # Re-sort by best axis and split
        sorted_triangles = sorted(triangles, key=lambda t: self._get_triangle_center(t, best_axis))

        left_triangles = sorted_triangles[:best_split_idx]
        right_triangles = sorted_triangles[best_split_idx:]

        node = BVHNode(bounds=bounds)
        node.left = self._build_bvh(left_triangles, depth + 1)
        node.right = self._build_bvh(right_triangles, depth + 1)

        return node

    def _compute_bounds(self, triangles: list[tuple[int, int, int]]) -> AABB:
        """Compute bounds for list of triangles."""
        points: list[Vec3] = []
        for v0_idx, v1_idx, v2_idx in triangles:
            points.append(self.mesh.vertices[v0_idx].position)
            points.append(self.mesh.vertices[v1_idx].position)
            points.append(self.mesh.vertices[v2_idx].position)

        return math3d.aabb_from_points(points)

    def _get_triangle_center(self, triangle: tuple[int, int, int], axis: int) -> float:
        """Get triangle center component along axis."""
        v0_idx, v1_idx, v2_idx = triangle
        v0 = self.mesh.vertices[v0_idx].position
        v1 = self.mesh.vertices[v1_idx].position
        v2 = self.mesh.vertices[v2_idx].position

        center = (v0 + v1 + v2) * (1 / 3)

        if axis == 0:
            return center.x
        elif axis == 1:
            return center.y
        else:
            return center.z

    def intersect(self, ray: Ray, max_distance: float = float("inf")) -> HitResult:
        """Find closest ray-mesh intersection.

        Args:
            ray: Ray to test
            max_distance: Maximum distance to search

        Returns:
            Intersection result
        """
        result = HitResult()
        self._intersect_node(self.root, ray, max_distance, result)
        return result

    def _intersect_node(self, node: BVHNode, ray: Ray, max_distance: float, result: HitResult) -> None:
        """Recursively traverse BVH and find intersections."""
        if node is None:
            return

        # Bounds check
        intersects, _ = ray_intersect_aabb(ray, node.bounds)
        if not intersects:
            return

        if node.is_leaf:
            # Test all triangles in leaf
            for v0_idx, v1_idx, v2_idx in node.triangles:
                v0 = self.mesh.vertices[v0_idx].position
                v1 = self.mesh.vertices[v1_idx].position
                v2 = self.mesh.vertices[v2_idx].position

                hit, t, u, v = ray_intersect_triangle(ray, v0, v1, v2, cull_backface=False)

                if hit and 0 < t < min(result.distance, max_distance):
                    result.hit = True
                    result.distance = t
                    result.position = ray.at(t)

                    # Compute normal
                    edge1 = v1 - v0
                    edge2 = v2 - v0
                    result.normal = edge1.cross(edge2).normalize()

                    result.material = Material()  # Could fetch from mesh
                    result.texcoord = (u, v)

        else:
            # Traverse children
            self._intersect_node(node.left, ray, max_distance, result)
            self._intersect_node(node.right, ray, max_distance, result)


class Raytracer:
    """High-level ray tracer."""

    def __init__(self, max_bounces: int = 5) -> None:
        """Initialize ray tracer.

        Args:
            max_bounces: Maximum ray bounces
        """
        self.max_bounces = max_bounces
        self.bvhs: list[BVH] = []

    def add_mesh(self, mesh: Mesh) -> None:
        """Add mesh to scene.

        Args:
            mesh: Mesh to add
        """
        self.bvhs.append(BVH(mesh))

    def trace_ray(
        self,
        ray: Ray,
        background_color: Color = Color(0.1, 0.1, 0.1, 1),
    ) -> Color:
        """Trace single ray through scene.

        Args:
            ray: Ray to trace
            background_color: Color if no hit

        Returns:
            Traced color
        """
        return self._trace_recursive(ray, 0, background_color)

    def _trace_recursive(self, ray: Ray, bounce: int, background_color: Color) -> Color:
        """Recursively trace ray."""
        if bounce > self.max_bounces:
            return background_color

        # Find closest intersection
        closest = HitResult()
        for bvh in self.bvhs:
            hit = bvh.intersect(ray)
            if hit.hit and hit.distance < closest.distance:
                closest = hit

        if not closest.hit:
            return background_color

        # Simple Blinn-Phong at hit point
        result = closest.material.ambient

        # Add a simple light at camera position
        light_dir = ray.direction * -1
        n_dot_l = max(0, closest.normal.dot(light_dir))
        result = result + closest.material.diffuse * n_dot_l

        # Reflection
        if closest.material.metallic > 0.5:
            reflect_dir = ray.direction - closest.normal * (2 * ray.direction.dot(closest.normal))
            reflect_ray = Ray(closest.position + reflect_dir * 0.01, reflect_dir)
            reflect_color = self._trace_recursive(reflect_ray, bounce + 1, background_color)
            result = result + reflect_color * closest.material.metallic

        # Refraction
        if closest.material.ior > 1.0:
            refract_dir = refract_direction(ray.direction, closest.normal, 1.0 / closest.material.ior)
            if refract_dir is not None:
                refract_ray = Ray(closest.position + refract_dir * 0.01, refract_dir)
                refract_color = self._trace_recursive(refract_ray, bounce + 1, background_color)

                cos_i = -ray.direction.dot(closest.normal)
                f = fresnel_schlick(cos_i, 0.04)

                result = result + refract_color * (1 - f)

        return result.clamp()


def compute_antialiasing_jitter(sample_x: float, sample_y: float, seed: int) -> tuple[float, float]:
    """Compute sub-pixel jitter for anti-aliasing.

    Args:
        sample_x, sample_y: Sample index
        seed: Random seed

    Returns:
        Jitter offsets in [0, 1)
    """
    # Simple pseudo-random via Xorshift
    x = int(sample_x + sample_y * 73856093 ^ seed * 19349663)
    y = int(sample_y + sample_x * 83492791 ^ seed * 17943463)

    x = (x * 16807) % 2147483647
    y = (y * 16807) % 2147483647

    jitter_x = (x % 256) / 256
    jitter_y = (y % 256) / 256

    return jitter_x, jitter_y


def compute_soft_shadow(
    position: Vec3,
    light: Light,
    scene_bvhs: list[BVH],
    num_samples: int = 4,
) -> float:
    """Compute soft shadow factor via area light sampling.

    Args:
        position: Surface position
        light: Light source
        scene_bvhs: BVH structures for scene
        num_samples: Number of light samples

    Returns:
        Shadow factor [0, 1]
    """
    if light.type == LightType.DIRECTIONAL:
        # Directional lights use small offset sampling
        lit_count = 0

        for i in range(num_samples):
            jitter_x, jitter_y = compute_antialiasing_jitter(i, 0, 42)
            offset = Vec3(
                (jitter_x - 0.5) * light.range * 0.01,
                (jitter_y - 0.5) * light.range * 0.01,
                0,
            )

            light_pos = light.position + offset
            light_dir = (light_pos - position).normalize()

            ray = Ray(position + light_dir * 0.01, light_dir)
            shadow_dist = (light_pos - position).length()

            # Check if light is occluded
            occluded = False
            for bvh in scene_bvhs:
                hit = bvh.intersect(ray, shadow_dist)
                if hit.hit:
                    occluded = True
                    break

            if not occluded:
                lit_count += 1

        return lit_count / num_samples

    else:
        # Point light: sample around light position
        lit_count = 0

        for i in range(num_samples):
            jitter_x, jitter_y = compute_antialiasing_jitter(i, 0, 42)

            # Sample random direction from light
            theta = jitter_x * 2 * math.pi
            phi = math.acos(jitter_y)

            sample_x = math.sin(phi) * math.cos(theta)
            sample_y = math.sin(phi) * math.sin(theta)
            sample_z = math.cos(phi)

            sample_pos = light.position + Vec3(sample_x, sample_y, sample_z) * 0.1

            light_dir = (sample_pos - position).normalize()
            ray = Ray(position + light_dir * 0.01, light_dir)
            shadow_dist = (sample_pos - position).length()

            # Check occlusion
            occluded = False
            for bvh in scene_bvhs:
                hit = bvh.intersect(ray, shadow_dist)
                if hit.hit:
                    occluded = True
                    break

            if not occluded:
                lit_count += 1

        return lit_count / num_samples
