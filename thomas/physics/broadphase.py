"""
Broad-phase collision detection: spatial hashing, sweep-and-prune, AABB trees.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from thomas.physics._types import AABB, Vec3
from thomas.physics.rigid_body import RigidBody


@dataclass
class SpatialHashGrid:
    """Spatial hashing grid for broad-phase collision detection."""

    cell_size: float = 1.0
    grid: dict[tuple[int, int, int], list[RigidBody]] = field(default_factory=dict)
    pair_set: set[tuple[int, int]] = field(default_factory=set)

    def _hash_position(self, pos: Vec3) -> tuple[int, int, int]:
        """Hash position to grid cell."""
        return (
            int(pos.x / self.cell_size),
            int(pos.y / self.cell_size),
            int(pos.z / self.cell_size),
        )

    def insert(self, body: RigidBody) -> None:
        """Insert body into grid."""
        self.grid.clear()
        self.pair_set.clear()

    def update(self, bodies: list[RigidBody]) -> None:
        """Update grid with current body positions."""
        self.grid.clear()

        for body in bodies:
            cell = self._hash_position(body.position)
            if cell not in self.grid:
                self.grid[cell] = []
            self.grid[cell].append(body)

    def get_broad_phase_pairs(self) -> list[tuple[RigidBody, RigidBody]]:
        """Get candidate collision pairs from grid cells."""
        pairs: list[tuple[RigidBody, RigidBody]] = []
        checked: set[tuple[int, int]] = set()

        for cell_bodies in self.grid.values():
            for i, body_a in enumerate(cell_bodies):
                for body_b in cell_bodies[i + 1 :]:
                    pair_key = tuple(sorted([body_a.body_id, body_b.body_id]))
                    if pair_key not in checked:
                        pairs.append((body_a, body_b))
                        checked.add(pair_key)

        # Check adjacent cells
        for cell in list(self.grid.keys()):
            x, y, z = cell
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    for dz in [-1, 0, 1]:
                        if dx == 0 and dy == 0 and dz == 0:
                            continue
                        neighbor = (x + dx, y + dy, z + dz)
                        if neighbor in self.grid:
                            for body_a in self.grid[cell]:
                                for body_b in self.grid[neighbor]:
                                    pair_key = tuple(sorted([body_a.body_id, body_b.body_id]))
                                    if pair_key not in checked:
                                        pairs.append((body_a, body_b))
                                        checked.add(pair_key)

        return pairs


@dataclass
class SweepAndPrune:
    """Sweep-and-prune (sort-and-sweep) broad-phase collision detection."""

    axis: int = 0  # 0=X, 1=Y, 2=Z
    active_pairs: set[tuple[int, int]] = field(default_factory=set)

    def get_broad_phase_pairs(self, bodies: list[RigidBody]) -> list[tuple[RigidBody, RigidBody]]:
        """Get candidate collision pairs using sweep-and-prune.

        Args:
            bodies: List of rigid bodies

        Returns:
            List of potential collision pairs
        """
        # Create intervals for each body
        intervals: list[tuple[float, bool, RigidBody]] = []

        for body in bodies:
            aabb = AABB(body.position - Vec3(0.5, 0.5, 0.5), body.position + Vec3(0.5, 0.5, 0.5))

            if self.axis == 0:
                intervals.append((aabb.min.x, True, body))
                intervals.append((aabb.max.x, False, body))
            elif self.axis == 1:
                intervals.append((aabb.min.y, True, body))
                intervals.append((aabb.max.y, False, body))
            else:
                intervals.append((aabb.min.z, True, body))
                intervals.append((aabb.max.z, False, body))

        # Sort intervals
        intervals.sort(key=lambda x: x[0])

        # Sweep through intervals
        new_pairs: set[tuple[int, int]] = set()
        active_bodies: set[int] = set()

        for _, is_start, body in intervals:
            if is_start:
                for other_id in active_bodies:
                    pair_key = tuple(sorted([body.body_id, other_id]))
                    new_pairs.add(pair_key)
                active_bodies.add(body.body_id)
            else:
                active_bodies.discard(body.body_id)

        # Get pairs from set
        pairs: list[tuple[RigidBody, RigidBody]] = []
        body_map = {body.body_id: body for body in bodies}

        for id_a, id_b in new_pairs:
            if id_a in body_map and id_b in body_map:
                pairs.append((body_map[id_a], body_map[id_b]))

        self.active_pairs = new_pairs
        return pairs


@dataclass
class AABBTreeNode:
    """Node in AABB tree."""

    aabb: AABB
    body: RigidBody | None = None
    left: AABBTreeNode | None = None
    right: AABBTreeNode | None = None
    parent: AABBTreeNode | None = None

    def is_leaf(self) -> bool:
        """Check if node is leaf."""
        return self.body is not None

    def surface_area(self) -> float:
        """Surface area of AABB."""
        return self.aabb.surface_area()


class AABBTree:
    """Dynamic AABB tree for broad-phase collision detection."""

    def __init__(self) -> None:
        """Initialize empty tree."""
        self.root: AABBTreeNode | None = None
        self.nodes: dict[int, AABBTreeNode] = {}

    def insert(self, body: RigidBody) -> None:
        """Insert body into tree.

        Args:
            body: Body to insert
        """
        aabb = AABB(
            body.position - Vec3(0.5, 0.5, 0.5),
            body.position + Vec3(0.5, 0.5, 0.5),
        )
        node = AABBTreeNode(aabb=aabb, body=body)
        self.nodes[body.body_id] = node

        if self.root is None:
            self.root = node
        else:
            self._insert_node(self.root, node)

    def _insert_node(self, parent: AABBTreeNode, new_node: AABBTreeNode) -> None:
        """Recursively insert node into tree.

        Args:
            parent: Current parent node
            new_node: Node to insert
        """
        if parent.is_leaf():
            # Create internal node
            internal = AABBTreeNode(
                aabb=parent.aabb.expand_by_aabb(new_node.aabb),
                left=parent,
                right=new_node,
            )
            parent.parent = internal
            new_node.parent = internal
            if parent.parent:
                if parent.parent.left == parent:
                    parent.parent.left = internal
                else:
                    parent.parent.right = internal
            else:
                self.root = internal
        else:
            # Choose best child for insertion
            left_aabb = parent.left.aabb if parent.left else parent.aabb
            right_aabb = parent.right.aabb if parent.right else parent.aabb

            left_expanded = left_aabb.expand_by_aabb(new_node.aabb)
            right_expanded = right_aabb.expand_by_aabb(new_node.aabb)

            if left_expanded.surface_area() < right_expanded.surface_area():
                if parent.left:
                    self._insert_node(parent.left, new_node)
            else:
                if parent.right:
                    self._insert_node(parent.right, new_node)

            # Update parent AABB
            if parent.left and parent.right:
                parent.aabb = parent.left.aabb.expand_by_aabb(parent.right.aabb)

    def remove(self, body_id: int) -> None:
        """Remove body from tree.

        Args:
            body_id: ID of body to remove
        """
        if body_id not in self.nodes:
            return

        node = self.nodes[body_id]
        parent = node.parent

        if parent is None:
            self.root = None
        else:
            sibling = parent.right if parent.left == node else parent.left
            if parent.parent is None:
                self.root = sibling
                if sibling:
                    sibling.parent = None
            else:
                if parent.parent.left == parent:
                    parent.parent.left = sibling
                else:
                    parent.parent.right = sibling
                if sibling:
                    sibling.parent = parent.parent

        del self.nodes[body_id]

    def get_broad_phase_pairs(self) -> list[tuple[RigidBody, RigidBody]]:
        """Get candidate collision pairs from tree.

        Returns:
            List of potential collision pairs
        """
        pairs: list[tuple[RigidBody, RigidBody]] = []
        if self.root:
            self._query_pairs(self.root, pairs)
        return pairs

    def _query_pairs(
        self,
        node: AABBTreeNode,
        pairs: list[tuple[RigidBody, RigidBody]],
    ) -> None:
        """Recursively query pairs in tree.

        Args:
            node: Current node
            pairs: List to accumulate pairs
        """
        if node.is_leaf() or not node.left or not node.right:
            return

        # Check left and right subtrees
        self._query_subtree_pairs(node.left, node.right, pairs)
        self._query_pairs(node.left, pairs)
        self._query_pairs(node.right, pairs)

    def _query_subtree_pairs(
        self,
        node_a: AABBTreeNode,
        node_b: AABBTreeNode,
        pairs: list[tuple[RigidBody, RigidBody]],
    ) -> None:
        """Query pairs between two subtrees.

        Args:
            node_a: First subtree root
            node_b: Second subtree root
            pairs: List to accumulate pairs
        """
        if not node_a.aabb or not node_b.aabb:
            return

        # Check AABB overlap
        if not (
            node_a.aabb.max.x >= node_b.aabb.min.x
            and node_a.aabb.min.x <= node_b.aabb.max.x
            and node_a.aabb.max.y >= node_b.aabb.min.y
            and node_a.aabb.min.y <= node_b.aabb.max.y
            and node_a.aabb.max.z >= node_b.aabb.min.z
            and node_a.aabb.min.z <= node_b.aabb.max.z
        ):
            return

        # Both leaves - add pair
        if node_a.is_leaf() and node_b.is_leaf():
            if node_a.body and node_b.body:
                pairs.append((node_a.body, node_b.body))
        # One or both are not leaves - recurse
        elif node_a.is_leaf():
            if node_b.left:
                self._query_subtree_pairs(node_a, node_b.left, pairs)
            if node_b.right:
                self._query_subtree_pairs(node_a, node_b.right, pairs)
        elif node_b.is_leaf():
            if node_a.left:
                self._query_subtree_pairs(node_a.left, node_b, pairs)
            if node_a.right:
                self._query_subtree_pairs(node_a.right, node_b, pairs)
        else:
            if node_a.left and node_b.left:
                self._query_subtree_pairs(node_a.left, node_b.left, pairs)
            if node_a.left and node_b.right:
                self._query_subtree_pairs(node_a.left, node_b.right, pairs)
            if node_a.right and node_b.left:
                self._query_subtree_pairs(node_a.right, node_b.left, pairs)
            if node_a.right and node_b.right:
                self._query_subtree_pairs(node_a.right, node_b.right, pairs)
