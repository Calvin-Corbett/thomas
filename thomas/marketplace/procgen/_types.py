"""
Type definitions for procedural generation engine.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class TerrainType(Enum):
    """Enumeration of terrain types."""

    DEEP_WATER = auto()
    SHALLOW_WATER = auto()
    SAND = auto()
    GRASS = auto()
    FOREST = auto()
    SWAMP = auto()
    MOUNTAIN = auto()
    SNOW = auto()
    ROCK = auto()


class BiomeType(Enum):
    """Enumeration of biome types (Whittaker diagram)."""

    TROPICAL_RAINFOREST = auto()
    TROPICAL_SEASONAL = auto()
    TROPICAL_SCRUB = auto()
    SUBTROPICAL_DESERT = auto()
    TEMPERATE_GRASSLAND = auto()
    TEMPERATE_DECIDUOUS_FOREST = auto()
    TEMPERATE_CONIFEROUS_FOREST = auto()
    BOREAL_FOREST = auto()
    TUNDRA = auto()
    GRASSLAND = auto()
    SHRUBLAND = auto()


class VegetationType(Enum):
    """Enumeration of vegetation types."""

    NONE = auto()
    GRASS = auto()
    SHRUB = auto()
    SMALL_TREE = auto()
    PINE_TREE = auto()
    OAK_TREE = auto()
    PALM_TREE = auto()
    DEAD_TREE = auto()
    FERN = auto()
    MOSS = auto()


class SettlementType(Enum):
    """Enumeration of settlement types."""

    HAMLET = auto()
    VILLAGE = auto()
    TOWN = auto()
    CITY = auto()
    METROPOLIS = auto()


class RoomType(Enum):
    """Enumeration of room types in dungeons."""

    GENERIC = auto()
    TREASURE = auto()
    GUARD = auto()
    BOSS = auto()
    LIBRARY = auto()
    LAB = auto()
    SHRINE = auto()
    BARRACKS = auto()


@dataclass
class Tile:
    """Represents a single tile in a map."""

    x: int
    y: int
    z: float = 0.0  # Height/elevation
    terrain_type: TerrainType = TerrainType.GRASS
    biome_type: BiomeType = BiomeType.TEMPERATE_GRASSLAND
    vegetation: VegetationType = VegetationType.NONE
    moisture: float = 0.5  # 0.0 to 1.0
    temperature: float = 0.5  # 0.0 to 1.0
    walkable: bool = True
    blocked: bool = False

    def __hash__(self) -> int:
        """Make tile hashable for use in sets/dicts."""
        return hash((self.x, self.y))

    def __eq__(self, other: Any) -> bool:
        """Check equality based on coordinates."""
        if not isinstance(other, Tile):
            return False
        return self.x == other.x and self.y == other.y


@dataclass
class HeightMap:
    """Stores terrain elevation data."""

    width: int
    height: int
    data: list[list[float]] = field(default_factory=list)
    min_height: float = 0.0
    max_height: float = 1.0

    def get(self, x: int, y: int) -> float:
        """Get elevation at position."""
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.data[y][x]
        return 0.0

    def set(self, x: int, y: int, value: float) -> None:
        """Set elevation at position."""
        if 0 <= x < self.width and 0 <= y < self.height:
            self.data[y][x] = value


@dataclass
class NoiseConfig:
    """Configuration for noise generation."""

    seed: int = 42
    scale: float = 50.0
    octaves: int = 4
    persistence: float = 0.5
    lacunarity: float = 2.0
    offset_x: float = 0.0
    offset_y: float = 0.0


@dataclass
class Room:
    """Represents a room in a dungeon."""

    x: int
    y: int
    width: int
    height: int
    room_type: RoomType = RoomType.GENERIC
    visited: bool = False
    treasure_value: int = 0
    monster_count: int = 0

    @property
    def center(self) -> tuple[int, int]:
        """Get center coordinates of the room."""
        return (self.x + self.width // 2, self.y + self.height // 2)

    @property
    def area(self) -> int:
        """Get area of the room."""
        return self.width * self.height


@dataclass
class Corridor:
    """Represents a corridor between rooms."""

    start: tuple[int, int]
    end: tuple[int, int]
    tiles: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class Dungeon:
    """Represents a complete dungeon."""

    width: int
    height: int
    rooms: list[Room] = field(default_factory=list)
    corridors: list[Corridor] = field(default_factory=list)
    tiles: dict[tuple[int, int], Tile] = field(default_factory=dict)
    difficulty: float = 0.5


@dataclass
class RiverSegment:
    """Represents a segment of a river."""

    x: int
    y: int
    width: int = 1
    length: int = 1
    flow_rate: float = 1.0


@dataclass
class Biome:
    """Represents biome characteristics."""

    name: str
    temperature_min: float
    temperature_max: float
    moisture_min: float
    moisture_max: float
    primary_terrain: TerrainType
    vegetation_types: list[VegetationType] = field(default_factory=list)
    colors: dict[str, tuple[int, int, int]] = field(default_factory=dict)


@dataclass
class WorldConfig:
    """Configuration for world generation."""

    width: int = 512
    height: int = 512
    seed: int = 42
    water_level: float = 0.4
    mountain_height: float = 0.8
    num_continents: int = 3
    num_cities: int = 10
    num_dungeons: int = 5
    noise_config: NoiseConfig = field(default_factory=NoiseConfig)


@dataclass
class LSystem:
    """Represents an L-System for procedural generation."""

    axiom: str
    rules: dict[str, str] = field(default_factory=dict)
    angle: float = 20.0
    scale: float = 0.9
    length: float = 10.0
    iterations: int = 5
    randomness: float = 0.0

    def apply(self, iterations: int | None = None) -> str:
        """Apply L-system rules for specified iterations."""
        current = self.axiom
        iters = iterations if iterations is not None else self.iterations
        for _ in range(iters):
            next_string = ""
            for char in current:
                next_string += self.rules.get(char, char)
            current = next_string
        return current


@dataclass
class Grammar:
    """Represents a context-free grammar for text generation."""

    rules: dict[str, list[str]] = field(default_factory=dict)
    start_symbol: str = "S"

    def add_rule(self, symbol: str, productions: list[str]) -> None:
        """Add a production rule to the grammar."""
        self.rules[symbol] = productions


@dataclass
class CellularRule:
    """Represents a rule for cellular automata."""

    birth_rules: set[int] = field(default_factory=set)
    survival_rules: set[int] = field(default_factory=set)
    name: str = "Conway"

    @staticmethod
    def conway_game_of_life() -> "CellularRule":
        """Create Conway's Game of Life rules."""
        return CellularRule(
            birth_rules={3},
            survival_rules={2, 3},
            name="Conway's Game of Life",
        )

    @staticmethod
    def cellular_caves() -> "CellularRule":
        """Create cellular automata rules for cave generation."""
        return CellularRule(
            birth_rules={6, 7, 8},
            survival_rules={4, 5, 6, 7, 8},
            name="Cellular Caves",
        )
