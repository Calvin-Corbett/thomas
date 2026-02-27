"""
Scene graph management: hierarchical transforms, culling, LOD, and spatial indexing.

Provides:
- Hierarchical transform tree (parent-child relationships)
- Scene traversal (DFS)
- Frustum culling
- Spatial indexing via octree
- Level-of-detail (LOD) selection
- Render queue sorting
- Light management
"""

from __future__ import annotations

from dataclasses import dataclass, field

from thomas.graphics3d import math3d
from thomas.graphics3d._types import (
    AABB,
    Light,
    Mat4,
    Material,
    Mesh,
    Plane,
    Vec3,
)


@dataclass
class Transform:
    """3D transform: position, rotation (quaternion), scale."""

    position: Vec3 = field(default_factory=lambda: Vec3(0, 0, 0))
    rotation: Vec3 = field(default_factory=lambda: Vec3(0, 0, 0))  # Euler angles
    scale: Vec3 = field(default_factory=lambda: Vec3(1, 1, 1))

    def to_matrix(self) -> Mat4:
        """Convert transform to 4x4 matrix."""
        translate = math3d.matrix_translate(self.position)
        rotate = math3d.matrix_rotate_euler(self.rotation.x, self.rotation.y, self.rotation.z)
        scale = math3d.matrix_scale(self.scale)

        # T * R * S
        return translate * rotate * scale


@dataclass
class SceneNode:
    """Scene graph node."""

    name: str = "Node"
    transform: Transform = field(default_factory=Transform)
    parent: SceneNode | None = None
    children: list[SceneNode] = field(default_factory=list)
    mesh: Mesh | None = None
    material: Material | None = None
    bounding_volume: AABB | None = None
    lod_meshes: list[Mesh] = field(default_factory=list)
    active: bool = True

    def add_child(self, child: SceneNode) -> None:
        """Add child node."""
        child.parent = self
        self.children.append(child)

    def remove_child(self, child: SceneNode) -> None:
        """Remove child node."""
        if child in self.children:
            self.children.remove(child)
            child.parent = None

    def get_world_transform(self) -> Mat4:
        """Get accumulated world transform."""
        if self.parent is None:
            return self.transform.to_matrix()

        parent_transform = self.parent.get_world_transform()
        local_transform = self.transform.to_matrix()

        return parent_transform * local_transform

    def traverse_dfs(self, callback) -> None:
        """Traverse subtree in depth-first order."""
        if self.active:
            callback(self)

        for child in self.children:
            child.traverse_dfs(callback)

    def get_all_meshes(self) -> list[tuple[SceneNode, Mesh]]:
        """Get all mesh instances in subtree."""
        meshes: list[tuple[SceneNode, Mesh]] = []

        def collect_mesh(node: SceneNode) -> None:
            if node.mesh is not None:
                meshes.append((node, node.mesh))

        self.traverse_dfs(collect_mesh)
        return meshes

    def compute_bounding_volume(self) -> AABB:
        """Compute bounding volume for this node and children."""
        if self.bounding_volume is not None:
            return self.bounding_volume

        volumes: list[AABB] = []

        # Add mesh bounds
        if self.mesh is not None:
            volumes.append(math3d.aabb_from_points([v.position for v in self.mesh.vertices]))

        # Add children bounds
        for child in self.children:
            volumes.append(child.compute_bounding_volume())

        if not volumes:
            center = self.get_world_transform() * Vec3(0, 0, 0)
            return AABB(center, center)

        # Merge all volumes
        result = volumes[0]
        for vol in volumes[1:]:
            result = math3d.aabb_merge(result, vol)

        return result


class RenderQueue:
    """Render queue: sorted list of items to render."""

    def __init__(self) -> None:
        """Initialize render queue."""
        self.opaque_items: list[RenderItem] = []
        self.transparent_items: list[RenderItem] = []

    def add_item(self, item: RenderItem) -> None:
        """Add item to queue."""
        if item.material.diffuse.a >= 0.99:
            self.opaque_items.append(item)
        else:
            self.transparent_items.append(item)

    def sort(self, camera_position: Vec3) -> None:
        """Sort queue for optimal rendering.

        Opaque items are sorted front-to-back (minimize overdraw).
        Transparent items are sorted back-to-front (correct blending).
        """

        # Front-to-back for opaque
        def opaque_key(item: RenderItem) -> float:
            mesh_center = Vec3(0, 0, 0)
            if item.mesh.vertices:
                avg = Vec3(0, 0, 0)
                for v in item.mesh.vertices:
                    avg = avg + v.position
                mesh_center = avg * (1.0 / len(item.mesh.vertices))

            world_center = item.world_transform * Vec3(mesh_center.x, mesh_center.y, mesh_center.z)
            return (camera_position - world_center).length()

        # Back-to-front for transparent
        def transparent_key(item: RenderItem) -> float:
            return -(opaque_key(item))

        self.opaque_items.sort(key=opaque_key)
        self.transparent_items.sort(key=transparent_key)

    def clear(self) -> None:
        """Clear queue."""
        self.opaque_items.clear()
        self.transparent_items.clear()

    def get_all_items(self) -> list[RenderItem]:
        """Get all items in render order."""
        return self.opaque_items + self.transparent_items


@dataclass
class RenderItem:
    """Single renderable item."""

    node: SceneNode
    mesh: Mesh
    material: Material
    world_transform: Mat4


class Octree:
    """Spatial index: octree for scene objects."""

    def __init__(self, bounds: AABB, max_depth: int = 8, max_items: int = 4) -> None:
        """Initialize octree.

        Args:
            bounds: Root bounds
            max_depth: Maximum tree depth
            max_items: Items per leaf before subdivision
        """
        self.bounds = bounds
        self.max_depth = max_depth
        self.max_items = max_items
        self.items: list[tuple[SceneNode, AABB]] = []
        self.children: list[Octree] = []
        self.depth = 0

    def insert(self, node: SceneNode, bounds: AABB) -> None:
        """Insert node into octree."""
        if not self._bounds_intersect(bounds):
            return

        if len(self.children) == 0:
            self.items.append((node, bounds))

            if len(self.items) > self.max_items and self.depth < self.max_depth:
                self._subdivide()
        else:
            # Push down to children
            for child in self.children:
                child.insert(node, bounds)

    def query(self, bounds: AABB) -> list[SceneNode]:
        """Query all nodes that might intersect bounds."""
        results: list[SceneNode] = []

        if not self._bounds_intersect(bounds):
            return results

        for node, node_bounds in self.items:
            results.append(node)

        for child in self.children:
            results.extend(child.query(bounds))

        return results

    def _bounds_intersect(self, other: AABB) -> bool:
        """Check if bounds intersect with this node's bounds."""
        return math3d.aabb_intersect(self.bounds, other)

    def _subdivide(self) -> None:
        """Subdivide octree node."""
        center = self.bounds.center()
        extent = self.bounds.extent()

        # Create 8 child octants
        for dx in [-1, 1]:
            for dy in [-1, 1]:
                for dz in [-1, 1]:
                    child_min = Vec3(
                        center.x + dx * extent.x / 2,
                        center.y + dy * extent.y / 2,
                        center.z + dz * extent.z / 2,
                    )
                    child_max = Vec3(
                        child_min.x + extent.x,
                        child_min.y + extent.y,
                        child_min.z + extent.z,
                    )

                    child = Octree(AABB(child_min, child_max), self.max_depth, self.max_items)
                    child.depth = self.depth + 1
                    self.children.append(child)

        # Redistribute items
        items_copy = self.items
        self.items.clear()

        for node, bounds in items_copy:
            for child in self.children:
                child.insert(node, bounds)


class Scene:
    """Scene: collection of nodes, lights, and camera."""

    def __init__(self) -> None:
        """Initialize scene."""
        self.root = SceneNode("Root")
        self.lights: list[Light] = []
        self.octree: Octree | None = None
        self.render_queue = RenderQueue()

    def add_node(self, node: SceneNode, parent: SceneNode | None = None) -> None:
        """Add node to scene."""
        if parent is None:
            parent = self.root
        parent.add_child(node)

    def get_lights(self) -> list[Light]:
        """Get all lights in scene."""
        return self.lights

    def add_light(self, light: Light) -> None:
        """Add light to scene."""
        self.lights.append(light)

    def build_octree(self, bounds: AABB) -> None:
        """Build spatial index from scene graph."""
        self.octree = Octree(bounds)

        def insert_node(node: SceneNode) -> None:
            if node.mesh is not None:
                node_bounds = node.compute_bounding_volume()
                self.octree.insert(node, node_bounds)

        self.root.traverse_dfs(insert_node)

    def build_render_queue(self, camera_position: Vec3, frustum_planes: list[Plane] = None) -> RenderQueue:
        """Build render queue with culling and LOD.

        Args:
            camera_position: Camera position for LOD and culling
            frustum_planes: Optional frustum planes for culling

        Returns:
            Sorted render queue
        """
        self.render_queue.clear()

        def process_node(node: SceneNode) -> None:
            if not node.active or node.mesh is None:
                return

            # Frustum culling
            bounds = node.compute_bounding_volume()
            if frustum_planes:
                culled = False
                for plane in frustum_planes:
                    dist = plane.signed_distance_to_point(bounds.center())
                    if dist < -bounds.extent().length():
                        culled = True
                        break
                if culled:
                    return

            # LOD selection
            world_transform = node.get_world_transform()
            mesh_center = Vec3(0, 0, 0)
            if node.mesh.vertices:
                avg = Vec3(0, 0, 0)
                for v in node.mesh.vertices:
                    avg = avg + v.position
                mesh_center = avg * (1.0 / len(node.mesh.vertices))

            world_center = world_transform * Vec3(mesh_center.x, mesh_center.y, mesh_center.z)
            distance = (camera_position - world_center).length()

            # Select mesh based on LOD
            selected_mesh = node.mesh
            if node.lod_meshes:
                if distance > 50:
                    selected_mesh = node.lod_meshes[-1] if node.lod_meshes else node.mesh
                elif distance > 20:
                    selected_mesh = node.lod_meshes[-2] if len(node.lod_meshes) > 1 else node.mesh

            material = node.material if node.material else Material()

            item = RenderItem(node, selected_mesh, material, world_transform)
            self.render_queue.add_item(item)

        self.root.traverse_dfs(process_node)
        self.render_queue.sort(camera_position)

        return self.render_queue
