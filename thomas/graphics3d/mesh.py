"""
Mesh operations: generation, manipulation, and optimization.

Provides:
- Mesh generation (cube, sphere, cylinder, cone, plane, torus)
- Normal calculation (face and vertex normals)
- Tangent space calculation
- Mesh merging
- Bounding volume computation
- Mesh simplification via edge collapse
"""

from __future__ import annotations

import math

from thomas.graphics3d import math3d
from thomas.graphics3d._types import (
    AABB,
    UV,
    Mesh,
    Vec3,
    Vertex,
)


def create_cube(size: float = 1.0) -> Mesh:
    """Create cube mesh centered at origin.

    Args:
        size: Half-extent of cube

    Returns:
        Mesh with cube geometry
    """
    s = size
    vertices = [
        # Front face
        Vertex(Vec3(-s, -s, s), Vec3(0, 0, 1), UV(0, 0)),
        Vertex(Vec3(s, -s, s), Vec3(0, 0, 1), UV(1, 0)),
        Vertex(Vec3(s, s, s), Vec3(0, 0, 1), UV(1, 1)),
        Vertex(Vec3(-s, s, s), Vec3(0, 0, 1), UV(0, 1)),
        # Back face
        Vertex(Vec3(s, -s, -s), Vec3(0, 0, -1), UV(0, 0)),
        Vertex(Vec3(-s, -s, -s), Vec3(0, 0, -1), UV(1, 0)),
        Vertex(Vec3(-s, s, -s), Vec3(0, 0, -1), UV(1, 1)),
        Vertex(Vec3(s, s, -s), Vec3(0, 0, -1), UV(0, 1)),
        # Top face
        Vertex(Vec3(-s, s, s), Vec3(0, 1, 0), UV(0, 0)),
        Vertex(Vec3(s, s, s), Vec3(0, 1, 0), UV(1, 0)),
        Vertex(Vec3(s, s, -s), Vec3(0, 1, 0), UV(1, 1)),
        Vertex(Vec3(-s, s, -s), Vec3(0, 1, 0), UV(0, 1)),
        # Bottom face
        Vertex(Vec3(-s, -s, -s), Vec3(0, -1, 0), UV(0, 0)),
        Vertex(Vec3(s, -s, -s), Vec3(0, -1, 0), UV(1, 0)),
        Vertex(Vec3(s, -s, s), Vec3(0, -1, 0), UV(1, 1)),
        Vertex(Vec3(-s, -s, s), Vec3(0, -1, 0), UV(0, 1)),
        # Right face
        Vertex(Vec3(s, -s, s), Vec3(1, 0, 0), UV(0, 0)),
        Vertex(Vec3(s, -s, -s), Vec3(1, 0, 0), UV(1, 0)),
        Vertex(Vec3(s, s, -s), Vec3(1, 0, 0), UV(1, 1)),
        Vertex(Vec3(s, s, s), Vec3(1, 0, 0), UV(0, 1)),
        # Left face
        Vertex(Vec3(-s, -s, -s), Vec3(-1, 0, 0), UV(0, 0)),
        Vertex(Vec3(-s, -s, s), Vec3(-1, 0, 0), UV(1, 0)),
        Vertex(Vec3(-s, s, s), Vec3(-1, 0, 0), UV(1, 1)),
        Vertex(Vec3(-s, s, -s), Vec3(-1, 0, 0), UV(0, 1)),
    ]

    indices = [
        0,
        1,
        2,
        0,
        2,
        3,  # Front
        4,
        5,
        6,
        4,
        6,
        7,  # Back
        8,
        9,
        10,
        8,
        10,
        11,  # Top
        12,
        13,
        14,
        12,
        14,
        15,  # Bottom
        16,
        17,
        18,
        16,
        18,
        19,  # Right
        20,
        21,
        22,
        20,
        22,
        23,  # Left
    ]

    return Mesh(vertices, indices)


def create_sphere(radius: float = 1.0, latitude_segments: int = 32, longitude_segments: int = 32) -> Mesh:
    """Create UV sphere mesh.

    Args:
        radius: Sphere radius
        latitude_segments: Number of segments from pole to pole
        longitude_segments: Number of segments around equator

    Returns:
        Mesh with sphere geometry
    """
    vertices: list[Vertex] = []
    indices: list[int] = []

    for lat in range(latitude_segments + 1):
        theta = (lat / latitude_segments) * math.pi
        sin_theta = math.sin(theta)
        cos_theta = math.cos(theta)

        for lon in range(longitude_segments + 1):
            phi = (lon / longitude_segments) * 2 * math.pi
            sin_phi = math.sin(phi)
            cos_phi = math.cos(phi)

            x = cos_phi * sin_theta
            y = cos_theta
            z = sin_phi * sin_theta

            normal = Vec3(x, y, z).normalize()
            position = normal * radius
            texcoord = UV(lon / longitude_segments, lat / latitude_segments)

            vertices.append(Vertex(position, normal, texcoord))

    for lat in range(latitude_segments):
        for lon in range(longitude_segments):
            first = lat * (longitude_segments + 1) + lon
            second = first + longitude_segments + 1

            indices.append(first)
            indices.append(second)
            indices.append(first + 1)

            indices.append(second)
            indices.append(second + 1)
            indices.append(first + 1)

    return Mesh(vertices, indices)


def create_cylinder(radius: float = 1.0, height: float = 2.0, segments: int = 32) -> Mesh:
    """Create cylinder mesh.

    Args:
        radius: Cylinder radius
        height: Cylinder height
        segments: Number of segments around circumference

    Returns:
        Mesh with cylinder geometry
    """
    vertices: list[Vertex] = []
    indices: list[int] = []

    # Top and bottom circle centers
    top_center = len(vertices)
    vertices.append(Vertex(Vec3(0, height / 2, 0), Vec3(0, 1, 0), UV(0.5, 0.5)))

    bottom_center = len(vertices)
    vertices.append(Vertex(Vec3(0, -height / 2, 0), Vec3(0, -1, 0), UV(0.5, 0.5)))

    # Top circle vertices
    top_start = len(vertices)
    for i in range(segments):
        angle = (i / segments) * 2 * math.pi
        x = math.cos(angle) * radius
        z = math.sin(angle) * radius
        normal = Vec3(x, 0, z).normalize()
        position = Vec3(x, height / 2, z)
        texcoord = UV(math.cos(angle) * 0.5 + 0.5, math.sin(angle) * 0.5 + 0.5)
        vertices.append(Vertex(position, normal, texcoord))

    # Bottom circle vertices
    bottom_start = len(vertices)
    for i in range(segments):
        angle = (i / segments) * 2 * math.pi
        x = math.cos(angle) * radius
        z = math.sin(angle) * radius
        normal = Vec3(x, 0, z).normalize()
        position = Vec3(x, -height / 2, z)
        texcoord = UV(math.cos(angle) * 0.5 + 0.5, math.sin(angle) * 0.5 + 0.5)
        vertices.append(Vertex(position, normal, texcoord))

    # Top cap
    for i in range(segments):
        indices.append(top_center)
        indices.append(top_start + (i + 1) % segments)
        indices.append(top_start + i)

    # Bottom cap
    for i in range(segments):
        indices.append(bottom_center)
        indices.append(bottom_start + i)
        indices.append(bottom_start + (i + 1) % segments)

    # Side faces
    for i in range(segments):
        top1 = top_start + i
        top2 = top_start + (i + 1) % segments
        bot1 = bottom_start + i
        bot2 = bottom_start + (i + 1) % segments

        indices.extend([top1, bot1, top2])
        indices.extend([top2, bot1, bot2])

    return Mesh(vertices, indices)


def create_plane(width: float = 1.0, height: float = 1.0, subdivisions: int = 1) -> Mesh:
    """Create plane mesh.

    Args:
        width: Plane width (X axis)
        height: Plane height (Z axis)
        subdivisions: Number of subdivisions per side

    Returns:
        Mesh with plane geometry
    """
    vertices: list[Vertex] = []
    indices: list[int] = []

    for z_idx in range(subdivisions + 1):
        for x_idx in range(subdivisions + 1):
            x = (x_idx / subdivisions - 0.5) * width
            z = (z_idx / subdivisions - 0.5) * height

            position = Vec3(x, 0, z)
            normal = Vec3(0, 1, 0)
            texcoord = UV(x_idx / subdivisions, z_idx / subdivisions)

            vertices.append(Vertex(position, normal, texcoord))

    for z_idx in range(subdivisions):
        for x_idx in range(subdivisions):
            tl = z_idx * (subdivisions + 1) + x_idx
            tr = tl + 1
            bl = (z_idx + 1) * (subdivisions + 1) + x_idx
            br = bl + 1

            indices.extend([tl, bl, tr])
            indices.extend([tr, bl, br])

    return Mesh(vertices, indices)


def create_cone(radius: float = 1.0, height: float = 2.0, segments: int = 32) -> Mesh:
    """Create cone mesh.

    Args:
        radius: Cone base radius
        height: Cone height
        segments: Number of segments around base

    Returns:
        Mesh with cone geometry
    """
    vertices: list[Vertex] = []
    indices: list[int] = []

    # Apex
    apex = len(vertices)
    vertices.append(Vertex(Vec3(0, height / 2, 0), Vec3(0, 1, 0), UV(0.5, 1)))

    # Base center
    base_center = len(vertices)
    vertices.append(Vertex(Vec3(0, -height / 2, 0), Vec3(0, -1, 0), UV(0.5, 0.5)))

    # Base circle
    base_start = len(vertices)
    for i in range(segments):
        angle = (i / segments) * 2 * math.pi
        x = math.cos(angle) * radius
        z = math.sin(angle) * radius

        # Side normal (points outward and slightly up)
        side_normal = Vec3(x, radius / height, z).normalize()
        position = Vec3(x, -height / 2, z)
        texcoord = UV(math.cos(angle) * 0.5 + 0.5, math.sin(angle) * 0.5 + 0.5)

        vertices.append(Vertex(position, side_normal, texcoord))

    # Side faces
    for i in range(segments):
        next_i = (i + 1) % segments
        indices.append(apex)
        indices.append(base_start + i)
        indices.append(base_start + next_i)

    # Base cap
    for i in range(segments):
        indices.append(base_center)
        indices.append(base_start + i)
        indices.append(base_start + (i + 1) % segments)

    return Mesh(vertices, indices)


def create_torus(
    major_radius: float = 1.0, minor_radius: float = 0.3, major_segments: int = 32, minor_segments: int = 16
) -> Mesh:
    """Create torus mesh.

    Args:
        major_radius: Major radius (from center to tube center)
        minor_radius: Minor radius (tube radius)
        major_segments: Segments around major circle
        minor_segments: Segments around minor circle

    Returns:
        Mesh with torus geometry
    """
    vertices: list[Vertex] = []
    indices: list[int] = []

    for major_idx in range(major_segments):
        major_angle = (major_idx / major_segments) * 2 * math.pi

        for minor_idx in range(minor_segments):
            minor_angle = (minor_idx / minor_segments) * 2 * math.pi

            # Position on torus
            x = (major_radius + minor_radius * math.cos(minor_angle)) * math.cos(major_angle)
            y = minor_radius * math.sin(minor_angle)
            z = (major_radius + minor_radius * math.cos(minor_angle)) * math.sin(major_angle)

            # Normal points toward minor circle center
            normal_x = math.cos(minor_angle) * math.cos(major_angle)
            normal_y = math.sin(minor_angle)
            normal_z = math.cos(minor_angle) * math.sin(major_angle)

            position = Vec3(x, y, z)
            normal = Vec3(normal_x, normal_y, normal_z).normalize()
            texcoord = UV(major_idx / major_segments, minor_idx / minor_segments)

            vertices.append(Vertex(position, normal, texcoord))

    # Indices
    for major_idx in range(major_segments):
        for minor_idx in range(minor_segments):
            curr = major_idx * minor_segments + minor_idx
            next_minor = major_idx * minor_segments + (minor_idx + 1) % minor_segments
            next_major = ((major_idx + 1) % major_segments) * minor_segments + minor_idx
            next_both = ((major_idx + 1) % major_segments) * minor_segments + (minor_idx + 1) % minor_segments

            indices.extend([curr, next_minor, next_major])
            indices.extend([next_minor, next_both, next_major])

    return Mesh(vertices, indices)


def compute_face_normals(mesh: Mesh) -> list[Vec3]:
    """Compute face normals for all triangles.

    Args:
        mesh: Input mesh

    Returns:
        List of face normals (one per triangle)
    """
    normals: list[Vec3] = []

    for i in range(0, len(mesh.indices), 3):
        i0, i1, i2 = mesh.indices[i], mesh.indices[i + 1], mesh.indices[i + 2]
        v0 = mesh.vertices[i0].position
        v1 = mesh.vertices[i1].position
        v2 = mesh.vertices[i2].position

        edge1 = v1 - v0
        edge2 = v2 - v0
        normal = edge1.cross(edge2)
        if normal.length() < 1e-9:
            # Degenerate triangle fallback to a stable unit axis.
            normal = Vec3(0, 1, 0)
        else:
            normal = normal.normalize()

        normals.append(normal)

    return normals


def compute_vertex_normals(mesh: Mesh, use_area_weighting: bool = True) -> Mesh:
    """Compute smooth vertex normals via area-weighted averaging.

    Args:
        mesh: Input mesh
        use_area_weighting: Use triangle area as weight

    Returns:
        Mesh with updated vertex normals
    """
    vertex_normals: list[Vec3] = [Vec3(0, 0, 0) for _ in range(len(mesh.vertices))]
    vertex_areas: list[float] = [0.0 for _ in range(len(mesh.vertices))]

    for i in range(0, len(mesh.indices), 3):
        i0, i1, i2 = mesh.indices[i], mesh.indices[i + 1], mesh.indices[i + 2]
        v0 = mesh.vertices[i0].position
        v1 = mesh.vertices[i1].position
        v2 = mesh.vertices[i2].position

        edge1 = v1 - v0
        edge2 = v2 - v0
        normal = edge1.cross(edge2)
        area = normal.length() * 0.5

        if area < 1e-12:
            continue

        normal = normal.normalize()

        weight = area if use_area_weighting else 1.0

        vertex_normals[i0] = vertex_normals[i0] + normal * weight
        vertex_normals[i1] = vertex_normals[i1] + normal * weight
        vertex_normals[i2] = vertex_normals[i2] + normal * weight

        if use_area_weighting:
            vertex_areas[i0] += area
            vertex_areas[i1] += area
            vertex_areas[i2] += area

    # Normalize
    for i in range(len(vertex_normals)):
        if vertex_normals[i].length() > 1e-9:
            vertex_normals[i] = vertex_normals[i].normalize()

    # Update mesh
    result_vertices = []
    for i, vertex in enumerate(mesh.vertices):
        result_vertices.append(Vertex(vertex.position, vertex_normals[i], vertex.texcoord, vertex.tangent))

    return Mesh(result_vertices, mesh.indices)


def compute_tangent_space(mesh: Mesh) -> Mesh:
    """Compute tangent vectors for normal mapping.

    Args:
        mesh: Input mesh with normals

    Returns:
        Mesh with updated tangent vectors
    """
    tangents: list[Vec3] = [Vec3(1, 0, 0) for _ in range(len(mesh.vertices))]
    tangent_weights: list[float] = [0.0 for _ in range(len(mesh.vertices))]

    for i in range(0, len(mesh.indices), 3):
        i0, i1, i2 = mesh.indices[i], mesh.indices[i + 1], mesh.indices[i + 2]

        v0 = mesh.vertices[i0]
        v1 = mesh.vertices[i1]
        v2 = mesh.vertices[i2]

        edge1 = v1.position - v0.position
        edge2 = v2.position - v0.position

        duv1_u = v1.texcoord.u - v0.texcoord.u
        duv1_v = v1.texcoord.v - v0.texcoord.v
        duv2_u = v2.texcoord.u - v0.texcoord.u
        duv2_v = v2.texcoord.v - v0.texcoord.v

        denom = duv1_u * duv2_v - duv2_u * duv1_v
        if abs(denom) < 1e-9:
            continue

        r = 1.0 / denom
        tangent_raw = edge1 * (duv2_v * r) - edge2 * (duv1_v * r)
        if tangent_raw.length() < 1e-9:
            continue
        tangent = tangent_raw.normalize()

        for idx in [i0, i1, i2]:
            tangents[idx] = tangents[idx] + tangent
            tangent_weights[idx] += 1.0

    # Normalize and orthogonalize
    for i in range(len(tangents)):
        if tangent_weights[i] > 0 and tangents[i].length() > 1e-9:
            tangents[i] = tangents[i].normalize()

            # Gram-Schmidt: orthogonalize with respect to normal
            normal = mesh.vertices[i].normal
            tangent_ortho = tangents[i] - normal * normal.dot(tangents[i])
            if tangent_ortho.length() > 1e-9:
                tangents[i] = tangent_ortho.normalize()
            else:
                # Degenerate case (tangent aligned with normal): pick stable fallback axis.
                fallback = Vec3(1, 0, 0) if abs(normal.x) < 0.9 else Vec3(0, 1, 0)
                tangent_ortho = fallback - normal * normal.dot(fallback)
                if tangent_ortho.length() > 1e-9:
                    tangents[i] = tangent_ortho.normalize()

    result_vertices = []
    for i, vertex in enumerate(mesh.vertices):
        result_vertices.append(Vertex(vertex.position, vertex.normal, vertex.texcoord, tangents[i]))

    return Mesh(result_vertices, mesh.indices)


def merge_meshes(meshes: list[Mesh]) -> Mesh:
    """Merge multiple meshes into one.

    Args:
        meshes: List of meshes to merge

    Returns:
        Single merged mesh
    """
    merged_vertices: list[Vertex] = []
    merged_indices: list[int] = []

    vertex_offset = 0
    for mesh in meshes:
        merged_vertices.extend(mesh.vertices)

        for idx in mesh.indices:
            merged_indices.append(idx + vertex_offset)

        vertex_offset += len(mesh.vertices)

    return Mesh(merged_vertices, merged_indices)


def compute_mesh_aabb(mesh: Mesh) -> AABB:
    """Compute axis-aligned bounding box for mesh.

    Args:
        mesh: Input mesh

    Returns:
        AABB of mesh
    """
    if not mesh.vertices:
        return AABB(Vec3(0, 0, 0), Vec3(0, 0, 0))

    positions = [v.position for v in mesh.vertices]
    return math3d.aabb_from_points(positions)


def simplify_mesh(mesh: Mesh, target_vertex_count: int) -> Mesh:
    """Simplify mesh via quadric error metric edge collapse.

    Args:
        mesh: Input mesh
        target_vertex_count: Target number of vertices

    Returns:
        Simplified mesh
    """
    if len(mesh.vertices) <= target_vertex_count:
        return mesh

    # Build edge-vertex adjacency
    edges: dict[tuple[int, int], float] = {}
    vertex_edges: list[set[int]] = [set() for _ in range(len(mesh.vertices))]

    for i in range(0, len(mesh.indices), 3):
        i0, i1, i2 = mesh.indices[i], mesh.indices[i + 1], mesh.indices[i + 2]

        for a, b in [(i0, i1), (i1, i2), (i2, i0)]:
            if a > b:
                a, b = b, a
            key = (a, b)
            edges[key] = 0.0
            vertex_edges[a].add(b)
            vertex_edges[b].add(a)

    # Simplified copy of mesh data
    vertices = list(mesh.vertices)
    indices = list(mesh.indices)
    valid = [True] * len(vertices)
    vertex_map = list(range(len(vertices)))

    # Collapse edges
    while len([v for v in valid if v]) > target_vertex_count and edges:
        # Find edge with smallest error
        min_error = float("inf")
        min_edge = None

        for edge, error in edges.items():
            if error < min_error:
                min_error = error
                min_edge = edge

        if min_edge is None:
            break

        i0, i1 = min_edge
        if not valid[i0] or not valid[i1]:
            del edges[min_edge]
            continue

        # Collapse edge by removing i1
        valid[i1] = False

        # Update indices to point i1 to i0
        for i in range(len(indices)):
            if indices[i] == i1:
                indices[i] = i0

        # Remove edges involving i1
        for neighbor in list(vertex_edges[i1]):
            key = (min(i1, neighbor), max(i1, neighbor))
            if key in edges:
                del edges[key]
            if neighbor != i0:
                key = (min(i0, neighbor), max(i0, neighbor))
                edges[key] = 0.0

        edges.pop(min_edge, None)

    # Rebuild mesh with valid vertices only
    vertex_remap = {}
    new_vertices = []

    for i, vertex in enumerate(vertices):
        if valid[i]:
            vertex_remap[i] = len(new_vertices)
            new_vertices.append(vertex)

    # Rebuild indices
    new_indices = []
    for idx in indices:
        if valid[idx]:
            mapped = vertex_remap.get(idx)
            if mapped is not None:
                new_indices.append(mapped)

    return Mesh(new_vertices, new_indices)
