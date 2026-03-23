"""
Tests for mesh operations.

Tests:
- Mesh generation (cube, sphere, cylinder, cone, plane, torus)
- Normal computation (face and vertex normals)
- Tangent space calculation
- Mesh merging
- Bounding volume computation
- Mesh simplification
"""

from thomas.marketplace.graphics3d import mesh
from thomas.marketplace.graphics3d._types import UV, Vec3, Vertex


class TestMeshGeneration:
    """Tests for mesh generation functions."""

    def test_create_cube(self) -> None:
        """Test cube mesh generation."""
        m = mesh.create_cube(1.0)
        assert m.vertex_count() > 0
        assert m.triangle_count() > 0
        assert len(m.vertices) == 24
        assert len(m.indices) == 36

    def test_create_sphere(self) -> None:
        """Test sphere mesh generation."""
        m = mesh.create_sphere(1.0, 16, 16)
        assert m.vertex_count() > 0
        assert m.triangle_count() > 0
        assert len(m.indices) % 3 == 0

    def test_create_cylinder(self) -> None:
        """Test cylinder mesh generation."""
        m = mesh.create_cylinder(1.0, 2.0, 32)
        assert m.vertex_count() > 0
        assert m.triangle_count() > 0

    def test_create_cone(self) -> None:
        """Test cone mesh generation."""
        m = mesh.create_cone(1.0, 2.0, 32)
        assert m.vertex_count() > 0
        assert m.triangle_count() > 0

    def test_create_plane(self) -> None:
        """Test plane mesh generation."""
        m = mesh.create_plane(2.0, 2.0, 2)
        assert m.vertex_count() > 0
        assert m.triangle_count() > 0

    def test_create_torus(self) -> None:
        """Test torus mesh generation."""
        m = mesh.create_torus(1.0, 0.3, 16, 16)
        assert m.vertex_count() > 0
        assert m.triangle_count() > 0


class TestNormalComputation:
    """Tests for normal calculation."""

    def test_compute_face_normals(self) -> None:
        """Test face normal computation."""
        m = mesh.create_cube(1.0)
        normals = mesh.compute_face_normals(m)
        assert len(normals) == m.triangle_count()

        # All normals should be normalized
        for normal in normals:
            length = normal.length()
            assert abs(length - 1.0) < 1e-6

    def test_compute_vertex_normals(self) -> None:
        """Test vertex normal computation."""
        m = mesh.create_sphere(1.0, 8, 8)
        m_smooth = mesh.compute_vertex_normals(m)

        assert len(m_smooth.vertices) == len(m.vertices)

        # Vertex normals should be normalized
        for vertex in m_smooth.vertices:
            if vertex.normal.length() > 1e-6:
                length = vertex.normal.length()
                assert abs(length - 1.0) < 1e-6

    def test_compute_vertex_normals_area_weighted(self) -> None:
        """Test area-weighted vertex normal computation."""
        m = mesh.create_cube(1.0)
        m_smooth = mesh.compute_vertex_normals(m, use_area_weighting=True)
        assert len(m_smooth.vertices) == len(m.vertices)


class TestTangentSpace:
    """Tests for tangent space calculation."""

    def test_compute_tangent_space(self) -> None:
        """Test tangent computation."""
        m = mesh.create_sphere(1.0, 16, 16)
        m = mesh.compute_vertex_normals(m)
        m_tangent = mesh.compute_tangent_space(m)

        # All tangents should be normalized
        for vertex in m_tangent.vertices:
            if vertex.tangent.length() > 1e-6:
                length = vertex.tangent.length()
                assert abs(length - 1.0) < 1e-6

    def test_tangent_orthogonal_to_normal(self) -> None:
        """Test that tangents are orthogonal to normals."""
        m = mesh.create_plane(2.0, 2.0, 1)
        m = mesh.compute_vertex_normals(m)
        m_tangent = mesh.compute_tangent_space(m)

        for vertex in m_tangent.vertices:
            # Dot product should be close to 0 (orthogonal)
            dot = vertex.normal.dot(vertex.tangent)
            assert abs(dot) < 0.1


class TestMeshMerging:
    """Tests for mesh merging."""

    def test_merge_meshes(self) -> None:
        """Test mesh merging."""
        m1 = mesh.create_cube(1.0)
        m2 = mesh.create_sphere(1.0, 8, 8)

        merged = mesh.merge_meshes([m1, m2])

        assert merged.vertex_count() == m1.vertex_count() + m2.vertex_count()
        assert merged.triangle_count() == m1.triangle_count() + m2.triangle_count()

    def test_merge_empty_list(self) -> None:
        """Test merging empty mesh list."""
        result = mesh.merge_meshes([])
        assert result.vertex_count() == 0
        assert result.triangle_count() == 0


class TestBoundingVolume:
    """Tests for bounding volume computation."""

    def test_compute_mesh_aabb(self) -> None:
        """Test AABB computation for mesh."""
        m = mesh.create_cube(1.0)
        aabb = mesh.compute_mesh_aabb(m)

        assert aabb.min.x <= aabb.max.x
        assert aabb.min.y <= aabb.max.y
        assert aabb.min.z <= aabb.max.z

    def test_compute_aabb_cube(self) -> None:
        """Test AABB for cube."""
        m = mesh.create_cube(0.5)
        aabb = mesh.compute_mesh_aabb(m)

        # Cube should be roughly [-0.5, 0.5]^3
        assert aabb.min.x < -0.4
        assert aabb.min.y < -0.4
        assert aabb.min.z < -0.4
        assert aabb.max.x > 0.4
        assert aabb.max.y > 0.4
        assert aabb.max.z > 0.4


class TestMeshSimplification:
    """Tests for mesh simplification."""

    def test_simplify_mesh(self) -> None:
        """Test mesh simplification."""
        m = mesh.create_sphere(1.0, 32, 32)
        initial_count = m.vertex_count()

        simplified = mesh.simplify_mesh(m, initial_count // 2)

        assert simplified.vertex_count() <= m.vertex_count()
        # Should reduce complexity
        assert simplified.triangle_count() <= m.triangle_count()

    def test_simplify_no_change(self) -> None:
        """Test simplification with no reduction needed."""
        m = mesh.create_cube(1.0)
        simplified = mesh.simplify_mesh(m, m.vertex_count() + 10)

        # Should not change if target is larger
        assert simplified.vertex_count() == m.vertex_count()


class TestMeshIntegrity:
    """Tests for mesh integrity checks."""

    def test_cube_has_valid_indices(self) -> None:
        """Test that cube has valid vertex indices."""
        m = mesh.create_cube(1.0)
        for idx in m.indices:
            assert 0 <= idx < len(m.vertices)

    def test_sphere_has_valid_indices(self) -> None:
        """Test that sphere has valid vertex indices."""
        m = mesh.create_sphere(1.0, 16, 16)
        for idx in m.indices:
            assert 0 <= idx < len(m.vertices)

    def test_all_triangles_valid(self) -> None:
        """Test that all triangles have 3 valid vertices."""
        m = mesh.create_cube(1.0)
        assert len(m.indices) % 3 == 0

        for i in range(0, len(m.indices), 3):
            v0 = m.vertices[m.indices[i]]
            v1 = m.vertices[m.indices[i + 1]]
            v2 = m.vertices[m.indices[i + 2]]

            # Vertices should be distinct and have valid positions
            assert v0.position is not None
            assert v1.position is not None
            assert v2.position is not None


class TestVertexData:
    """Tests for vertex data."""

    def test_vertex_has_normal(self) -> None:
        """Test that generated vertices have normals."""
        m = mesh.create_cube(1.0)
        for vertex in m.vertices:
            assert vertex.normal is not None
            assert vertex.normal.length() > 0

    def test_vertex_has_texcoord(self) -> None:
        """Test that generated vertices have texture coordinates."""
        m = mesh.create_plane(1.0, 1.0, 1)
        for vertex in m.vertices:
            assert vertex.texcoord is not None
            assert 0 <= vertex.texcoord.u <= 1
            assert 0 <= vertex.texcoord.v <= 1

    def test_vertex_equality(self) -> None:
        """Test vertex equality."""
        v1 = Vertex(Vec3(1, 2, 3), Vec3(0, 1, 0), UV(0.5, 0.5))
        v2 = Vertex(Vec3(1, 2, 3), Vec3(0, 1, 0), UV(0.5, 0.5))
        assert v1 == v2
