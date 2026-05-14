"""
Terrain generation including heightmaps, erosion, biomes, and rivers.
"""

import random
from dataclasses import dataclass

from thomas.marketplace.procgen._exceptions import InvalidConfigError
from thomas.marketplace.procgen._types import (
    Biome,
    BiomeType,
    HeightMap,
    NoiseConfig,
    TerrainType,
    Tile,
    VegetationType,
)
from thomas.marketplace.procgen.noise import PerlinNoise, fractal_brownian_motion


@dataclass
class TerrainGenerator:
    """Generate terrain heightmaps from noise functions."""

    width: int
    height: int
    config: NoiseConfig

    def __post_init__(self) -> None:
        """Validate configuration."""
        if self.width < 1 or self.height < 1:
            raise InvalidConfigError("Width and height must be positive", "dimensions")
        if self.config.scale <= 0:
            raise InvalidConfigError("Scale must be positive", "scale")

    def generate_heightmap(self) -> HeightMap:
        """
        Generate heightmap using multi-octave Perlin noise.

        Returns:
            HeightMap object with elevation data
        """
        perlin = PerlinNoise(seed=self.config.seed)
        heightmap = HeightMap(width=self.width, height=self.height)
        heightmap.data = [[0.0 for _ in range(self.width)] for _ in range(self.height)]

        for y in range(self.height):
            for x in range(self.width):
                # Normalize coordinates to noise space
                nx = (x / self.width) * self.config.scale + self.config.offset_x
                ny = (y / self.height) * self.config.scale + self.config.offset_y

                # Apply FBM
                value = fractal_brownian_motion(
                    perlin.get_2d,
                    nx,
                    ny,
                    octaves=self.config.octaves,
                    persistence=self.config.persistence,
                    lacunarity=self.config.lacunarity,
                )

                # Normalize to [0, 1]
                normalized = (value + 1.0) / 2.0
                heightmap.data[y][x] = max(0.0, min(1.0, normalized))

        heightmap.min_height = 0.0
        heightmap.max_height = 1.0

        return heightmap

    def apply_erosion(self, heightmap: HeightMap, iterations: int = 5) -> None:
        """
        Apply hydraulic erosion simulation using particle-based approach.

        Args:
            heightmap: HeightMap to erode (modified in place)
            iterations: Number of erosion particles to simulate
        """
        random.seed(self.config.seed)

        for _ in range(iterations):
            # Start raindrop at random position
            x = random.uniform(0, self.width - 1)
            y = random.uniform(0, self.height - 1)

            velocity_x = 0.0
            velocity_y = 0.0
            sediment = 0.0

            for step in range(100):
                ix = int(x)
                iy = int(y)

                # Bounds check
                if ix < 0 or ix >= self.width - 1 or iy < 0 or iy >= self.height - 1:
                    break

                # Get current height and neighbors
                heightmap.get(ix, iy)
                h_left = heightmap.get(ix - 1, iy)
                h_right = heightmap.get(ix + 1, iy)
                h_up = heightmap.get(ix, iy - 1)
                h_down = heightmap.get(ix, iy + 1)

                # Calculate gravity direction (steepest descent)
                grad_x = (h_right - h_left) / 2.0
                grad_y = (h_down - h_up) / 2.0

                # Update velocity (friction + acceleration)
                velocity_x = velocity_x * 0.9 - grad_x * 0.1
                velocity_y = velocity_y * 0.9 - grad_y * 0.1

                # Update position
                x += velocity_x
                y += velocity_y

                # Deposit or pick up sediment
                sediment_capacity = max(0.01, (velocity_x**2 + velocity_y**2) ** 0.5)
                if sediment > sediment_capacity:
                    # Deposit
                    deposit = min(sediment, sediment_capacity * 0.1)
                    heightmap.data[iy][ix] += deposit * 0.0001
                    sediment -= deposit
                else:
                    # Pick up
                    pickup = min(0.01, sediment_capacity * 0.1 - sediment)
                    heightmap.data[iy][ix] -= pickup * 0.0001
                    sediment += pickup


@dataclass
class BiomeAssigner:
    """Assign biomes based on temperature and moisture (Whittaker diagram)."""

    _biomes: dict[BiomeType, Biome] = None

    def __post_init__(self) -> None:
        """Initialize standard biomes."""
        self._biomes = self._create_standard_biomes()

    @staticmethod
    def _create_standard_biomes() -> dict[BiomeType, Biome]:
        """Create standard biomes with temperature/moisture ranges."""
        return {
            BiomeType.TROPICAL_RAINFOREST: Biome(
                name="Tropical Rainforest",
                temperature_min=0.7,
                temperature_max=1.0,
                moisture_min=0.6,
                moisture_max=1.0,
                primary_terrain=TerrainType.FOREST,
                vegetation_types=[
                    VegetationType.PALM_TREE,
                    VegetationType.FERN,
                ],
            ),
            BiomeType.TROPICAL_SCRUB: Biome(
                name="Tropical Scrub",
                temperature_min=0.7,
                temperature_max=1.0,
                moisture_min=0.2,
                moisture_max=0.6,
                primary_terrain=TerrainType.GRASS,
                vegetation_types=[VegetationType.SHRUB, VegetationType.GRASS],
            ),
            BiomeType.SUBTROPICAL_DESERT: Biome(
                name="Subtropical Desert",
                temperature_min=0.6,
                temperature_max=1.0,
                moisture_min=0.0,
                moisture_max=0.2,
                primary_terrain=TerrainType.SAND,
                vegetation_types=[VegetationType.SHRUB],
            ),
            BiomeType.TEMPERATE_GRASSLAND: Biome(
                name="Temperate Grassland",
                temperature_min=0.4,
                temperature_max=0.7,
                moisture_min=0.3,
                moisture_max=0.6,
                primary_terrain=TerrainType.GRASS,
                vegetation_types=[VegetationType.GRASS],
            ),
            BiomeType.TEMPERATE_DECIDUOUS_FOREST: Biome(
                name="Temperate Deciduous Forest",
                temperature_min=0.4,
                temperature_max=0.7,
                moisture_min=0.6,
                moisture_max=1.0,
                primary_terrain=TerrainType.FOREST,
                vegetation_types=[VegetationType.OAK_TREE, VegetationType.GRASS],
            ),
            BiomeType.TEMPERATE_CONIFEROUS_FOREST: Biome(
                name="Temperate Coniferous Forest",
                temperature_min=0.2,
                temperature_max=0.5,
                moisture_min=0.6,
                moisture_max=1.0,
                primary_terrain=TerrainType.FOREST,
                vegetation_types=[VegetationType.PINE_TREE],
            ),
            BiomeType.BOREAL_FOREST: Biome(
                name="Boreal Forest",
                temperature_min=0.0,
                temperature_max=0.3,
                moisture_min=0.4,
                moisture_max=0.8,
                primary_terrain=TerrainType.FOREST,
                vegetation_types=[VegetationType.PINE_TREE],
            ),
            BiomeType.TUNDRA: Biome(
                name="Tundra",
                temperature_min=0.0,
                temperature_max=0.2,
                moisture_min=0.2,
                moisture_max=0.6,
                primary_terrain=TerrainType.SNOW,
                vegetation_types=[VegetationType.MOSS],
            ),
        }

    def get_biome(self, temperature: float, moisture: float) -> BiomeType:
        """
        Get biome type based on temperature and moisture.

        Args:
            temperature: Temperature value [0, 1]
            moisture: Moisture value [0, 1]

        Returns:
            BiomeType enum value
        """
        temperature = max(0.0, min(1.0, temperature))
        moisture = max(0.0, min(1.0, moisture))

        best_biome = BiomeType.TEMPERATE_GRASSLAND
        best_distance = float("inf")

        for biome_type, biome in self._biomes.items():
            # Calculate center of biome range
            temp_center = (biome.temperature_min + biome.temperature_max) / 2.0
            moist_center = (biome.moisture_min + biome.moisture_max) / 2.0

            # Distance to biome center
            distance = ((temperature - temp_center) ** 2 + (moisture - moist_center) ** 2) ** 0.5

            if distance < best_distance:
                best_distance = distance
                best_biome = biome_type

        return best_biome

    def assign_biomes(self, tiles: dict[tuple[int, int], Tile], temperature_map, moisture_map) -> None:
        """
        Assign biomes to all tiles based on temperature and moisture maps.

        Args:
            tiles: Dictionary of tile coordinates to Tile objects
            temperature_map: Map of temperature values
            moisture_map: Map of moisture values
        """
        for (x, y), tile in tiles.items():
            temp = temperature_map.get(x, y) if hasattr(temperature_map, "get") else 0.5
            moist = moisture_map.get(x, y) if hasattr(moisture_map, "get") else 0.5
            tile.biome_type = self.get_biome(temp, moist)


@dataclass
class RiverGenerator:
    """Generate rivers by tracing downhill from peaks."""

    heightmap: HeightMap
    min_elevation: float = 0.7

    def generate_rivers(self, num_rivers: int = 5) -> list[list[tuple[int, int]]]:
        """
        Generate rivers by finding peaks and tracing downhill.

        Args:
            num_rivers: Number of rivers to generate

        Returns:
            List of river paths (each path is list of coordinates)
        """
        rivers = []
        random.seed(42)

        # Find peak positions
        peaks = []
        for y in range(self.heightmap.height):
            for x in range(self.heightmap.width):
                if self.heightmap.get(x, y) >= self.min_elevation:
                    peaks.append((x, y))

        random.shuffle(peaks)

        for _ in range(min(num_rivers, len(peaks))):
            if not peaks:
                break
            start = peaks.pop()
            river = self._trace_river(start[0], start[1])
            if len(river) > 3:
                rivers.append(river)

        return rivers

    def _trace_river(self, start_x: int, start_y: int) -> list[tuple[int, int]]:
        """Trace a river from a peak by following downhill gradient."""
        path = [(start_x, start_y)]
        x, y = start_x, start_y

        for _ in range(200):
            # Find lowest neighbor
            lowest_h = self.heightmap.get(x, y)
            next_x, next_y = x, y

            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < self.heightmap.width and 0 <= ny < self.heightmap.height:
                        h = self.heightmap.get(nx, ny)
                        if h < lowest_h:
                            lowest_h = h
                            next_x, next_y = nx, ny

            if (next_x, next_y) == (x, y):  # Reached minimum
                break

            x, y = next_x, next_y
            if (x, y) not in path:
                path.append((x, y))

        return path


@dataclass
class CoastlineGenerator:
    """Generate coastlines based on water level threshold."""

    heightmap: HeightMap
    water_level: float = 0.4

    def generate_coastline(self) -> list[tuple[int, int]]:
        """
        Generate coastline tiles at the boundary between water and land.

        Returns:
            List of coastline coordinates
        """
        coastline = []

        for y in range(self.heightmap.height):
            for x in range(self.heightmap.width):
                height = self.heightmap.get(x, y)
                is_water = height < self.water_level

                # Check neighbors
                has_land_neighbor = False
                for dx in [-1, 0, 1]:
                    for dy in [-1, 0, 1]:
                        if dx == 0 and dy == 0:
                            continue
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < self.heightmap.width and 0 <= ny < self.heightmap.height:
                            neighbor_h = self.heightmap.get(nx, ny)
                            if neighbor_h >= self.water_level:
                                has_land_neighbor = True
                                break

                if is_water and has_land_neighbor:
                    coastline.append((x, y))

        return coastline

    def classify_terrain(self, height: float) -> TerrainType:
        """
        Classify terrain type based on elevation.

        Args:
            height: Elevation value [0, 1]

        Returns:
            TerrainType enum
        """
        if height < self.water_level - 0.1:
            return TerrainType.DEEP_WATER
        elif height < self.water_level:
            return TerrainType.SHALLOW_WATER
        elif height < self.water_level + 0.05:
            return TerrainType.SAND
        elif height < 0.5:
            return TerrainType.GRASS
        elif height < 0.7:
            return TerrainType.FOREST
        elif height < 0.85:
            return TerrainType.MOUNTAIN
        else:
            return TerrainType.SNOW
