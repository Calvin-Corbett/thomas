"""
Assembly management for multi-part CAD models.

Includes part instances, assembly trees, mate constraints, interference detection,
and bill of materials generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ._exceptions import AssemblyError
from ._types import Point3D, Solid, Vector3D
from .geometry3d import BoundingBox, compute_bounding_box


@dataclass
class Transform:
    """3D transformation (translation + rotation)."""

    translation: Vector3D = field(default_factory=lambda: Vector3D(0, 0, 0))
    rotation_matrix: list[list[float]] = field(
        default_factory=lambda: [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]
    )

    @classmethod
    def translation_only(cls, tx: float, ty: float, tz: float) -> Transform:
        """Create translation transform."""
        return cls(translation=Vector3D(tx, ty, tz))

    @classmethod
    def identity(cls) -> Transform:
        """Create identity transform."""
        return cls()

    def apply_to_point(self, point: Point3D) -> Point3D:
        """Apply transformation to point."""
        m = self.rotation_matrix
        rotated = Point3D(
            m[0][0] * point.x + m[0][1] * point.y + m[0][2] * point.z,
            m[1][0] * point.x + m[1][1] * point.y + m[1][2] * point.z,
            m[2][0] * point.x + m[2][1] * point.y + m[2][2] * point.z,
        )
        return rotated + self.translation

    def compose(self, other: Transform) -> Transform:
        """Compose two transformations."""
        m1 = self.rotation_matrix
        m2 = other.rotation_matrix

        composed_rotation = [[sum(m1[i][k] * m2[k][j] for k in range(3)) for j in range(3)] for i in range(3)]

        composed_translation = Vector3D(
            m1[0][0] * other.translation.x
            + m1[0][1] * other.translation.y
            + m1[0][2] * other.translation.z
            + self.translation.x,
            m1[1][0] * other.translation.x
            + m1[1][1] * other.translation.y
            + m1[1][2] * other.translation.z
            + self.translation.y,
            m1[2][0] * other.translation.x
            + m1[2][1] * other.translation.y
            + m1[2][2] * other.translation.z
            + self.translation.z,
        )

        result = Transform(composed_translation)
        result.rotation_matrix = composed_rotation
        return result


@dataclass
class PartInstance:
    """An instance of a part in an assembly."""

    name: str
    solid: Solid
    transform: Transform = field(default_factory=Transform.identity)
    visible: bool = True
    mass: float = 1.0

    def get_bounding_box(self) -> BoundingBox:
        """Get bounding box in assembly coordinates."""
        if not self.solid.vertices:
            return BoundingBox(Point3D(0, 0, 0), Point3D(0, 0, 0))

        transformed_points = [self.transform.apply_to_point(v.point) for v in self.solid.vertices]
        return compute_bounding_box(transformed_points)

    def get_centroid(self) -> Point3D:
        """Get centroid in assembly coordinates."""
        if not self.solid.vertices:
            return Point3D(0, 0, 0)

        xs = sum(v.point.x for v in self.solid.vertices)
        ys = sum(v.point.y for v in self.solid.vertices)
        zs = sum(v.point.z for v in self.solid.vertices)
        n = len(self.solid.vertices)

        local_centroid = Point3D(xs / n, ys / n, zs / n)
        return self.transform.apply_to_point(local_centroid)


@dataclass
class Mate:
    """A mate constraint between two parts."""

    mate_type: str
    part1_name: str
    part2_name: str
    entity1: object | None = None
    entity2: object | None = None
    offset: float = 0.0

    def __repr__(self) -> str:
        return f"Mate({self.mate_type}, {self.part1_name}↔{self.part2_name})"


class Assembly:
    """A multi-part assembly."""

    def __init__(self, name: str = "Assembly") -> None:
        """
        Initialize assembly.

        Args:
            name: Assembly name
        """
        self.name = name
        self.parts: dict[str, PartInstance] = {}
        self.mates: list[Mate] = []
        self.subassemblies: dict[str, Assembly] = {}

    def add_part(self, instance: PartInstance) -> None:
        """
        Add part instance to assembly.

        Args:
            instance: Part instance
        """
        if instance.name in self.parts:
            raise AssemblyError(f"Part '{instance.name}' already exists")

        self.parts[instance.name] = instance

    def add_mate(self, mate: Mate) -> None:
        """
        Add mate constraint.

        Args:
            mate: Mate constraint
        """
        if mate.part1_name not in self.parts or mate.part2_name not in self.parts:
            raise AssemblyError("One or both parts not in assembly")

        self.mates.append(mate)

    def add_subassembly(self, name: str, assembly: Assembly) -> None:
        """
        Add sub-assembly.

        Args:
            name: Sub-assembly name
            assembly: Assembly object
        """
        self.subassemblies[name] = assembly

    def get_part(self, name: str) -> PartInstance | None:
        """Get part by name."""
        return self.parts.get(name)

    def get_all_parts(self, include_subassemblies: bool = True) -> list[PartInstance]:
        """
        Get all parts in assembly.

        Args:
            include_subassemblies: Include parts from sub-assemblies

        Returns:
            List of parts
        """
        parts_list = list(self.parts.values())

        if include_subassemblies:
            for subasm in self.subassemblies.values():
                parts_list.extend(subasm.get_all_parts(include_subassemblies=True))

        return parts_list

    def detect_interference(self) -> list[tuple[str, str]]:
        """
        Detect interference (overlapping parts).

        Uses axis-aligned bounding box collision detection.

        Returns:
            List of (part1, part2) pairs with interference
        """
        interferences: list[tuple[str, str]] = []

        parts_list = list(self.parts.items())

        for i, (name1, part1) in enumerate(parts_list):
            bbox1 = part1.get_bounding_box()

            for name2, part2 in parts_list[i + 1 :]:
                bbox2 = part2.get_bounding_box()

                if bbox1.intersects(bbox2):
                    interferences.append((name1, name2))

        return interferences

    def get_mass_properties(self) -> dict[str, float]:
        """
        Compute assembly mass properties.

        Returns:
            Dict with 'mass' and 'volume'
        """
        total_mass = 0.0
        total_volume = 0.0

        for part in self.get_all_parts():
            total_mass += part.mass
            total_volume += sum(f.area() for f in part.solid.faces)

        return {
            "mass": total_mass,
            "volume": total_volume,
        }

    def explode(self, axis: Vector3D, distance: float = 50.0) -> Assembly:
        """
        Generate exploded assembly view.

        Translates parts along axis.

        Args:
            axis: Direction to explode
            distance: Distance to explode each part

        Returns:
            New assembly with exploded transforms
        """
        exploded = Assembly(f"{self.name}_exploded")

        axis_norm = axis.normalize()
        centroid_assembly = self._get_assembly_centroid()

        for i, (name, part) in enumerate(self.parts.items()):
            centroid_part = part.get_centroid()
            centroid_part - centroid_assembly

            explode_offset = axis_norm * (distance * (i + 1))

            new_transform = part.transform.compose(
                Transform.translation_only(explode_offset.x, explode_offset.y, explode_offset.z)
            )

            new_part = PartInstance(
                name=part.name, solid=part.solid, transform=new_transform, visible=part.visible, mass=part.mass
            )

            exploded.add_part(new_part)

        return exploded

    def _get_assembly_centroid(self) -> Point3D:
        """Compute assembly centroid."""
        if not self.parts:
            return Point3D(0, 0, 0)

        total_x, total_y, total_z = 0.0, 0.0, 0.0

        for part in self.parts.values():
            centroid = part.get_centroid()
            total_x += centroid.x
            total_y += centroid.y
            total_z += centroid.z

        n = len(self.parts)
        return Point3D(total_x / n, total_y / n, total_z / n)


class BillOfMaterials:
    """Bill of Materials for assembly."""

    def __init__(self) -> None:
        """Initialize BOM."""
        self.items: dict[str, int] = {}

    def add_part(self, part_name: str, quantity: int = 1) -> None:
        """
        Add part to BOM.

        Args:
            part_name: Part name
            quantity: Quantity
        """
        if part_name in self.items:
            self.items[part_name] += quantity
        else:
            self.items[part_name] = quantity

    def from_assembly(self, assembly: Assembly) -> None:
        """
        Generate BOM from assembly.

        Args:
            assembly: Assembly object
        """
        for part in assembly.get_all_parts():
            self.add_part(part.name)

    def to_table(self) -> list[tuple[str, int]]:
        """
        Get BOM as table (sorted).

        Returns:
            List of (part_name, quantity) tuples
        """
        return sorted(self.items.items(), key=lambda x: x[0])

    def to_csv(self, filename: str) -> None:
        """
        Export BOM to CSV.

        Args:
            filename: Output file path
        """
        with open(filename, "w") as f:
            f.write("Part,Quantity\n")
            for part_name, quantity in self.to_table():
                f.write(f"{part_name},{quantity}\n")

    def __repr__(self) -> str:
        return f"BOM({len(self.items)} unique parts)"
