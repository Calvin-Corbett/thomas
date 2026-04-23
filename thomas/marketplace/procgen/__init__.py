"""
Procedural Generation Engine for Games and Worlds.

A comprehensive suite for generating game content including terrain,
dungeons, cities, vegetation, NPCs, loot, and quests.
"""

from thomas.marketplace.procgen._exceptions import (
    GenerationError,
    InvalidConfigError,
    ProcGenError,
)
from thomas.marketplace.procgen._types import (
    Biome,
    CellularRule,
    Corridor,
    Dungeon,
    Grammar,
    HeightMap,
    LSystem,
    NoiseConfig,
    RiverSegment,
    Room,
    SettlementType,
    TerrainType,
    Tile,
    VegetationType,
    WorldConfig,
)
from thomas.marketplace.procgen.cities import CityGenerator
from thomas.marketplace.procgen.dungeons import (
    BSPDungeonGenerator,
    CellularDungeonGenerator,
    DungeonGenerator,
)
from thomas.marketplace.procgen.loot import LootGenerator
from thomas.marketplace.procgen.names import NameGenerator
from thomas.marketplace.procgen.noise import (
    PerlinNoise,
    SimplexNoise,
    WorleyNoise,
    domain_warp,
    fractal_brownian_motion,
    turbulence,
    value_noise,
)
from thomas.marketplace.procgen.quests import QuestGenerator
from thomas.marketplace.procgen.terrain import (
    BiomeAssigner,
    CoastlineGenerator,
    RiverGenerator,
    TerrainGenerator,
)
from thomas.marketplace.procgen.vegetation import LSystemGenerator, VegetationGenerator
from thomas.marketplace.procgen.world import WorldGenerator

__version__ = "0.1.0"
__all__ = [
    "PerlinNoise",
    "SimplexNoise",
    "WorleyNoise",
    "fractal_brownian_motion",
    "domain_warp",
    "value_noise",
    "turbulence",
    "TerrainGenerator",
    "BiomeAssigner",
    "RiverGenerator",
    "CoastlineGenerator",
    "DungeonGenerator",
    "BSPDungeonGenerator",
    "CellularDungeonGenerator",
    "CityGenerator",
    "VegetationGenerator",
    "LSystemGenerator",
    "NameGenerator",
    "LootGenerator",
    "QuestGenerator",
    "WorldGenerator",
    "Tile",
    "Biome",
    "HeightMap",
    "NoiseConfig",
    "Room",
    "Corridor",
    "Dungeon",
    "TerrainType",
    "VegetationType",
    "SettlementType",
    "RiverSegment",
    "WorldConfig",
    "LSystem",
    "Grammar",
    "CellularRule",
    "ProcGenError",
    "InvalidConfigError",
    "GenerationError",
]
