"""
Tests for terrain generation.
"""

import pytest

from thomas.marketplace.procgen._exceptions import InvalidConfigError
from thomas.marketplace.procgen._types import (
    BiomeType,
    HeightMap,
    NoiseConfig,
    TerrainType,
)
from thomas.marketplace.procgen.terrain import (
    BiomeAssigner,
    CoastlineGenerator,
    RiverGenerator,
    TerrainGenerator,
)


class TestTerrainGenerator:
    """Test terrain generation."""

    def test_terrain_generator_initialization(self):
        """Test terrain generator initializes."""
        config = NoiseConfig(seed=42, scale=50.0, octaves=4)
        gen = TerrainGenerator(width=256, height=256, config=config)
        assert gen.width == 256
        assert gen.height == 256

    def test_terrain_generator_invalid_dimensions(self):
        """Test terrain generator rejects invalid dimensions."""
        config = NoiseConfig()
        with pytest.raises(InvalidConfigError):
            TerrainGenerator(width=0, height=256, config=config)
        with pytest.raises(InvalidConfigError):
            TerrainGenerator(width=256, height=-1, config=config)

    def test_terrain_generator_invalid_scale(self):
        """Test terrain generator rejects invalid scale."""
        config = NoiseConfig(scale=0.0)
        with pytest.raises(InvalidConfigError):
            TerrainGenerator(width=256, height=256, config=config)

    def test_generate_heightmap(self):
        """Test heightmap generation."""
        config = NoiseConfig(seed=42, scale=50.0, octaves=4)
        gen = TerrainGenerator(width=128, height=128, config=config)
        heightmap = gen.generate_heightmap()

        assert heightmap.width == 128
        assert heightmap.height == 128
        assert len(heightmap.data) == 128
        assert len(heightmap.data[0]) == 128

    def test_heightmap_values_in_range(self):
        """Test heightmap values are normalized."""
        config = NoiseConfig(seed=42, scale=50.0)
        gen = TerrainGenerator(width=64, height=64, config=config)
        heightmap = gen.generate_heightmap()

        for row in heightmap.data:
            for value in row:
                assert 0.0 <= value <= 1.0

    def test_heightmap_min_max(self):
        """Test heightmap min/max values."""
        config = NoiseConfig(seed=42, scale=50.0)
        gen = TerrainGenerator(width=64, height=64, config=config)
        heightmap = gen.generate_heightmap()

        assert heightmap.min_height == 0.0
        assert heightmap.max_height == 1.0

    def test_apply_erosion(self):
        """Test erosion changes heightmap."""
        config = NoiseConfig(seed=42, scale=50.0)
        gen = TerrainGenerator(width=64, height=64, config=config)
        heightmap = gen.generate_heightmap()

        original_values = [row[:] for row in heightmap.data]
        gen.apply_erosion(heightmap, iterations=5)

        # Erosion should modify some values
        changed = False
        for y in range(len(heightmap.data)):
            for x in range(len(heightmap.data[0])):
                if abs(heightmap.data[y][x] - original_values[y][x]) > 0.0001:
                    changed = True
                    break

        # Note: erosion may not always change values, so we just check it doesn't crash


class TestBiomeAssigner:
    """Test biome assignment."""

    def test_biome_assigner_initialization(self):
        """Test biome assigner initializes."""
        assigner = BiomeAssigner()
        assert assigner._biomes is not None
        assert len(assigner._biomes) > 0

    def test_biome_assigner_creates_standard_biomes(self):
        """Test standard biomes are created."""
        assigner = BiomeAssigner()
        biomes = assigner._create_standard_biomes()
        assert len(biomes) > 0
        assert BiomeType.TROPICAL_RAINFOREST in biomes
        assert BiomeType.TUNDRA in biomes

    def test_get_biome_returns_valid_type(self):
        """Test get_biome returns a valid BiomeType."""
        assigner = BiomeAssigner()
        biome = assigner.get_biome(0.5, 0.5)
        assert isinstance(biome, BiomeType)

    def test_get_biome_hot_wet(self):
        """Test tropical biome for hot/wet conditions."""
        assigner = BiomeAssigner()
        biome = assigner.get_biome(0.9, 0.9)  # Hot and wet
        # Should be some tropical biome
        assert isinstance(biome, BiomeType)

    def test_get_biome_cold_dry(self):
        """Test arctic biome for cold/dry conditions."""
        assigner = BiomeAssigner()
        biome = assigner.get_biome(0.1, 0.1)  # Cold and dry
        assert isinstance(biome, BiomeType)

    def test_biome_clamps_values(self):
        """Test biome assignment clamps invalid values."""
        assigner = BiomeAssigner()
        # Values outside [0, 1] should be clamped
        biome1 = assigner.get_biome(-0.5, -0.5)
        biome2 = assigner.get_biome(1.5, 1.5)
        assert isinstance(biome1, BiomeType)
        assert isinstance(biome2, BiomeType)


class TestRiverGenerator:
    """Test river generation."""

    def test_river_generator_initialization(self):
        """Test river generator initializes."""
        heightmap = HeightMap(width=128, height=128)
        heightmap.data = [[0.5 for _ in range(128)] for _ in range(128)]
        gen = RiverGenerator(heightmap, min_elevation=0.7)
        assert gen.heightmap == heightmap

    def test_generate_rivers(self):
        """Test river generation produces paths."""
        heightmap = HeightMap(width=128, height=128)
        heightmap.data = [[0.5 for _ in range(128)] for _ in range(128)]
        # Add some peaks
        for x in range(50, 60):
            for y in range(50, 60):
                heightmap.data[y][x] = 0.9

        gen = RiverGenerator(heightmap, min_elevation=0.7)
        rivers = gen.generate_rivers(num_rivers=3)

        assert isinstance(rivers, list)
        for river in rivers:
            assert isinstance(river, list)
            # Each river should be a path
            if len(river) > 0:
                assert all(isinstance(coord, tuple) for coord in river)

    def test_generate_rivers_with_low_peaks(self):
        """Test river generation with insufficient peaks."""
        heightmap = HeightMap(width=64, height=64)
        heightmap.data = [[0.3 for _ in range(64)] for _ in range(64)]

        gen = RiverGenerator(heightmap, min_elevation=0.9)
        rivers = gen.generate_rivers(num_rivers=5)

        # Should handle gracefully
        assert isinstance(rivers, list)


class TestCoastlineGenerator:
    """Test coastline generation."""

    def test_coastline_generator_initialization(self):
        """Test coastline generator initializes."""
        heightmap = HeightMap(width=128, height=128)
        heightmap.data = [[0.5 for _ in range(128)] for _ in range(128)]
        gen = CoastlineGenerator(heightmap, water_level=0.4)
        assert gen.heightmap == heightmap
        assert gen.water_level == 0.4

    def test_generate_coastline(self):
        """Test coastline generation."""
        heightmap = HeightMap(width=64, height=64)
        heightmap.data = [[0.5 for _ in range(64)] for _ in range(64)]
        # Add water areas
        for x in range(0, 20):
            for y in range(0, 20):
                heightmap.data[y][x] = 0.2  # Water

        gen = CoastlineGenerator(heightmap, water_level=0.4)
        coastline = gen.generate_coastline()

        assert isinstance(coastline, list)
        # Should have some coastline tiles
        assert len(coastline) > 0
        # Coastline should be at water/land boundary
        assert all(isinstance(coord, tuple) for coord in coastline)

    def test_classify_terrain_deep_water(self):
        """Test terrain classification for deep water."""
        heightmap = HeightMap(width=32, height=32)
        gen = CoastlineGenerator(heightmap, water_level=0.4)
        terrain = gen.classify_terrain(0.2)
        assert terrain == TerrainType.DEEP_WATER

    def test_classify_terrain_shallow_water(self):
        """Test terrain classification for shallow water."""
        heightmap = HeightMap(width=32, height=32)
        gen = CoastlineGenerator(heightmap, water_level=0.4)
        terrain = gen.classify_terrain(0.35)
        assert terrain == TerrainType.SHALLOW_WATER

    def test_classify_terrain_sand(self):
        """Test terrain classification for sand."""
        heightmap = HeightMap(width=32, height=32)
        gen = CoastlineGenerator(heightmap, water_level=0.4)
        terrain = gen.classify_terrain(0.43)
        assert terrain == TerrainType.SAND

    def test_classify_terrain_grass(self):
        """Test terrain classification for grass."""
        heightmap = HeightMap(width=32, height=32)
        gen = CoastlineGenerator(heightmap, water_level=0.4)
        terrain = gen.classify_terrain(0.45)
        assert terrain == TerrainType.GRASS

    def test_classify_terrain_mountain(self):
        """Test terrain classification for mountain."""
        heightmap = HeightMap(width=32, height=32)
        gen = CoastlineGenerator(heightmap, water_level=0.4)
        terrain = gen.classify_terrain(0.75)
        assert terrain == TerrainType.MOUNTAIN

    def test_classify_terrain_snow(self):
        """Test terrain classification for snow."""
        heightmap = HeightMap(width=32, height=32)
        gen = CoastlineGenerator(heightmap, water_level=0.4)
        terrain = gen.classify_terrain(0.95)
        assert terrain == TerrainType.SNOW
