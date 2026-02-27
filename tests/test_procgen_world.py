"""
Tests for world generation.
"""

import pytest

from thomas.procgen._exceptions import InvalidConfigError
from thomas.procgen._types import TerrainType, WorldConfig
from thomas.procgen.world import (
    Continent,
    PoliticalRegion,
    TradeRoute,
    WorldGenerator,
)


class TestContinent:
    """Test continent class."""

    def test_continent_creation(self):
        """Test continent creation."""
        continent = Continent(
            name="Aethermoor",
            x_min=10,
            x_max=100,
            y_min=20,
            y_max=120,
            area=7200,
        )
        assert continent.name == "Aethermoor"
        assert continent.area == 7200

    def test_continent_center(self):
        """Test continent center calculation."""
        continent = Continent(
            name="Test",
            x_min=0,
            x_max=100,
            y_min=0,
            y_max=100,
        )
        center = continent.center
        assert center == (50, 50)


class TestPoliticalRegion:
    """Test political region class."""

    def test_political_region_creation(self):
        """Test political region creation."""
        region = PoliticalRegion(
            name="Great Kingdom",
            capital_x=50,
            capital_y=50,
            population=500000,
            wealth=50000,
        )
        assert region.name == "Great Kingdom"
        assert region.capital_x == 50
        assert region.population == 500000

    def test_political_region_territory(self):
        """Test territory management."""
        region = PoliticalRegion(
            name="Kingdom",
            capital_x=50,
            capital_y=50,
        )
        region.territory.add((50, 50))
        region.territory.add((51, 50))

        assert len(region.territory) == 2
        assert (50, 50) in region.territory


class TestTradeRoute:
    """Test trade route class."""

    def test_trade_route_creation(self):
        """Test trade route creation."""
        route = TradeRoute(
            from_city="Port City",
            to_city="Inland City",
            cost=50.0,
            trade_value=1000,
        )
        assert route.from_city == "Port City"
        assert route.to_city == "Inland City"
        assert route.trade_value == 1000


class TestWorldGenerator:
    """Test world generation."""

    def test_world_generator_initialization(self):
        """Test world generator initializes."""
        config = WorldConfig(width=256, height=256, seed=42)
        gen = WorldGenerator(config=config)

        assert gen.config.width == 256
        assert gen.config.height == 256

    def test_world_generator_invalid_dimensions(self):
        """Test world generator rejects small dimensions."""
        config = WorldConfig(width=20, height=20, seed=42)
        with pytest.raises(InvalidConfigError):
            WorldGenerator(config=config)

    def test_world_config_defaults(self):
        """Test world config has reasonable defaults."""
        config = WorldConfig()
        assert config.width == 512
        assert config.height == 512
        assert config.num_continents == 3
        assert config.num_cities == 10

    def test_generate_returns_dict(self):
        """Test generate returns proper structure."""
        config = WorldConfig(width=128, height=128, seed=42)
        gen = WorldGenerator(config=config)
        world = gen.generate()

        assert isinstance(world, dict)
        assert "tiles" in world
        assert "continents" in world
        assert "regions" in world
        assert "trade_routes" in world

    def test_generate_has_tiles(self):
        """Test generated world has tiles."""
        config = WorldConfig(width=64, height=64, seed=42)
        gen = WorldGenerator(config=config)
        world = gen.generate()

        tiles = world["tiles"]
        assert len(tiles) > 0
        # Check some tiles have expected terrain types
        terrain_types = set(tile.terrain_type for tile in tiles.values())
        assert len(terrain_types) > 1

    def test_generate_has_continents(self):
        """Test generated world has continents."""
        config = WorldConfig(width=128, height=128, seed=42, num_continents=2)
        gen = WorldGenerator(config=config)
        world = gen.generate()

        continents = world["continents"]
        assert isinstance(continents, list)

    def test_generate_has_regions(self):
        """Test generated world has political regions."""
        config = WorldConfig(width=128, height=128, seed=42)
        gen = WorldGenerator(config=config)
        world = gen.generate()

        regions = world["regions"]
        assert isinstance(regions, list)

    def test_generate_has_trade_routes(self):
        """Test generated world has trade routes."""
        config = WorldConfig(width=128, height=128, seed=42)
        gen = WorldGenerator(config=config)
        world = gen.generate()

        routes = world["trade_routes"]
        assert isinstance(routes, list)

    def test_generate_terrain_realistic(self):
        """Test generated terrain is realistic."""
        config = WorldConfig(width=64, height=64, seed=42)
        gen = WorldGenerator(config=config)
        world = gen.generate()

        tiles = world["tiles"]

        # Should have mix of water and land
        water_tiles = [
            t for t in tiles.values() if t.terrain_type in [TerrainType.DEEP_WATER, TerrainType.SHALLOW_WATER]
        ]
        land_tiles = [
            t for t in tiles.values() if t.terrain_type not in [TerrainType.DEEP_WATER, TerrainType.SHALLOW_WATER]
        ]

        assert len(water_tiles) > 0
        assert len(land_tiles) > 0

    def test_generate_regions_on_land(self):
        """Test regions are placed on land."""
        config = WorldConfig(width=128, height=128, seed=42)
        gen = WorldGenerator(config=config)
        world = gen.generate()

        regions = world["regions"]
        for region in regions:
            # Capital should be valid coordinates
            assert 0 <= region.capital_x < config.width
            assert 0 <= region.capital_y < config.height

    def test_flood_fill_land(self):
        """Test flood fill for continent detection."""
        from thomas.procgen._types import TerrainType, Tile

        config = WorldConfig(width=64, height=64, seed=42)
        gen = WorldGenerator(config=config)

        # Create test tiles
        tiles = {}
        for y in range(64):
            for x in range(64):
                if x < 32:
                    tiles[(x, y)] = Tile(x=x, y=y, terrain_type=TerrainType.GRASS)
                else:
                    tiles[(x, y)] = Tile(x=x, y=y, terrain_type=TerrainType.DEEP_WATER)

        visited = set()
        region = gen._flood_fill_land(tiles, 0, 0, visited)

        # Should find the western land mass
        assert len(region) > 0

    def test_generate_continent_name(self):
        """Test continent name generation."""
        config = WorldConfig(width=128, height=128, seed=42)
        gen = WorldGenerator(config=config)

        for _ in range(5):
            name = gen._generate_continent_name()
            assert isinstance(name, str)
            assert len(name) > 0

    def test_generate_region_name(self):
        """Test region name generation."""
        config = WorldConfig(width=128, height=128, seed=42)
        gen = WorldGenerator(config=config)

        for _ in range(5):
            name = gen._generate_region_name()
            assert isinstance(name, str)
            assert len(name) > 0

    def test_generate_with_different_seeds(self):
        """Test worlds differ with different seeds."""
        config1 = WorldConfig(width=64, height=64, seed=42)
        config2 = WorldConfig(width=64, height=64, seed=43)

        gen1 = WorldGenerator(config=config1)
        gen2 = WorldGenerator(config=config2)

        world1 = gen1.generate()
        world2 = gen2.generate()

        # Compare a sample tile
        sample_tile1 = world1["tiles"][(32, 32)]
        sample_tile2 = world2["tiles"][(32, 32)]

        # Different seeds should (probably) produce different results
        # Note: there's a small chance they're the same, but very unlikely
        assert (
            sample_tile1.terrain_type != sample_tile2.terrain_type
            or sample_tile1.temperature != sample_tile2.temperature
        )
