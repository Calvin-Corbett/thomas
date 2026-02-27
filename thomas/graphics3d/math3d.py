"""
3D mathematical operations and transformations.

Provides:
- Vector operations (normalize, length, dot, cross, lerp, slerp)
- Matrix operations (multiply, transpose, inverse, determinant)
- Quaternion operations (from euler, from axis-angle, slerp, nlerp)
- Transformation matrices (translate, rotate, scale, look-at)
- Camera projections (perspective, orthographic)
- Frustum planes extraction
"""

from __future__ import annotations

import math

from thomas.graphics3d._exceptions import MathError
from thomas.graphics3d._types import (
    AABB,
    Mat4,
    Plane,
    Quaternion,
    Vec3,
    Vec4,
)


def vec3_add(a: Vec3, b: Vec3) -> Vec3:
    """Add two 3D vectors."""
    return a + b


def vec3_subtract(a: Vec3, b: Vec3) -> Vec3:
    """Subtract two 3D vectors."""
    return a - b


def vec3_multiply(v: Vec3, scalar: float) -> Vec3:
    """Multiply vector by scalar."""
    return v * scalar


def vec3_dot(a: Vec3, b: Vec3) -> float:
    """Compute dot product of two vectors."""
    return a.dot(b)


def vec3_cross(a: Vec3, b: Vec3) -> Vec3:
    """Compute cross product of two vectors."""
    return a.cross(b)


def vec3_length(v: Vec3) -> float:
    """Compute vector length."""
    return v.length()


def vec3_normalize(v: Vec3) -> Vec3:
    """Normalize vector to unit length."""
    return v.normalize()


def vec3_distance(a: Vec3, b: Vec3) -> float:
    """Compute distance between two points."""
    return (b - a).length()


def vec3_lerp(a: Vec3, b: Vec3, t: float) -> Vec3:
    """Linear interpolation between two vectors."""
    return a.lerp(b, t)


def vec3_slerp(a: Vec3, b: Vec3, t: float) -> Vec3:
    """Spherical linear interpolation (via quaternions)."""
    a_norm = a.normalize()
    b_norm = b.normalize()

    dot_product = a_norm.dot(b_norm)
    dot_product = max(-1.0, min(1.0, dot_product))

    theta = math.acos(dot_product)
    if abs(math.sin(theta)) < 1e-9:
        return vec3_lerp(a, b, t)

    sin_theta = math.sin(theta)
    w1 = math.sin((1 - t) * theta) / sin_theta
    w2 = math.sin(t * theta) / sin_theta

    return a_norm * w1 + b_norm * w2


def mat4_multiply(a: Mat4, b: Mat4) -> Mat4:
    """Multiply two 4x4 matrices."""
    return a * b


def mat4_multiply_vec4(m: Mat4, v: Vec4) -> Vec4:
    """Multiply matrix by vector."""
    return m * v


def mat4_transpose(m: Mat4) -> Mat4:
    """Transpose 4x4 matrix."""
    return m.transpose()


def mat4_determinant(m: Mat4) -> float:
    """Compute determinant of 4x4 matrix."""
    return m.determinant()


def mat4_inverse(m: Mat4) -> Mat4:
    """Compute inverse of 4x4 matrix."""
    return m.inverse()


def quaternion_from_axis_angle(axis: Vec3, angle: float) -> Quaternion:
    """Create quaternion from axis-angle representation."""
    return Quaternion.from_axis_angle(axis, angle)


def quaternion_from_euler(pitch: float, yaw: float, roll: float) -> Quaternion:
    """Create quaternion from Euler angles (radians)."""
    return Quaternion.from_euler(pitch, yaw, roll)


def quaternion_slerp(a: Quaternion, b: Quaternion, t: float) -> Quaternion:
    """Spherical linear interpolation between quaternions."""
    return a.slerp(b, t)


def quaternion_nlerp(a: Quaternion, b: Quaternion, t: float) -> Quaternion:
    """Normalized linear interpolation between quaternions."""
    return a.nlerp(b, t)


def matrix_translate(translation: Vec3) -> Mat4:
    """Create translation matrix."""
    result = Mat4.identity()
    result[0, 3] = translation.x
    result[1, 3] = translation.y
    result[2, 3] = translation.z
    return result


def matrix_rotate(axis: Vec3, angle: float) -> Mat4:
    """Create rotation matrix from axis-angle."""
    q = Quaternion.from_axis_angle(axis, angle)
    return q.to_rotation_matrix()


def matrix_rotate_euler(pitch: float, yaw: float, roll: float) -> Mat4:
    """Create rotation matrix from Euler angles."""
    q = Quaternion.from_euler(pitch, yaw, roll)
    return q.to_rotation_matrix()


def matrix_scale(scale: Vec3) -> Mat4:
    """Create scale matrix."""
    result = Mat4.identity()
    result[0, 0] = scale.x
    result[1, 1] = scale.y
    result[2, 2] = scale.z
    return result


def matrix_look_at(eye: Vec3, target: Vec3, up: Vec3) -> Mat4:
    """Create view matrix (look-at)."""
    forward = (target - eye).normalize()
    right = forward.cross(up.normalize()).normalize()
    actual_up = right.cross(forward).normalize()

    result = Mat4.identity()
    result[0, 0] = right.x
    result[0, 1] = right.y
    result[0, 2] = right.z
    result[0, 3] = -right.dot(eye)

    result[1, 0] = actual_up.x
    result[1, 1] = actual_up.y
    result[1, 2] = actual_up.z
    result[1, 3] = -actual_up.dot(eye)

    result[2, 0] = -forward.x
    result[2, 1] = -forward.y
    result[2, 2] = -forward.z
    result[2, 3] = forward.dot(eye)

    result[3, 0] = 0
    result[3, 1] = 0
    result[3, 2] = 0
    result[3, 3] = 1

    return result


def matrix_perspective(fov: float, aspect: float, near: float, far: float) -> Mat4:
    """Create perspective projection matrix.

    Args:
        fov: Field of view in radians (vertical)
        aspect: Aspect ratio (width / height)
        near: Near clipping plane
        far: Far clipping plane

    Returns:
        Perspective projection matrix in OpenGL convention (NDC: -1 to 1)
    """
    if abs(far - near) < 1e-9:
        raise MathError("Near and far planes too close")

    tan_half_fov = math.tan(fov / 2)

    result = Mat4.identity()
    result[0, 0] = 1 / (aspect * tan_half_fov)
    result[1, 1] = 1 / tan_half_fov
    result[2, 2] = -(far + near) / (far - near)
    result[2, 3] = -(2 * far * near) / (far - near)
    result[3, 2] = -1
    result[3, 3] = 0

    return result


def matrix_orthographic(left: float, right: float, bottom: float, top: float, near: float, far: float) -> Mat4:
    """Create orthographic projection matrix.

    Args:
        left: Left clipping plane
        right: Right clipping plane
        bottom: Bottom clipping plane
        top: Top clipping plane
        near: Near clipping plane
        far: Far clipping plane

    Returns:
        Orthographic projection matrix
    """
    if abs(right - left) < 1e-9 or abs(top - bottom) < 1e-9 or abs(far - near) < 1e-9:
        raise MathError("Degenerate orthographic projection parameters")

    result = Mat4.identity()
    result[0, 0] = 2 / (right - left)
    result[0, 3] = -(right + left) / (right - left)
    result[1, 1] = 2 / (top - bottom)
    result[1, 3] = -(top + bottom) / (top - bottom)
    result[2, 2] = -2 / (far - near)
    result[2, 3] = -(far + near) / (far - near)
    result[3, 3] = 1

    return result


def extract_frustum_planes(projection_view: Mat4) -> list[Plane]:
    """Extract frustum planes from projection-view matrix.

    Returns 6 planes: left, right, top, bottom, near, far.

    Args:
        projection_view: Combined projection * view matrix

    Returns:
        List of 6 frustum planes
    """
    planes: list[Plane] = []

    m = projection_view

    # Left plane
    normal = Vec3(
        m[3, 0] + m[0, 0],
        m[3, 1] + m[0, 1],
        m[3, 2] + m[0, 2],
    )
    dist = m[3, 3] + m[0, 3]
    normal = normal.normalize()
    planes.append(Plane(normal, dist))

    # Right plane
    normal = Vec3(
        m[3, 0] - m[0, 0],
        m[3, 1] - m[0, 1],
        m[3, 2] - m[0, 2],
    )
    dist = m[3, 3] - m[0, 3]
    normal = normal.normalize()
    planes.append(Plane(normal, dist))

    # Top plane
    normal = Vec3(
        m[3, 0] - m[1, 0],
        m[3, 1] - m[1, 1],
        m[3, 2] - m[1, 2],
    )
    dist = m[3, 3] - m[1, 3]
    normal = normal.normalize()
    planes.append(Plane(normal, dist))

    # Bottom plane
    normal = Vec3(
        m[3, 0] + m[1, 0],
        m[3, 1] + m[1, 1],
        m[3, 2] + m[1, 2],
    )
    dist = m[3, 3] + m[1, 3]
    normal = normal.normalize()
    planes.append(Plane(normal, dist))

    # Near plane
    normal = Vec3(
        m[3, 0] + m[2, 0],
        m[3, 1] + m[2, 1],
        m[3, 2] + m[2, 2],
    )
    dist = m[3, 3] + m[2, 3]
    normal = normal.normalize()
    planes.append(Plane(normal, dist))

    # Far plane
    normal = Vec3(
        m[3, 0] - m[2, 0],
        m[3, 1] - m[2, 1],
        m[3, 2] - m[2, 2],
    )
    dist = m[3, 3] - m[2, 3]
    normal = normal.normalize()
    planes.append(Plane(normal, dist))

    return planes


def aabb_from_points(points: list[Vec3]) -> AABB:
    """Create AABB from list of points."""
    if not points:
        return AABB(Vec3(0, 0, 0), Vec3(0, 0, 0))

    min_x = min_y = min_z = float("inf")
    max_x = max_y = max_z = float("-inf")

    for p in points:
        min_x = min(min_x, p.x)
        min_y = min(min_y, p.y)
        min_z = min(min_z, p.z)
        max_x = max(max_x, p.x)
        max_y = max(max_y, p.y)
        max_z = max(max_z, p.z)

    return AABB(Vec3(min_x, min_y, min_z), Vec3(max_x, max_y, max_z))


def aabb_intersect(a: AABB, b: AABB) -> bool:
    """Test if two AABBs intersect."""
    return (
        a.min.x <= b.max.x
        and a.max.x >= b.min.x
        and a.min.y <= b.max.y
        and a.max.y >= b.min.y
        and a.min.z <= b.max.z
        and a.max.z >= b.min.z
    )


def aabb_merge(a: AABB, b: AABB) -> AABB:
    """Merge two AABBs into their union."""
    return AABB(
        Vec3(
            min(a.min.x, b.min.x),
            min(a.min.y, b.min.y),
            min(a.min.z, b.min.z),
        ),
        Vec3(
            max(a.max.x, b.max.x),
            max(a.max.y, b.max.y),
            max(a.max.z, b.max.z),
        ),
    )


def ray_intersect_sphere(
    ray_origin: Vec3, ray_direction: Vec3, sphere_center: Vec3, sphere_radius: float
) -> tuple[bool, float]:
    """Test ray-sphere intersection.

    Args:
        ray_origin: Ray starting point
        ray_direction: Ray direction (assumed normalized)
        sphere_center: Sphere center
        sphere_radius: Sphere radius

    Returns:
        Tuple of (intersects: bool, t: float) where t is distance along ray
    """
    oc = ray_origin - sphere_center
    a = ray_direction.dot(ray_direction)
    b = 2 * oc.dot(ray_direction)
    c = oc.dot(oc) - sphere_radius * sphere_radius

    discriminant = b * b - 4 * a * c

    if discriminant < 0:
        return False, 0.0

    sqrt_disc = math.sqrt(discriminant)
    t1 = (-b - sqrt_disc) / (2 * a)
    t2 = (-b + sqrt_disc) / (2 * a)
    hit_epsilon = 1e-9

    if t1 >= 0:
        return True, t1 + hit_epsilon
    if t2 >= 0:
        return True, t2 + hit_epsilon

    return False, 0.0


def ray_intersect_triangle(
    ray_origin: Vec3,
    ray_direction: Vec3,
    v0: Vec3,
    v1: Vec3,
    v2: Vec3,
) -> tuple[bool, float, float, float]:
    """Test ray-triangle intersection using Möller-Trumbore algorithm.

    Args:
        ray_origin: Ray starting point
        ray_direction: Ray direction (assumed normalized)
        v0, v1, v2: Triangle vertices

    Returns:
        Tuple of (intersects: bool, t: float, u: float, v: float)
        where barycentric coordinates are (1-u-v, u, v)
    """
    epsilon = 1e-8

    edge1 = v1 - v0
    edge2 = v2 - v0
    h = ray_direction.cross(edge2)
    a = edge1.dot(h)

    if abs(a) < epsilon:
        return False, 0.0, 0.0, 0.0

    f = 1.0 / a
    s = ray_origin - v0
    u = f * s.dot(h)

    if u < 0.0 or u > 1.0:
        return False, 0.0, 0.0, 0.0

    q = s.cross(edge1)
    v = f * ray_direction.dot(q)

    if v < 0.0 or u + v > 1.0:
        return False, 0.0, 0.0, 0.0

    t = f * edge2.dot(q)

    if t > epsilon:
        return True, t, u, v

    return False, 0.0, 0.0, 0.0


def ray_intersect_aabb(ray_origin: Vec3, ray_direction: Vec3, aabb: AABB) -> tuple[bool, float]:
    """Test ray-AABB intersection using slab method.

    Args:
        ray_origin: Ray starting point
        ray_direction: Ray direction
        aabb: Axis-aligned bounding box

    Returns:
        Tuple of (intersects: bool, t: float)
    """
    t_min = float("-inf")
    t_max = float("inf")

    for axis in range(3):
        if axis == 0:
            origin_coord = ray_origin.x
            dir_coord = ray_direction.x
            min_coord = aabb.min.x
            max_coord = aabb.max.x
        elif axis == 1:
            origin_coord = ray_origin.y
            dir_coord = ray_direction.y
            min_coord = aabb.min.y
            max_coord = aabb.max.y
        else:
            origin_coord = ray_origin.z
            dir_coord = ray_direction.z
            min_coord = aabb.min.z
            max_coord = aabb.max.z

        if abs(dir_coord) < 1e-9:
            if origin_coord < min_coord or origin_coord > max_coord:
                return False, 0.0
        else:
            t1 = (min_coord - origin_coord) / dir_coord
            t2 = (max_coord - origin_coord) / dir_coord

            if t1 > t2:
                t1, t2 = t2, t1

            t_min = max(t_min, t1)
            t_max = min(t_max, t2)

            if t_min > t_max:
                return False, 0.0

    if t_min >= 0:
        return True, t_min
    if t_max >= 0:
        return True, t_max

    return False, 0.0


def vector_transform_direction(v: Vec3, m: Mat4) -> Vec3:
    """Transform direction vector (ignores translation)."""
    v4 = m * Vec4(v.x, v.y, v.z, 0)
    return Vec3(v4.x, v4.y, v4.z)


def vector_transform_position(v: Vec3, m: Mat4) -> Vec3:
    """Transform position vector (includes translation)."""
    v4 = m * Vec4(v.x, v.y, v.z, 1)
    return v4.to_vec3()


def normalize_homogeneous(v: Vec4) -> Vec3:
    """Perspective divide of homogeneous coordinate."""
    return v.to_vec3()


def viewport_transform(ndc_x: float, ndc_y: float, viewport_width: int, viewport_height: int) -> tuple[float, float]:
    """Transform from NDC [-1, 1] to viewport [0, width] x [0, height]."""
    screen_x = (ndc_x + 1) * 0.5 * viewport_width
    screen_y = (1 - ndc_y) * 0.5 * viewport_height

    return screen_x, screen_y
