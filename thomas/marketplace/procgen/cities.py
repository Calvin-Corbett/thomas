"""
City generation including road networks, buildings, and zoning.
"""

import math
import random
from dataclasses import dataclass, field

from thomas.marketplace.procgen._exceptions import InvalidConfigError
from thomas.marketplace.procgen._types import LSystem


@dataclass
class Building:
    """Represents a building in a city."""

    x: int
    y: int
    width: int
    height: int
    floors: int = 1
    zone_type: str = "residential"  # residential, commercial, industrial
    height_meters: float = 10.0

    @property
    def area(self) -> int:
        """Get building footprint area."""
        return self.width * self.height


@dataclass
class Block:
    """Represents a city block."""

    x: int
    y: int
    width: int
    height: int
    buildings: list[Building] = field(default_factory=list)
    zone_type: str = "residential"


@dataclass
class CityGenerator:
    """Generate cities with roads, blocks, and buildings."""

    width: int
    height: int
    center_x: int = None
    center_y: int = None
    seed: int = 42
    city_scale: float = 100.0  # Approximate city size in map units

    def __post_init__(self) -> None:
        """Validate and initialize configuration."""
        if self.width < 50 or self.height < 50:
            raise InvalidConfigError("City dimensions must be at least 50x50", "dimensions")
        if self.center_x is None:
            self.center_x = self.width // 2
        if self.center_y is None:
            self.center_y = self.height // 2
        random.seed(self.seed)

    def generate(self) -> dict:
        """
        Generate complete city with roads and buildings.

        Returns:
            Dictionary with 'roads', 'blocks', and 'buildings'
        """
        # Generate road network
        roads = self._generate_road_network()

        # Subdivide into blocks
        blocks = self._create_blocks(roads)

        # Generate buildings in blocks
        buildings = self._generate_buildings(blocks)

        return {
            "roads": roads,
            "blocks": blocks,
            "buildings": buildings,
            "city_center": (self.center_x, self.center_y),
        }

    def _generate_road_network(self) -> list[list[tuple[int, int]]]:
        """
        Generate road network using L-system with density guidance.

        Returns:
            List of road segments (paths)
        """
        # Create L-system for road generation
        lsystem = LSystem(
            axiom="X",
            rules={
                "X": "F[+X][-X]FX",  # Recursive branching
                "F": "FF",  # Move forward
            },
            angle=25.0,
            scale=0.9,
            length=self.city_scale / 10,
            iterations=4,
        )

        roads = []
        x, y = float(self.center_x), float(self.center_y)
        angle = 0.0
        path = [(int(x), int(y))]

        # Simplified road generation: create grid-like pattern with variation
        road_spacing = 20
        for gx in range(0, self.width, road_spacing):
            road_y = []
            for gy in range(0, self.height, road_spacing):
                # Add variation to make organic
                var_x = random.randint(-3, 3)
                var_y = random.randint(-3, 3)
                road_y.append((gx + var_x, gy + var_y))
            roads.append(road_y)

        # Add vertical roads
        for gy in range(0, self.height, road_spacing):
            road_x = []
            for gx in range(0, self.width, road_spacing):
                var_x = random.randint(-3, 3)
                var_y = random.randint(-3, 3)
                road_x.append((gx + var_x, gy + var_y))
            roads.append(road_x)

        return roads

    def _create_blocks(self, roads: list[list[tuple[int, int]]]) -> list[Block]:
        """
        Create blocks from road network.

        Args:
            roads: Road network

        Returns:
            List of Block objects
        """
        blocks = []

        # Simple block creation from grid
        block_width = 20
        block_height = 20

        for y in range(0, self.height, block_height):
            for x in range(0, self.width, block_width):
                if x + block_width <= self.width and y + block_height <= self.height:
                    # Determine zone type by distance from center
                    dist = math.sqrt((x - self.center_x) ** 2 + (y - self.center_y) ** 2)
                    zone = self._get_zone_type(dist)

                    block = Block(x=x, y=y, width=block_width, height=block_height, zone_type=zone)
                    blocks.append(block)

        return blocks

    def _get_zone_type(self, distance_from_center: float) -> str:
        """
        Determine zone type based on distance from city center.

        Args:
            distance_from_center: Distance from city center

        Returns:
            Zone type string
        """
        max_distance = math.sqrt(self.width**2 + self.height**2)
        normalized_dist = distance_from_center / max_distance

        if normalized_dist < 0.2:
            return "commercial"  # Downtown
        elif normalized_dist < 0.6:
            return "residential"  # Mid-city
        else:
            return "industrial"  # Outskirts

    def _generate_buildings(self, blocks: list[Block]) -> list[Building]:
        """
        Generate buildings in blocks.

        Args:
            blocks: List of blocks

        Returns:
            List of Building objects
        """
        buildings = []

        for block in blocks:
            # Subdivide block with setbacks
            setback = 2
            interior_x = block.x + setback
            interior_y = block.y + setback
            interior_width = block.width - setback * 2
            interior_height = block.height - setback * 2

            # Create building footprints
            num_buildings = random.randint(1, 4)

            for _ in range(num_buildings):
                bw = random.randint(max(4, interior_width // 2 - 2), interior_width - 2)
                bh = random.randint(max(4, interior_height // 2 - 2), interior_height - 2)

                bx = random.randint(interior_x, interior_x + interior_width - bw)
                by = random.randint(interior_y, interior_y + interior_height - bh)

                # Height based on distance from center
                dist = math.sqrt((bx - self.center_x) ** 2 + (by - self.center_y) ** 2)
                max_dist = math.sqrt(self.width**2 + self.height**2)
                normalized = 1.0 - (dist / max_dist)
                floors = max(1, int(1 + normalized * 15))
                height = floors * 3.5

                building = Building(
                    x=bx,
                    y=by,
                    width=bw,
                    height=bh,
                    floors=floors,
                    zone_type=block.zone_type,
                    height_meters=height,
                )
                buildings.append(building)
                block.buildings.append(building)

        return buildings

    def _generate_landmarks(self, blocks: list[Block], num_landmarks: int = 3) -> list[dict]:
        """
        Generate landmark positions in the city.

        Args:
            blocks: List of blocks
            num_landmarks: Number of landmarks

        Returns:
            List of landmark dictionaries
        """
        landmarks = []
        commercial_blocks = [b for b in blocks if b.zone_type == "commercial"]

        for _ in range(min(num_landmarks, len(commercial_blocks))):
            block = random.choice(commercial_blocks)
            landmark = {
                "x": block.x + block.width // 2,
                "y": block.y + block.height // 2,
                "type": random.choice(["plaza", "market", "temple"]),
            }
            landmarks.append(landmark)

        return landmarks

    def _generate_walls(self) -> list[tuple[int, int]]:
        """
        Generate city wall perimeter.

        Returns:
            List of wall coordinates
        """
        walls = []
        margin = 3

        # Create outer wall
        for x in range(margin, self.width - margin):
            walls.append((x, margin))
            walls.append((x, self.height - margin - 1))

        for y in range(margin, self.height - margin):
            walls.append((margin, y))
            walls.append((self.width - margin - 1, y))

        return walls
