"""
World generation including continents, oceans, politics, and trade routes.
"""

import math
import random
from dataclasses import dataclass, field

from thomas.marketplace.procgen._exceptions import InvalidConfigError
from thomas.marketplace.procgen._types import TerrainType, Tile, WorldConfig
from thomas.marketplace.procgen.noise import PerlinNoise
from thomas.marketplace.procgen.terrain import (
    BiomeAssigner,
    CoastlineGenerator,
    TerrainGenerator,
)


@dataclass
class Continent:
    """Represents a continent."""

    name: str
    x_min: int
    x_max: int
    y_min: int
    y_max: int
    area: int = 0
    population: int = 0

    @property
    def center(self) -> tuple[int, int]:
        """Get center coordinates."""
        return ((self.x_min + self.x_max) // 2, (self.y_min + self.y_max) // 2)


@dataclass
class PoliticalRegion:
    """Represents a political region/empire."""

    name: str
    capital_x: int
    capital_y: int
    territory: set[tuple[int, int]] = field(default_factory=set)
    allies: list[str] = field(default_factory=list)
    enemies: list[str] = field(default_factory=list)
    population: int = 0
    wealth: int = 0


@dataclass
class TradeRoute:
    """Represents a trade route between settlements."""

    from_city: str
    to_city: str
    cost: float  # Distance/difficulty
    trade_value: int
    path: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class WorldGenerator:
    """Generate complete worlds with terrain, politics, and trade."""

    config: WorldConfig

    def __post_init__(self) -> None:
        """Validate configuration."""
        if self.config.width < 50 or self.config.height < 50:
            raise InvalidConfigError("World dimensions must be at least 50x50", "dimensions")

    def generate(self) -> dict:
        """
        Generate a complete world.

        Returns:
            Dictionary with 'tiles', 'continents', 'regions', 'routes'
        """
        # Generate terrain
        tiles = self._generate_terrain()

        # Find continents
        continents = self._find_continents(tiles)

        # Generate political regions
        regions = self._generate_regions(continents)

        # Generate trade routes
        routes = self._generate_trade_routes(regions)

        return {
            "tiles": tiles,
            "continents": continents,
            "regions": regions,
            "trade_routes": routes,
        }

    def _generate_terrain(self) -> dict[tuple[int, int], Tile]:
        """Generate base terrain."""
        # Generate heightmap
        terrain_gen = TerrainGenerator(self.config.width, self.config.height, self.config.noise_config)
        heightmap = terrain_gen.generate_heightmap()

        # Apply erosion
        terrain_gen.apply_erosion(heightmap, iterations=10)

        # Classify terrain
        coastline_gen = CoastlineGenerator(heightmap, self.config.water_level)

        # Generate temperature and moisture maps
        perlin = PerlinNoise(seed=self.config.seed)
        temperature_map = HeightMap(self.config.width, self.config.height)
        temperature_map.data = [[0.0 for _ in range(self.config.width)] for _ in range(self.config.height)]

        moisture_map = HeightMap(self.config.width, self.config.height)
        moisture_map.data = [[0.0 for _ in range(self.config.width)] for _ in range(self.config.height)]

        # Calculate temperature (latitude-based + noise)
        for y in range(self.config.height):
            for x in range(self.config.width):
                # Latitude-based temperature (poles are cold)
                lat_factor = 1.0 - abs(y - self.config.height / 2) / (self.config.height / 2)
                noise_temp = (perlin.get_2d(x / 50, y / 50) + 1.0) / 2.0
                temperature = lat_factor * 0.7 + noise_temp * 0.3
                temperature_map.data[y][x] = max(0.0, min(1.0, temperature))

                # Moisture based on proximity to water
                noise_moist = (perlin.get_2d(x / 30 + 1000, y / 30 + 1000) + 1.0) / 2.0
                moisture_map.data[y][x] = noise_moist

        # Create tiles
        tiles = {}
        biome_assigner = BiomeAssigner()

        for y in range(self.config.height):
            for x in range(self.config.width):
                height = heightmap.get(x, y)
                temp = temperature_map.get(x, y)
                moist = moisture_map.get(x, y)

                # Classify terrain
                terrain_type = coastline_gen.classify_terrain(height)

                # Assign biome
                biome_type = biome_assigner.get_biome(temp, moist)

                tile = Tile(
                    x=x,
                    y=y,
                    z=height,
                    terrain_type=terrain_type,
                    biome_type=biome_type,
                    temperature=temp,
                    moisture=moist,
                )

                tiles[(x, y)] = tile

        return tiles

    def _find_continents(self, tiles: dict[tuple[int, int], Tile]) -> list[Continent]:
        """Find continuous land masses."""
        continents = []
        visited = set()

        for (x, y), tile in tiles.items():
            if (x, y) not in visited and tile.terrain_type != TerrainType.DEEP_WATER:
                if tile.terrain_type != TerrainType.SHALLOW_WATER:
                    # Flood fill to find continent
                    continent_tiles = self._flood_fill_land(tiles, x, y, visited)

                    if len(continent_tiles) > 100:  # Minimum continent size
                        xs = [t[0] for t in continent_tiles]
                        ys = [t[1] for t in continent_tiles]

                        continent = Continent(
                            name=self._generate_continent_name(),
                            x_min=min(xs),
                            x_max=max(xs),
                            y_min=min(ys),
                            y_max=max(ys),
                            area=len(continent_tiles),
                        )
                        continents.append(continent)

        return continents

    def _flood_fill_land(self, tiles: dict, start_x: int, start_y: int, visited: set) -> list[tuple[int, int]]:
        """Flood fill to find connected land."""
        land = []
        stack = [(start_x, start_y)]

        while stack:
            x, y = stack.pop()

            if (x, y) in visited:
                continue
            if (x, y) not in tiles:
                continue

            tile = tiles[(x, y)]
            if tile.terrain_type == TerrainType.DEEP_WATER or tile.terrain_type == TerrainType.SHALLOW_WATER:
                continue

            visited.add((x, y))
            land.append((x, y))

            # Check neighbors
            for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
                stack.append((x + dx, y + dy))

        return land

    def _generate_regions(self, continents: list[Continent]) -> list[PoliticalRegion]:
        """Generate political regions."""
        regions = []
        random.seed(self.config.seed)

        for i, continent in enumerate(continents):
            num_regions = random.randint(1, 3)

            for j in range(num_regions):
                # Place capital
                cap_x = continent.x_min + random.randint(0, continent.x_max - continent.x_min)
                cap_y = continent.y_min + random.randint(0, continent.y_max - continent.y_min)

                region = PoliticalRegion(
                    name=self._generate_region_name(),
                    capital_x=cap_x,
                    capital_y=cap_y,
                    population=random.randint(100000, 1000000),
                    wealth=random.randint(10000, 100000),
                )
                regions.append(region)

        return regions

    def _generate_trade_routes(self, regions: list[PoliticalRegion]) -> list[TradeRoute]:
        """Generate trade routes between regions."""
        routes = []

        for i, region1 in enumerate(regions):
            for region2 in regions[i + 1 :]:
                # Calculate distance
                dx = region1.capital_x - region2.capital_x
                dy = region1.capital_y - region2.capital_y
                distance = math.sqrt(dx * dx + dy * dy)

                # Create route if within reasonable distance
                if distance < self.config.width / 2:
                    trade_value = int((region1.wealth + region2.wealth) / (distance + 1))

                    route = TradeRoute(
                        from_city=region1.name,
                        to_city=region2.name,
                        cost=distance,
                        trade_value=trade_value,
                    )
                    routes.append(route)

        return routes

    def _generate_continent_name(self) -> str:
        """Generate a random continent name."""
        names = [
            "Aethermoor",
            "Valdoria",
            "Crystalline",
            "Shadowlands",
            "Brightholme",
            "Windreach",
            "Deepmire",
            "Starholm",
        ]
        return random.choice(names)

    def _generate_region_name(self) -> str:
        """Generate a random region/kingdom name."""
        adjectives = ["Northern", "Southern", "Eastern", "Western", "Great", "Lesser"]
        nouns = [
            "Kingdom",
            "Empire",
            "Dominion",
            "Realm",
            "Domain",
            "Territory",
        ]

        return f"{random.choice(adjectives)} {random.choice(nouns)}"


# Import HeightMap for use in this module
from thomas.marketplace.procgen._types import HeightMap
